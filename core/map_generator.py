from pathlib import Path
from datetime import timedelta, datetime, date
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import pandas as pd
import re

from core.api_client import (
    fetch_agendamentos,
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
    periodo_from_time
)

from core.normalize_df import normalize_and_validate

# Carregamento de dados auxiliares
df_prof = list_profissionals()
df_esp = list_especialidades()
df_loc = list_salas()
df_unid = list_unidades()

def generate_weekly_maps(start_date, unidade_id=None, output_dir="mapas_gerados"):
    """
    Função de Mapa Semanal (Mantida a lógica funcional e limpa).
    """
    start_date_str = start_date if isinstance(start_date, str) else start_date.strftime("%d-%m-%Y")
    df_unid_list = list_unidades()

    start_dt = datetime.strptime(start_date_str, "%d-%m-%Y")
    end_date_str = (start_dt + timedelta(days=6)).strftime("%d-%m-%Y")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    unidade_sel_id = None
    if unidade_id and unidade_id != 'Todas':
        filtro = df_unid_list[df_unid_list['nome_fantasia'] == unidade_id]
        if not filtro.empty:
            unidade_sel_id = int(filtro['unidade_id'].iloc[0])

    # Busca dados
    df_ag = fetch_agendamentos(start_date=start_date_str, end_date=end_date_str, unidade_id=unidade_sel_id)
    if df_ag.empty: return {"warning": "Vazio"}
    
    # Injeção de Grade
    profs_ativos = df_ag["profissional_id"].unique()
    all_slots = []
    for p_id in profs_ativos:
        p_int = int(p_id)
        sid = get_main_specialty_id(p_int)
        if sid:
            vagas = fetch_horarios_disponiveis(unidade_sel_id, start_date_str, end_date_str, p_int, especialidade_id=int(sid))
            if not vagas.empty:
                vagas['agendamento_id'], vagas['status_id'] = 0, 0 
                all_slots.append(vagas)

    # União
    if all_slots:
        df = pd.concat([df_ag, pd.concat(all_slots)], ignore_index=True)
        # Sincronização simples para o semanal
        df['especialidade_id'] = df.groupby(['profissional_id', 'local_id'])['especialidade_id'].transform(lambda x: x.ffill().bfill())
    else:
        df = df_ag.copy()

    # Merges
    df = df.merge(df_esp[['especialidade_id', 'nome']], on="especialidade_id", how="left").rename(columns={'nome': 'especialidade'})
    df = df.merge(df_prof[['profissional_id', 'nome']], on="profissional_id", how="left").rename(columns={'nome': 'nome_profissional'})
    df = df.merge(df_loc[['id', 'local']], left_on="local_id", right_on="id", how="left").rename(columns={'local': 'sala'})

    # Normalização
    df_final, _ = normalize_and_validate(df)

    # Remove salas inválidas para o mapa
    remover = ['LABORATÓRIO', 'RAIO X', 'SALA DE VACINA', 'COLETA DOMICILIAR', 'VACINA', 'LABORATORIO']
    df_final = df_final[~df_final['sala'].isin(remover)]
    
    # Fix Unidade
    if unidade_id and unidade_id != 'Todas':
        df_final['unidade'] = unidade_id
    else:
        if 'unidade_id' in df_final.columns:
            df_final = df_final.merge(df_unid_list[['unidade_id', 'nome_fantasia']], on="unidade_id", how="left")
            df_final.rename(columns={'nome_fantasia': 'unidade'}, inplace=True)
            
    df_final['unidade'] = df_final['unidade'].fillna("Geral")
    df_final = df_final[~df_final['sala'].str.upper().isin(['SALA DE VACINA', 'LABORATÓRIO', 'RAIO X'])]

    # Geração
    out_bytes = {}
    for unidade in df_final["unidade"].unique():
        if not unidade: continue
        matrices, occ, days = build_matrices(df_final[df_final["unidade"] == unidade], include_taxa=False)
        pdf_bytes = render_pdf_from_template(unidade, matrices, occ, days, start_date_str, end_date_str, "templates/semanal2.html", cell_font_size_px=9, return_bytes=True)
        out_bytes[unidade] = pdf_bytes
    return out_bytes

def generate_daily_maps(start_date, unidade_id=None, output_dir="mapas_gerados"):
    start_date_str = start_date if isinstance(start_date, str) else start_date.strftime("%d-%m-%Y")
    df_unid_list = list_unidades()

    # 1. Identificação da Unidade
    unidade_sel_id = None
    if unidade_id and unidade_id != 'Todas':
        filtro = df_unid_list[df_unid_list['nome_fantasia'] == unidade_id]
        if not filtro.empty:
            unidade_sel_id = int(filtro['unidade_id'].iloc[0])

    # 2. Busca Agendamentos
    df_ag = fetch_agendamentos(start_date=start_date_str, end_date=start_date_str, unidade_id=unidade_sel_id)
    if df_ag.empty: return {"warning": "Sem agendamentos para esta data."}

    # Tipagem forte
    for col in ['profissional_id', 'local_id', 'especialidade_id', 'agendamento_id']:
        if col in df_ag.columns:
            df_ag[col] = pd.to_numeric(df_ag[col], errors='coerce').fillna(0).astype(int)

    # 3. INJEÇÃO DE GRADE (ESTRATÉGIA MULTI-ESPECIALIDADE)
    # Em vez de adivinhar uma, buscamos a grade para TODAS as especialidades que o médico tem no dia.
    profs = df_ag["profissional_id"].unique()
    all_slots = []
    
    for p_id in profs:
        p_int = int(p_id)
        
        # Lista de especialidades ativas deste médico HOJE nos agendamentos
        specs_do_dia = df_ag[df_ag['profissional_id'] == p_int]['especialidade_id'].unique()
        specs_do_dia = [int(s) for s in specs_do_dia if s > 0]
        
        # Se não tiver agendamento com especialidade definida, tenta o fallback da API
        if not specs_do_dia:
            sid_main = get_main_specialty_id(p_int)
            if sid_main: 
                specs_do_dia = [sid_main]
            
        # Busca vagas para CADA especialidade encontrada
        for sid in specs_do_dia:
            v_df = fetch_horarios_disponiveis(
                unidade_id=unidade_sel_id, 
                data_start=start_date_str, 
                data_end=start_date_str, 
                profissional_id=p_int, 
                especialidade_id=int(sid)
            )
            
            if not v_df.empty:
                v_df['agendamento_id'] = 0
                v_df['status_id'] = 0
                v_df['profissional_id'] = p_int
                # Marca a especialidade que usamos para buscar
                v_df['especialidade_id'] = int(sid)
                
                # Herda o local_id dos agendamentos se a API de vagas não trouxe
                if 'local_id' not in v_df.columns or v_df['local_id'].sum() == 0:
                     locais = df_ag[df_ag['profissional_id'] == p_int]['local_id'].unique()
                     local_fallback = locais[0] if len(locais) > 0 else 0
                     v_df['local_id'] = int(local_fallback)
                
                all_slots.append(v_df)

    # 4. União e Limpeza
    if all_slots:
        df_grade = pd.concat(all_slots, ignore_index=True)
        
        # [CRUCIAL] Remove duplicatas de horário (mesmo slot servindo p/ 2 especialidades)
        # Isso impede que a grade dobre de tamanho artificialmente
        df_grade = df_grade.drop_duplicates(subset=['profissional_id', 'horario', 'local_id'])
        
        df = pd.concat([df_ag, df_grade], ignore_index=True)
    else:
        df = df_ag.copy()

    # 5. Sincronização de Especialidade (Evita Duplicação Visual)
    # Cria mapa de especialidade dominante por sala
    spec_map = {}
    valid_specs = df_ag[df_ag['especialidade_id'] > 0]
    if not valid_specs.empty:
        spec_map = valid_specs.groupby(['profissional_id', 'local_id'])['especialidade_id'].first().to_dict()
    
    def corrigir_especialidade(row):
        k = (row['profissional_id'], row['local_id'])
        return spec_map.get(k, row['especialidade_id']) # Usa a do mapa ou mantém a original

    df['especialidade_id'] = df.apply(corrigir_especialidade, axis=1)

    # Merges
    df = df.merge(df_esp[['especialidade_id', 'nome']], on="especialidade_id", how="left").rename(columns={'nome': 'especialidade'})
    df = df.merge(df_prof[['profissional_id', 'nome']], on="profissional_id", how="left").rename(columns={'nome': 'nome_profissional'})
    df = df.merge(df_loc[['id', 'local']], left_on="local_id", right_on="id", how="left").rename(columns={'local': 'sala'})

    # Normalização e Filtros
    df_final, _ = normalize_and_validate(df)
    
    # Filtro de Salas Administrativas
    remover = ['LABORATÓRIO', 'RAIO X', 'SALA DE VACINA', 'COLETA DOMICILIAR', 'VACINA', 'LABORATORIO']
    df_final = df_final[~df_final['sala'].str.upper().str.contains('|'.join(remover), na=False)]
    
    df_final['time'] = df_final['horario'].apply(to_time)
    df_final['periodo'] = df_final['time'].apply(periodo_from_time)
    
    # 6. Agrupamento (Grade vs Pacientes)
    master_data = {}
    dados_uni = {
        "Manhã": [], "Tarde": [], 
        "totais": {'Manhã': {'grade': 0, 'pacientes': 0, 'taxa': 0}, 'Tarde': {'grade': 0, 'pacientes': 0, 'taxa': 0}, 'dia': {'grade': 0, 'pacientes': 0, 'taxa': 0}}
    }
    
    grouped = df_final.groupby(['sala', 'nome_profissional', 'especialidade', 'periodo']).agg(
        pacientes_reais=('agendamento_id', lambda x: (pd.to_numeric(x, errors='coerce').fillna(0) > 0).sum()),
        grade_total=('horario', 'count')
    ).reset_index()

    def natural_key(text):
        # Divide o texto em partes numéricas e não numéricas para ordenar corretamente
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(text))]

    # Aplica a chave de ordenação
    grouped['sort_key'] = grouped['sala'].apply(natural_key)
    # Ordena o DataFrame usando essa chave
    grouped = grouped.sort_values(by='sort_key')

    for _, row in grouped.iterrows():
        g = int(row['grade_total'])
        p = int(row['pacientes_reais'])
        
        # Se Grade < Pacientes, houve falha na busca da grade, assumimos 100% (grade = pacientes)
        if g < p: g = p
            
        taxa = (p / g * 100) if g > 0 else 0
        
        item = {
            'sala': row['sala'], 'periodo_detalhe': row['periodo'], 'especialidade': row['especialidade'],
            'medico': row['nome_profissional'], 'ocupacao': p, 'vagas_grade': g, 'taxa_ocupacao': f"{taxa:.1f}%", 'taxa_num': taxa
        }
        
        if row['periodo'] in ["Manhã", "Tarde"]:
            dados_uni[row['periodo']].append(item)
            dados_uni['totais'][row['periodo']]['grade'] += g
            dados_uni['totais'][row['periodo']]['pacientes'] += p

    # Totais consolidados
    for per in ['Manhã', 'Tarde']:
        g_t = dados_uni['totais'][per]['grade']
        p_t = dados_uni['totais'][per]['pacientes']
        dados_uni['totais'][per]['taxa'] = (p_t / g_t * 100) if g_t > 0 else 0
        dados_uni['totais']['dia']['grade'] += g_t
        dados_uni['totais']['dia']['pacientes'] += p_t

    g_d = dados_uni['totais']['dia']['grade']
    p_d = dados_uni['totais']['dia']['pacientes']
    dados_uni['totais']['dia']['taxa'] = (p_d / g_d * 100) if g_d > 0 else 0
    
    unidade_chave = unidade_id if unidade_id else "Geral"
    master_data[unidade_chave] = dados_uni

    tpl = Environment(loader=FileSystemLoader('.')).get_template("templates/diario.html")
    html = tpl.render(unidade=unidade_chave, all_data=master_data, date_str=start_date_str, 
                      grand_total=dados_uni['totais']['dia']['pacientes'], 
                      generated=datetime.now().strftime("%d/%m/%Y %H:%M"))
    
    return {unidade_chave: HTML(string=html).write_pdf()}