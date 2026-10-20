"""Build the HW 7 news database offline, before the app ever runs.

Run from the repo root with the project venv:

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe HW/HW7_build_db.py

It reads HW/HW7-Data/news.csv and writes two files next to it, both committed,
so the deployed app only loads them and never embeds or scores at start-up:

- news_embeddings.npy  one normalized text-embedding-3-small vector per article
- news_store.json      the cleaned articles, story clusters, and an
                       "interest" score from each chat model

Steps: clean and dedupe the CSV, embed, group near-duplicate coverage of the
same story into clusters, then have each chat model score every article for a
law firm that monitors these companies as clients. Re-running only rescores
when --rescore is passed, because scoring is the slow, paid step.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import tomllib
from datetime import datetime

import numpy as np
from openai import OpenAI

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(BASE_DIR, "HW7-Data")
CSV_PATH = os.path.join(DATA_DIR, "news.csv")
STORE_PATH = os.path.join(DATA_DIR, "news_store.json")
EMBED_PATH = os.path.join(DATA_DIR, "news_embeddings.npy")

# Everything goes through OpenRouter, which serves the same OpenAI models
# behind an OpenAI-compatible API, so the openai SDK only needs a base_url.
OPENROUTER_URL = "https://openrouter.ai/api/v1"
EMBEDDING_MODEL = "openai/text-embedding-3-small"

# The two models the write-up compares: one lower-cost, one higher-cost.
SCORING_MODELS = ["openai/gpt-5-mini", "openai/gpt-5.5"]

# Articles are scored in batches; 20 keeps each request small enough that the
# model does not lose track of ids, and the whole set takes about 55 calls.
SCORE_BATCH = 20

# Characters of article body sent for scoring. Most rows are a headline and a
# one-line description, so this only trims the long full-text rows.
SCORE_BODY_CHARS = 1_200

# Characters of article body embedded. text-embedding-3-small takes far more,
# but past this the long rows are mostly site boilerplate.
EMBED_BODY_CHARS = 2_000

# Two articles filed under the same company with cosine similarity at or above
# this are treated as coverage of the same story. Picked by reading pairs in
# bands: from 0.78 up they are almost all different outlets on one event
# (Advantest's raised outlook, Amazon's Q2 miss, the Google antitrust ruling);
# below about 0.76 they turn into separate news that only shares a topic, like
# two different Acer laptop deals or two unrelated Amdocs holdings filings.
CLUSTER_THRESHOLD = 0.78

SCORING_PROMPT = """You screen news for a large global law firm. Every article \
below was collected under the name of one of the firm's clients, given as \
"client". Score each article for the firm's client-monitoring team.

First decide "about_client": true only if the article is actually about that \
client company. Name collisions are common in this feed and must be false: a \
garden caterpillar for Caterpillar, Leonardo da Vinci for VINCI, footballer \
Eni Aluko for Eni, the Kolkata Knight Riders cricket team for KKR, the Silver \
Lake neighborhood for Silver Lake, a Breville "Oracle" espresso machine for \
Oracle, the alphabet song for Alphabet, the Amazon rainforest for Amazon, The \
Points Guy for TPG, a Birmingham venue for NEC, and so on. A retail deal on a \
product the client only makes a part for (a gaming PC with an Intel chip, a \
Samsung phone with a Qualcomm chip, an Amazon discount on an Apple Watch) is \
not about the client either.

Then give "score", 0 to 10, for how much the firm needs to know about it:
- 9-10: litigation, enforcement or a regulator acting against the client, \
antitrust rulings or probes, large settlements, tax disputes, major M&A or \
take-private deals, mass layoffs, data breaches, fatal safety incidents.
- 7-8: lawsuits or investigations at an early stage, sizable deals and \
financings, big earnings misses or guidance shocks, government contract \
awards, executive departures, restructurings.
- 4-6: routine earnings and outlook, partnerships, product launches with \
business weight, analyst rating changes with a stated reason.
- 1-3: product reviews, marketing, minor holdings filings, stock-ticker \
filler, generic market commentary.
- 0: not about the client (about_client false).

Also give "category" (one or two words, e.g. "litigation", "regulatory", \
"M&A", "earnings", "labor", "product", "markets", "off-topic") and "why": \
one sentence on why it matters to the firm, or why it does not.

Return JSON only: {"articles": [{"id": ..., "about_client": ..., "score": \
..., "category": ..., "why": ...}, ...]} with one entry per input id."""


def load_api_key():
    with open(os.path.join(REPO_DIR, ".streamlit", "secrets.toml"), "rb") as handle:
        return tomllib.load(handle)["OPENROUTER_API_KEY"]


def split_document(document):
    """Split the CSV's Document field into title, description and body.

    Every row reads "<title> Description: <description>", and about a fifth
    continue " content: <full text>". Only the first marker of each is a
    separator; article text can contain the words again.
    """
    title, _, rest = document.partition(" Description: ")
    description, _, body = rest.partition(" content: ")
    return title.strip(), description.strip(), body.strip()


def parse_date(value):
    """The CSV mixes "+00:00" and "Z" timestamps; both are UTC."""
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))


def outlet(url):
    host = re.sub(r"^https?://", "", url).split("/", 1)[0].lower()
    return re.sub(r"^(www\d?|m|ca|uk|sg|au|in|edition|news|pro)\.", "", host)


def load_articles():
    """Read the CSV, tidy it, and drop exact repeats.

    The file repeats whole company blocks and lists some URLs twice, once with
    just a description and once with full text. One article is kept per
    (company, URL), the version with the longest Document. The same URL filed
    under two companies (a Big Tech roundup under Apple and Alphabet) is kept
    once per company, since each is news about a different client.
    """
    with open(CSV_PATH, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    best = {}
    for row in rows:
        company = row["company_name"].strip()
        key = (company, row["URL"].strip())
        if key not in best or len(row["Document"]) > len(best[key]["Document"]):
            best[key] = row

    articles = []
    for (company, url), row in best.items():
        title, description, body = split_document(row["Document"])
        published = parse_date(row["Date"])
        articles.append({
            "company": company,
            "title": title,
            "description": description,
            "body": body,
            "url": url,
            "outlet": outlet(url),
            "date": published.strftime("%Y-%m-%d"),
            "timestamp": published.timestamp(),
        })

    # Stable order so ids, embeddings and scores line up across re-runs.
    articles.sort(key=lambda a: (a["company"].lower(), -a["timestamp"], a["url"]))
    for i, article in enumerate(articles):
        article["id"] = i
    return len(rows), articles


def embed_text(article):
    return (
        f"{article['company']}: {article['title']}. {article['description']} "
        f"{article['body'][:EMBED_BODY_CHARS]}"
    ).strip()


def embed_all(client, articles):
    vectors = []
    for start in range(0, len(articles), 100):
        batch = [embed_text(a) for a in articles[start:start + 100]]
        response = client.embeddings.create(input=batch, model=EMBEDDING_MODEL)
        vectors.extend(item.embedding for item in response.data)
        print(f"  embedded {min(start + 100, len(articles))}/{len(articles)}")
    matrix = np.array(vectors, dtype=np.float32)
    # Normalized once here, so the app's cosine similarity is a dot product.
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix


def cluster(articles, matrix):
    """Group articles under the same company that cover the same story.

    Union-find over every same-company pair above CLUSTER_THRESHOLD. The
    cluster id is the lowest article id in the group, and its size counts
    distinct outlets, which the ranking uses as a coverage signal.
    """
    parent = list(range(len(articles)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_company = {}
    for article in articles:
        by_company.setdefault(article["company"], []).append(article["id"])
    for ids in by_company.values():
        sims = matrix[ids] @ matrix[ids].T
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                if sims[a, b] >= CLUSTER_THRESHOLD:
                    parent[find(ids[a])] = find(ids[b])

    groups = {}
    for article in articles:
        groups.setdefault(find(article["id"]), []).append(article["id"])
    for members in groups.values():
        cluster_id = min(members)
        outlets = sorted({articles[i]["outlet"] for i in members})
        for i in members:
            articles[i]["cluster"] = cluster_id
            articles[i]["coverage"] = len(outlets)
    return len(groups)


def score_batch(client, model, batch):
    payload = [
        {
            "id": a["id"],
            "client": a["company"],
            "date": a["date"],
            "outlet": a["outlet"],
            "title": a["title"],
            "description": a["description"],
            "body": a["body"][:SCORE_BODY_CHARS],
        }
        for a in batch
    ]
    messages = [
        {"role": "system", "content": SCORING_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                # Low reasoning effort: this is a sorting task, and reasoning
                # tokens are most of the cost. The output cap keeps OpenRouter
                # from reserving the model's full 64k-token default per call.
                max_tokens=8_000,
                extra_body={"reasoning": {"effort": "low"}},
            )
            results = json.loads(response.choices[0].message.content)["articles"]
            by_id = {int(r["id"]): r for r in results}
            missing = [a["id"] for a in batch if a["id"] not in by_id]
            if missing:
                raise ValueError(f"missing ids {missing}")
            return by_id
        except Exception as error:  # noqa: BLE001 - retried, then re-raised
            print(f"    {model} batch retry {attempt + 1}: {error}")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{model} could not score batch starting {batch[0]['id']}")


def score_all(client, model, articles):
    started = time.time()
    scores = {}
    for start in range(0, len(articles), SCORE_BATCH):
        batch = articles[start:start + SCORE_BATCH]
        for article_id, result in score_batch(client, model, batch).items():
            scores[article_id] = {
                "about_client": bool(result.get("about_client")),
                "score": max(0, min(10, int(result.get("score") or 0))),
                "category": str(result.get("category") or "").strip().lower(),
                "why": str(result.get("why") or "").strip(),
            }
        print(f"  {model}: scored {min(start + SCORE_BATCH, len(articles))}/{len(articles)}")
    # Off-topic articles never rank, whatever number the model put on them.
    for result in scores.values():
        if not result["about_client"]:
            result["score"] = 0
    return scores, time.time() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rescore", action="store_true",
                        help="score again even if news_store.json already has scores")
    parser.add_argument("--models", nargs="+", default=SCORING_MODELS,
                        help="which models to score with; others keep their saved scores")
    args = parser.parse_args()

    client = OpenAI(api_key=load_api_key(), base_url=OPENROUTER_URL)
    raw_count, articles = load_articles()
    print(f"{raw_count} CSV rows -> {len(articles)} articles after dedupe")

    previous = {}
    if os.path.exists(STORE_PATH):
        with open(STORE_PATH, encoding="utf-8") as handle:
            previous = json.load(handle)

    print("Embedding...")
    matrix = embed_all(client, articles)
    clusters = cluster(articles, matrix)
    print(f"{clusters} stories after clustering at {CLUSTER_THRESHOLD}")

    scoring_seconds = previous.get("scoring_seconds", {})
    for model in SCORING_MODELS:
        old = {a["url"] + "|" + a["company"]: a.get("scores", {}).get(model)
               for a in previous.get("articles", [])}
        reusable = old and all(old.get(a["url"] + "|" + a["company"]) for a in articles)
        if reusable and (model not in args.models or not args.rescore):
            print(f"Reusing saved {model} scores")
            for a in articles:
                a.setdefault("scores", {})[model] = old[a["url"] + "|" + a["company"]]
            continue
        if model not in args.models:
            print(f"Skipping {model}: not requested and no saved scores")
            continue
        print(f"Scoring with {model}...")
        scores, seconds = score_all(client, model, articles)
        scoring_seconds[model] = round(seconds, 1)
        for a in articles:
            a.setdefault("scores", {})[model] = scores[a["id"]]

    store = {
        "built": datetime.now().isoformat(timespec="seconds"),
        "source_rows": raw_count,
        "embedding_model": EMBEDDING_MODEL,
        "scoring_models": SCORING_MODELS,
        "scoring_seconds": scoring_seconds,
        "cluster_threshold": CLUSTER_THRESHOLD,
        "articles": articles,
    }
    with open(STORE_PATH, "w", encoding="utf-8") as handle:
        json.dump(store, handle, ensure_ascii=False, indent=1)
    np.save(EMBED_PATH, matrix)
    print(f"Wrote {STORE_PATH} and {EMBED_PATH} ({matrix.shape[0]} x {matrix.shape[1]})")


if __name__ == "__main__":
    sys.exit(main())
