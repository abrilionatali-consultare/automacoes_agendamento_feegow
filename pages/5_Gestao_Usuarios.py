import streamlit as st

if not st.session_state.get("logged_in", False):
    st.switch_page("Home.py")   # Redireciona para login
    st.stop()

st.set_page_config(page_title="Gestão de Usuários", page_icon="📆", layout="wide")

st.title("🤵‍♀️ Gestão de usuários")
st.subheader("Em breve...")