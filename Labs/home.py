import streamlit as st

st.title("IST 688 — Lab Applications")
st.write(
    "Each lab is a separate page in this app. "
)

st.subheader("Labs")
st.markdown(
    """
- **Lab 1** — Document question answering. Upload a `.txt` or `.md` file and ask a
  question about it.
- **Lab 2** — Document summarizer. Upload a `.pdf`, `.txt`, or `.md` file and choose a
  summary style and output language in the sidebar.
- **Lab 3** — Creating an AI chat bot.
- **Lab 4** — Course information chatbot. Answers questions about seven IST course
  syllabi by retrieving the closest ones from a ChromaDB vector database and adding
  them to the prompt (RAG).
- **Lab 5** — The "What to Wear" bot. Enter a city and get clothing and outdoor
  activity advice for today. The LLM calls a weather tool (live data from wttr.in)
  when it needs the forecast.
"""
)
