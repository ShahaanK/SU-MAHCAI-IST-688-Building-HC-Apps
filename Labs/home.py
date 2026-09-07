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
"""
)
