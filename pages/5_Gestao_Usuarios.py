import streamlit as st
import pandas as pd
from datetime import date, timedelta
import numpy as np
import io

from core.api_client import (
    fetch_agendamentos,
    list_profissionals,
    list_unidades,
    list_especialidades,
    fetch_horarios_disponiveis,
    get_main_specialty_id,
    list_blocks
)

if not st.session_state.get("logged_in", False):
    st.switch_page("Home.py")   # Redireciona para login
    st.stop()

st.set_page_config(page_title="Gestão de Usuários", page_icon="📆", layout="wide")

st.title("🤵‍♀️ Gestão de usuários")
st.subheader("Em breve...")

df_blocks = list_blocks(start_date='19-01-2026', end_date='24-01-2026')

st.write(df_blocks)

id_medico = st.text_input("Insira o ID do médico para ver seus agendamentos:", value="")

df_profissionals = list_profissionals()

if id_medico:
    st.write(df_profissionals[df_profissionals['profissional_id'] == int(id_medico)])