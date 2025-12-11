import io
import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
from core.api_client import (
    fetch_agendamentos,
    list_profissionals,
    list_salas,
    list_especialidades,
    list_unidades
)

st.set_page_config(page_title="Agendamentos", page_icon="📅", layout="wide")

if not st.session_state.get("logged_in", False):
    st.switch_page("Home.py")   # Redireciona para login
    st.stop()

st.title("📅 Agendamentos Feegow")
st.write("Use os filtros abaixo para consultar os agendamentos.")

# ===============================================
# IMPORTAÇÃO DADOS
# ===============================================
df_prof = list_profissionals()
df_esp = list_especialidades()
df_salas = list_salas()
df_unid = list_unidades()

# ===============================================
# FILTROS
# ===============================================

# Datas
col1, col2, Col3, Col4 = st.columns(4)
with col1:
    data_inicio = st.date_input("Data inicial", value=date.today(), format='DD/MM/YYYY')
    start_date = data_inicio.strftime("%d-%m-%Y")

with col2:
    data_fim = st.date_input("Data final", value=date.today() + timedelta(days=1), format='DD/MM/YYYY')
    end_date = data_fim.strftime("%d-%m-%Y")
    
with Col3:
    # Unidades
    unidade_sel = st.selectbox('Unidade', options=["Todas"] + list(df_unid['nome_fantasia']))

with Col4:
    # Salas
    salas = df_salas[['id', 'local']].sort_values('local')
    salas_dict = dict(zip(salas['local'], salas['id']))
    salas_sel = st.selectbox("Consultório", options=["Todos"] + list(salas_dict.keys()))



col1, col2, col3= st.columns(3)
with col1:
    # Profissional
    profissionais = df_prof[["profissional_id", "nome"]].sort_values("nome")
    prof_dict = dict(zip(profissionais['nome'], profissionais['profissional_id']))
    prof_sel = st.selectbox("Profissional", options=["Todos"] + list(prof_dict.keys()))
with col2:
    # Especialidade
    especialidades = df_esp[['especialidade_id', 'nome']].sort_values('nome')
    esp_dict = dict(zip(especialidades['nome'], especialidades['especialidade_id']))
    esp_sel = st.selectbox("Especialidade", options=["Todas"] + list(esp_dict.keys()))

# Status
status = {
    1: 'MARCADO - NÃO CONFIRMADO',
    2: 'EM ANDAMENTO',
    3: 'ATENDIDO',
    4: 'EM ATENDIMENTO/AGUARDANDO',
    6: 'NÃO COMPARECEU',
    7: 'MARCADO - CONFIRMADO',
    11: 'DESMARCADO PELO PACIENTE',
    15: 'REMARCADO',
    16: 'DESMARCADO PELO PROFISSIONAL',
    22: 'CANELADO PELO PROFISSIONAL'
}

with col3:
    status_default = ['Todos']
    status_dict = dict(zip(status.values(), status.keys()))
    status_sel = st.multiselect("Status do agendamento", options=['Todos'] + list(status.values()), default=status_default, 
                                width="stretch", placeholder='Selecione o status do agendamento')

if data_fim < data_inicio:
        st.warning("A data final deve ser maior ou igual à inicial.")
        st.stop()

# ===============================================
# BOTÃO PARA BUSCAR DADOS
# ===============================================
if st.button("🔍 Buscar agendamentos"):
    with st.spinner("Carregandos dados do Feegow..."):      
        if unidade_sel != 'Todas':
            unidade_id = df_unid.loc[df_unid['nome_fantasia'] == unidade_sel, 'unidade_id'].iloc[0]
        else:
            unidade_id = None

        df = fetch_agendamentos(
            unidade_id=unidade_id,
            start_date=start_date,
            end_date=end_date
        )

        if df.empty:
            st.warning("Nenhum agendamento encontrado para os filtros selecionados.")
            st.stop()

        # Filtros adicionais
        if prof_sel != "Todos":
            df = df[df['profissional_id'] == prof_dict[prof_sel]]

        if esp_sel != "Todas":
            df = df[df["especialidade_id"] == esp_dict[esp_sel]]

        if status_sel != ["Todos"]:
            selected_status = [status_dict[i] for i in status_sel]
            df = df[df['status_id'].isin(selected_status)]

        if salas_sel != "Todos":
            df = df[df['local_id'] == salas_dict[salas_sel]]

        if unidade_sel != "Todas":
            df = df[df['unidade_id'] == unidade_id]

        # Junta nome do profissional
        df = df.merge(df_prof[['profissional_id', 'nome']], on='profissional_id', how='left')
        df.rename(columns={'nome': 'nome_profissional'}, inplace=True)
        
        # Junta especialidade
        df = df.merge(df_esp[['especialidade_id', 'nome']], on='especialidade_id', how='left')
        df.rename(columns={'nome': 'especialidade'}, inplace=True)

        # Junta local (sala)
        df = df.merge(df_salas[['id', 'local']], left_on='local_id', right_on='id', how='left')
        df.rename(columns={'local': 'sala', 'nome_fantasia': 'unidade'}, inplace=True)

        # Junta status
        df['status'] = df['status_id'].map(status)

        colunas_exibir = {
            "agendamento_id": 'ID Agendamento',
            "status": 'Status',
            "data": 'Data',
            "horario": 'Horário',
            "nome_profissional": 'Profissional',
            "especialidade": 'Especialidade',
            "paciente_id": 'ID Paciente',
            "unidade": 'Unidade',
            "sala": 'Sala'
        }

        df.rename(columns=colunas_exibir, inplace=True)

        df = df[colunas_exibir.values()]

        st.success("Busca concluída!")
        st.dataframe(
            df, width='stretch', hide_index=True,
        )

        # EXPORTAR DADOS
        buffer = io.BytesIO()
        df.to_excel(buffer, engine='xlsxwriter', index=False)
        buffer.seek(0)
        st.download_button(
            label="📥 Baixar relatório",
            data=buffer,
            file_name="agendamentos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )