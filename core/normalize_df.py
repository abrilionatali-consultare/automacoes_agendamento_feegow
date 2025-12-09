# --- Normalização e validação do DataFrame antes da agregação ---
import pandas as pd
import re
from datetime import datetime

def normalize_and_validate(df):
    """
    Recebe df (provavelmente com colunas object) e:
      - normaliza nomes (strip, case)
      - converte agendamento_id para int (quando possível)
      - converte 'data' para datetime.date (dayfirst=True)
      - converte 'horario' para datetime.time (tenta vários formatos)
      - reporta problemas e devolve df limpo
    Retorna: (df_clean, diagnostics_dict)
    """
    df = df.copy()
    diag = {}

    # Trim strings e normalizar colunas de texto
    text_cols = ['nome_profissional', 'nome_fantasia', 'especialidade', 'sala']
    for c in text_cols:
        if c in df.columns:
            df[c] = df[c].astype(str).fillna('').str.strip()
            # optionally uppercase
            # df[c] = df[c].str.upper()

    # agendamento_id -> inteiro quando possível
    if 'agendamento_id' in df.columns:
        before = df['agendamento_id'].dtype
        df['agendamento_id'] = pd.to_numeric(df['agendamento_id'], errors='coerce').astype('Int64')
        diag['agendamento_id_before_dtype'] = str(before)
        diag['agendamento_id_nulls'] = int(df['agendamento_id'].isna().sum())
    else:
        diag['agendamento_id_present'] = False

    # DATA: tentar parse com dayfirst True (DD-MM-YYYY)
    if 'data' in df.columns:
        before = df['data'].dtype
        # Primeira tentativa: formato dd-mm-YYYY
        df['data_parsed'] = pd.to_datetime(df['data'], dayfirst=True, errors='coerce')
        # Segunda tentativa: ISO fallback
        mask_na = df['data_parsed'].isna()
        if mask_na.any():
            df.loc[mask_na, 'data_parsed'] = pd.to_datetime(df.loc[mask_na, 'data'], errors='coerce')
        # Extrair só a data
        df['data'] = df['data_parsed'].dt.date
        diag['data_before_dtype'] = str(before)
        diag['data_parse_nulls'] = int(df['data_parsed'].isna().sum())
        df.drop(columns=['data_parsed'], inplace=True)
    else:
        diag['data_present'] = False

    # HORARIO: tentar extrair horário - exemplos aceitos: '08:00', '08:00:00', '2025-12-01T08:00:00', '08h00'
    def parse_time_cell(x):
        if pd.isna(x):
            return None
        if isinstance(x, datetime):
            return x.time()
        s = str(x).strip()
        if s == '':
            return None
        # caso seja 'HH:MM' ou 'HH:MM:SS'
        try:
            return datetime.strptime(s, "%H:%M:%S").time()
        except:
            try:
                return datetime.strptime(s, "%H:%M").time()
            except:
                pass
        # extrair padrão com regex HH:MM possivelmente dentro de datetime string
        m = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", s)
        if m:
            tstr = m.group(1)
            try:
                return datetime.strptime(tstr, "%H:%M:%S").time()
            except:
                try:
                    return datetime.strptime(tstr, "%H:%M").time()
                except:
                    return None
        # capturar formatos com 'h' como 08h30
        m2 = re.search(r"(\d{1,2})\s*h\s*(\d{2})", s)
        if m2:
            try:
                hh = int(m2.group(1)); mm = int(m2.group(2))
                return datetime.strptime(f"{hh:02d}:{mm:02d}", "%H:%M").time()
            except:
                return None
        return None

    if 'horario' in df.columns:
        df['horario_parsed'] = df['horario'].apply(parse_time_cell)
        diag['horario_nulls'] = int(df['horario_parsed'].isna().sum())
        df['horario'] = df['horario_parsed']
        df.drop(columns=['horario_parsed'], inplace=True)
    else:
        diag['horario_present'] = False

    # Padronizar 'nome_fantasia' (unidade) removendo espaços duplos
    if 'nome_fantasia' in df.columns:
        df['nome_fantasia'] = df['nome_fantasia'].replace('', pd.NA).astype('string')
        df['nome_fantasia'] = df['nome_fantasia'].str.replace(r'\s+', ' ', regex=True).str.strip()

    # Remover linhas sem data/hora/agendamento_id - mas primeiro reportar quantos
    missing_date = df['data'].isna().sum() if 'data' in df.columns else None
    missing_time = df['horario'].isna().sum() if 'horario' in df.columns else None
    missing_id = df['agendamento_id'].isna().sum() if 'agendamento_id' in df.columns else None
    diag['missing_date_count'] = int(missing_date) if missing_date is not None else None
    diag['missing_time_count'] = int(missing_time) if missing_time is not None else None
    diag['missing_id_count'] = int(missing_id) if missing_id is not None else None

    # Opcional: remover rows completamente sem data ou id (comente se preferir inspecionar)
    df_clean = df.copy()
    # manter linhas com data e agendamento_id
    if 'data' in df_clean.columns and 'agendamento_id' in df_clean.columns:
        df_clean = df_clean[df_clean['data'].notna() & df_clean['agendamento_id'].notna()]
    elif 'data' in df_clean.columns:
        df_clean = df_clean[df_clean['data'].notna()]

    # Garantir colunas de texto existam e sejam string
    for c in ['nome_profissional','especialidade','sala','nome_fantasia']:
        if c in df_clean.columns:
            df_clean[c] = df_clean[c].astype(str).fillna('').str.strip()

    diag['rows_before'] = int(len(df))
    diag['rows_after'] = int(len(df_clean))

    # mostrar amostras de linhas problemáticas (até 10)
    problems = {}
    if missing_date and missing_date > 0:
        problems['sample_missing_date'] = df[df['data'].isna()].head(10).to_dict(orient='records')
    if missing_time and missing_time > 0:
        problems['sample_missing_time'] = df[df['horario'].isna()].head(10).to_dict(orient='records')
    if missing_id and missing_id > 0:
        problems['sample_missing_id'] = df[df['agendamento_id'].isna()].head(10).to_dict(orient='records')

    diag['sample_problems'] = problems
    return df_clean, diag