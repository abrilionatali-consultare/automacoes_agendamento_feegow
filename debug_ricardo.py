import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("FEEGOW_ACCESS_TOKEN")

# ==========================================
# PREENCHA AQUI COM OS DADOS DO MÉDICO PROBLEMA
# ==========================================
UNIDADE_ID = 12          # O ID que validamos (Shopping)
PROFISSIONAL_ID = 11  # <--- COLOQUE O ID DO MÉDICO AQUI
DATA_TESTE = "13-01-2026" # <--- UMA DATA QUE VOCÊ TEM CERTEZA QUE TEM VAGA (D+1)
ESPECIALIDADE_ID = 129   # <--- ID DA ESPECIALIDADE DELE
# ==========================================

HEADERS = {"x-access-token": TOKEN, "Content-Type": "application/json"}

def testar(nome_teste, payload):
    url = "https://api.feegow.com/v1/api/appoints/available-schedule"
    print(f"\n🧪 TESTE: {nome_teste}")
    try:
        resp = requests.get(url, headers=HEADERS, json=payload)
        data = resp.json()
        
        # Verifica se tem conteúdo real
        tem_vaga = False
        if data.get('content'):
            # Navega para ver se não é só um dicionário vazio
            p_data = data['content'].get('profissional_id', {}).get(str(PROFISSIONAL_ID))
            if p_data:
                print(f"   ✅ SUCESSO! Retornou dados.")
                print(f"   Amostra: {str(p_data)[:200]}...")
            else:
                print(f"   ⚠️  200 OK, mas JSON vazio para o ID {PROFISSIONAL_ID}")
        else:
             print(f"   ❌ Vazio (content: null ou [])")
             
    except Exception as e:
        print(f"   Erro: {e}")

# 1. Teste Padrão (O que o sistema faz hoje)
testar("1. Padrão (Por Especialidade)", {
    "unidade_id": UNIDADE_ID,
    "profissional_id": PROFISSIONAL_ID,
    "data_start": DATA_TESTE, "data_end": DATA_TESTE,
    "tipo": "E",
    "especialidade_id": ESPECIALIDADE_ID
})

# 2. Teste sem Especialidade (Se a API permitir, traz tudo)
testar("2. Sem Filtro de Especialidade", {
    "unidade_id": UNIDADE_ID,
    "profissional_id": PROFISSIONAL_ID,
    "data_start": DATA_TESTE, "data_end": DATA_TESTE
})

# 3. Teste Inverso: Listar a ESTRUTURA (Ver se a agenda existe mesmo)
url_struct = "https://api.feegow.com/v1/api/professional/list-schedules"
print(f"\n🏗️ TESTE ESTRUTURA (Configuração da Agenda)")
try:
    resp = requests.get(url_struct, headers=HEADERS, params={"profissional_id": PROFISSIONAL_ID, "unidade_id": UNIDADE_ID})
    print(f"   Status: {resp.status_code}")
    print(f"   Retorno: {str(resp.json().get('content', 'Vazio'))[:300]}")
except Exception as e:
    print(f"Erro: {e}")