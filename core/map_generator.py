from pathlib import Path
from datetime import timedelta, datetime
import pandas as pd
import re

from core.api_client import (
    fetch_agendamentos,
    list_profissionals,
    list_especialidades,
    list_salas,
    list_unidades
)

from core.utils import (
    build_matrices,
    render_pdf_from_template
)

from core.normalize_df import normalize_and_validate


# ===============================================
# Função principal para geração de mapas semanais
# ===============================================
def generate_weekly_maps(start_date, unidade_id=None, output_dir="mapas_gerados"):
    """
    Gera os mapas semanais (PDF) para uma unidade específica ou para todas.
    unidade_id: Pode ser o Nome da Unidade (str), "Todas" ou None.
    """

    df_prof = list_profissionals()
    df_esp = list_especialidades()
    df_loc = list_salas()
    df_unid = list_unidades() # Traz colunas: id, nome_fantasia (ou nome)

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
    # [CORREÇÃO CRUCIAL] Filtro final de Unidade
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