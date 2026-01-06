import streamlit as st
from core.api_client import fetch_agendamentos, fetch_horarios_disponiveis

if not st.session_state.get("logged_in", False):
    st.switch_page("Home.py")   # Redireciona para login
    st.stop()

st.set_page_config(page_title="Mapa mensal", page_icon="📆", layout="wide")

st.title("📅 Gerar Mapa de Salas - Mensal")
st.subheader("Em breve...")
