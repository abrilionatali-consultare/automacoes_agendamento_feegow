import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("FEEGOW_ACCESS_TOKEN")

# Configuração igual à imagem
URL = "https://api.feegow.com/v1/api/appoints/available-schedule"
HEADERS = {
    "x-access-token": TOKEN,
    "Content-Type": "application/json" # Obriga o servidor a ler o JSON
}

# Dados fixos
PROFISSIONAL = 2497 
ESPECIALIDADE = 102
DATA = "06-01-2026"

def testar_unidade(id_teste, descricao):
    print(f"\n🧪 TESTANDO UNIDADE: {id_teste} ({descricao})")
    
    # Payload EXATAMENTE como na imagem da doc
    payload = {
        "tipo": "E",
        "especialidade_id": ESPECIALIDADE,
        "unidade_id": id_teste,
        "profissional_id": PROFISSIONAL,
        "data_start": DATA,
        "data_end": DATA
    }
    
    print(f"   Enviando GET com JSON body...")
    try:
        # requests.request permite mandar body no GET
        resp = requests.request("GET", URL, headers=HEADERS, json=payload, timeout=10)
        print(f"   Status: {resp.status_code}")
        
        if resp.status_code == 200:
            content = resp.json().get("content")
            if content:
                print(f"   ✅ SUCESSO! Conteúdo encontrado com ID {id_teste}!")
                print(f"   Amostra: {str(content)[:150]}...")
            else:
                print(f"   ⚠️  200 OK, mas vazio. O ID {id_teste} provavelmente não tem agenda ou está incorreto.")
        else:
            print(f"   ❌ Erro: {resp.text}")
            
    except Exception as e:
        print(f"   Erro de conexão: {e}")

# TESTE A: O ID que você informou agora
testar_unidade(12, "Seu ID informado: 12")

# TESTE B: O ID que apareceu nos logs anteriores (Shopping Campinas)
testar_unidade(39867, "ID Histórico Shopping Campinas: 39867")