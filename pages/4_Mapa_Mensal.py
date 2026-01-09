import streamlit as st
from core.api_client import fetch_agendamentos, fetch_horarios_disponiveis, list_salas

if not st.session_state.get("logged_in", False):
    st.switch_page("Home.py")   # Redireciona para login
    st.stop()

st.set_page_config(page_title="Mapa mensal", page_icon="📆", layout="wide")

st.title("📅 Gerar Mapa de Salas - Mensal")
st.subheader("Em breve...")

st.subheader("Salas")
df_salas = list_salas()
selected_sala = st.selectbox("Selecione a sala:", options=[2, 3, 12])
filtered_salas = df_salas[df_salas['unidade_id'] == selected_sala]
st.write(filtered_salas)

st.write(filtered_salas['local'].unique().tolist())

salas_remover = ['PRÉ ATENDIMENTO', 'COLETA DOMICILIAR', "TELEMEDICINA"]
total_salas_unid = filtered_salas[~filtered_salas['local'].str.upper().isin(salas_remover)]['local'].unique().tolist()
st.write(total_salas_unid)

