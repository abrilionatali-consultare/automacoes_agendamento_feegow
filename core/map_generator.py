from pathlib import Path
from datetime import timedelta, datetime
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
    list_unidades
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
    Gera os mapas semanais (PDF) para uma unidade específica ou para todas.
    unidade_id: Pode ser o Nome da Unidade (str), "Todas" ou None.
    """ 

    df_unid = list_unidades()

    # -------------------------------
    # Preparação das datas
    # -------------------------------
    end_date = datetime.strptime(start_date, "%d-%m-%Y") + timedelta(days=6)
    end_date_str = end_date.strftime("%d-%m-%Y")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------
    # Preparação do ID da Unidade
    # -------------------------------
    unidade_sel_id = None
    
    # O wrapper pode enviar None se for "Todas". Tratamos ambos aqui.
    if unidade_id and unidade_id != 'Todas':
        # Identificar coluna de nome (algumas APIs retornam 'nome', outras 'nome_fantasia')
        col_nome = 'nome_fantasia' if 'nome_fantasia' in df_unid.columns else 'nome'
        
        try:
            # Filtra pelo nome e pega o ID
            filtro = df_unid[df_unid[col_nome] == unidade_id]
            if not filtro.empty:
                unidade_sel_id = filtro['id'].iloc[0]
            else:
                print(f"Aviso: Unidade '{unidade_id}' não encontrada na lista de unidades. Buscando geral.")
        except Exception as e:
            print(f"Erro ao buscar ID da unidade: {e}")
            unidade_sel_id = None
    else:
        # Se for None ou "Todas", id continua None para a API buscar tudo
        unidade_sel_id = None

    # -------------------------------
    # Busca de dados nas APIs
    # -------------------------------
    df_ag = fetch_agendamentos(
        start_date=start_date,
        end_date=end_date_str,
        unidade_id=unidade_sel_id
    )

    if df_ag.empty:
        return {
            "pdf_files": {},
            "saved_paths": {},
            "start_date": start_date,
            "end_date": end_date_str,
            "warning": "Nenhum agendamento encontrado no período."
        }
    
    # Inicializa df de forma segura
    df = df_ag.copy()

    # -------------------------------
    # Correção de especialidade_id
    # -------------------------------
    if "especialidade_id" in df.columns and "profissional_id" in df.columns:
        df["especialidade_id"] = df.groupby("profissional_id")["especialidade_id"] \
            .transform(lambda x: x.ffill().bfill())

    # -------------------------------
    # Mesclas (Merges)
    # -------------------------------
    # 1. Especialidades
    if not df_esp.empty and "especialidade_id" in df.columns:
        df = df.merge(df_esp, on="especialidade_id", how="left")
        if 'nome' in df_esp.columns:
            df.rename(columns={'nome': 'especialidade'}, inplace=True)
    else:
        if 'especialidade' not in df.columns: df['especialidade'] = ''
    
    # 2. Profissionais
    if not df_prof.empty and "profissional_id" in df.columns:
        df = df.merge(df_prof, on="profissional_id", how="left")
        if 'nome' in df_prof.columns:
            df.rename(columns={'nome': 'nome_profissional'}, inplace=True)
    
    # 3. Salas / Locais
    # Importante: O merge com locais pode trazer o nome da unidade associada à sala
    if not df_loc.empty and "local_id" in df.columns:
        df = df.merge(df_loc, left_on="local_id", right_on="id", how="left", suffixes=("", "_loc"))
    
    # Renomeações padrão para o template
    rename_map = {}
    if 'local' in df.columns: rename_map['local'] = 'sala'
    elif 'nome' in df.columns and 'sala' not in df.columns: rename_map['nome'] = 'sala'
    
    # Se 'nome_fantasia' veio do merge de locais, ele é a Unidade
    if 'nome_fantasia' in df.columns: rename_map['nome_fantasia'] = 'unidade'
    
    df.rename(columns=rename_map, inplace=True)

    # -------------------------------
    # Normalização
    # -------------------------------
    df_final, diagnostics = normalize_and_validate(df)

    # Garante coluna unidade
    if 'unidade' not in df_final.columns:
        df_final['unidade'] = 'Geral'

    # -------------------------------
    # Filtros de Regra de Negócio
    # -------------------------------
    if "status_id" in df_final.columns:
        required_status = [1, 7, 2, 3, 4]
        df_final = df_final[df_final["status_id"].isin(required_status)]

    remover_salas = ["LABORATÓRIO", "COLETA DOMICILIAR", "RAIO X", "SALA DE VACINA"]
    if "sala" in df_final.columns:
        df_final = df_final[~df_final["sala"].isin(remover_salas)]

    # Seleção de colunas necessárias
    cols_to_keep = ["agendamento_id","data","horario","nome_profissional","unidade","especialidade","sala"]
    existing_cols = [c for c in cols_to_keep if c in df_final.columns]
    df_final = df_final[existing_cols]

    # -------------------------------
    # Filtro final de Unidade
    # -------------------------------
    # Se o usuário pediu uma unidade específica, filtramos o DataFrame final
    # para garantir que não vazem dados de outras unidades vindos dos Merges.
    if unidade_id and unidade_id != "Todas":
        # Filtra onde a coluna 'unidade' é igual ao nome selecionado
        df_final = df_final[df_final["unidade"] == unidade_id]

    if df_final.empty:
        return {
           "pdf_files": {}, "saved_paths": {},
           "warning": f"Nenhum dado encontrado para a unidade {unidade_id} após filtragem."
        }

    # -------------------------------
    # Geração dos PDFs
    # -------------------------------
    unidades_para_gerar = df_final["unidade"].unique()
    out_bytes = {}

    for unidade in unidades_para_gerar:
        if not unidade: continue
        
        df_unid = df_final[df_final["unidade"] == unidade]
        if df_unid.empty: continue

        matrices, occ, day_names = build_matrices(df_unid)

        safe_unidade = re.sub(r"[^A-Za-z0-9._-]", "_", str(unidade))
        file_name = f"MAPA_SEMANAL_{safe_unidade}_-_{start_date}.pdf"
        path_pdf = out_dir / file_name

        # 1. Salva em disco
        render_pdf_from_template(
            unidade=unidade,
            matrices=matrices,
            occupancy=occ,
            day_names=day_names,
            week_start_date=start_date,
            week_end_date=end_date_str,
            template_path="templates/semanal2.html",
            out_pdf_path=path_pdf,
            cell_font_size_px=9,
            return_bytes=False
        )

        # 2. Gera bytes para download/preview
        pdf_bytes = render_pdf_from_template(
            unidade=unidade,
            matrices=matrices,
            occupancy=occ,
            day_names=day_names,
            week_start_date=start_date,
            week_end_date=end_date_str,
            template_path="templates/semanal2.html",
            out_pdf_path=None,
            cell_font_size_px=9,
            return_bytes=True
        )

        out_bytes[unidade] = pdf_bytes

    return out_bytes

def generate_daily_maps(start_date, unidade_id=None, output_dir="mapas_gerados"):
    """
    Gera os mapas diários (PDF) para um unidade específica ou para todas.
    unidade_id: Pode ser nome_fantasia (str), "Todas" ou None.
    """

    # -------------------------------
    # Preparação do ID da Unidade
    # -------------------------------
    unidade_sel_id = None
    
    # O wrapper pode enviar None se for "Todas". Tratamos ambos aqui.
    if unidade_id and unidade_id != 'Todas':
        # Identificar coluna de nome (algumas APIs retornam 'nome', outras 'nome_fantasia')
        col_nome = 'nome_fantasia' if 'nome_fantasia' in df_unid.columns else 'nome'
        
        try:
            # Filtra pelo nome e pega o ID
            filtro = df_unid[df_unid[col_nome] == unidade_id]
            if not filtro.empty:
                unidade_sel_id = filtro['id'].iloc[0]
            else:
                print(f"Aviso: Unidade '{unidade_id}' não encontrada na lista de unidades. Buscando geral.")
        except Exception as e:
            print(f"Erro ao buscar ID da unidade: {e}")
            unidade_sel_id = None
    else:
        # Se for None ou "Todas", id continua None para a API buscar tudo
        unidade_sel_id = None

    # -------------------------------
    # Busca de dados nas APIs
    # -------------------------------
    df = fetch_agendamentos_completos(
        start_date=start_date,
        end_date=start_date, # Busca dados apenas do dia solicitado
        unidade_id=unidade_sel_id
    )

    if df.empty:
        return {"warning": f"Nenhum agendamento encontrado para {start_date}."}
    
    if "status_id" in df.columns:
        df = df[df["status_id"].isin([1, 7, 2, 3, 4])] 
        
    remover_salas = ["LABORATÓRIO", "COLETA DOMICILIAR", "RAIO X", "SALA DE VACINA"]
    if "sala" in df.columns:
        df = df[~df["sala"].isin(remover_salas)]

    # Seleção de colunas necessárias
    cols_to_keep = ["agendamento_id","data","horario","nome_profissional","unidade","especialidade","sala"]
    existing_cols = [c for c in cols_to_keep if c in df.columns]
    df_final = df[existing_cols]

    # Colunas temporais
    df_final["time"] = df_final["horario"].apply(to_time)
    df_final["periodo"] = df_final["time"].apply(periodo_from_time) # Manhã/Tarde
    
    # -------------------------------
    # Filtro final de Unidade
    # -------------------------------
    # Se o usuário pediu uma unidade específica, filtramos o DataFrame final
    # para garantir que não vazem dados de outras unidades vindos dos Merges.
    if unidade_id and unidade_id != "Todas":
        # Filtra onde a coluna 'unidade' é igual ao nome selecionado
        df_final = df_final[df_final["unidade"] == unidade_id]

    if df_final.empty:
        return {
           "pdf_files": {}, "saved_paths": {},
           "warning": f"Nenhum dado encontrado para a unidade {unidade_id} após filtragem."
        }
    
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Config Jinja2
    env = Environment(loader=FileSystemLoader('.'))
    try:
        tpl = env.get_template("templates/diario.html")
    except:
        print("Template diario.html não encontrado")
        return {}
    
    # ---------------------------------------------------------
    # PROCESSAMENTO DOS DADOS (Agrupar tudo em um dict mestre)
    # ---------------------------------------------------------
    # Estrutura: master_data = { "NomeUnidade": { 'Manhã': [rows], 'totais': ... } }
    master_data = {}
    grand_total_geral = 0

    unidades_unicas = df_final['unidade'].unique()

    for unidade in unidades_unicas:
        df_uni = df_final[df_final['unidade'] == unidade].copy()
        if df_uni.empty: continue

        if 'sala' in df_uni.columns:
            df_uni['sala_sort'] = df_uni['sala'].apply(get_natural_key)
            df_uni.sort_values(by=['sala_sort', 'nome_profissional'], inplace=True)
            df_uni.drop(columns=['sala_sort'], inplace=True)

        # Estrutura da unidade
        dados_uni = {
            "Manhã": [],
            "Tarde": [],
            "totais": {'Manhã': 0, 'Tarde': 0, 'total_geral': 0}
        }

        # Agrupamento
        grouped = df_uni.groupby(['sala', 'nome_profissional', 'especialidade', 'periodo']).size().reset_index(name='ocupacao')

        for _, row in grouped.iterrows():
            periodo_macro = "Manhã" if row['periodo'] == "Manhã" else "Tarde"

            # Detecção simples de integral: se o médico aparecer na manha E tarde na mesma sala
            # (Lógica simplificada: mantemos o periodo original por enquanto)
            
            item = {
                'sala': row['sala'],
                'periodo_detalhe': row['periodo'], 
                'especialidade': row['especialidade'],
                'medico': row['nome_profissional'],
                'ocupacao': row['ocupacao']
            }

            if periodo_macro in dados_uni:
                dados_uni[periodo_macro].append(item)
                dados_uni['totais'][periodo_macro] += row['ocupacao']
                dados_uni['totais']['total_geral'] += row['ocupacao']
        
        master_data[unidade] = dados_uni
        grand_total_geral += dados_uni['totais']['total_geral']

    if not master_data:
        return {"warning": "Nenhum dado válido após processamento."}
    
    # ---------------------------------------------------------
    # 1. GERAR PDF GERAL (Todas as Unidades)
    # ---------------------------------------------------------
    html_geral = tpl.render(
        unidade="Relatório Geral",
        all_data=master_data, # Passa o dicionário completo
        date_str=start_date,
        grand_total=grand_total_geral,
        generated=datetime.now().strftime("%d/%m/%Y %H:%M")
    )
    
    fname_geral = f"MAPA_DIARIO_GERAL_{start_date}.pdf"
    path_geral = out_dir / fname_geral
    HTML(string=html_geral).write_pdf(path_geral)
    bytes_geral = HTML(string=html_geral).write_pdf()

    # ---------------------------------------------------------
    # 2. GERAR PDFs INDIVIDUAIS
    # ---------------------------------------------------------
    individual_files = {}
    
    for unidade, dados_uni in master_data.items():
        # Cria um mini-dict apenas com essa unidade para reaproveitar o template
        single_unit_data = {unidade: dados_uni}
        
        html_single = tpl.render(
            unidade=unidade,
            all_data=single_unit_data,
            date_str=start_date,
            grand_total=dados_uni['totais']['total_geral'],
            generated=datetime.now().strftime("%d/%m/%Y %H:%M")
        )
        
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", str(unidade))
        fname_single = f"MAPA_DIARIO_{safe_name}_{start_date}.pdf"
        
        # Gera bytes
        bytes_single = HTML(string=html_single).write_pdf()
        individual_files[unidade] = bytes_single
        
        # Salva em disco (opcional)
        HTML(string=html_single).write_pdf(out_dir / fname_single)

    return {
        "Geral": bytes_geral,
        "Individual": individual_files
    }