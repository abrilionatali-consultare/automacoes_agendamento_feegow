import streamlit as st
import pandas as pd
from datetime import date, timedelta
import numpy as np
import io

from core.api_client import (
    list_procedure_types,
    list_procedures
)

st.set_page_config(page_title="Relatório de Intervalos", page_icon="⏱️", layout="wide")

df_procedures = list_procedures()
df_types = list_procedure_types()
cols = ['procedimento_id', 'tipo_procedimento', 'nome']
df_procedures['procedimento_id'] = df_procedures['procedimento_id'].astype(int)
procedure_map = {
    0: 'Indefinido',
    1: 'Cirurgia',
    2: 'Consulta',
    3: 'Exame',
    4: 'Procedimento',
    9: 'Retorno',
    11: 'Vacina',
    12: 'Outras terapias    '
}

df_ = df_procedures[cols]

df_['tipo_procedimento'] = df_['tipo_procedimento'].map(procedure_map)

st.dataframe(df_)