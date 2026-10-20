"""Measure the HW 7 ranking, and compare the two scoring models.

Run from the repo root with the project venv, after HW7_build_db.py:

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe HW/HW7_evaluate.py ranking
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe HW/HW7_evaluate.py compare

"ranking" is free. It checks the app's global ranking (the same sort rank_news
uses) against HW7-Data/gold_set.json, a hand-picked list written before any
model scored anything: how many must-see stories land in the top 10/15/20,
and whether any name-collision or filler article ranks at all.

"compare" is paid. gpt-5.5 rescores a fixed sample of articles with the
same prompt gpt-5-mini used for the whole set, and the script reports how
far the cheaper model's scores are from the expensive one's. The sample is
every gold-set article plus a seeded random draw, saved to
HW7-Data/scorer_comparison.json so the numbers can be checked later.
"""

import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import HW7_build_db as build  # noqa: E402  (same prompt, client and batching)

from openai import OpenAI  # noqa: E402

DATA_DIR = build.DATA_DIR
GOLD_PATH = os.path.join(DATA_DIR, "gold_set.json")
COMPARE_PATH = os.path.join(DATA_DIR, "scorer_comparison.json")

CHEAP, PREMIUM = build.SCORING_MODELS
SAMPLE_SIZE = 100
SEED = 7

# Added to the sample after reading gpt-5-mini's ranking, not chosen blind:
# the two Walmart crime stories it scored 10/10 and ranked in its top 11.
# They test whether the premium model makes the same call.
PROBES = [
    {"company": "Walmart", "title": "Woman stabbed to death"},
    {"company": "Walmart", "title": "El Paso Walmart shooting"},
]


def load():
    with open(build.STORE_PATH, encoding="utf-8") as handle:
        store = json.load(handle)
    with open(GOLD_PATH, encoding="utf-8") as handle:
        gold = json.load(handle)
    return store["articles"], gold


def matches(article, entry):
    return (article["company"] == entry["company"]
            and entry["title"].lower() in article["title"].lower())


def ranked_stories(articles, scorer):
    """The same order rank_news produces with no company filter."""
    best = {}
    for a in articles:
        s = a["scores"][scorer]
        if not s["about_client"] or s["score"] <= 0:
            continue
        key = (s["score"], len(a["body"]) + len(a["description"]))
        if a["cluster"] not in best or key > best[a["cluster"]][0]:
            best[a["cluster"]] = (key, a)
    stories = [a for _, a in best.values()]
    stories.sort(key=lambda a: (a["scores"][scorer]["score"], a["coverage"], a["timestamp"]),
                 reverse=True)
    return stories


def ranking_report(articles, gold, scorer):
    stories = ranked_stories(articles, scorer)
    clusters = [a["cluster"] for a in stories]

    def gold_rank(entry):
        hits = [a["cluster"] for a in articles if matches(a, entry)]
        if not hits:
            return None, "not in CSV"
        ranks = [clusters.index(c) + 1 for c in hits if c in clusters]
        return (min(ranks), "") if ranks else (None, "scored off-topic or 0")

    print(f"=== Ranking by {scorer}: {len(stories)} rankable stories")
    print("Top 15:")
    for i, a in enumerate(stories[:15], start=1):
        s = a["scores"][scorer]
        print(f"{i:>2}. [{s['score']}] {a['company']}: {a['title'][:80]} "
              f"({a['coverage']} outlet(s))")

    print("\nMust-see stories (gold 'top'):")
    ranks = []
    for entry in gold["top"]:
        rank, why = gold_rank(entry)
        ranks.append(rank)
        print(f"  {str(rank or '-'):>4}  {entry['company']}: {entry['title']} {why}")
    found = [r for r in ranks if r]
    for k in (10, 15, 20, 30):
        print(f"  gold stories in top {k}: {sum(r <= k for r in found)}/{len(ranks)}")

    print("\nNoise (gold 'noise') - should be scored off-topic and never rank:")
    leaked = 0
    for entry in gold["noise"]:
        rows = [a for a in articles if matches(a, entry)]
        labels = {(a["scores"][scorer]["about_client"], a["scores"][scorer]["score"]) for a in rows}
        rank, _ = gold_rank(entry)
        leaked += bool(rank)
        print(f"  {entry['company']}: {entry['title']} -> about_client/score {sorted(labels)} "
              f"rank {rank or '-'}")
    print(f"  noise items that rank at all: {leaked}/{len(gold['noise'])}")

    off = sum(not a["scores"][scorer]["about_client"] for a in articles)
    print(f"\nArticles labeled not about their client: {off}/{len(articles)}")
    return stories


def pick_sample(articles, gold):
    chosen = {a["id"] for a in articles
              for e in gold["top"] + gold["noise"] + PROBES if matches(a, e)}
    rest = [a["id"] for a in articles if a["id"] not in chosen]
    random.Random(SEED).shuffle(rest)
    chosen.update(rest[:max(0, SAMPLE_SIZE - len(chosen))])
    return sorted(chosen)


def spearman(xs, ys):
    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return out
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    var = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return cov / var if var else 0.0


def compare(articles, gold):
    by_id = {a["id"]: a for a in articles}
    sample_ids = pick_sample(articles, gold)
    sample = [by_id[i] for i in sample_ids]

    if os.path.exists(COMPARE_PATH):
        with open(COMPARE_PATH, encoding="utf-8") as handle:
            saved = json.load(handle)
        premium = {int(k): v for k, v in saved["premium_scores"].items()}
        seconds = saved["seconds"]
        print(f"Reusing saved {PREMIUM} scores from {COMPARE_PATH}")
    else:
        client = OpenAI(api_key=build.load_api_key(), base_url=build.OPENROUTER_URL)
        premium, seconds = build.score_all(client, PREMIUM, sample)
        with open(COMPARE_PATH, "w", encoding="utf-8") as handle:
            json.dump({"model": PREMIUM, "sample_ids": sample_ids, "seconds": round(seconds, 1),
                       "premium_scores": premium}, handle, ensure_ascii=False, indent=1)

    cheap = {a["id"]: a["scores"][CHEAP] for a in sample}
    agree_about = sum(cheap[i]["about_client"] == premium[i]["about_client"] for i in sample_ids)
    xs = [cheap[i]["score"] for i in sample_ids]
    ys = [premium[i]["score"] for i in sample_ids]
    mae = sum(abs(x - y) for x, y in zip(xs, ys)) / len(xs)
    within1 = sum(abs(x - y) <= 1 for x, y in zip(xs, ys))

    def top(scores, k=10):
        ranked = sorted(sample_ids, key=lambda i: (scores[i]["score"], -i), reverse=True)
        return ranked[:k]
    overlap = len(set(top(cheap)) & set(top(premium)))

    print(f"\n=== {CHEAP} vs {PREMIUM} on {len(sample_ids)} articles "
          f"({PREMIUM} took {seconds:.0f}s)")
    print(f"about_client agreement: {agree_about}/{len(sample_ids)}")
    print(f"score mean absolute difference: {mae:.2f}; within 1 point: {within1}/{len(xs)}")
    print(f"Spearman rank correlation: {spearman(xs, ys):.3f}")
    print(f"top-10 overlap within the sample: {overlap}/10")
    print(f"mean score: {CHEAP} {sum(xs)/len(xs):.2f}, {PREMIUM} {sum(ys)/len(ys):.2f}")
    print("\nBiggest disagreements:")
    diffs = sorted(sample_ids, key=lambda i: abs(cheap[i]["score"] - premium[i]["score"]), reverse=True)
    for i in diffs[:8]:
        a = by_id[i]
        print(f"  {cheap[i]['score']} vs {premium[i]['score']}  {a['company']}: {a['title'][:70]}")
        print(f"      mini: {cheap[i]['why']}")
        print(f"      5.5:  {premium[i]['why']}")
    for label, entries in (("must-see", gold["top"]), ("probe", PROBES)):
        print(f"\n{label} items, {CHEAP} vs {PREMIUM}:")
        for a in sample:
            if any(matches(a, e) for e in entries):
                print(f"  {cheap[a['id']]['score']:>2} vs {premium[a['id']]['score']:>2}  "
                      f"{a['company']}: {a['title'][:70]}")
    gold_ids = {a["id"] for a in sample for e in gold["noise"] if matches(a, e)}
    print(f"\nNoise items {PREMIUM} also labels off-topic: "
          f"{sum(not premium[i]['about_client'] for i in gold_ids)}/{len(gold_ids)}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "ranking"
    articles, gold = load()
    if mode == "ranking":
        ranking_report(articles, gold, CHEAP)
    elif mode == "compare":
        compare(articles, gold)
    else:
        sys.exit("usage: HW7_evaluate.py ranking|compare")


if __name__ == "__main__":
    main()
