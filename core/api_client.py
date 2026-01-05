import requests
import pandas as pd
import os
import yaml
import string
from pathlib import Path
from typing import Union
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta, time, date
from dateutil.parser import parse as date_parse
import streamlit as st

# Carrega variáveis de ambiente locais (.env) se existirem
load_dotenv()

# Define o caminho do arquivo de configuração (Relativo, funciona no Cloud e Local)
current_dir = Path(__file__).parent
API_CONFIG_FILE = current_dir.parent / "api_config.yaml"

# ==========================================================
# CARREGA CONFIGURAÇÃO DA API
# ==========================================================
@st.cache_resource
def load_api_config():
    try:
        with open(API_CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
            return cfg
    except FileNotFoundError:
        st.error(f"Arquivo de configuração não encontrado em: {API_CONFIG_FILE}")
        st.stop()

# ==========================================================
# PARÂMETROS GLOBAIS DA API
# ==========================================================
cfg = load_api_config()
globals_cfg = cfg.get("globals", {})
timeout = globals_cfg.get("timeout_seconds", 15)
method_default = globals_cfg.get("method", "GET")
global_headers = globals_cfg.get("headers", {})
auth_cfg = globals_cfg.get("auth", {})

# ======== CONVERTE endpoints(lista) → dict ========
endpoints_list = cfg.get("endpoints", [])
ENDPOINTS = {ep["name"]: ep for ep in endpoints_list}

# ==========================================================
# CONFIGURAÇÃO DE SESSÃO STREAMLIT
# ==========================================================
@st.cache_resource
def get_session():
    session = requests.Session()

    retry_strategy = Retry(
        total=globals_cfg.get("retries", 3),
        backoff_factor=globals_cfg.get("backoff_factor", 1),
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "DELETE", "HEAD"]
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session

session = get_session()
retry_strategy = Retry(
    total=globals_cfg.get("retries", 3),
    backoff_factor=globals_cfg.get("backoff_factor", 1),
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST", "PUT", "DELETE", "HEAD"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)

# ==========================================================
# EXTRAÇÃO DE DADOS DA API
# ==========================================================
def build_headers(endpoint_cfg, has_payload=False):
    headers = dict(global_headers)
    headers.update(endpoint_cfg.get("headers", {}))
    if not has_payload:
        headers.pop("Content-Type", None)

    auth = endpoint_cfg.get("auth", auth_cfg)
    if auth and auth.get("type") == "env_header":
        env_name = auth.get("env_var")
        token = st.secrets.get(env_name, os.getenv(env_name))
        
        # CORREÇÃO: Acesso seguro ao dicionário aninhado
        if not token:
            api_sec = st.secrets.get("api", {})
            token = api_sec.get("token") if isinstance(api_sec, dict) else None

        if not token:
            raise RuntimeError(f"Token '{env_name}' não encontrado.")
            
        headers[auth.get("header_name", "Authorization")] = str(token)
    return headers

def fill_body_template(template: dict, context: dict):
    """Substitui placeholders e garante que tipos Pandas (int64) sejam convertidos para tipos nativos."""
    body = {}
    
    # Injeta o contexto original convertendo tipos int64/float64 se necessário
    for k, v in context.items():
        # O método .item() converte escalares do NumPy/Pandas para tipos nativos do Python
        if hasattr(v, "item") and not isinstance(v, (list, dict, str)):
            body[k] = v.item()
        else:
            body[k] = v

    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    for k, v in template.items():
        if isinstance(v, str) and "{" in v:
            val = string.Formatter().vformat(v, (), SafeDict(context))
            
            # Converte para int apenas se o valor final for numérico puro
            if val.isdigit():
                body[k] = int(val)
            else:
                body[k] = val
        else:
            # Garante conversão de tipos aqui também para segurança
            if hasattr(v, "item") and not isinstance(v, (list, dict, str)):
                body[k] = v.item()
            else:
                body[k] = v
    return body

def request_endpoint(ep_cfg, global_context=None):
    url = ep_cfg["url"]
    method = ep_cfg.get("method", method_default).upper()
    headers = build_headers(ep_cfg)
    needs_body = ep_cfg.get("needs_body", False)
    body_template = ep_cfg.get("body_template", {})

    json_payload = None
    if needs_body:
        ctx = (global_context or {}).copy()
        
        for k in ["data_start", "data_end", "data"]:
            if k in ctx and isinstance(ctx[k], (datetime, date)):
                ctx[k] = ctx[k].strftime("%d-%m-%Y")

        if "data_start" not in ctx or "data_end" not in ctx:
            today = datetime.now().date().strftime("%d-%m-%Y")
            ctx.setdefault("data_start", today)
            ctx.setdefault("data_end", today)
        
        json_payload = fill_body_template(body_template, ctx)

    real_method = "POST" if needs_body and ep_cfg.get("use_post_for_body", False) else method

    try:
        resp = session.request(real_method, url, headers=headers, json=json_payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json() if resp.text else {}
    except Exception as e:
        # Mantém seu log de erro original
        return {"error": True, "text": str(e)}

# ==========================================================
# Helpers internos
# ==========================================================
def _call_endpoint(name: str, context: dict = None):
    ep_cfg = ENDPOINTS.get(name)
    if not ep_cfg:
        raise RuntimeError(f"Endpoint não encontrado: {name}")

    result = request_endpoint(ep_cfg, global_context=context or {})
    if result and "error" in result:
        print(f"[API ERROR] {name}: {result}")
        return None
    return result

def _normalize_df(data, nested_key=None):
    if data is None:
        return pd.DataFrame()
    
    if nested_key and isinstance(data, dict) and nested_key in data:
        data = data[nested_key]
    
    try:
        return pd.json_normalize(data)
    except Exception:
        return pd.DataFrame(data)
    
# ==========================================================
# API PÚBLICA PARA O STREAMLIT
# ==========================================================
@st.cache_data(ttl=300)
def fetch_agendamentos(unidade_id=None, start_date=None, end_date=None):
    """
    Busca agendamentos no período via API.
    """
    ctx = {}
    if start_date: ctx['data_start'] = start_date
    if end_date: ctx['data_end'] = end_date
    if unidade_id: ctx['unidade_id'] = unidade_id

    raw = _call_endpoint('appointments', context=ctx)
    df = _normalize_df(raw, nested_key='content')
    return df

@st.cache_data(ttl=3600)
def list_profissionals():
    raw = _call_endpoint('list-professional')
    df = _normalize_df(raw, nested_key='content')
    return df

@st.cache_data(ttl=3600)
def list_especialidades():
    raw = _call_endpoint("list-specialties")
    df = _normalize_df(raw, nested_key="content")
    return df

@st.cache_data(ttl=3600)
def list_salas(unidade_id=None):
    raw = _call_endpoint("list-local")
    df = _normalize_df(raw, nested_key="content")
    return df

@st.cache_data(ttl=3600)    
def list_unidades():
    """
    Extrai a lista de unidades baseada no histórico de agendamentos.
    Busca um período de 5 dias para garantir que todas as unidades ativas sejam listadas.
    """
    from datetime import datetime, timedelta
    
    # Define um período amplo para garantir que tragamos dados das unidades
    today = datetime.now()
    start_date = (today - timedelta(days=10)).strftime("%d-%m-%Y")
    end_date = today.strftime("%d-%m-%Y")
    
    # Passamos as datas explicitamente para não depender do "today" da request_endpoint
    ctx = {
        "data_start": start_date,
        "data_end": end_date
    }
    
    # Chamada ao endpoint de agendamentos com o contexto de datas ampliado
    raw = _call_endpoint("appointments", context=ctx) 
    df = _normalize_df(raw, nested_key='content')
    
    if not df.empty:
        # Verifica se as colunas esperadas existem no retorno
        cols = df.columns
        id_col = 'unidade_id' if 'unidade_id' in cols else None
        nome_col = 'nome_fantasia' if 'nome_fantasia' in cols else None
        
        if id_col and nome_col:
            # Filtra, remove nulos e duplicatas
            df = df[[id_col, nome_col]].dropna().drop_duplicates()
            # Garante que unidade_id seja sempre inteiro
            df[id_col] = df[id_col].astype(int)
            # Ordena por nome para facilitar a seleção no Streamlit
            df = df.sort_values(by=nome_col)
            
    return df

# ===================================
# CONSULTA DE PACIENTES
# ===================================
@st.cache_data(ttl=600)
def get_patient_by_id(patient_id):
    patient_id = int(patient_id)
    
    ep_cfg = {
        "name": "patient-search",
        "url": "https://api.feegow.com/v1/api/patient/search",
        "method": "GET",
        "needs_body": True,
        "body_template": {"paciente_id": patient_id},
    }
    
    result = request_endpoint(ep_cfg)

    # CORREÇÃO: Verifica se o resultado é um dicionário antes de usar .get()
    if isinstance(result, dict) and result.get("error"):
        return result

    # Se o resultado for uma lista (comum no Feegow para buscas), pega o primeiro item
    if isinstance(result, list) and len(result) > 0:
        return result[0]
    elif isinstance(result, dict) and "content" in result:
        # Caso a API retorne encapsulado em 'content'
        content = result["content"]
        return content[0] if isinstance(content, list) and content else content
    
    return {"error": True, "message": "Nenhum paciente encontrado."}

def get_patient_name_by_id(patient_id):
    paciente = get_patient_by_id(patient_id)
    # [CORREÇÃO]: Protege contra retorno de lista ou erro
    if isinstance(paciente, dict):
        if paciente.get('error'):
            return None
        return paciente.get('nome')
    return None

@st.cache_data(ttl=300)
def fetch_agendamentos_completos(start_date, end_date, unidade_id=None):
    """
    Retorna agendamentos completos (com joins).
    """
    df = fetch_agendamentos(start_date=start_date, end_date=end_date, unidade_id=unidade_id)

    if df.empty:
        return df

    df_prof = list_profissionals()
    df_esp = list_especialidades()
    df_loc = list_salas()
    df_unid = list_unidades()

    # Merges
    if not df_esp.empty and "especialidade_id" in df.columns:
        df = df.merge(df_esp, on="especialidade_id", how="left", suffixes=("", "_esp"))
        df.rename(columns={"nome": "especialidade"}, inplace=True)

    if not df_prof.empty and "profissional_id" in df.columns:
        df = df.merge(df_prof, on="profissional_id", how="left", suffixes=("", "_prof"))
        if "nome_prof" in df.columns:
            df.rename(columns={"nome_prof": "nome_profissional"}, inplace=True)
        elif "nome" in df.columns:
            df.rename(columns={"nome": "nome_profissional"}, inplace=True)
            
        if "tratamento" in df.columns and "nome_profissional" in df.columns:
            df["nome_profissional"] = (
                df["tratamento"].fillna("") + " " + df["nome_profissional"].fillna("")
            ).str.strip()
        

    # Correção Especialidade
    if "profissional_id" in df.columns and "especialidade_id" in df.columns:
        df["especialidade_id"] = (
            df.groupby("profissional_id")["especialidade_id"]
            .transform(lambda x: x.ffill().bfill())
        )

    if "especialidades" in df.columns:
        df["especialidade_id"] = df["especialidade_id"].fillna(
            df["especialidades"].apply(
                lambda x: x[0]["especialidade_id"]
                if isinstance(x, list) and len(x) > 0 else None
            )
        )

    # Merge Locais
    if not df_loc.empty and "local_id" in df.columns:
        df = df.merge(df_loc, left_on="local_id", right_on="id", how="left", suffixes=("", "_sala"))
    
    if "local" in df.columns:
        df.rename(columns={"local": "sala"}, inplace=True)

    # Merge Unidades
    if not df_unid.empty and not 'unidade' in df.columns:
        df['unidade'] = df['nome_fantasia']

    return df

def fetch_horarios_disponiveis(unidade_id, data_start, data_end, profissional_id, tipo='E', especialidade_id=None, procedimento_id=None):
    """
    Busca slots livres garantindo tipos numéricos e chaves limpas.
    """
    # Criamos o contexto apenas com o essencial
    def format_if_date(d):
        if isinstance(d, (date, datetime)):
            return d.strftime("%d-%m-%Y")
        return str(d)
    
    ctx = {
        'unidade_id': int(unidade_id if unidade_id is not None else 0),
        'profissional_id': int(profissional_id),
        'data_start': format_if_date(data_start),
        'data_end': format_if_date(data_end),
        'tipo': tipo
    }

    # Injeta ID de especialidade OU procedimento, nunca ambos ou vazios
    if tipo == 'E' and especialidade_id:
        ctx['especialidade_id'] = int(especialidade_id)
    elif tipo == 'P' and procedimento_id:
        ctx['procedimento_id'] = int(procedimento_id)

    raw = _call_endpoint('available-schedule', context=ctx)
    
    lista_final = []
    if isinstance(raw, dict) and 'content' in raw:
        content = raw['content']
        
        if isinstance(content, dict):
            profissionais = content.get('profissional_id', {})
            for p_id, p_info in profissionais.items():
                locais = p_info.get('local_id', {})
                for l_id, datas in locais.items():
                    for data, lista_horarios in datas.items():
                        if isinstance(lista_horarios, list):
                            for hora in lista_horarios:
                                lista_final.append({
                                    "data": data,
                                    "horario": hora,
                                    "profissional_id": int(p_id),
                                    "local_id": int(l_id)
                                })
                            
    return pd.DataFrame(lista_final)

def get_main_specialty_id(profissional_id):
    """
    Busca o ID da primeira especialidade vinculada ao profissional.
    Útil para preencher o requisito obrigatório da API de disponibilidade.
    """
    # Usa a função que já existe no seu projeto para listar profissionais
    # Se ela retorna um DataFrame, filtramos ele.
    df_prof = list_profissionals() 
    
    if df_prof.empty:
        return None
        
    # Garante tipos compatíveis
    profissional_id = int(profissional_id)
    
    # Filtra o profissional
    prof_data = df_prof[df_prof['profissional_id'] == profissional_id]
    
    if prof_data.empty:
        return None
    
    # Tenta extrair o especialidade_id
    # O formato depende de como o 'list_profissionals' normaliza os dados.
    # Geralmente vem numa coluna 'especialidade_id' ou dentro de uma lista 'especialidades'
    
    try:
        # Opção A: Se o dataframe já tem a coluna direta (seu código atual faz merge, então deve ter)
        if 'especialidade_id' in prof_data.columns:
            return int(prof_data.iloc[0]['especialidade_id'])
            
        # Opção B: Se estiver aninhado (lista de dicts)
        if 'especialidades' in prof_data.columns:
            specs = prof_data.iloc[0]['especialidades']
            if isinstance(specs, list) and len(specs) > 0:
                return int(specs[0]['especialidade_id'])
                
    except Exception as e:
        print(f"Erro ao extrair especialidade: {e}")
        
    return None

# Evita que o código rode sozinho ao importar
if __name__ == "__main__":
    # Apenas para teste local, não rodará no import
    print("Testando fetch localmente...")
    teste = fetch_agendamentos(start_date='14-06-2025', end_date='14-06-2025')
    print(teste.head())
