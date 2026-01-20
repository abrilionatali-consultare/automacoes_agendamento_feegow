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

st.set_page_config(page_title="Relatório de Intervalos", page_icon="⏱️", layout="wide")

st.title("⏱️ Intervalos entre Consultas (Raio-X Completo)")
st.markdown("""
Este relatório analisa a grade dos médicos para identificar o tempo de consulta (intervalo).
**Lógica de Análise:**
1.  **Futuro (15 dias):** Busca agendamentos e grades livres.
2.  **Passado (60 dias):** Se não achar nada no futuro, busca histórico de atendimentos.
3.  **Resultado:** Exibe **TODOS** os profissionais cadastrados.
""")

# ==============================================================================
# FUNÇÕES AUXILIARES DE CÁLCULO
# ==============================================================================
def calcular_moda_intervalos(df_dados):
    """
    Recebe um DataFrame com colunas 'profissional_id', 'especialidade_id', 'horario_full'
    Retorna um dicionário com os resultados processados.
    """
    resultados_dict = {}
    
    # Unificação de Especialidades "Não Definidas"
    df_valid_specs = df_dados[df_dados['especialidade_id'] > 0]
    if not df_valid_specs.empty:
        # Mapa: Médico -> Especialidade Mais Frequente
        mapa_espec_dominante = df_valid_specs.groupby('profissional_id')['especialidade_id'].agg(
            lambda x: x.mode()[0] if not x.mode().empty else 0
        ).to_dict()
        
        # Aplica correção
        def corrigir(row):
            if row['especialidade_id'] > 0: return row['especialidade_id']
            return mapa_espec_dominante.get(row['profissional_id'], 0)
            
        df_dados['especialidade_id'] = df_dados.apply(corrigir, axis=1)

    # Agrupamento e Cálculo
    grupos = df_dados.groupby(['profissional_id', 'especialidade_id'])
    
    for (pid, sid), group in grupos:
        if pid == 0: continue
        
        # Remove horários duplicados e ordena
        group = group.drop_duplicates(subset=['horario_full']).sort_values('horario_full')
        
        if len(group) < 2: continue
            
        # Diferença entre horários
        group['diff'] = (group['horario_full'].shift(-1) - group['horario_full']).dt.total_seconds() / 60
        
        # Filtra intervalos válidos (5 a 120 min)
        valid_diffs = group[(group['diff'] >= 5) & (group['diff'] <= 120)]['diff']
        
        if not valid_diffs.empty:
            intervalo = valid_diffs.mode()[0]
            confianca = (valid_diffs == intervalo).sum()
            total = len(valid_diffs)
            
            # Chave única para o dicionário
            key = (pid, sid)
            resultados_dict[key] = {
                'intervalo': int(intervalo),
                'amostras': confianca,
                'total_amostras': total,
                'origem': 'Calculado'
            }
            
    return resultados_dict

# ==============================================================================
# INTERFACE E FILTROS
# ==============================================================================
col1, col2 = st.columns(2)

with col1:
    dias_varredura = st.slider("Dias Futuros (Varredura)", 7, 30, 15)
    dias_historico = 180 # Fixo ou configurável

with col2:
    df_unid = list_unidades()
    opcoes_unid = ["Todas"] + list(df_unid['nome_fantasia'])
    unidade_sel = st.selectbox("Unidade", options=opcoes_unid)

map_unidades = dict(zip(df_unid['nome_fantasia'], df_unid['unidade_id']))

if st.button("🚀 Gerar Relatório Completo"):
    
    # CONFIGURAÇÃO DE DATAS
    hoje = date.today()
    start_future = today_str = hoje.strftime("%d-%m-%Y")
    end_future = (hoje + timedelta(days=dias_varredura)).strftime("%d-%m-%Y")
    
    start_history = (hoje - timedelta(days=dias_historico)).strftime("%d-%m-%Y")
    # End history é ontem
    end_history = (hoje - timedelta(days=1)).strftime("%d-%m-%Y")

    # PREPARAÇÃO DE MAPAS
    unidade_id = None
    if unidade_sel != 'Todas':
        unidade_id = int(map_unidades[unidade_sel])
        unidade_id_busca = 12 if unidade_id == 39867 else unidade_id
    else:
        unidade_id_busca = 12 # Fallback
    
    df_profs = list_profissionals()
    df_esp = list_especialidades()
    
    map_prof = dict(zip(df_profs['profissional_id'], df_profs['nome']))
    map_esp = dict(zip(df_esp['especialidade_id'], df_esp['nome']))
    
    # Lista Mestra de Todos os Profissionais (Meta: Preencher todos)
    todos_profs_ids = set(df_profs['profissional_id'].unique())
    todos_profs_ids.discard(0) # Remove ID 0 se existir
    
    resultados_finais = {} # Chave: (pid, sid) -> Valor: dict dados
    
    # ==========================================================================
    # FASE 1: DADOS FUTUROS (Agendamentos + Vagas)
    # ==========================================================================
    with st.spinner(f"Fase 1/2: Analisando grade futura ({start_future} a {end_future})..."):
        slots_futuros = []
        medicos_com_dados_futuros = set()
        
        # 1.1 Agendamentos Futuros
        df_ag_fut = fetch_agendamentos(unidade_id=unidade_id, start_date=start_future, end_date=end_future)
        
        if not df_ag_fut.empty:
            df_ag_fut['profissional_id'] = pd.to_numeric(df_ag_fut['profissional_id'], errors='coerce').fillna(0).astype(int)
            df_ag_fut['especialidade_id'] = pd.to_numeric(df_ag_fut['especialidade_id'], errors='coerce').fillna(0).astype(int)
            
            for _, row in df_ag_fut.iterrows():
                slots_futuros.append({
                    'profissional_id': row['profissional_id'],
                    'especialidade_id': row['especialidade_id'],
                    'horario_full': pd.to_datetime(f"{row['data']} {row['horario']}", dayfirst=True)
                })
                medicos_com_dados_futuros.add(row['profissional_id'])
        
        # 1.2 Vagas Livres (Para quem não tem agendamento)
        profs_sem_agendamento = [p for p in todos_profs_ids if p not in medicos_com_dados_futuros]
        
        # Barra de progresso para busca de vagas
        if profs_sem_agendamento:
            prog = st.progress(0)
            status = st.empty()
            
            for i, pid in enumerate(profs_sem_agendamento):
                prog.progress((i+1)/len(profs_sem_agendamento))
                # status.text(f"Buscando grade: {map_prof.get(pid, pid)}") # Opcional: Descomente para debug visual
                
                sid = get_main_specialty_id(pid)
                if not sid: continue
                sid = int(sid)
                
                try:
                    df_vagas = fetch_horarios_disponiveis(
                        unidade_id=unidade_id_busca, 
                        data_start=start_future, 
                        data_end=end_future, 
                        profissional_id=pid, 
                        especialidade_id=sid
                    )
                    if not df_vagas.empty:
                         for _, row in df_vagas.iterrows():
                            slots_futuros.append({
                                'profissional_id': pid,
                                'especialidade_id': sid,
                                'horario_full': pd.to_datetime(f"{row['data']} {row['horario']}", dayfirst=True)
                            })
                            medicos_com_dados_futuros.add(pid)
                except: pass
            
            prog.empty()
            status.empty()
            
        # 1.3 Processa Fase 1
        if slots_futuros:
            df_fase1 = pd.DataFrame(slots_futuros)
            res_fase1 = calcular_moda_intervalos(df_fase1)
            resultados_finais.update(res_fase1)

    # ==========================================================================
    # FASE 2: DADOS HISTÓRICOS (Fallback)
    # ==========================================================================
    # Identifica quem ainda não tem resultado calculado
    profs_com_resultado = set([k[0] for k in resultados_finais.keys()])
    profs_pendentes = todos_profs_ids - profs_com_resultado
    
    if profs_pendentes:
        with st.spinner(f"Fase 2/2: Verificando histórico ({dias_historico} dias) para {len(profs_pendentes)} médicos restantes..."):
            
            # Busca agendamentos passados (Geral da unidade, é mais rápido que um por um)
            df_hist = fetch_agendamentos(unidade_id=unidade_id, start_date=start_history, end_date=end_history)
            
            if not df_hist.empty:
                df_hist['profissional_id'] = pd.to_numeric(df_hist['profissional_id'], errors='coerce').fillna(0).astype(int)
                df_hist['especialidade_id'] = pd.to_numeric(df_hist['especialidade_id'], errors='coerce').fillna(0).astype(int)
                
                # Filtra apenas os médicos que nos interessam (os pendentes)
                df_hist_filtrado = df_hist[df_hist['profissional_id'].isin(profs_pendentes)]
                
                slots_historicos = []
                for _, row in df_hist_filtrado.iterrows():
                    slots_historicos.append({
                        'profissional_id': row['profissional_id'],
                        'especialidade_id': row['especialidade_id'],
                        'horario_full': pd.to_datetime(f"{row['data']} {row['horario']}", dayfirst=True)
                    })
                
                if slots_historicos:
                    df_fase2 = pd.DataFrame(slots_historicos)
                    res_fase2 = calcular_moda_intervalos(df_fase2)
                    
                    # Atualiza os resultados finais, marcando origem como Histórico
                    for k, v in res_fase2.items():
                        v['origem'] = 'Histórico'
                        resultados_finais[k] = v

    # ==========================================================================
    # CONSOLIDAÇÃO E EXIBIÇÃO
    # ==========================================================================
    
    lista_tabela = []
    
    # Percorre TODOS os médicos cadastrados para garantir que ninguém fique de fora
    # Ordena por nome
    ids_ordenados = sorted(list(todos_profs_ids), key=lambda x: map_prof.get(x, ""))
    
    for pid in ids_ordenados:
        nome_medico = map_prof.get(pid, f"ID {pid}")
        
        # Verifica se achamos alguma especialidade/intervalo para esse médico nos resultados
        # Pode haver múltiplas especialidades para o mesmo médico
        entradas_medico = {k: v for k, v in resultados_finais.items() if k[0] == pid}
        
        if entradas_medico:
            # Adiciona uma linha para cada especialidade encontrada
            for (pid_key, sid_key), dados in entradas_medico.items():
                nome_esp = map_esp.get(sid_key, f"Esp {sid_key}") if sid_key > 0 else "Geral / Indefinida"
                
                lista_tabela.append({
                    "Profissional": nome_medico,
                    "Especialidade": nome_esp,
                    "Intervalo (min)": dados['intervalo'],
                    "Fonte de Dados": dados['origem'],
                    "Amostras": f"{dados['amostras']}/{dados['total_amostras']}",
                    "Status": "✅ Configurado"
                })
        else:
            # Adiciona linha de "Não Encontrado"
            lista_tabela.append({
                "Profissional": nome_medico,
                "Especialidade": "-",
                "Intervalo (min)": None, # Vai virar NaN/Traço
                "Fonte de Dados": "Sem dados (Futuro/Passado)",
                "Amostras": "0/0",
                "Status": "⚠️ Sem Dados"
            })
            
    # Cria DataFrame Final
    df_relatorio = pd.DataFrame(lista_tabela)
    
    st.success("Análise concluída!")
    
    # Exibe a tabela
    st.dataframe(
        df_relatorio,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Intervalo (min)": st.column_config.NumberColumn("Intervalo", format="%d min"),
            "Status": st.column_config.TextColumn("Status", width="small"),
            "Fonte de Dados": st.column_config.TextColumn("Base da Análise", help="Se foi calculado com agendamentos futuros ou histórico"),
        }
    )
    
    # Cria um buffer na memória (arquivo virtual)
    output = io.BytesIO()

    # Escreve o DataFrame no buffer usando o formato Excel
    # Importante: Certifique-se de ter 'xlsxwriter' ou 'openpyxl' instalado (pip install xlsxwriter)
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_relatorio.to_excel(writer, index=False, sheet_name='Relatorio_Intervalos')
        
        # (Opcional) Ajuste automático da largura das colunas para ficar bonito
        worksheet = writer.sheets['Relatorio_Intervalos']
        for i, col in enumerate(df_relatorio.columns):
            # Calcula largura baseada no maior texto da coluna
            max_len = max(df_relatorio[col].astype(str).map(len).max(), len(col)) + 2
            worksheet.set_column(i, i, max_len)

    # Prepara os dados para o botão
    data_excel = output.getvalue()

    st.download_button(
        label="📥 Baixar Relatório Excel",
        data=data_excel,
        file_name="intervalos_completo.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )