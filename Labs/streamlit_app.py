import streamlit as st

st.set_page_config(
    page_title="IST 688 Labs", 
    page_icon="📄", 
    layout="centered", 
    initial_sidebar_state="expanded", 
    menu_items=None)

home_page = st.Page(
    'home.py',
    title="Home",
    icon="🏠",
    default=False
    )
lab_1_page = st.Page(
    'Lab 1/Lab1.py',
    title= "Lab 1",
    icon= "📄",
    default=False
    )
lab_2_page = st.Page(
    'Lab 2/Lab2.py',
    title= "Lab 2",
    icon= "📄",
    default=True
    )
pgs = st.navigation(
    [
        home_page,
        lab_1_page,
        lab_2_page,
    ]
)


pgs.run()