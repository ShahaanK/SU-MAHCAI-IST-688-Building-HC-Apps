import json
import os
import re
import sys

# ChromaDB needs sqlite3 >= 3.35 and Streamlit Community Cloud has shipped older
# builds, so swap in the bundled pysqlite3 when it is installed. Inert locally,
# where the system sqlite3 is already new enough.
try:
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules["pysqlite3"]
except ImportError:
    pass

import chromadb
import streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI

# HW 5 reads the same vector database HW 4 built: same folder, same collection,
# same embedding model. Whichever page runs first on a fresh deployment builds
# it, and the other opens the existing files, so nothing is embedded twice.
COLLECTION_NAME = "HW4Collection"
EMBEDDING_MODEL = "text-embedding-3-small"

# Resolved from this file, not the working directory: Streamlit runs pages with
# the CWD set to wherever the app was launched from, which is the repo root.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "HW4-Data")
CHROMA_DIR = os.path.join(BASE_DIR, "HW4-ChromaDB")

# Whole org pages are what gets sent to the model, capped here. The longest page
# in the corpus is about 4,800 characters, so this is headroom rather than a cut.
PAGE_MAX_CHARS = 6_000

# How many organizations each relevant_club_info call returns.
TOP_K = 5

# Mini-documents pulled from Chroma before collapsing to distinct organizations.
# Every org owns exactly two, so 20 always leaves enough for TOP_K distinct orgs.
CHUNK_POOL = 20

# Chat messages kept in the window sent to the model: the last 5 interactions,
# one interaction being a user turn plus a reply.
BUFFER_MESSAGES = 10

# Every page title is "<Organization Name> - 'Cuse Activities".
TITLE_SUFFIX_RE = re.compile(r"\s*[-–]\s*'?Cuse Activities\s*$", re.IGNORECASE)

CHAT_MODELS = {
    "gpt-5-mini (fast)": "gpt-5-mini",
    "gpt-5.4-mini (fast, newer)": "gpt-5.4-mini",
    "gpt-5.5 (premium)": "gpt-5.5",
}

# Sent with the first call, which may call the tool. Its only job is deciding
# whether to search and writing the search query; the answer comes from the
# second call.
TOOL_PROMPT = """You are a student involvement advisor for Syracuse \
University. You have a relevant_club_info tool that searches the university's \
'Cuse Activities directory of registered student organizations.

Call relevant_club_info before answering any question about student \
organizations, clubs, Greek life, club sports, meeting times, officers, \
contacts, or getting involved at SU. Never answer those from memory.

Write the query as a standalone search phrase, not a copy of the user's \
message. Use the conversation to resolve references: if the user asks "when \
do they meet?" after asking about Alpha Phi Omega, search for "Alpha Phi Omega \
meeting time". Name the organization or topic explicitly and leave out filler \
words. If one message asks about two unrelated things, call the tool once for \
each.

If the message is only small talk or a thank-you, reply in one short sentence \
without calling the tool. If it has nothing to do with student organizations, \
do not call the tool; answer briefly, starting with "Not in the organization \
pages - answering from general knowledge:"."""

# Sent with the second call, which has the search results and no tools.
ANSWER_PROMPT = """You are a student involvement advisor for Syracuse \
University. The relevant_club_info results in this conversation are \
organization pages from the university's 'Cuse Activities directory, \
retrieved for the user's latest message.

Rules for every answer:
- Lead with one short line saying where the answer comes from. If the \
retrieved pages cover the question, write "From the organization pages:" and \
name the organizations you used. If they do not cover it, write "Not in the \
organization pages - answering from general knowledge:" instead.
- Only the retrieved pages are directory material. Never present general \
knowledge as though it came from them.
- Name the organization a fact came from, and give details like meeting times, \
locations, and contact emails exactly as the page states them.
- If the pages only partly cover the question, answer that part from them and \
say plainly what they do not say. Many pages leave fields as "No Response"; \
that means the directory does not say, not that the answer is no.
- You can only search the directory and answer. Do not offer to send emails, \
contact anyone, or sign the user up.
- Keep answers short and readable."""

# The tool definition handed to the OpenAI API. The model writes the query;
# the page runs the vector search with it (see run_club_tool).
CLUB_TOOL = {
    "type": "function",
    "function": {
        "name": "relevant_club_info",
        "description": (
            "Search Syracuse University's 'Cuse Activities directory of "
            f"registered student organizations. Returns the {TOP_K} most "
            "relevant organization pages: name, description, contact details, "
            "meeting times, officers and events where the page lists them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A standalone search phrase naming the organization or "
                        "topic, with references like 'they' or 'that club' "
                        "replaced by the name, e.g. 'Alpha Phi Omega meeting "
                        "time' or 'robotics clubs for engineering students'."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

st.title("HW 5 — Student Organization Chatbot with a Search Tool")

st.write(
    "Ask about Syracuse University's registered student organizations. Your "
    "question is not embedded directly. The LLM decides whether it needs the "
    "directory and writes its own search query for the `relevant_club_info` "
    "tool, using the conversation to fill in what \"they\" or \"that club\" "
    "means. The tool searches the ChromaDB collection of 513 'Cuse Activities "
    "pages, and a second LLM call answers from the pages it returns."
)


def get_openai_client():
    """One OpenAI client per session, reused for embeddings and for chat."""
    if "openai_client" not in st.session_state:
        try:
            api_key = st.secrets["OPENAI_API_KEY"]
        except (KeyError, FileNotFoundError):
            st.error(
                "No `OPENAI_API_KEY` found. Add it to `.streamlit/secrets.toml` "
                "locally, or to **Settings > Secrets** on Streamlit Community "
                "Cloud.",
                icon="🗝️",
            )
            st.stop()
        st.session_state.openai_client = OpenAI(api_key=api_key)
    return st.session_state.openai_client


def page_url(filename):
    """Rebuild the source URL from the saved filename.

    The files are saved as "syracuse.campuslabs.com_engage_organization_<slug>",
    but plenty of slugs contain underscores themselves, so only the first three
    underscores are path separators.
    """
    stem = filename[:-5] if filename.lower().endswith(".html") else filename
    return "https://" + "/".join(stem.split("_", 3))


def read_org_page(path):
    """Return (organization name, page text) for one saved HTML page.

    The organization name comes from <title>, never from the filename: the
    directory exported two pages whose slugs are literally "-" and "-----------",
    so filenames are not reliable identifiers.
    """
    with open(path, encoding="utf-8", errors="ignore") as handle:
        soup = BeautifulSoup(handle.read(), "html.parser")

    # Scripts and styles are the bulk of these pages and none of the content.
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""
    name = TITLE_SUFFIX_RE.sub("", title).strip()
    if not name:
        # No usable title: fall back to the slug, tidied into words.
        slug = page_url(path).rsplit("/", 1)[-1]
        name = slug.replace("-", " ").replace("_", " ").strip().title()

    return name, soup.get_text(" ", strip=True)


def split_in_two(text):
    """Split one organization page into two mini-documents at the midpoint,
    snapped forward to the next space so no word is cut in half. Same method as
    HW 4, which explains the choice."""
    midpoint = len(text) // 2
    split_at = text.find(" ", midpoint)
    if split_at == -1:
        split_at = midpoint
    return [text[:split_at].strip(), text[split_at:].strip()]


def embed(texts):
    """Embed a list of strings with the OpenAI embeddings model."""
    response = get_openai_client().embeddings.create(
        input=texts,
        model=EMBEDDING_MODEL,
    )
    return [item.embedding for item in response.data]


def build_collection(collection):
    """Embed every organization page into an empty collection, two chunks each.

    This must build exactly what HW 4 builds, since the two pages share one
    database: ids "<filename>::0" and "<filename>::1", the filename in metadata,
    and the organization name prefixed onto the text being embedded (but not
    onto the stored document).
    """
    filenames = sorted(f for f in os.listdir(DATA_DIR) if f.lower().endswith(".html"))

    ids, documents, embed_inputs, metadatas = [], [], [], []
    for filename in filenames:
        name, text = read_org_page(os.path.join(DATA_DIR, filename))
        if not text.strip():
            continue
        for part, chunk in enumerate(split_in_two(text)):
            if not chunk:
                continue
            ids.append(f"{filename}::{part}")
            documents.append(chunk)
            embed_inputs.append(f"{name}\n{chunk}")
            metadatas.append({
                "filename": filename,
                "organization": name,
                "url": page_url(filename),
                "part": part,
            })

    # Added in batches to keep each embeddings request a reasonable size.
    progress = st.progress(0.0, text="Embedding organization pages...")
    for start in range(0, len(ids), 100):
        stop = min(start + 100, len(ids))
        collection.add(
            ids=ids[start:stop],
            documents=documents[start:stop],
            metadatas=metadatas[start:stop],
            embeddings=embed(embed_inputs[start:stop]),
        )
        progress.progress(
            stop / len(ids),
            text=f"Embedded {stop} of {len(ids)} mini-documents...",
        )
    progress.empty()


@st.cache_resource(show_spinner=False)
def get_collection():
    """Open the persistent vector database, building it only the first time."""
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    if collection.count() == 0:
        with st.spinner("Building the HW4Collection vector database (first run only)..."):
            build_collection(collection)
    return collection


def fetch_page(collection, filename):
    """Reassemble a whole organization page from its two mini-documents."""
    stored = collection.get(ids=[f"{filename}::0", f"{filename}::1"])
    # get() gives no ordering guarantee, so put the halves back in order by id.
    by_id = dict(zip(stored["ids"], stored["documents"]))
    halves = [by_id.get(f"{filename}::{part}", "") for part in (0, 1)]
    return " ".join(half for half in halves if half).strip()


def search(collection, query, n_results=TOP_K):
    """Return the organizations most relevant to a query, best first.

    Mini-documents are what gets matched, but whole pages are what gets
    returned, so the answer is never missing a fact that sat in the other half.
    """
    pool = max(1, min(CHUNK_POOL, collection.count()))
    results = collection.query(
        query_embeddings=embed([query]),
        n_results=pool,
        include=["metadatas", "distances"],
    )

    # Chroma returns one list of results per query, so everything is at [0].
    # Collapse the two halves to one entry per page, keeping the closer half.
    ranked, seen = [], set()
    for i, meta in enumerate(results["metadatas"][0]):
        if meta["filename"] in seen:
            continue
        seen.add(meta["filename"])
        ranked.append({
            "filename": meta["filename"],
            "metadata": meta,
            "distance": results["distances"][0][i],
        })

    hits = ranked[:n_results]
    for hit in hits:
        hit["document"] = fetch_page(collection, hit["filename"])[:PAGE_MAX_CHARS]
    return hits


def build_context(hits):
    """Format the retrieved organization pages as the tool's result."""
    if not hits:
        return "No organization pages matched this query."
    blocks = []
    for hit in hits:
        meta = hit["metadata"]
        blocks.append(
            f"--- ORGANIZATION: {meta['organization']} "
            f"(source: {meta['url']}) ---\n{hit['document']}"
        )
    return "\n\n".join(blocks)


def relevant_club_info(query):
    """The function behind the tool: vector search on the model's query.

    Returns the formatted pages for the model and the raw hits for the page's
    "what was searched" expander.
    """
    hits = search(get_collection(), query)
    return build_context(hits), hits


def run_club_tool(tool_call, fallback_query):
    """Run one relevant_club_info call the model asked for.

    The model's query is used as given. The user's own message is only a
    fallback, for the rare call that arrives with no usable query.
    """
    try:
        arguments = json.loads(tool_call.function.arguments or "{}")
    except json.JSONDecodeError:
        arguments = {}
    query = (arguments.get("query") or "").strip() or fallback_query
    context, hits = relevant_club_info(query)
    return query, context, hits


def recent_history(history):
    """The last BUFFER_MESSAGES chat messages, starting on a user turn.

    A cut mid-exchange would orphan an assistant reply whose question is gone,
    so the window is trimmed until it starts with the user.
    """
    buffered = history[-BUFFER_MESSAGES:]
    while buffered and buffered[0]["role"] != "user":
        buffered.pop(0)
    return buffered


def text_chunks(stream):
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def show_searches(searches):
    """List each query the model wrote and the organizations it returned."""
    label = "Search the LLM ran" if len(searches) == 1 else f"Searches the LLM ran ({len(searches)})"
    with st.expander(label):
        for query, hits in searches:
            st.markdown(f"`relevant_club_info(query=\"{query}\")`")
            for i, hit in enumerate(hits, start=1):
                meta = hit["metadata"]
                st.markdown(
                    f"{i}. **{meta['organization']}** "
                    f"([page]({meta['url']}), distance {hit['distance']:.3f})"
                )


collection = get_collection()

with st.sidebar:
    st.header("Model")
    choice = st.selectbox("Which LLM?", list(CHAT_MODELS))
    model = CHAT_MODELS[choice]
    st.caption(f"Chat: `{model}`")
    st.caption(f"Embeddings: `{EMBEDDING_MODEL}`")

    st.header("Collection")
    chunk_count = collection.count()
    st.caption(
        f"`{COLLECTION_NAME}` — {chunk_count // 2} organizations, "
        f"{chunk_count} mini-documents indexed"
    )
    st.caption(f"Tool: `relevant_club_info`, top {TOP_K} organizations per search")
    st.caption(f"Memory: last {BUFFER_MESSAGES // 2} interactions")

    if st.button("Clear conversation"):
        st.session_state.hw5_messages = []

if "hw5_messages" not in st.session_state:
    st.session_state.hw5_messages = []

# Only user and assistant text is kept in the history. Tool calls and the pages
# they returned belong to the turn that made them; a later question gets a
# fresh search instead of carrying old pages through the memory window.
for message in st.session_state.hw5_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about SU student organizations..."):
    st.session_state.hw5_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    history = recent_history(st.session_state.hw5_messages)
    client = get_openai_client()

    # First call: the model sees the memory window and the tool, and decides
    # whether to search and what to search for. tool_choice="auto" lets it skip
    # the search for small talk.
    with st.spinner("Thinking..."):
        first = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": TOOL_PROMPT}] + history,
            tools=[CLUB_TOOL],
            tool_choice="auto",
        )
    reply = first.choices[0].message

    if not reply.tool_calls:
        # No search needed, so the first reply is the answer.
        response = reply.content or ""
        with st.chat_message("assistant"):
            st.markdown(response)
    else:
        # Every tool call the model makes needs its own "tool" reply, matched
        # by id, or the second call is rejected.
        tool_messages, searches = [], []
        with st.spinner("Searching the organization directory..."):
            for tool_call in reply.tool_calls:
                query, context, hits = run_club_tool(tool_call, prompt)
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": context,
                })
                searches.append((query, hits))

        # Second call: the search results go back to the model as the tool
        # results, and no tools are passed, so this call can only answer. The
        # assistant turn is rebuilt by hand rather than dumped from the SDK
        # object, which carries response-only fields the request does not take.
        answer_messages = [
            {"role": "system", "content": ANSWER_PROMPT},
            *history,
            {
                "role": "assistant",
                "content": reply.content,
                "tool_calls": [tool_call.model_dump() for tool_call in reply.tool_calls],
            },
            *tool_messages,
        ]
        stream = client.chat.completions.create(
            model=model,
            messages=answer_messages,
            stream=True,
        )

        with st.chat_message("assistant"):
            response = st.write_stream(text_chunks(stream))
            show_searches(searches)

    st.session_state.hw5_messages.append({"role": "assistant", "content": response})
