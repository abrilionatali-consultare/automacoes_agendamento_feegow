import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
from core.api_client import (
    fetch_agendamentos,
    fetch_horarios_disponiveis,
    list_profissionals,
    list_salas,
    list_especialidades,
    list_unidades,
    get_main_specialty_id
)

if not st.session_state.get("logged_in", False):
    st.switch_page("Home.py")   # Redireciona para login
    st.stop()

st.set_page_config(page_title="Mapa mensal", page_icon="📆", layout="wide")

st.title("📅 Gerar Mapa de Salas - Mensal")
st.subheader("Em breve...")

st.divider()

st.write(list_unidades())

df_agendamentos = fetch_agendamentos(
    unidade_id=12,
    start_date='06-01-2026',
    end_date='06-01-2026'
)

st.write(df_agendamentos[df_agendamentos['profissional_id'] == 2365])

st.dataframe(data=list_profissionals())

st.write("Especialidade:", get_main_specialty_id(2365))
especialidades = list_especialidades()

st.write(especialidades[especialidades['especialidade_id'] == get_main_specialty_id(2365)])

vagas_livres = fetch_horarios_disponiveis(
    profissional_id=2365,
    unidade_id=12,
    data_start='06-01-2026',
    data_end='07-01-2026',
    tipo='P',
    procedimento_id=31
)

st.write("Vagas livres: ", len(vagas_livres))