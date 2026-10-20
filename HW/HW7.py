import json
import os
import re

import numpy as np
import streamlit as st
from openai import OpenAI

# The news database is built offline by HW7_build_db.py and committed, so this
# page only loads it: no embedding or scoring happens when the app starts.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "HW7-Data")
STORE_PATH = os.path.join(DATA_DIR, "news_store.json")
EMBED_PATH = os.path.join(DATA_DIR, "news_embeddings.npy")

# Chat and query embeddings go through OpenRouter, with the same embedding
# model the build script used so query vectors match the stored ones.
OPENROUTER_URL = "https://openrouter.ai/api/v1"
EMBEDDING_MODEL = "openai/text-embedding-3-small"

# One lower-cost and one higher-cost model, the pair the write-up compares.
# Each model also ranks with its own offline interest scores, so switching the
# picker compares the whole pipeline, not just the wording of the answer.
CHAT_MODELS = {
    "gpt-5-mini (lower cost)": "openai/gpt-5-mini",
    "gpt-5.5 (higher cost)": "openai/gpt-5.5",
}
# Scores used when a model has none saved, so the page still ranks.
FALLBACK_SCORER = "openai/gpt-5-mini"

# OpenRouter reserves a model's full default output budget (64k tokens for
# gpt-5.5) against the key's credit limit unless a cap is sent.
MAX_OUTPUT_TOKENS = 6_000

DEFAULT_TOP_N = 10
MAX_TOP_N = 25
DEFAULT_SEARCH_K = 8
MAX_SEARCH_K = 15

# Below this cosine similarity a search hit shares little more than vocabulary
# with the query. text-embedding-3-small puts on-topic news at roughly 0.4-0.6.
MIN_SIMILARITY = 0.25

# Article body characters handed to the model per result. Most rows are only a
# headline and a description; this trims the few long full-text rows.
BODY_CHARS = 600

# Chat messages kept in the window sent to the model: the last 5 interactions.
BUFFER_MESSAGES = 10

# Everyday names for clients the feed files under another name.
ALIASES = {
    "meta": "Facebook",
    "meta platforms": "Facebook",
    "instagram": "Facebook",
    "google": "Alphabet",
    "foxconn": "Hon Hai Precision",
    "jpmorgan": "JPMorgan Chase",
    "jp morgan": "JPMorgan Chase",
    "chase": "JPMorgan Chase",
    "amd": "Advanced Micro Devices (AMD)",
    "tsmc": "Taiwan Semiconductor Manufacturing Co., Ltd. (TSMC)",
    "hpe": "Hewlett Packard Enterprise",
    "cd&r": "Clayton, Dubilier & Rice",
    "p&g": "Procter & Gamble",
    "bbva": "BBVA-Banco Bilbao Vizcaya",
    "tcs": "Tata Consultancy Services",
    "a16z": "Andreessen Horowitz",
    "carlyle": "The Carlyle Group",
    "disney": "Walt Disney",
    "toyota": "Toyota Motor",
    "hynix": "SK Hynix Inc.",
    "umc": "United Microelectronics Corporation",
    "epson": "Seiko Epson Corporation",
}


def normalize(name):
    return re.sub(r"[^a-z0-9& ]+", " ", name.lower()).split()


@st.cache_resource(show_spinner=False)
def load_store():
    """Open the prebuilt news database: article records plus their vectors."""
    if not (os.path.exists(STORE_PATH) and os.path.exists(EMBED_PATH)):
        return None
    with open(STORE_PATH, encoding="utf-8") as handle:
        store = json.load(handle)
    store["matrix"] = np.load(EMBED_PATH)
    store["companies"] = sorted({a["company"] for a in store["articles"]}, key=str.lower)
    return store


store = load_store()
if store is None:
    st.error(
        "The news database is missing. Build it once with "
        "`python HW/HW7_build_db.py` from the repo root, then reload.",
        icon="🗞️",
    )
    st.stop()

ARTICLES = store["articles"]
MATRIX = store["matrix"]
COMPANIES = store["companies"]
DATES = sorted(a["date"] for a in ARTICLES)
DATE_RANGE = f"{DATES[0]} to {DATES[-1]}"

TOOL_PROMPT = f"""You are the news desk for a large global law firm that \
monitors news about its clients. You can only report on a fixed set of \
{len(ARTICLES)} news articles published {DATE_RANGE}. You have two tools:

- rank_news: the articles ranked by how much the firm needs to know about \
them. Use it for "most interesting", "most important", "top stories", "what \
should we know about" or any request for a ranking, for all clients or for \
one client.
- search_news: semantic search over the articles. Use it for "find news \
about X" when X is a topic, an event, or a company, and for specific \
questions about what happened.

The firm's clients, exactly as the feed names them: {"; ".join(COMPANIES)}.

When the user names a client, pass it as `company`, using the name above that \
it refers to (Meta is Facebook, Google is Alphabet, Foxconn is Hon Hai \
Precision). When they name a company that is not a client, do not pass \
`company`; search for it by name in `query`. Resolve follow-ups like "what \
about them?" from the conversation. If one message asks for two things, call \
a tool for each.

Never answer news questions from memory. If the message is small talk or \
unrelated to the news, reply in one short sentence without a tool."""

ANSWER_PROMPT = f"""You are the news desk for a large global law firm that \
monitors news about its clients. The tool results in this conversation are \
the only news you may report. They come from a fixed set of articles \
published {DATE_RANGE}, so describe dates as they appear and never call \
anything "recent" or "today".

Rules:
- Report only what the tool results contain. Do not add facts, figures or \
background from your own knowledge.
- For a ranking from rank_news, give a numbered list in the tool's order. For \
each story: the headline as a markdown link to its URL, the client, the date \
and outlet, one sentence on what happened, and a "Why it matters:" sentence \
explaining the legal or business stakes for the firm. Mention when several \
outlets covered the story. Then one short line on how the list was ranked.
- For search_news results, lead with the articles that actually answer the \
question, newest first, each with its linked headline, date and one or two \
sentences. Leave out hits that are off-topic. If none are relevant, say \
plainly that the articles have nothing on it.
- If the user asked about a company that is not one of the firm's clients, \
say so, then report any articles that mention it.
- Keep it scannable. No offers to set alerts, email anyone or do anything \
beyond answering."""

RANK_TOOL = {
    "type": "function",
    "function": {
        "name": "rank_news",
        "description": (
            "Return the most important stories in the news set, ranked for a "
            "law firm monitoring its clients. Ranking uses a stored 0-10 "
            "interest score, then how many outlets covered the story, then "
            "recency. Each story appears once even when several outlets ran "
            "it, and articles that only share a client's name are excluded."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": (
                        "Optional. Limit the ranking to one client, by its "
                        "feed name. Omit to rank across all clients."
                    ),
                },
                "top_n": {
                    "type": "integer",
                    "description": (
                        f"Optional. How many stories to return, default "
                        f"{DEFAULT_TOP_N}, at most {MAX_TOP_N}."
                    ),
                },
            },
            "additionalProperties": False,
        },
    },
}

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_news",
        "description": (
            "Semantic search over the news articles. Returns the closest "
            "matching stories with headline, date, outlet, a text excerpt, "
            "and the stored interest score."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A standalone search phrase naming the topic or event, "
                        "e.g. 'CFPB Zelle enforcement' or 'antitrust lawsuits'."
                    ),
                },
                "company": {
                    "type": "string",
                    "description": (
                        "Optional. Restrict results to one client, by its feed "
                        "name. Leave out for topics or for companies that are "
                        "not clients."
                    ),
                },
                "top_k": {
                    "type": "integer",
                    "description": (
                        f"Optional. How many stories to return, default "
                        f"{DEFAULT_SEARCH_K}, at most {MAX_SEARCH_K}."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

st.title("HW 7 — News Information Bot")

st.write(
    f"A news desk for a law firm that monitors {len(COMPANIES)} client "
    f"companies, limited to {len(ARTICLES)} articles from {DATE_RANGE}. Ask "
    "for the **most interesting news** to get a ranked list with the reason "
    "each story matters, or **find news about** a client or topic. The LLM "
    "chooses a tool: `rank_news` reads interest scores the model gave every "
    "article offline, and `search_news` runs a vector search over the "
    "prebuilt embeddings."
)


def get_client():
    """One OpenRouter client per session, for chat and query embeddings."""
    if "hw7_client" not in st.session_state:
        try:
            api_key = st.secrets["OPENROUTER_API_KEY"]
        except (KeyError, FileNotFoundError):
            st.error(
                "No `OPENROUTER_API_KEY` found. Add it to "
                "`.streamlit/secrets.toml` locally, or to **Settings > "
                "Secrets** on Streamlit Community Cloud.",
                icon="🗝️",
            )
            st.stop()
        st.session_state.hw7_client = OpenAI(api_key=api_key, base_url=OPENROUTER_URL)
    return st.session_state.hw7_client


def scorer_for(model):
    """The model whose offline scores rank the news: the chat model if it has
    scores saved, otherwise the fallback scorer."""
    if model in ARTICLES[0].get("scores", {}):
        return model
    return FALLBACK_SCORER


def resolve_company(name):
    """Map a company name the model passed to the feed's client names.

    Returns (matches, note). An exact or alias match wins; otherwise any client
    whose name contains all the words given ("Bain" -> Bain Capital), or whose
    whole name appears in them ("Toyota Motor Corp" -> Toyota Motor). Words,
    not substrings, so "ING" cannot match inside another name. No match
    returns an empty list, and the caller searches without a filter.
    """
    if not name or not name.strip():
        return [], ""
    words = set(normalize(name))
    wanted = " ".join(normalize(name))
    if wanted in ALIASES:
        return [ALIASES[wanted]], ""
    exact = [c for c in COMPANIES if " ".join(normalize(c)) == wanted]
    if exact:
        return exact, ""
    loose = [
        c for c in COMPANIES
        if words <= set(normalize(c)) or set(normalize(c)) <= words
    ]
    if loose:
        return loose, ""
    return [], f'"{name}" is not one of the firm\'s clients.'


def pick(args, key, default, limit):
    """Optional integer arguments arrive missing, as "", or out of range."""
    try:
        value = int(args.get(key) or default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(limit, value))


def story_line(rank, article, score, extra=""):
    body = article["body"][:BODY_CHARS]
    lines = [
        f"{rank}. [{article['company']}] {article['title']}",
        f"   date: {article['date']} | outlet: {article['outlet']} | "
        f"outlets covering this story: {article['coverage']}{extra}",
        f"   interest score: {score['score']}/10 ({score['category']}) - {score['why']}",
        f"   url: {article['url']}",
        f"   description: {article['description']}",
    ]
    if body:
        lines.append(f"   excerpt: {body}")
    return "\n".join(lines)


def best_per_story(candidates, scorer):
    """Keep one article per story cluster: the highest scored, then the one
    with the most text, so the summary has the most to work from."""
    best = {}
    for article in candidates:
        key = article["cluster"]
        rank_key = (article["scores"][scorer]["score"], len(article["body"]) + len(article["description"]))
        if key not in best or rank_key > best[key][0]:
            best[key] = (rank_key, article)
    return [article for _, article in best.values()]


def rank_news(args, model):
    scorer = scorer_for(model)
    companies, note = resolve_company(args.get("company") or "")
    top_n = pick(args, "top_n", DEFAULT_TOP_N, MAX_TOP_N)
    if note:
        return f"{note} Use search_news to find articles that mention it.", []

    pool = [
        a for a in ARTICLES
        if a["scores"][scorer]["about_client"] and a["scores"][scorer]["score"] > 0
        and (not companies or a["company"] in companies)
    ]
    stories = best_per_story(pool, scorer)
    stories.sort(
        key=lambda a: (a["scores"][scorer]["score"], a["coverage"], a["timestamp"]),
        reverse=True,
    )
    picked = stories[:top_n]
    scope = ", ".join(companies) if companies else "all clients"
    if not picked:
        return f"No articles in the set are actually about {scope}.", []

    header = (
        f"Top {len(picked)} stories for {scope}, ranked by interest score "
        f"(scored offline by {scorer}), then outlets covering the story, then "
        f"date. {len(stories)} distinct stories were eligible."
    )
    lines = [story_line(i, a, a["scores"][scorer]) for i, a in enumerate(picked, start=1)]
    return header + "\n\n" + "\n\n".join(lines), picked


def search_news(args, model, fallback_query):
    scorer = scorer_for(model)
    query = (args.get("query") or "").strip() or fallback_query
    top_k = pick(args, "top_k", DEFAULT_SEARCH_K, MAX_SEARCH_K)
    companies, note = resolve_company(args.get("company") or "")

    response = get_client().embeddings.create(input=[query], model=EMBEDDING_MODEL)
    vector = np.array(response.data[0].embedding, dtype=np.float32)
    sims = MATRIX @ (vector / np.linalg.norm(vector))

    order = np.argsort(-sims)
    hits, seen_clusters, seen_urls, off_topic = [], set(), set(), 0
    for i in order:
        article = ARTICLES[int(i)]
        if sims[i] < MIN_SIMILARITY or len(hits) >= top_k:
            break
        if companies and article["company"] not in companies:
            continue
        if not article["scores"][scorer]["about_client"]:
            # A name collision, like the garden caterpillar under Caterpillar.
            off_topic += 1
            continue
        # One hit per story, and one per URL: the feed files a few roundups
        # under two clients, like a Big Tech piece under Apple and Alphabet.
        if article["cluster"] in seen_clusters or article["url"] in seen_urls:
            continue
        seen_clusters.add(article["cluster"])
        seen_urls.add(article["url"])
        hits.append((article, float(sims[i])))

    scope = ", ".join(companies) if companies else "all clients"
    header = f'Search "{query}" across {scope}: {len(hits)} stories.'
    if note:
        header = f"{note} Searched all clients' articles for it instead. " + header
    if off_topic:
        header += (
            f" {off_topic} matching articles were dropped because they only "
            "share a client's name and are not about the client."
        )
    if not hits:
        return header + " Nothing in the set matches.", []
    lines = [
        story_line(n, a, a["scores"][scorer], extra=f" | similarity {sim:.2f}")
        for n, (a, sim) in enumerate(hits, start=1)
    ]
    return header + "\n\n" + "\n\n".join(lines), [a for a, _ in hits]


def run_tool(tool_call, model, fallback_query):
    try:
        args = json.loads(tool_call.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    name = tool_call.function.name
    if name == "rank_news":
        result, articles = rank_news(args, model)
    elif name == "search_news":
        result, articles = search_news(args, model, fallback_query)
    else:
        result, articles = f"Unknown tool {name}.", []
    shown = ", ".join(f'{k}="{v}"' for k, v in args.items() if v not in ("", None))
    return f"{name}({shown})", result, articles


def recent_history(history):
    """The last BUFFER_MESSAGES messages, trimmed to start on a user turn."""
    buffered = history[-BUFFER_MESSAGES:]
    while buffered and buffered[0]["role"] != "user":
        buffered.pop(0)
    return buffered


def escape_dollars(text):
    """News is full of dollar amounts, and Streamlit markdown reads a pair of
    "$" as LaTeX math, so "$6 billion ... $1.4B" renders as garbled math."""
    return text.replace("$", r"\$")


def text_chunks(stream):
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield escape_dollars(chunk.choices[0].delta.content)


def show_tool_calls(calls, scorer):
    label = "Tool call" if len(calls) == 1 else f"Tool calls ({len(calls)})"
    with st.expander(label):
        for signature, articles in calls:
            st.markdown(f"`{signature}`")
            for i, a in enumerate(articles, start=1):
                score = a["scores"][scorer]
                st.markdown(
                    f"{i}. **{a['company']}**, {a['date']}: [{escape_dollars(a['title'])}]({a['url']}) "
                    f"— score {score['score']}, {a['coverage']} outlet(s)"
                )


with st.sidebar:
    st.header("Model")
    choice = st.selectbox("Which LLM?", list(CHAT_MODELS))
    model = CHAT_MODELS[choice]
    st.caption(f"Chat: `{model}`")
    st.caption(f"Ranking scores: `{scorer_for(model)}`")
    st.caption(f"Embeddings: `{EMBEDDING_MODEL}`")

    st.header("News set")
    stories = len({a["cluster"] for a in ARTICLES})
    st.caption(
        f"{store['source_rows']} CSV rows → {len(ARTICLES)} articles after "
        f"dedupe → {stories} stories, {len(COMPANIES)} clients"
    )
    st.caption(f"Published {DATE_RANGE}")
    st.caption(f"Memory: last {BUFFER_MESSAGES // 2} interactions")

    if st.button("Clear conversation"):
        st.session_state.hw7_messages = []

if "hw7_messages" not in st.session_state:
    st.session_state.hw7_messages = []

for message in st.session_state.hw7_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("e.g. Find the most interesting news / Find news about Nvidia"):
    st.session_state.hw7_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    history = recent_history(st.session_state.hw7_messages)
    client = get_client()

    # First call: the model picks a tool and writes its arguments, or answers
    # directly when no news lookup is needed.
    with st.spinner("Thinking..."):
        first = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": TOOL_PROMPT}] + history,
            tools=[RANK_TOOL, SEARCH_TOOL],
            tool_choice="auto",
            max_tokens=MAX_OUTPUT_TOKENS,
        )
    reply = first.choices[0].message

    if not reply.tool_calls:
        response = escape_dollars(reply.content or "")
        with st.chat_message("assistant"):
            st.markdown(response)
    else:
        tool_messages, calls = [], []
        with st.spinner("Reading the news..."):
            for tool_call in reply.tool_calls:
                signature, result, articles = run_tool(tool_call, model, prompt)
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })
                calls.append((signature, articles))

        # Second call: tool results in, no tools offered, so it can only
        # answer. The assistant turn is rebuilt by hand with only the fields
        # a request accepts.
        answer_messages = [
            {"role": "system", "content": ANSWER_PROMPT},
            *history,
            {
                "role": "assistant",
                "content": reply.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in reply.tool_calls
                ],
            },
            *tool_messages,
        ]
        stream = client.chat.completions.create(
            model=model,
            messages=answer_messages,
            stream=True,
            max_tokens=MAX_OUTPUT_TOKENS,
        )

        with st.chat_message("assistant"):
            response = st.write_stream(text_chunks(stream))
            show_tool_calls(calls, scorer_for(model))

    st.session_state.hw7_messages.append({"role": "assistant", "content": response})
