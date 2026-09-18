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
from openai import OpenAI
from pypdf import PdfReader

COLLECTION_NAME = "Lab4Collection"
EMBEDDING_MODEL = "text-embedding-3-small"

# Resolved from this file, not the working directory: Streamlit runs pages with
# the CWD set to wherever the app was launched from, which is the repo root.
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Lab-04-Data")

# Each syllabus is split into overlapping chunks before embedding. One vector
# per whole syllabus was measurably worse: a single embedding over 17 pages
# dilutes the signal badly enough that "which course teaches Python" did not
# return the Python syllabus at all. ~2,000 characters is roughly one syllabus
# section, which is the granularity questions are actually asked at.
CHUNK_CHARS = 2_000
CHUNK_OVERLAP = 200

# Chunks are retrieved, but whole syllabi are sent to the model (see search()),
# so this caps one syllabus inside the prompt rather than an embedding input.
PARENT_MAX_CHARS = 25_000

# How many syllabi to put in the prompt for each question.
TOP_K = 3

# Chunks pulled from Chroma before collapsing to distinct files. Enough that
# TOP_K distinct syllabi survive even when one file owns the closest matches.
CHUNK_POOL = 25

# Chat messages kept in the window sent to the model. 6 = 3 exchanges.
BUFFER_MESSAGES = 6

# Course codes named in a question, e.g. "IST 488" or "ist488".
COURSE_CODE_RE = re.compile(r"\bIST\s*(\d{3})\b", re.IGNORECASE)

CHAT_MODELS = {
    "gpt-5-mini (fast)": "gpt-5-mini",
    "gpt-5.4-mini (fast, newer)": "gpt-5.4-mini",
    "gpt-5.5 (premium)": "gpt-5.5",
}

SYSTEM_PROMPT = """You are a course advisor for the Syracuse University iSchool. \
You answer questions about IST courses using the course syllabi supplied below.

Rules for every answer:
- Lead with one short line saying where the answer comes from. If the syllabi \
below cover the question, write "From the course syllabi:" and name the course \
codes you used. If they do not cover it, write "Not in the course syllabi - \
answering from general knowledge:" instead.
- Only the syllabi below are course material. Never present general knowledge \
as though it came from them.
- Quote or paraphrase the syllabi where it helps, and name the course a fact \
came from.
- If the syllabi only partly cover the question, answer that part from them and \
say plainly what they do not say.
- Keep answers short and readable."""

st.title("Lab 4 — Course Information Chatbot")

st.write(
    "Ask about any of the seven IST course syllabi in this collection. Each "
    "question is embedded and matched against a ChromaDB collection of those "
    "syllabi, and the closest three are added to the prompt sent to the LLM — "
    "so the bot answers from the actual course documents, and says so when it "
    "does."
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


def read_pdf(path):
    """Return the full text of a PDF. extract_text() can return None per page."""
    reader = PdfReader(path)
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def describe(filename):
    """Pull the course code and title out of a filename, for the metadata."""
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
    course, _, title = stem.partition(" Syllabus - ")
    return {
        "filename": filename,
        "course": course.strip(),
        "title": title.strip() or stem,
    }


def chunk_text(text):
    """Split text into overlapping windows of roughly CHUNK_CHARS characters."""
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + CHUNK_CHARS])
        start += CHUNK_CHARS - CHUNK_OVERLAP
    return chunks


def embed(texts):
    """Embed a list of strings with the OpenAI embeddings model."""
    response = get_openai_client().embeddings.create(
        input=texts,
        model=EMBEDDING_MODEL,
    )
    return [item.embedding for item in response.data]


def create_lab4_collection():
    """Build the Lab4Collection ChromaDB collection from the syllabus PDFs.

    Returns (collection, documents) where documents maps filename -> full text.

    The filename is the key throughout: chunk ids are "<filename>::<n>" and
    every chunk carries its filename in metadata, so any chunk can be traced
    back to the syllabus it came from and the full text fetched by that name.

    Embeddings are computed here with OpenAI and handed to Chroma explicitly,
    which means queries must also be made with query_embeddings: passing raw
    query text instead would make Chroma fall back to its own default embedding
    function and silently compare vectors from two different spaces.
    """
    collection = chromadb.Client().get_or_create_collection(name=COLLECTION_NAME)

    filenames = sorted(f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf"))
    documents = {}
    ids, chunks, metadatas = [], [], []
    for filename in filenames:
        text = read_pdf(os.path.join(DATA_DIR, filename))
        if not text.strip():
            st.warning(f"No extractable text in {filename}; skipped.", icon="📄")
            continue
        documents[filename] = text
        meta = describe(filename)
        for i, chunk in enumerate(chunk_text(text)):
            ids.append(f"{filename}::{i}")
            # The course name is prefixed onto the chunk so the course itself is
            # part of what gets embedded, not just the surrounding prose.
            chunks.append(f"[{meta['course']} — {meta['title']}]\n{chunk}")
            metadatas.append(dict(meta, chunk=i))

    # Added in batches to keep each embeddings request a reasonable size.
    for start in range(0, len(ids), 100):
        batch = chunks[start:start + 100]
        collection.add(
            ids=ids[start:start + 100],
            documents=batch,
            metadatas=metadatas[start:start + 100],
            embeddings=embed(batch),
        )
    return collection, documents


def named_courses(query):
    """Course codes explicitly named in the question, e.g. {'IST 488'}."""
    return {f"IST {number}" for number in COURSE_CODE_RE.findall(query)}


def search(collection, documents, query, n_results=TOP_K):
    """Return the syllabi most relevant to a query, best first.

    Chunks are what gets matched, but whole syllabi are what gets returned:
    retrieving at chunk granularity ranks accurately, while handing the model
    the complete syllabus avoids answering "the syllabus doesn't say" just
    because the winning chunk stopped one paragraph short.
    """
    pool = max(1, min(CHUNK_POOL, collection.count()))
    results = collection.query(
        query_embeddings=embed([query]),
        n_results=pool,
        include=["metadatas", "distances"],
    )
    # Chroma returns one list of results per query, so everything is at [0].
    # Collapse chunks to one entry per file, keeping each file's closest chunk.
    ranked = []
    for i, meta in enumerate(results["metadatas"][0]):
        if meta["filename"] not in {hit["filename"] for hit in ranked}:
            ranked.append({
                "filename": meta["filename"],
                "metadata": meta,
                "distance": results["distances"][0][i],
            })

    # Lexical assist for course codes. Pure vector search cannot reliably act
    # on a course number: every syllabus carries near-identical boilerplate, so
    # "what is the attendance policy in IST 488" scores all seven within 0.2 of
    # each other and the right one lands fifth. A question that names a course
    # should always be answered from that course, so named courses are moved to
    # the front and vector hits fill the remaining slots. No-op for questions
    # that name no course, which is the common case.
    wanted = named_courses(query)
    if wanted:
        by_course = {hit["metadata"]["course"].upper(): hit for hit in ranked}
        named = []
        for course in sorted(wanted):
            hit = by_course.get(course)
            if hit is None:
                # The course was named but none of its chunks made the pool.
                match = next(
                    (f for f in documents if describe(f)["course"].upper() == course),
                    None,
                )
                if match:
                    hit = {
                        "filename": match,
                        "metadata": describe(match),
                        "distance": None,
                    }
            if hit:
                named.append(hit)
        chosen = {hit["filename"] for hit in named}
        ranked = named + [hit for hit in ranked if hit["filename"] not in chosen]

    hits = ranked[:n_results]
    for hit in hits:
        hit["document"] = documents.get(hit["filename"], "")[:PARENT_MAX_CHARS]
    return hits


def build_context(hits):
    """Format the retrieved syllabi for the prompt."""
    blocks = []
    for hit in hits:
        meta = hit["metadata"]
        blocks.append(
            f"--- SYLLABUS: {meta['course']} — {meta['title']} "
            f"(file: {meta['filename']}) ---\n{hit['document']}"
        )
    return "\n\n".join(blocks)


def build_messages(hits, history):
    """System prompt with the retrieved syllabi, plus the recent chat window."""
    system = SYSTEM_PROMPT + "\n\nCOURSE SYLLABI RETRIEVED FOR THIS QUESTION:\n\n"
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


# Build the vector database exactly once per session. Rebuilding it on every
# interaction would re-embed all seven syllabi, and re-bill, on every rerun.
if "Lab4_VectorDB" not in st.session_state:
    with st.spinner("Building the Lab4Collection vector database..."):
        collection, documents = create_lab4_collection()
        st.session_state.Lab4_VectorDB = collection
        st.session_state.Lab4_Documents = documents

collection = st.session_state.Lab4_VectorDB
documents = st.session_state.Lab4_Documents

with st.sidebar:
    st.header("Model")
    choice = st.selectbox("Which LLM?", list(CHAT_MODELS))
    model = CHAT_MODELS[choice]
    st.caption(f"Chat: `{model}`")
    st.caption(f"Embeddings: `{EMBEDDING_MODEL}`")

    st.header("Collection")
    st.caption(
        f"`{COLLECTION_NAME}` — {len(documents)} syllabi, "
        f"{collection.count()} chunks indexed"
    )

    if st.button("Clear conversation"):
        st.session_state.lab4_messages = []

if "lab4_messages" not in st.session_state:
    st.session_state.lab4_messages = []

for message in st.session_state.lab4_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about the IST courses..."):
    st.session_state.lab4_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.spinner("Searching the syllabi..."):
        hits = search(collection, documents, prompt)

    client = get_openai_client()
    stream = client.chat.completions.create(
        model=model,
        messages=build_messages(hits, st.session_state.lab4_messages),
        stream=True,
    )

    with st.chat_message("assistant"):
        response = st.write_stream(text_chunks(stream))
        if hits:
            with st.expander(f"Syllabi retrieved for this question ({len(hits)})"):
                for i, hit in enumerate(hits, start=1):
                    meta = hit["metadata"]
                    distance = (
                        "named in question" if hit["distance"] is None
                        else f"distance {hit['distance']:.3f}"
                    )
                    st.markdown(
                        f"{i}. **{meta['course']} — {meta['title']}** "
                        f"(`{meta['filename']}`, {distance})"
                    )

    st.session_state.lab4_messages.append({"role": "assistant", "content": response})
