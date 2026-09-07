import requests
import streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI

SUMMARY_STYLES = {
    "100 words": "Summarize the page in exactly 100 words.",
    "2 connecting paragraphs": (
        "Summarize the page in exactly 2 connecting paragraphs, where the "
        "second paragraph flows naturally from the first."
    ),
    "5 bullet points": "Summarize the page in exactly 5 bullet points.",
}

LANGUAGES = ["English", "Spanish", "French", "German", "Hindi", "Urdu", "Chinese", "Arabic"]

OPENROUTER_URL = "https://openrouter.ai/api/v1"

PROVIDERS = {
    "OpenAI": {
        "secret": "OPENAI_API_KEY",
        "base_url": None,
        "basic": "gpt-5-nano",
        "advanced": "gpt-5-mini",
    },
    "Claude (via OpenRouter)": {
        "secret": "OPENROUTER_API_KEY",
        "base_url": OPENROUTER_URL,
        "basic": "anthropic/claude-haiku-4.5",
        "advanced": "anthropic/claude-sonnet-5",
    },
    "Gemini (via OpenRouter)": {
        "secret": "OPENROUTER_API_KEY",
        "base_url": OPENROUTER_URL,
        "basic": "google/gemini-2.5-flash",
        "advanced": "google/gemini-2.5-pro",
    },
}

MAX_CHARS = 40_000

BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IST688-HW2/1.0)"}

st.title("HW 2 — URL Summarizer")
st.write(
    "Paste a URL below and pick a summary style, an output language, and an LLM "
    "in the sidebar."
)

url = st.text_input("URL to summarize", placeholder="https://example.com/article")

with st.sidebar:
    st.header("Summary options")
    language = st.selectbox("Output language", LANGUAGES)
    summary_style = st.selectbox("Type of summary", list(SUMMARY_STYLES))
    provider_name = st.selectbox("LLM", list(PROVIDERS))
    use_advanced = st.checkbox(
        "Use advanced model",
        help="Unchecked uses the provider's cheaper model; checked uses its stronger one.",
    )

provider = PROVIDERS[provider_name]
model = provider["advanced"] if use_advanced else provider["basic"]
st.sidebar.caption(f"Model: `{model}`")


def secret(name):
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return None


def read_url_content(url):
    try:
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        return soup.get_text()
    except requests.RequestException as e:
        print(f"Error reading {url}: {e}")
        return None


def text_chunks(stream):
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


if url:
    api_key = secret(provider["secret"])
    if not api_key:
        st.error(
            f"No `{provider['secret']}` found in secrets, so **{provider_name}** "
            "can't be used. Add it to `.streamlit/secrets.toml` or pick another LLM.",
            icon="🗝️",
        )
        st.stop()

    document = read_url_content(url)

    if document is None:
        st.error(
            "Couldn't read that URL. Check the address (including the `https://`) "
            "and that the page is publicly reachable.",
            icon="🔗",
        )
        st.stop()

    if not document.strip():
        st.error(
            "That page had no readable text. Pages that render entirely through "
            "JavaScript come back empty, so try a different URL.",
            icon="📄",
        )
        st.stop()

    if len(document) > MAX_CHARS:
        document = document[:MAX_CHARS]
        st.caption(f"Long page — only the first {MAX_CHARS:,} characters were summarized.")

    client = OpenAI(api_key=api_key, base_url=provider["base_url"])

    messages = [
        {
            "role": "user",
            "content": (
                f"Here's the text of a web page:\n\n{document}\n\n---\n\n"
                f"{SUMMARY_STYLES[summary_style]} "
                f"Write the summary in {language}."
            ),
        }
    ]

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
    )

    st.subheader(f"Summary ({summary_style}, in {language})")
    st.write_stream(text_chunks(stream))
