import streamlit as st
from openai import OpenAI
import numpy as np
import tiktoken

# Title
st.title("Lab 3 — Creating an AI Chat Bot")

# Check if OPENAI_API_KEY is present in secrets.toml
if "OPENAI_API_KEY" not in st.secrets:
    st.error(
        "No OPENAI_API_KEY found.",
        icon="🗝️",
    )
    st.stop()

# Creating the option to pick a model
openAI_model = st.sidebar.selectbox("Which Model?",
                                    ("mini", "regular"))
if openAI_model == "mini":
    model = "gpt-4o-mini"
else:
    model = "gpt-4o"

max_tokens = st.sidebar.number_input(
    "Max tokens for buffer",
    min_value=100,
    max_value=8000,
    value=1000,
    step=100,
)

# Create an OpenAI client
if "client" not in st.session_state:
    api_key = st.secrets["OPENAI_API_KEY"]
    st.session_state.client = OpenAI(api_key=api_key)

SYSTEM_PROMPT = (
    "You are a friendly helpful assistant. Explain every answer so that a "
    "10 year old could easily understand it, using short sentences and "
    "simple everyday words. After you answer the user's question, always "
    "ask exactly: 'Do you want more info?' If the user answers yes, give "
    "more simple information about the same topic and ask 'Do you want "
    "more info?' again. If the user answers no, stop giving more info on "
    "that topic and ask what else you can help with."
)

# Check if any previous messages exist in the session state, if not initialize an empty list
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

def get_encoding(model_name):
    try:
        return tiktoken.encoding_for_model(model_name)
    except KeyError:
        return tiktoken.get_encoding("o200k_base")

def count_tokens(messages, model_name):
    encoding = get_encoding(model_name)
    return sum(len(encoding.encode(m["content"])) for m in messages)

def build_buffer(messages, max_turns, max_tokens, model_name):
    system_messages = [m for m in messages if m["role"] == "system"]
    other_messages = [m for m in messages if m["role"] != "system"]
    other_messages = other_messages[-(max_turns * 2):]
    while other_messages and count_tokens(system_messages + other_messages, model_name) > max_tokens:
        other_messages.pop(0)
    return system_messages + other_messages

# Display previous messages in the chat
for message in st.session_state.messages:
    if message["role"] == "system":
        continue
    chat_message = st.chat_message(message["role"])
    chat_message.write(message["content"])

# Reacting to user input
if prompt := st.chat_input("Type your message here..."):
    # Display user message in chat message container
    #chat_message = st.chat_message("user")
    #chat_message.write(prompt)

    # Add user message to session state
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    client = st.session_state.client
    buffered_messages = build_buffer(st.session_state.messages, 2, max_tokens, model)
    stream = client.chat.completions.create(
        model=model,
        messages=buffered_messages,
        stream=True
        )
    with st.chat_message("assistant"):
        response = st.write_stream(stream)

    # Add assistant message to session state
    st.session_state.messages.append({"role": "assistant", "content": response})