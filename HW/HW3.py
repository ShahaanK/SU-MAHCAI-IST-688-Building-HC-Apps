import requests
import streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI

# Two vendors. Each offers its current premium (flagship) model, which is what
# the homework asks for, plus a cheaper/faster model for quick testing.
OPENROUTER_URL = "https://openrouter.ai/api/v1"

MODELS = {
    "OpenAI — GPT-5.5 (premium)": {
        "secret": "OPENAI_API_KEY",
        "base_url": None,
        "model": "gpt-5.5",
    },
    "OpenAI — GPT-5.4 mini (fast)": {
        "secret": "OPENAI_API_KEY",
        "base_url": None,
        "model": "gpt-5.4-mini",
    },
    "Anthropic — Claude Opus 5 (premium)": {
        "secret": "OPENROUTER_API_KEY",
        "base_url": OPENROUTER_URL,
        "model": "anthropic/claude-opus-5",
    },
    "Anthropic — Claude Haiku 4.5 (fast)": {
        "secret": "OPENROUTER_API_KEY",
        "base_url": OPENROUTER_URL,
        "model": "anthropic/claude-haiku-4.5",
    },
}

# How many past chat messages are kept. 6 messages = 3 user/assistant exchanges.
BUFFER_MESSAGES = 6

# Per-document cap, so two long pages still leave room in the context window.
MAX_CHARS = 20_000

BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IST688-HW3/1.0)"}

st.title("HW 3 — Chat About a URL")

st.write(
    "Add up to two URLs in the sidebar and pick an LLM, then ask questions about "
    "those pages in the chat below. The answers stream in token by token.\n\n"
    "**How the memory works.** The text of every URL you supply is packed into a "
    "system prompt that is rebuilt and re-sent on every single turn, so the "
    "documents are *never* discarded no matter how long the conversation runs. "
    "The conversation itself uses a **buffer of the last 6 messages — 3 "
    "user/assistant exchanges**. Once the chat grows past that, the oldest "
    "exchange is dropped from what the model sees, so the bot remembers your most "
    "recent three back-and-forths plus the full documents, but nothing older. If "
    "that cut would leave a reply whose question was dropped, the orphaned reply "
    "is trimmed too, so the window always starts on one of your messages. The "
    "transcript on screen still shows everything you have said; only what gets "
    "sent to the model is trimmed."
)


@st.cache_data(show_spinner=False)
def read_url_content(url):
    """Fetch a page and return its visible text. Re-used from HW 2."""
    try:
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        return soup.get_text()
    except requests.RequestException as e:
        print(f"Error reading {url}: {e}")
        return None


def secret(name):
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return None


def build_system_prompt(documents):
    """Build the system message that carries the URL text. Rebuilt every turn."""
    parts = [
        "You are a helpful assistant who answers questions about the web pages "
        "given below. Ground every answer in those pages and quote or paraphrase "
        "them where it helps. If the pages do not cover something the user asks "
        "about, say so plainly instead of inventing an answer, then offer what "
        "the pages do say. Explain things simply, as if to someone new to the "
        "topic, and keep answers reasonably short."
    ]
    for i, (url, text) in enumerate(documents, start=1):
        parts.append(f"--- DOCUMENT {i} (source: {url}) ---\n{text}")
    return {"role": "system", "content": "\n\n".join(parts)}


def build_messages(documents, history):
    """System prompt (never dropped) + the last BUFFER_MESSAGES chat messages."""
    buffered = history[-BUFFER_MESSAGES:]
    # If the cut lands mid-exchange it leaves an assistant reply whose question
    # was dropped, so trim that orphan and start the window on a user turn.
    while buffered and buffered[0]["role"] != "user":
        buffered.pop(0)
    return [build_system_prompt(documents)] + buffered


def text_chunks(stream):
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


with st.sidebar:
    st.header("Sources")
    url_1 = st.text_input("URL 1", placeholder="https://example.com/page")
    url_2 = st.text_input("URL 2 (optional)", placeholder="https://example.com/other")

    st.header("Model")
    choice = st.selectbox("Which LLM?", list(MODELS))

    if st.button("Clear conversation"):
        st.session_state.messages = []

config = MODELS[choice]
st.sidebar.caption(f"Model: `{config['model']}`")

# Load whichever URLs were supplied, reporting on each one in the sidebar.
documents = []
for url in (url_1, url_2):
    url = url.strip()
    if not url:
        continue
    text = read_url_content(url)
    if text is None:
        st.sidebar.error(f"Couldn't read {url}", icon="🔗")
        continue
    if not text.strip():
        st.sidebar.error(f"No readable text at {url}", icon="📄")
        continue
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        st.sidebar.caption(f"Trimmed {url} to the first {MAX_CHARS:,} characters.")
    documents.append((url, text))

if documents:
    st.sidebar.success(f"Using {len(documents)} document(s) as context.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if not documents:
    st.info("Add at least one URL in the sidebar to start chatting.", icon="👈")

prompt = st.chat_input(
    "Ask something about the page(s)...",
    disabled=not documents,
)

if prompt:
    api_key = secret(config["secret"])
    if not api_key:
        st.error(
            f"No `{config['secret']}` found in secrets, so **{choice}** can't be "
            "used. Add it to `.streamlit/secrets.toml` or pick the other model.",
            icon="🗝️",
        )
        st.stop()

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    client = OpenAI(api_key=api_key, base_url=config["base_url"])
    stream = client.chat.completions.create(
        model=config["model"],
        messages=build_messages(documents, st.session_state.messages),
        stream=True,
    )

    with st.chat_message("assistant"):
        response = st.write_stream(text_chunks(stream))

    st.session_state.messages.append({"role": "assistant", "content": response})
