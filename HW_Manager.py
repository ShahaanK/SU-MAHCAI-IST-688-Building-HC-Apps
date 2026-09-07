import streamlit as st

st.set_page_config(
    page_title="HW Manager",
    page_icon="📝",
    layout="centered",
    initial_sidebar_state="expanded",
    menu_items=None)

hw_1_page = st.Page(
    'HW/HW1.py',
    title="HW 1",
    icon="📄",
    default=False
    )
hw_2_page = st.Page(
    'HW/HW2.py',
    title="HW 2",
    icon="🔗",
    default=True
    )
pgs = st.navigation(
    [
        hw_1_page,
        hw_2_page,
    ]
)


pgs.run()
