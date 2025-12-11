import streamlit as st

if not st.session_state.get("logged_in", False):
    st.switch_page("Home.py")   # Redireciona para login
    st.stop()
