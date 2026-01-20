import pandas as pd
from datetime import date, time
from core.api_client import list_blocks, fetch_agendamentos
from core.utils import to_time

def diagnostico_cirurgico():
    print("👩‍⚕️ --- DIAGNÓSTICO MÉDICA ID 2589 (DIA 23/01) ---")
    
    # 1. Busca o Bloqueio na API (Raw)
    print("\n1. Buscando Bloqueios...")
    df_blocks = list_blocks(start_date="23-01-2026", end_date="23-01-2026")
    
    # Filtra só a médica
    blocos_medica = df_blocks[df_blocks['professional_id'] == 2589]
    
    if blocos_medica.empty:
        print("❌ Nenhum bloqueio encontrado para o ID 2589 neste dia.")
        print("   Verifique se o ID está correto ou se o bloqueio é global (ID 0).")
    else:
        print(f"✅ Encontrados {len(blocos_medica)} bloqueios.")
        for i, row in blocos_medica.iterrows():
            units = row.get('units')
            print(f"   [Bloco {row['id']}]")
            print(f"   - Datas: {row['date_start']} até {row['date_end']}")
            print(f"   - Horas: {row.get('time_start')} até {row.get('time_end')}")
            print(f"   - Unidades (RAW): {units} (Tipo: {type(units)})")
            if isinstance(units, list) and len(units) > 0:
                print(f"     -> Tipo do 1º item: {type(units[0])}")

    # 2. Simula o Agendamento/Vaga
    print("\n2. Simulando Comparação...")
    # Cria uma linha fake representando uma vaga dela nesse dia
    vaga_teste = pd.DataFrame([{
        'data': '23-01-2026', 
        'horario': '10:00:00', 
        'profissional_id': 2589
    }])
    
    # Converte data para teste
    dt_vaga = pd.to_datetime(vaga_teste['data'].iloc[0], dayfirst=True).date()
    print(f"   - Data da Vaga (Convertida): {dt_vaga}")
    
    # Testa a lógica de unidade
    unidade_alvo = 12 # Vamos supor Shopping
    print(f"   - Testando contra Unidade Alvo: {unidade_alvo}")
    
    if not blocos_medica.empty:
        bloco = blocos_medica.iloc[0]
        units_bloco = bloco.get('units', [])
        
        # Simula o erro de tipagem
        if isinstance(units_bloco, list):
            tem_int = unidade_alvo in units_bloco
            tem_str = str(unidade_alvo) in units_bloco
            print(f"   - Comparação Direta (Int): {tem_int}")
            print(f"   - Comparação Convertida (Str): {tem_str}")
            
            if not tem_int and tem_str:
                print("🚨 CAUSA IDENTIFICADA: A lista de unidades é String, mas seu código busca Int.")

if __name__ == "__main__":
    diagnostico_cirurgico()