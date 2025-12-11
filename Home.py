import streamlit as st
import os
from dotenv import load_dotenv
from streamlit_cookies_manager import EncryptedCookieManager
from login_page import login_page

load_dotenv()

# Tenta pegar dos secrets (Cloud), se falhar tenta do OS (Local com .env), se falhar usa string vazia
COOKIES_SECRET = st.secrets.get("STREAMLIT_COOKIES_MANAGER_SECRET", os.getenv("STREAMLIT_COOKIES_MANAGER_SECRET"))

st.set_page_config(page_icon='🏠', layout='centered', page_title='Relatório de Agendamentos')

# --- Inicializa cookies apenas uma vez --- 
if "cookies" not in st.session_state:
    cookies = EncryptedCookieManager(
        prefix="feegow_dashboard_",
        password=COOKIES_SECRET
    )
    if not cookies.ready():
        st.stop()
    st.session_state["cookies"] = cookies

cookies = st.session_state["cookies"]

# --- Validação de login ---
if cookies.get("logged_in") == "true":
    st.session_state["logged_in"] = True
    st.session_state["username"] = cookies.get("username")
    st.session_state["role"] = cookies.get("role")

# Se não estiver logado → página de login
if not st.session_state.get("logged_in"):
    login_page()
    st.stop()

# Sidebar
st.sidebar.write(f"👋 Olá, {st.session_state['username']}")

if st.sidebar.button("Sair"):
    cookies["logged_in"] = ""
    cookies["username"] = ""
    cookies["role"] = ""
    cookies.save()

    st.session_state.clear()
    st.rerun()

# Conteúdo
st.write("# Bem-vindo ao sistema!")
st.write("Selecione uma página no menu ao lado.")
