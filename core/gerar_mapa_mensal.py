from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta, time
from utils import *
from pathlib import Path
from normalize_df import normalize_and_validate
import requests
import os
import pandas as pd
import yaml
import time
import re

load_dotenv()

# ======= CONFIGURAÇÕES ======= #
with open("api_config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

globals_cfg = cfg.get("globals", {})
timeout = globals_cfg.get("timeout_seconds", 15)
method_default = globals_cfg.get("method", "GET")
global_headers = globals_cfg.get("headers", {})
auth_cfg = globals_cfg.get("auth", {})

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

# ======= EXTRAÇÃO DE DADOS ======= #
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

def get_patient_by_id(patient_id: int):
    # Criar configuração temporária para o endpoint de paciente (reutiliza globals)
    ep_cfg = {
        "name": "patient-search",
        "url": "https://api.feegow.com/v1/api/patient/search",
        "method": "GET",  # Como na documentação
        "needs_body": True,  # Envia payload no corpo
        "body_template": {"paciente_id": patient_id}  # Payload fixo para este endpoint
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


# ======= FUNÇÃO PRINCIPAL ======= #
def main():
    out_dir = Path("mapas_gerados")
    out_dir.mkdir(parents=True, exist_ok=True)
    start_date = ask_week_start()
    end_date = start_date + timedelta(days=5)
    date_str = start_date.strftime("%d-%m-%Y") if hasattr(start_date, "strftime") else str(start_date)

    context = {
        "data_start": start_date.strftime("%d-%m-%Y"),
        "data_end": end_date.strftime("%d-%m-%Y")
    }
    raw_data = {}

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
    # O ícone de triângulo com ponto de exclamação indica que há uma discrepância entre o local do agendamento
    #  e o configurado na grade. Este ícone serve como um alerta visual para que o usuário verifique 
    # os detalhes do agendamento.

    for ep in cfg.get("endpoints", []):
        print("-> Processando fonte", ep["name"], '...')
        result = request_endpoint(ep, global_context=context)

        if isinstance(result, dict) and result.get("error"):
            if result.get("status") == 422:
                print("422 recebido. Verifique o payload e o formato dos campos. body:", result.get("text"))
            continue

        try:
            raw_data[ep["name"]] = pd.DataFrame(result.get("content", {}))
        except:
            raw_data[ep["name"]] = pd.DataFrame(result)  

        time.sleep(0.2)

    # Mescla com dados do profissional
    df_profissional = pd.merge(
            left=raw_data["appointments"], right=raw_data['list-professional'], 
            right_on='profissional_id', left_on='profissional_id', how="left")
    df_profissional.rename(columns={'nome': 'nome_profissional'}, inplace=True)

    # Preencher especialidade_id nulo usando outra linha do mesmo profissional_id
    df_profissional['especialidade_id'] = df_profissional.groupby('profissional_id')['especialidade_id'] \
        .transform(lambda x: x.ffill().bfill())

    # Preencher especialidade_id nulo usando a coluna 'especialidades'
    df_profissional['especialidade_id'] = df_profissional['especialidade_id'].fillna(
        df_profissional['especialidades'].apply(
            lambda x: x[0]['especialidade_id'] if isinstance(x, list) and len(x) > 0 else None
        )
    )

    df_especialidade = pd.merge(
            left=df_profissional, right=raw_data["list-specialties"], 
            on='especialidade_id', how="left")
    df_especialidade.rename(columns={'nome': 'especialidade'}, inplace=True)  

    # Mescla com dados do local (sala)
    df_local = pd.merge(
            left=df_especialidade, right=raw_data['list-local'],
            right_on='id', left_on='local_id', how='left')

    df_local.rename(columns={'local': 'sala'}, inplace=True)

    df, diagnostics = normalize_and_validate(df_local)

    # Remove status inválidos para o agendamento
    required_status = [1, 7, 2, 3, 4]
    df = df[df['status_id'].isin(required_status)]

    # Seleciona colunas e remove salas
    required_cols = ['agendamento_id','data','horario','nome_profissional','nome_fantasia','especialidade','sala']
    remover_salas = ['LABORATÓRIO', 'COLETA DOMICILIAR', 'RAIO X', 'SALA DE VACINA']
    df = df[~df['sala'].isin(remover_salas)]

    df_final = df[required_cols].copy()

    # Faz o processamento por unidade
    for unidade in df_final['nome_fantasia'].unique():
        df_unidade = df_final[df_final['nome_fantasia'] == unidade]

        # Agora build_matrices retorna 3 valores
        matrices, occ, day_names = build_matrices(df_unidade)

        safe_unidade = re.sub(r'[^A-Za-z0-9._-]', '_', str(unidade))
        fname = f"MAPA_MENSAL_{safe_unidade}_-_{date_str}.pdf"
        out_pdf_path = out_dir / fname

        render_pdf_from_template(
            unidade=unidade,
            matrices=matrices,
            occupancy=occ,
            day_names=day_names,               
            week_start_date=start_date,
            week_end_date=end_date,
            template_path="mapa_mensal_template2.html",
            out_pdf_path=out_pdf_path,
            cell_font_size_px=9
        )

    print("Relatório gerados com sucesso!")

if __name__ == '__main__':
    main()
