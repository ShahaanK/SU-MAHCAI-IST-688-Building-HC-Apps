import streamlit as st
from openai import OpenAI
from pypdf import PdfReader

# The three summary styles 
SUMMARY_STYLES = {
    "100 words": "Summarize the document in exactly 100 words.",
    "2 connecting paragraphs": (
        "Summarize the document in exactly 2 connecting paragraphs, where the "
        "second paragraph flows naturally from the first."
    ),
    "5 bullet points": "Summarize the document in exactly 5 bullet points.",
}

LANGUAGES = ["English", "Spanish", "French", "German", "Hindi", "Urdu", "Chinese", "Arabic"]

BASIC_MODEL = "gpt-5-nano"
ADVANCED_MODEL = "gpt-5-mini"

st.title("Lab 2 — Document Summarizer")
st.write(
    "Upload a PDF, text, or Markdown file and pick a summary style in the sidebar. "
)

# Part B
try:
    openai_api_key = st.secrets["OPENAI_API_KEY"]
except KeyError:
    st.error(
        "No OPENAI_API_KEY found.",
        icon="🗝️",
    )
    st.stop()

client = OpenAI(api_key=openai_api_key)

# Part C
with st.sidebar:
    st.header("Summary options")
    language = st.selectbox("Output language", LANGUAGES)
    summary_style = st.selectbox("Type of summary", list(SUMMARY_STYLES))
    use_advanced = st.checkbox(
        "Use advanced model",
        help=f"Unchecked uses {BASIC_MODEL}; checked uses the stronger {ADVANCED_MODEL}.",
    )

model = ADVANCED_MODEL if use_advanced else BASIC_MODEL
st.sidebar.caption(f"Model: `{model}`")


def extract_text(file) -> str:
    """Pull plain text out of an uploaded PDF, .txt, or .md file."""
    if file.name.lower().endswith(".pdf"):
        reader = PdfReader(file)
        # extract_text() returns None on pages with no text layer (e.g. scans),
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return file.read().decode()


uploaded_file = st.file_uploader(
    "Upload a document (.pdf, .txt, or .md)", type=("pdf", "txt", "md")
)

# No question box any more
if uploaded_file:
    document = extract_text(uploaded_file)

    if not document.strip():
        st.error(
            "No text could be read from that file. A scanned PDF has no text layer, "
            "so try a text-based PDF instead.",
            icon="📄",
        )
        st.stop()

    messages = [
        {
            "role": "user",
            "content": (
                f"Here's a document:\n\n{document}\n\n---\n\n"
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
    st.write_stream(stream)
