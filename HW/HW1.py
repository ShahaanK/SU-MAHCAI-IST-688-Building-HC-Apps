import streamlit as st
from openai import OpenAI, AuthenticationError, APIError
import pymupdf


def validate_api_key(api_key):
    # Validate the OpenAI API key 
    try:
        client = OpenAI(api_key=api_key)
        client.models.list()
        return True
    except AuthenticationError:
        return False
    except APIError:
        return True


def read_pdf(uploaded_file):
    """Extract text from an uploaded PDF file."""
    doc = pymupdf.open(stream=uploaded_file.read(), filetype="pdf")
    document = ""
    for page in doc:
        document += page.get_text()
    doc.close()
    return document

# Show title and description.
st.title("My Document question answering")
st.write(
    "Upload a document below and ask a question about it – GPT will answer! "
    "To use this app, you need to provide an OpenAI API key, which you can get [here](https://platform.openai.com/account/api-keys). "
)


# Ask user for their OpenAI API key via `st.text_input`.
# Alternatively, you can store the API key in `./.streamlit/secrets.toml` and access it
# via `st.secrets`, see https://docs.streamlit.io/develop/concepts/connections/secrets-management
openai_api_key = st.text_input("OpenAI API Key", type="password")
if not openai_api_key:
    st.info("Please add your OpenAI API key to continue.", icon="🗝️")
elif not validate_api_key(openai_api_key):
    st.error(
        "That doesn't look like a valid OpenAI API key. "
        "Please check it and enter a valid key to continue.",
    )
else:

    # Create an OpenAI client.
    client = OpenAI(api_key=openai_api_key)

    # Let the user upload a file via `st.file_uploader`. Only allow .txt, and .pdf files.
    uploaded_file = st.file_uploader(
        "Upload a document (.txt, or .pdf)", type=("txt",  "pdf")
    )

    # Ask the user for a question via `st.text_area`.
    question = st.text_area(
        "Now ask a question about the document!",
        placeholder="Can you give me a short summary?",
        disabled=not uploaded_file,
    )

    if uploaded_file and question:
        # Determine the file type from its extension.
        file_extension = uploaded_file.name.split('.')[-1]
        document = None
        if file_extension == 'txt':
            document = uploaded_file.read().decode()
        elif file_extension == 'pdf':
            document = read_pdf(uploaded_file)
        else:
            st.error("Unsupported file type.")

    if uploaded_file and question and document is not None:
        messages = [
            {
                "role": "user",
                "content": f"Here's a document: {document} \n\n---\n\n {question}",
            }
        ]

        # We are going to have 4 different models 
        # (gpt-3.5, gpt-4.1, gpt-5, gpt-5-nano) and the
        # output will have all 4 outputs.
        # Generate an answer using the OpenAI API for each of the 4 models 
        # and stream the response to the app using `st.write_stream`.
        stream = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            stream=True,
        )
        # Second model
        stream2 = client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            stream=True,
        )
        # Third model
        stream3 = client.chat.completions.create(
            model="gpt-5",
            messages=messages,
            stream=True,
        )
        # Fourth model
        stream4 = client.chat.completions.create(
            model="gpt-5-nano",
            messages=messages,
            stream=True,
        )

        # Stream the response to the app using `st.write_stream`.
        st.subheader("GPT-3.5")
        st.write_stream(stream)
        st.subheader("GPT-4.1")
        st.write_stream(stream2)
        st.subheader("GPT-5")
        st.write_stream(stream3)
        st.subheader("GPT-5-Nano")
        st.write_stream(stream4)
