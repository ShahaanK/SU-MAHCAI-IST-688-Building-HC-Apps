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

COLLECTION_NAME = "HW4Collection"
EMBEDDING_MODEL = "text-embedding-3-small"

# Resolved from this file, not the working directory: Streamlit runs pages with
# the CWD set to wherever the app was launched from, which is the repo root.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "HW4-Data")

# The vector database lives on disk, so it survives the process exiting. It is
# built on the first run and reused by every run after that (see
# get_collection). Lab 4 kept its collection in st.session_state, which rebuilt
# it — and re-billed the embeddings — every time the app restarted.
CHROMA_DIR = os.path.join(BASE_DIR, "HW4-ChromaDB")

# Whole org pages are what gets sent to the model, capped here. The longest page
# in the corpus is about 4,800 characters, so this is headroom rather than a cut.
PAGE_MAX_CHARS = 6_000

# How many organizations to put in the prompt for each question.
TOP_K = 5

# Mini-documents pulled from Chroma before collapsing to distinct organizations.
# Every org owns exactly two, so 20 always leaves enough for TOP_K distinct orgs.
CHUNK_POOL = 20

# Chat messages kept in the window sent to the model. The assignment asks for the
# last 5 interactions, and one interaction is a user turn plus a reply, so 10.
BUFFER_MESSAGES = 10

# Every page title is "<Organization Name> - 'Cuse Activities".
TITLE_SUFFIX_RE = re.compile(r"\s*[-–]\s*'?Cuse Activities\s*$", re.IGNORECASE)

CHAT_MODELS = {
    "gpt-5-mini (fast)": "gpt-5-mini",
    "gpt-5.4-mini (fast, newer)": "gpt-5.4-mini",
    "gpt-5.5 (premium)": "gpt-5.5",
}

SYSTEM_PROMPT = """You are a student involvement advisor for Syracuse \
University. You answer questions about registered student organizations using \
the organization pages supplied below, which come from the university's \
'Cuse Activities directory.

Rules for every answer:
- Lead with one short line saying where the answer comes from. If the pages \
below cover the question, write "From the organization pages:" and name the \
organizations you used. If they do not cover it, write "Not in the \
organization pages - answering from general knowledge:" instead.
- Only the pages below are directory material. Never present general knowledge \
as though it came from them.
- Name the organization a fact came from, and give details like meeting times, \
locations, and contact emails exactly as the page states them.
- If the pages only partly cover the question, answer that part from them and \
say plainly what they do not say. Many pages leave fields as "No Response"; \
that means the directory does not say, not that the answer is no.
- Keep answers short and readable."""

st.title("HW 4 — Student Organization Chatbot")

st.write(
    "Ask about Syracuse University's registered student organizations. Every "
    "question is embedded and matched against a ChromaDB collection built from "
    "513 'Cuse Activities organization pages, and the five closest pages are "
    "added to the prompt sent to the LLM — so the bot answers from the actual "
    "directory, and says so when it cannot."
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
    so filenames are not reliable identifiers, while every title follows the same
    "<Name> - 'Cuse Activities" pattern.
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
    """Split one organization page into exactly two mini-documents.

    Chunking method: a single midpoint split, snapped forward to the next space
    so no word is cut in half. The assignment asks for two mini-documents per
    document, and this is the method that fits these particular documents.

    Why this rather than a fixed-size sliding window (what Lab 4 used) or a
    recursive character splitter:

    - The count is the requirement. A sliding window produces however many chunks
      a page's length happens to yield: 1 for the shortest page in this corpus,
      4 for the longest. Halving produces exactly two for all 513 pages, so the
      collection holds exactly 1,026 mini-documents.
    - These pages are short and uniform. The median is about 1,600 characters, so
      each half lands near 800 — already a good embedding granularity. There is
      nothing to gain from cutting further, while embedding a whole page as one
      vector would blur an organization's purpose into its roster and events.
    - The halves line up with the natural shape of the page. 'Cuse Activities
      renders every organization in the same order: name, contact details,
      description and leadership first, then events, officers and documents.
      Cutting at the midpoint tends to separate "what this organization is" from
      "when it meets and who runs it", which are the two things people actually
      ask about, so each half stays roughly about one topic.
    - Overlap is unnecessary at this size. Overlap exists to stop a fact being
      severed at a boundary, and here the whole page is reassembled and sent to
      the model whenever either half is retrieved (see fetch_page), so a fact
      landing on the seam is never lost.
    """
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

    The filename is the key throughout: chunk ids are "<filename>::0" and
    "<filename>::1", and every chunk carries its filename in metadata, so any
    chunk can be traced back to the page it came from and its other half fetched
    by name.

    Embeddings are computed here with OpenAI and handed to Chroma explicitly,
    which means queries must also be made with query_embeddings: passing raw
    query text instead would make Chroma fall back to its own default embedding
    function and silently compare vectors from two different spaces.
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
            # What gets embedded is not quite what gets stored. The organization
            # name is prefixed onto the text being embedded so the name is part
            # of the vector: the second half of a page is a roster and an event
            # list that never repeats the organization's name, and without this
            # prefix it would not match a question that names the organization.
            # The stored document stays clean so the two halves concatenate back
            # into the original page (see fetch_page) with no header in between.
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
    """Open the persistent vector database, building it only the first time.

    PersistentClient writes the collection to CHROMA_DIR on disk, so the check
    below is what the assignment asks for: the database is created once, and
    every later run — including a brand new process — opens the existing files
    and embeds nothing. Deleting CHROMA_DIR is what forces a rebuild.

    st.cache_resource rather than st.session_state so the one collection is
    shared across reruns and across browser sessions, not rebuilt per visitor.
    """
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    if collection.count() == 0:
        with st.spinner("Building the HW4Collection vector database (first run only)..."):
            build_collection(collection)
    return collection


def fetch_page(collection, filename):
    """Reassemble a whole organization page from its two mini-documents.

    The halves were stored unmodified and in order, so joining them returns the
    original page text. Nothing has to be re-parsed from the HTML at query time:
    the vector database is the only thing the running app reads from.
    """
    stored = collection.get(ids=[f"{filename}::0", f"{filename}::1"])
    # get() gives no ordering guarantee, so put the halves back in order by id.
    by_id = dict(zip(stored["ids"], stored["documents"]))
    halves = [by_id.get(f"{filename}::{part}", "") for part in (0, 1)]
    return " ".join(half for half in halves if half).strip()


def search(collection, query, n_results=TOP_K):
    """Return the organizations most relevant to a query, best first.

    Mini-documents are what gets matched, but whole pages are what gets returned:
    retrieving at half-page granularity ranks accurately, while handing the model
    the complete page avoids answering "the directory doesn't say" just because
    the winning half stopped before the meeting time.
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
    """Format the retrieved organization pages for the prompt."""
    blocks = []
    for hit in hits:
        meta = hit["metadata"]
        blocks.append(
            f"--- ORGANIZATION: {meta['organization']} "
            f"(source: {meta['url']}) ---\n{hit['document']}"
        )
    return "\n\n".join(blocks)


def build_messages(hits, history):
    """System prompt with the retrieved pages, plus the recent chat window."""
    system = SYSTEM_PROMPT + "\n\nORGANIZATION PAGES RETRIEVED FOR THIS QUESTION:\n\n"
    system += build_context(hits) if hits else "(none retrieved)"

    buffered = history[-BUFFER_MESSAGES:]
    # A cut mid-exchange orphans an assistant reply whose question is gone, so
    # trim until the window starts on a user turn.
    while buffered and buffered[0]["role"] != "user":
        buffered.pop(0)
    return [{"role": "system", "content": system}] + buffered


def text_chunks(stream):
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


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
    st.caption(f"Memory: last {BUFFER_MESSAGES // 2} interactions")

    if st.button("Clear conversation"):
        st.session_state.hw4_messages = []

if "hw4_messages" not in st.session_state:
    st.session_state.hw4_messages = []

for message in st.session_state.hw4_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about SU student organizations..."):
    st.session_state.hw4_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.spinner("Searching the organization directory..."):
        hits = search(collection, prompt)

    client = get_openai_client()
    stream = client.chat.completions.create(
        model=model,
        messages=build_messages(hits, st.session_state.hw4_messages),
        stream=True,
    )

    with st.chat_message("assistant"):
        response = st.write_stream(text_chunks(stream))
        if hits:
            with st.expander(f"Organizations retrieved for this question ({len(hits)})"):
                for i, hit in enumerate(hits, start=1):
                    meta = hit["metadata"]
                    st.markdown(
                        f"{i}. **{meta['organization']}** "
                        f"([page]({meta['url']}), distance {hit['distance']:.3f})"
                    )

    st.session_state.hw4_messages.append({"role": "assistant", "content": response})
