import streamlit as st
from openai import OpenAI

# Show title and description.
st.title("My Document question answering")
st.write(
    "Upload a document below and ask a question about it – GPT will answer! "
    "Supply your own OpenAI API key, or press the button to use the app's key."
)

# Session state is shared across pages in a multi-page app, so this flag is
# namespaced with a `lab1_` prefix to keep it from colliding with other pages.
if "lab1_use_app_key" not in st.session_state:
    st.session_state.lab1_use_app_key = False


def app_key() -> str | None:
    """The key from Streamlit secrets, or None if secrets aren't configured.

    StreamlitSecretNotFoundError subclasses FileNotFoundError and is raised when
    there's no secrets.toml at all; KeyError means the file exists but has no
    OPENAI_API_KEY entry.
    """
    try:
        return st.secrets["OPENAI_API_KEY"]
    except (KeyError, FileNotFoundError):
        return None


if st.session_state.lab1_use_app_key:
    openai_api_key = app_key()
    st.success("Using the app's OpenAI key.", icon="🔑")
    if st.button("Use my own key instead"):
        st.session_state.lab1_use_app_key = False
        st.rerun()
else:
    # Ask user for their OpenAI API key via `st.text_input`.
    openai_api_key = st.text_input("OpenAI API Key", type="password")
    has_app_key = app_key() is not None
    if st.button("Use the app's key instead", disabled=not has_app_key):
        st.session_state.lab1_use_app_key = True
        st.rerun()
    if not has_app_key:
        st.caption("No app key is configured in secrets, so that button is disabled.")

if not openai_api_key:
    st.info("Please add your OpenAI API key to continue.", icon="🗝️")
else:

    # Create an OpenAI client.
    client = OpenAI(api_key=openai_api_key)

    # Let the user upload a file via `st.file_uploader`.
    uploaded_file = st.file_uploader(
        "Upload a document (.txt or .md)", type=("txt", "md")
    )

    # Ask the user for a question via `st.text_area`.
    question = st.text_area(
        "Now ask a question about the document!",
        placeholder="Can you give me a short summary?",
        disabled=not uploaded_file,
    )

    if uploaded_file and question:

        # Process the uploaded file and question.
        document = uploaded_file.read().decode()
        messages = [
            {
                "role": "user",
                "content": f"Here's a document: {document} \n\n---\n\n {question}",
            }
        ]

        # Generate an answer using the OpenAI API.
        stream = client.chat.completions.create(
            model="gpt-5-nano",
            messages=messages,
            stream=True,
        )

        # Stream the response to the app using `st.write_stream`.
        st.write_stream(stream)
