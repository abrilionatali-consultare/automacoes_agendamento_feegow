from pathlib import Path
from datetime import timedelta, datetime, date
from jinja2 import Environment,FileSystemLoader
from weasyprint import HTML
import pandas as pd
import re

from core.api_client import (
    fetch_agendamentos,
    fetch_agendamentos_completos,
    list_profissionals,
    list_especialidades,
    list_salas,
    list_unidades,
    fetch_horarios_disponiveis,
    get_main_specialty_id
)

from core.utils import (
    build_matrices,
    render_pdf_from_template,
    to_time,
    periodo_from_time,
    get_natural_key
)

from core.normalize_df import normalize_and_validate

# ===============================================
# Importações de dados da API
# ===============================================
df_prof = list_profissionals()
df_esp = list_especialidades()
df_loc = list_salas()
df_unid = list_unidades() # Traz colunas: id, nome_fantasia (ou nome)

# ===============================================
# Função principal para geração de mapas semanais
# ===============================================
def generate_weekly_maps(start_date, unidade_id=None, output_dir="mapas_gerados"):
    """
    Gera mapas semanais corrigindo o conflito de nomes entre 'nome_fantasia' e 'unidade'.
    """
    start_date_str = start_date if isinstance(start_date, str) else start_date.strftime("%d-%m-%Y")
    df_unid_list = list_unidades()

    # Preparação de datas
    start_dt = datetime.strptime(start_date_str, "%d-%m-%Y")
    end_date_str = (start_dt + timedelta(days=6)).strftime("%d-%m-%Y")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Identificação da Unidade selecionada no Streamlit
    unidade_sel_id = None
    if unidade_id and unidade_id != 'Todas':
        filtro = df_unid_list[df_unid_list['nome_fantasia'] == unidade_id]
        if not filtro.empty:
            unidade_sel_id = int(filtro['unidade_id'].iloc[0])

    # 2. Busca Agendamentos e Injeção de Grade (Dra. Layne)
    df_ag = fetch_agendamentos(start_date=start_date_str, end_date=end_date_str, unidade_id=unidade_sel_id)
    if df_ag.empty: return {"warning": "Vazio"}
    
    df_base = df_ag.copy()
    profs_ativos = df_base["profissional_id"].unique()
    all_slots = []
    
    for p_id in profs_ativos:
        p_id_native = int(p_id)
        sid_query = get_main_specialty_id(p_id_native)
        if sid_query:
            vagas = fetch_horarios_disponiveis(unidade_sel_id, start_date_str, end_date_str, p_id_native, especialidade_id=int(sid_query))
            if not vagas.empty:
                vagas['agendamento_id'], vagas['status_id'] = 0, 0 
                all_slots.append(vagas)

    if all_slots:
        df = pd.concat([df_base, pd.concat(all_slots)], ignore_index=True)
        # Sincroniza especialidade para unificar blocos de horário
        df['especialidade_id'] = df.groupby(['profissional_id', 'data', 'local_id'])['especialidade_id'].transform(lambda x: x.ffill().bfill())
        df['especialidade_id'] = df['especialidade_id'].fillna(df['profissional_id'].map(lambda x: get_main_specialty_id(x)))
    else:
        df = df_base

    # 3. Merges de Apoio
    df = df.merge(df_esp[['especialidade_id', 'nome']], on="especialidade_id", how="left").rename(columns={'nome': 'especialidade'})
    df = df.merge(df_prof[['profissional_id', 'nome']], on="profissional_id", how="left").rename(columns={'nome': 'nome_profissional'})
    df = df.merge(df_loc[['id', 'local']], left_on="local_id", right_on="id", how="left").rename(columns={'local': 'sala'})

    # 4. Normalização (Onde a coluna 'nome_fantasia' costuma se perder)
    df_final, _ = normalize_and_validate(df)

    # 5. RESOLUÇÃO DO ERRO 'unidade'
    if unidade_id and unidade_id != 'Todas':
        # Se uma unidade específica foi escolhida, forçamos o nome dela
        df_final['unidade'] = unidade_id
    else:
        # Se for 'Todas', usamos o 'nome_fantasia' que vem da API e renomeamos para 'unidade'
        if 'nome_fantasia' in df_final.columns:
            df_final.rename(columns={'nome_fantasia': 'unidade'}, inplace=True)
        elif 'unidade_id' in df_final.columns:
            # Caso o nome tenha sumido mas o ID permaneça, recuperamos o nome
            df_final = df_final.merge(df_unid_list[['unidade_id', 'nome_fantasia']], on="unidade_id", how="left")
            df_final.rename(columns={'nome_fantasia': 'unidade'}, inplace=True)
    
    # Preenchimento de segurança se nada funcionar
    if 'unidade' not in df_final.columns:
        df_final['unidade'] = 'Geral'
    else:
        df_final['unidade'] = df_final['unidade'].fillna("Geral")

    # 6. Filtros de Regra e Salas
    df_final = df_final[df_final["status_id"].isin([0, 1, 7, 2, 3, 4])]
    salas_remover = ['SALA DE VACINA', 'LABORATÓRIO', 'RAIO X', 'COLETA DOMICILIAR']
    df_final = df_final[~df_final['sala'].isin(salas_remover)]

    # 7. Geração dos PDFs
    out_bytes = {}
    for unidade in df_final["unidade"].unique():
        if not unidade: continue
        df_sub = df_final[df_final["unidade"] == unidade]
        
        # Mapa Semanal limpo (include_taxa=False)
        matrices, occ, days = build_matrices(df_sub, include_taxa=False)

        pdf_bytes = render_pdf_from_template(
            unidade=unidade, matrices=matrices, occupancy=occ, day_names=days,
            week_start_date=start_date_str, week_end_date=end_date_str,
            template_path="templates/semanal2.html", cell_font_size_px=9, return_bytes=True
        )
        out_bytes[unidade] = pdf_bytes
        
    return out_bytes

def generate_daily_maps(start_date, unidade_id=None, output_dir="mapas_gerados"):
    start_date_str = start_date if isinstance(start_date, str) else start_date.strftime("%d-%m-%Y")
    df_unid_list = list_unidades()

    unidade_sel_id = None
    unidade_nome_real = unidade_id 
    if unidade_id and unidade_id != 'Todas':
        col_nome = next((c for c in ['nome_fantasia', 'nome'] if c in df_unid_list.columns), None)
        if col_nome:
            filtro = df_unid_list[df_unid_list[col_nome] == unidade_id]
            if not filtro.empty:
                unidade_sel_id = int(filtro['unidade_id'].iloc[0])
                unidade_nome_real = filtro['nome_fantasia'].iloc[0]

    df_ag_raw = fetch_agendamentos(start_date=start_date_str, end_date=start_date_str, unidade_id=unidade_sel_id)
    if df_ag_raw.empty: return {"warning": "Vazio"}

    # Injeção de Grade
    profs = df_ag_raw["profissional_id"].unique()
    all_slots = []
    for p_id in profs:
        p_id_native = int(p_id)
        sid = get_main_specialty_id(p_id_native)
        if sid:
            v_df = fetch_horarios_disponiveis(unidade_sel_id, start_date_str, start_date_str, p_id_native, especialidade_id=int(sid))
            if not v_df.empty:
                v_df['agendamento_id'], v_df['status_id'] = 0, 0
                all_slots.append(v_df)

    if all_slots:
        df = pd.concat([df_ag_raw, pd.concat(all_slots)], ignore_index=True)
        df['especialidade_id'] = df.groupby(['profissional_id', 'local_id'])['especialidade_id'].transform(lambda x: x.ffill().bfill())
    else:
        df = df_ag_raw.copy()

    df = df.merge(df_esp[['especialidade_id', 'nome']], on="especialidade_id", how="left").rename(columns={'nome': 'especialidade'})
    df = df.merge(df_prof[['profissional_id', 'nome']], on="profissional_id", how="left").rename(columns={'nome': 'nome_profissional'})
    df = df.merge(df_loc[['id', 'local']], left_on="local_id", right_on="id", how="left").rename(columns={'local': 'sala'})

    # 4. Normalização e Atribuição de Unidade
    df_final, _ = normalize_and_validate(df)
    
    # [FIX] Re-atribuição da coluna unidade para evitar o KeyError
    if unidade_sel_id:
        df_final['unidade'] = unidade_nome_real
    else:
        df_final = df_final.merge(df_unid_list[['unidade_id', 'nome_fantasia']], on="unidade_id", how="left")
        df_final.rename(columns={'nome_fantasia': 'unidade'}, inplace=True)

    df_final['unidade'] = df_final['unidade'].fillna("Geral")
    remover_salas = ['SALA DE VACINA', 'LABORATÓRIO', 'RAIO X', 'COLETA DOMICILIAR']
    df_final = df_final[~df_final['sala'].isin(remover_salas)]

    df_final['time'] = df_final['horario'].apply(to_time)
    df_final['periodo'] = df_final['time'].apply(periodo_from_time)
    
    # 5. Agrupamento para o Template
    master_data = {}
    unidades_para_processar = df_final['unidade'].unique()
    for unidade in unidades_para_processar:
        if not unidade: continue
        # [FIX] Filtragem correta por unidade dentro do loop para não duplicar dados
        df_uni = df_final[df_final['unidade'] == unidade].copy()
        dados_uni = {
            "Manhã": [], "Tarde": [], 
            "totais": {
                'Manhã': {'grade': 0, 'pacientes': 0, 'taxa': 0},
                'Tarde': {'grade': 0, 'pacientes': 0, 'taxa': 0},
                'dia': {'grade': 0, 'pacientes': 0, 'taxa': 0}
            }
        }
        
        grouped = df_uni.groupby(['sala', 'nome_profissional', 'especialidade', 'periodo']).agg(
            agendamentos=('agendamento_id', lambda x: (x > 0).sum()),
            vagas_totais=('horario', 'count')
        ).reset_index()

        for _, row in grouped.iterrows():
            taxa = (row['agendamentos'] / row['vagas_totais'] * 100) if row['vagas_totais'] > 0 else 0
            item = {
                'sala': row['sala'], 'periodo_detalhe': row['periodo'], 'especialidade': row['especialidade'],
                'medico': row['nome_profissional'], 'ocupacao': int(row['agendamentos']), 
                'vagas_grade': int(row['vagas_totais']), 'taxa_ocupacao': f"{taxa:.1f}%", 'taxa_num': taxa
            }
            if row['periodo'] in dados_uni:
                dados_uni[row['periodo']].append(item)
                dados_uni['totais'][row['periodo']]['grade'] += int(row['vagas_totais'])
                dados_uni['totais'][row['periodo']]['pacientes'] += int(row['agendamentos'])
        
        for p in ['Manhã', 'Tarde']:
            g_per = dados_uni['totais'][p]['grade']
            p_per = dados_uni['totais'][p]['pacientes']
            dados_uni['totais'][p]['taxa'] = (p_per / g_per * 100) if g_per > 0 else 0
            dados_uni['totais']['dia']['grade'] += g_per
            dados_uni['totais']['dia']['pacientes'] += p_per

        g_dia = dados_uni['totais']['dia']['grade']
        p_dia = dados_uni['totais']['dia']['pacientes']
        dados_uni['totais']['dia']['taxa'] = (p_dia / g_dia * 100) if g_dia > 0 else 0
        master_data[unidade] = dados_uni
        
    tpl = Environment(loader=FileSystemLoader('.')).get_template("templates/diario.html")
    html = tpl.render(unidade=unidade_id or "Geral", all_data=master_data, date_str=start_date_str, 
                      grand_total=int(df_final[df_final['agendamento_id']>0].shape[0]), 
                      generated=datetime.now().strftime("%d/%m/%Y %H:%M"))
    return {unidade_id: HTML(string=html).write_pdf()}