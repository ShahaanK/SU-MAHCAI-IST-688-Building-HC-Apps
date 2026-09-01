import streamlit as st

# Show title and description.
st.title("My Document question answering")
st.write(
    "Upload a document below and ask a question about it – GPT will answer! "
    "To use this app, you need to provide an OpenAI API key, which you can get [here](https://platform.openai.com/account/api-keys). "
)

st.set_page_config(
    page_title="Base", 
    page_icon="📄", 
    layout="centered", 
    initial_sidebar_state="expanded", 
    menu_items=None)

lab_1_page = st.Page(
    'Labs\\Lab 1\\szkhan-Lab-1.py',
    title= "Bob",
    icon= "📄",
    default=False
    )
lab_2_page = st.Page(
    'Labs\\Lab 2\\szkhan-Lab-2.py',
    title= "Bob",
    icon= "📄",
    default=False
    )
pgs = st.navigation(
    [
        lab_1_page,
        lab_2_page,
    ],
    default=lab_1_page,
    title="Labs",
    icon="📄",
)

st.set_page_config(
    page_title="Base",
    page_icon="📄")

pgs.run()