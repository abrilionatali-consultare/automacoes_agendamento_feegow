import requests
import pandas as pd
import os
import yaml
from typing import Union
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta, time
from dateutil.parser import parse as date_parse
import streamlit as st

load_dotenv()

API_BASE = os.getenv('FEEGOW_ACCESS_TOKEN')
API_CONFIG_FILE = "C:/Consultare/automacoes_agenda_feegow/api_config.yaml"

with open(API_CONFIG_FILE, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

globals_cfg = cfg.get("globals", {})
timeout = globals_cfg.get("timeout_seconds", 15)
method_default = globals_cfg.get("method", "GET")
global_headers = globals_cfg.get("headers", {})
auth_cfg = globals_cfg.get("auth", {})

# ======== CONVERTE endpoints(lista) → dict ========
endpoints_list = cfg.get("endpoints", [])
ENDPOINTS = {ep["name"]: ep for ep in endpoints_list}

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

# ==========================================================
# EXTRAÇÃO DE DADOS DA API
# ==========================================================
def build_headers(endpoint_cfg):
    headers = dict(global_headers)
    headers.update(endpoint_cfg.get("headers", {}))
    auth = endpoint_cfg.get("auth", auth_cfg)
    if auth and auth.get("type") == "env_header":
        env_name = auth.get("env_var")
        token = os.getenv(env_name)
        if not token:
            raise RuntimeError(f"Variável de ambiente {env_name} não encontrada")
        headers[auth.get("header_name", "Authorization")] = token
    return headers

def fill_body_template(template: dict, context: dict):
    """Substitui placeholders simples no template (ex: '{data_start}')"""
    body = {}
    for k, v in template.items():
        if isinstance(v, str) and "{" in v:
            body[k] = v.format(**context)
        else:
            body[k] = v
    return body

def request_endpoint(ep_cfg, global_context=None):
    url = ep_cfg["url"]
    method = ep_cfg.get("method", method_default).upper()
    headers = build_headers(ep_cfg)
    needs_body = ep_cfg.get("needs_body", False)
    use_post_for_body = ep_cfg.get("use_post_for_body", False)
    body_template = ep_cfg.get("body_template", {})

    json_payload = None
    params = None

    if needs_body:
        # exemplo de contexto: preencher datas dinâmicas
        ctx = global_context or {}
        # default: extrair últimos 2 dias (ajuste conforme necessidade)
        if "data_start" not in ctx or "data_end" not in ctx:
            today = datetime.utcnow().date()
            ctx.setdefault("data_end", today.strftime("%d-%m-%Y"))
            ctx.setdefault("data_start", (today - timedelta(days=1)).strftime("%d-%m-%Y"))
        json_payload = fill_body_template(body_template, ctx)

    # decide método real (feegow aceita GET com body no exemplo, mas alguns servidores ignoram)
    real_method = method
    if needs_body and use_post_for_body:
        real_method = "POST"

    try:
        if real_method == "GET":
            # muitos endpoints GET sem body → usar params; se json_payload existe e API aceita corpo em GET,
            # ainda é possível enviar json=..., mas alguns proxies ignoram. Aqui enviamos json se existe.
            resp = session.request("GET", url, headers=headers, params=params, json=json_payload, timeout=timeout)
        else:
            resp = session.request(real_method, url, headers=headers, params=params, json=json_payload, timeout=timeout)

        resp.raise_for_status()
        # tenta parse JSON, se possível
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}
    except requests.HTTPError as e:
        # log do erro + corpo para diagnosticar 422
        text = e.response.text if e.response is not None else ""
        status = e.response.status_code if e.response is not None else None
        print(f"[ERROR] endpoint={ep_cfg.get('name')} status={status} error={e} body={text}")
        return {"error": True, "status": status, "text": text}
    except requests.RequestException as e:
        print(f"[ERROR] endpoint={ep_cfg.get('name')} request failed: {e}")
        return {"error": True, "exception": str(e)}

# ==========================================================
# Helpers internos
# ==========================================================
def _call_endpoint(name: str, context: dict = None):
    ep_cfg = ENDPOINTS.get(name)   # <-- AGORA FUNCIONA
    if not ep_cfg:
        raise RuntimeError(f"Endpoint não encontrado: {name}")

    result = request_endpoint(ep_cfg, global_context=context or {})
    if result and "error" in result:
        print(f"[API ERROR] {name}: {result}")
        return None
    return result

def _normalize_df(data, nested_key=None):
    """Transforma listas/dicts em DataFrame."""
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
@st.cache_data
def fetch_agendamentos(unidade_id=None, start_date=None, end_date=None):
    """
    Busca agendamentos no período via API.
    Usa o endpoint configurado como 'appointments'.
    """
    ctx = {}

    # Datas - sempre no formato dd-mm-yyyy (Feegow)
    if start_date:
        ctx['data_start'] = start_date
    if end_date:
        ctx['data_end'] = end_date
    if unidade_id:
        ctx['unidade_id'] = unidade_id

    raw = _call_endpoint('appointments', context=ctx)
    df = _normalize_df(raw, nested_key='content')

    return df

@st.cache_data
def list_profissionals():
    raw = _call_endpoint('list-professional')  # CORRIGIDO
    df = _normalize_df(raw, nested_key='content')
    return df

@st.cache_data
def list_especialidades():
    """Retorna DataFrame com especialidades."""
    raw = _call_endpoint("list-specialties")
    df = _normalize_df(raw, nested_key="content")
    return df

@st.cache_data
def list_salas(unidade_id=None):
    """Retorna DataFrame com locais (salas)"""
    raw = _call_endpoint("list-local")
    df = _normalize_df(raw, nested_key="content")
    return df

@st.cache_data
def list_unidades():
    """Retorna DataFrame com unidades"""
    raw = _call_endpoint("appointments")
    df = _normalize_df(raw, nested_key='content')
    df = df[['unidade_id', 'nome_fantasia']]
    df.drop_duplicates(inplace=True)  
    
    return df

# ===================================
# CONSULTA DE PACIENTES CADASTRADOS
# ===================================
# Funções de consulta individual
@st.cache_data
def get_patient_by_id(patient_id):

    patient_id = int(patient_id)  # <- aqui!

    ep_cfg = {
        "name": "patient-search",
        "url": "https://api.feegow.com/v1/api/patient/search",
        "method": "GET",
        "needs_body": True,
        "body_template": {"paciente_id": patient_id}
    }

    # Usar request_endpoint para fazer a requisição (reutiliza headers, auth, session, retries)
    result = request_endpoint(ep_cfg)

    if result.get("error"):
        return result  # Retorna erro diretamente (já tratado por request_endpoint)

    # Verificar estrutura da resposta
    data = result
    print("Resposta da API:", data)  # DEBUG: remova depois de testar

    content = data.get("content")
    if isinstance(content, list) and len(content) > 0:
        return content[0]  # Retorna o primeiro paciente
    else:
        return {"error": True, "message": "Nenhum paciente encontrado ou resposta inesperada.", "raw_response": data}

@st.cache_data
def get_patient_name_by_id(patient_id):
    patient_id = int(patient_id)

    paciente = get_patient_by_id(patient_id)

    if paciente.get('error'):
        return None
    
    return paciente.get('nome')

df = fetch_agendamentos(
    start_date='14-06-2025',
    end_date='10-12-2025'
)


def fetch_agendamentos_completos(start_date, end_date, unidade_id=None):
    """
    Retorna agendamentos + profissionais + especialidades + salas
    já mesclados e prontos para uso no sistema.
    """

    # -----------------------------
    # 1. BUSCA NA API
    # -----------------------------
    df = fetch_agendamentos(
        start_date=start_date,
        end_date=end_date,
        unidade_id=unidade_id
    )

    if df.empty:
        return df  # Sem dados no período

    df_prof = list_profissionals()
    df_esp = list_especialidades()
    df_loc = list_salas(unidade_id)

    # -----------------------------
    # 2. MERGE COM ESPECIALIDADES
    # -----------------------------
    df = df.merge(df_esp, on="especialidade_id", how="left", suffixes=("", "_esp"))
    df.rename(columns={"nome": "especialidade"}, inplace=True)

    # -----------------------------
    # 3. MERGE COM PROFISSIONAIS
    # -----------------------------
    df = df.merge(df_prof, on="profissional_id", how="left", suffixes=("", "_prof"))

    # Renomeia o nome do profissional
    if "nome_prof" in df.columns:
        df.rename(columns={"nome_prof": "nome_profissional"}, inplace=True)
    elif "nome" in df.columns:
        df.rename(columns={"nome": "nome_profissional"}, inplace=True)

    # Concatena tratamento + nome, se existir
    if "tratamento" in df.columns and "nome_profissional" in df.columns:
        df["nome_profissional"] = (
            df["tratamento"].fillna("") + " " + df["nome_profissional"].fillna("")
        ).str.strip()

    # -----------------------------
    # 4. CORREÇÃO DE especialidade_id
    # -----------------------------
    # 4.1 — propaga valores dentro do mesmo profissional_id
    df["especialidade_id"] = (
        df.groupby("profissional_id")["especialidade_id"]
        .transform(lambda x: x.ffill().bfill())
    )

    # 4.2 — extrai do campo "especialidades" quando presente
    if "especialidades" in df.columns:
        df["especialidade_id"] = df["especialidade_id"].fillna(
            df["especialidades"].apply(
                lambda x: x[0]["especialidade_id"]
                if isinstance(x, list) and len(x) > 0 else None
            )
        )

    # -----------------------------
    # 5. MERGE COM LOCAIS (SALAS)
    # -----------------------------
    df = df.merge(df_loc, left_on="local_id", right_on="id", how="left", suffixes=("", "_sala"))

    if "local" in df.columns:
        df.rename(columns={"local": "sala"}, inplace=True)

    return df
