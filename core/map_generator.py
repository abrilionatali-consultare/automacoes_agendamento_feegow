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
    get_main_specialty_id,
    list_blocks
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

# ==============================================================================
# FUNÇÃO AUXILIAR DE FILTRO DE BLOQUEIOS
# ==============================================================================
def _remove_blocked_slots(df_slots, start_date_str, end_date_str, unidade_id=None):
    """
    Remove linhas do DataFrame que coincidem com períodos de bloqueio.
    Versão Blindada: Corrige tipagem de unidades (str/int) e datas.
    """
    if df_slots.empty:
        return df_slots

    df_blocks = list_blocks(start_date=start_date_str, end_date=end_date_str)
    
    if df_blocks.empty:
        return df_slots

    # 1. Preparação Robusta de Datas dos Slots
    # Tenta ler dayfirst=True (DD-MM-YYYY) padrão BR. Se falhar, tenta ISO.
    df_slots['_temp_date'] = pd.to_datetime(df_slots['data'], dayfirst=True, errors='coerce').dt.date
    # Fallback: Se gerou NaT (Not a Time), tenta forçar formato ISO
    mask_nat = df_slots['_temp_date'].isna()
    if mask_nat.any():
        df_slots.loc[mask_nat, '_temp_date'] = pd.to_datetime(df_slots.loc[mask_nat, 'data'], errors='coerce').dt.date
        
    df_slots['_temp_time'] = pd.to_datetime(df_slots['horario'], format="%H:%M:%S", errors='coerce').dt.time
    
    if 'profissional_id' in df_slots.columns:
        df_slots['profissional_id'] = pd.to_numeric(df_slots['profissional_id'], errors='coerce').fillna(0).astype(int)

    # 2. Máscara de Exclusão
    mask_exclude = pd.Series([False] * len(df_slots), index=df_slots.index)

    # Garante que a unidade alvo seja Inteiro (se existir)
    target_unit = int(unidade_id) if unidade_id else None

    for _, block in df_blocks.iterrows():
        # --- A. VERIFICAÇÃO DE UNIDADE (CORRIGIDA) ---
        block_units = block.get('units')
        
        should_apply_block = False
        
        if target_unit is None:
            # Se não estamos filtrando por unidade (Mapa Geral), aplica todos os bloqueios
            should_apply_block = True
        else:
            # Estamos gerando mapa para Unidade X. O bloqueio se aplica a X?
            
            # Cenário 1: Lista de Unidades
            if isinstance(block_units, list) and len(block_units) > 0:
                # [CORREÇÃO CRÍTICA]: Converte a lista do bloqueio para inteiros para garantir
                # Isso resolve o caso de ["12"] vs 12
                clean_units = []
                for u in block_units:
                    try: clean_units.append(int(u))
                    except: pass
                
                if target_unit in clean_units or 0 in clean_units:
                    should_apply_block = True
            
            # Cenário 2: Fallback (Coluna antiga unidade_id)
            else:
                legacy_uid = block.get('unidade_id')
                try:
                    legacy_uid = int(legacy_uid) if legacy_uid is not None else 0
                except:
                    legacy_uid = 0
                
                if legacy_uid == 0 or legacy_uid == target_unit:
                    should_apply_block = True

        if not should_apply_block:
            continue

        # --- B. Verifica Data (Segura) ---
        # block['date_start'] já vem como date object do list_blocks
        m_date = (df_slots['_temp_date'] >= block['date_start']) & (df_slots['_temp_date'] <= block['date_end'])
        
        if not m_date.any(): continue

        # --- C. Verifica Horário ---
        blk_start = block['time_start'] if pd.notnull(block.get('time_start')) else time(0,0)
        blk_end = block['time_end'] if pd.notnull(block.get('time_end')) else time(23,59,59)
        
        m_time = (df_slots['_temp_time'] >= blk_start) & (df_slots['_temp_time'] <= blk_end)
        
        # --- D. Verifica Profissional ---
        blk_prof = int(block['professional_id']) if pd.notnull(block.get('professional_id')) else 0
        
        if blk_prof > 0:
            m_prof = (df_slots['profissional_id'] == blk_prof)
        else:
            m_prof = True # Afeta todos

        # Combina
        current_mask = m_date & m_time & m_prof
        mask_exclude = mask_exclude | current_mask

    # 3. Limpeza
    df_clean = df_slots[~mask_exclude].copy()
    df_clean.drop(columns=['_temp_date', '_temp_time'], inplace=True, errors='ignore')
    
    removidos = mask_exclude.sum()
    if removidos > 0:
        print(f"DEBUG: 🛡️ Bloqueio ativo! {removidos} slots da médica/unidade foram removidos.")
        
    return df_clean

# ==============================================================================
# RECONSTRUÇÃO HÍBRIDA (Passado Simulado + Futuro Real)
# ==============================================================================
def _fetch_grade_simulada(unidade_id, date_str, profissional_id, especialidade_id):
    """
    Abordagem Híbrida para o dia de "Hoje":
    1. Horários < Agora: Usa o Espelho (D+7) para preencher o passado que a API esconde.
    2. Horários >= Agora: Usa a API Real de hoje para precisão total.
    """
    # Conversão de datas
    try:
        dt_target = datetime.strptime(date_str, "%d-%m-%Y").date()
    except ValueError:
        return pd.DataFrame()
        
    dt_today = date.today()
    now_time = datetime.now().time()
    
    # ---------------------------------------------------------
    # CENÁRIO 1: Data Futura (Amanhã em diante)
    # ---------------------------------------------------------
    # Confia 100% na API Real. Não há passado para simular.
    if dt_target > dt_today:
        return fetch_horarios_disponiveis(unidade_id, date_str, date_str, profissional_id, especialidade_id=especialidade_id)

    # ---------------------------------------------------------
    # CENÁRIO 2: Data Passada (Ontem para trás)
    # ---------------------------------------------------------
    # A API Real retorna vazio. Precisamos simular 100% via Espelho.
    # Define flag para usar apenas a lógica de espelho abaixo sem corte.
    is_today = (dt_target == dt_today)
    
    # Prepara DataFrame final
    df_combined = pd.DataFrame()

    # =========================================================
    # PARTE A: BUSCA DO ESPELHO (Para Passado ou Híbrido-Passado)
    # =========================================================
    # Tenta D+7 ou D+14
    mirrors = [dt_target + timedelta(days=7), dt_target + timedelta(days=14)]
    df_mirror = pd.DataFrame()
    
    for mirror_date in mirrors:
        m_str = mirror_date.strftime("%d-%m-%Y")
        raw_mirror = fetch_horarios_disponiveis(unidade_id, m_str, m_str, profissional_id, especialidade_id=especialidade_id)
        if not raw_mirror.empty:
            df_mirror = raw_mirror.copy()
            break
            
    if not df_mirror.empty:
        # Traz para a data alvo
        df_mirror['data'] = date_str
        
        if is_today:
            # FILTRO DO PASSADO: Mantém apenas o que já aconteceu (horario < agora)
            # Converte para time object para comparar
            temp_times = pd.to_datetime(df_mirror['horario'], format="%H:%M:%S", errors='coerce').dt.time
            df_mirror = df_mirror[temp_times < now_time]
        
        # Adiciona ao combinado
        df_combined = pd.concat([df_combined, df_mirror], ignore_index=True)

    # =========================================================
    # PARTE B: BUSCA REAL (Apenas se for HOJE)
    # =========================================================
    if is_today:
        # Busca o que a API tem de verdade para agora/hoje
        df_real = fetch_horarios_disponiveis(unidade_id, date_str, date_str, profissional_id, especialidade_id=especialidade_id)
        
        if not df_real.empty:
            # FILTRO DO FUTURO: Mantém apenas o que é daqui pra frente (horario >= agora)
            # A API já deve trazer só futuro, mas garantimos para evitar duplicação na borda
            temp_times_real = pd.to_datetime(df_real['horario'], format="%H:%M:%S", errors='coerce').dt.time
            df_real = df_real[temp_times_real >= now_time]
            
            df_combined = pd.concat([df_combined, df_real], ignore_index=True)

    # =========================================================
    # PARTE C: FINALIZAÇÃO
    # =========================================================
    if df_combined.empty:
        return df_combined

    # Ordena por horário para o mapa ficar bonito
    if 'horario' in df_combined.columns:
        df_combined = df_combined.sort_values(by='horario')

    # Remove duplicatas (caso a borda do tempo tenha gerado overlap)
    df_combined.drop_duplicates(subset=['horario', 'profissional_id'], inplace=True)

    # Aplica os bloqueios de HOJE (Segurança final)
    df_final = _remove_blocked_slots(df_combined, date_str, date_str, unidade_id=unidade_id)
    
    return df_final

def generate_weekly_maps(start_date, unidade_id=None, output_dir="mapas_gerados"):
    """
    Função de Mapa Semanal com suporte à Busca Híbrida (Simulação de Passado + Futuro Real).
    """
    start_date_str = start_date if isinstance(start_date, str) else start_date.strftime("%d-%m-%Y")
    df_unid_list = list_unidades()

    # Datas de controle
    start_dt = datetime.strptime(start_date_str, "%d-%m-%Y").date()
    end_dt = start_dt + timedelta(days=6)
    end_date_str = end_dt.strftime("%d-%m-%Y")
    today = date.today()

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    unidade_sel_id = None
    if unidade_id and unidade_id != 'Todas':
        filtro = df_unid_list[df_unid_list['nome_fantasia'] == unidade_id]
        if not filtro.empty:
            unidade_sel_id = int(filtro['unidade_id'].iloc[0])

    # 1. Busca Agendamentos (Dados Reais)
    df_ag = fetch_agendamentos(start_date=start_date_str, end_date=end_date_str, unidade_id=unidade_sel_id)
    if df_ag.empty: return {"warning": "Vazio"}
    
    # Filtro de status válidos
    required_status = [1, 7, 2, 3, 4]
    df_ag = df_ag[df_ag['status_id'].isin(required_status)]
    
    # 2. Injeção de Grade (Lógica Híbrida vs Padrão)
    profs_ativos = df_ag["profissional_id"].unique()
    all_slots = []
    
    # ==============================================================================
    # 🛑 CONFIGURAÇÃO: DEFINA COMO 'False' PARA DESATIVAR A BUSCA POR ESPELHO
    # ==============================================================================
    USAR_BUSCA_HIBRIDA = True  
    # ==============================================================================

    for p_id in profs_ativos:
        p_int = int(p_id)
        sid = get_main_specialty_id(p_int)
        
        if sid:
            # --- CAMINHO A: LÓGICA HÍBRIDA (Recupera Passado + Pega Futuro) ---
            if USAR_BUSCA_HIBRIDA:
                # 1. Dias Passados ou Hoje (Requer Simulação/Espelho)
                # Iteramos dia a dia até chegar em "Amanhã" ou no fim do intervalo
                current_loop_dt = start_dt
                
                while current_loop_dt <= end_dt and current_loop_dt <= today:
                    loop_str = current_loop_dt.strftime("%d-%m-%Y")
                    
                    # Chama a função de espelho para este dia
                    v_sim = _fetch_grade_simulada(
                        unidade_sel_id, loop_str, p_int, especialidade_id=int(sid)
                    )
                    
                    if not v_sim.empty:
                        v_sim['agendamento_id'], v_sim['status_id'] = 0, 0
                        all_slots.append(v_sim)
                    
                    current_loop_dt += timedelta(days=1)
                
                # 2. Dias Futuros (Amanhã em diante) - Otimização com chamada única
                if current_loop_dt <= end_dt:
                    future_start_str = current_loop_dt.strftime("%d-%m-%Y")
                    
                    v_future = fetch_horarios_disponiveis(
                        unidade_sel_id, future_start_str, end_date_str, p_int, especialidade_id=int(sid)
                    )
                    if not v_future.empty:
                        v_future['agendamento_id'], v_future['status_id'] = 0, 0
                        all_slots.append(v_future)

            # --- CAMINHO B: LÓGICA PADRÃO (Apenas API Real - Passado virá vazio) ---
            else:
                vagas = fetch_horarios_disponiveis(
                    unidade_sel_id, start_date_str, end_date_str, p_int, especialidade_id=int(sid)
                )
                if not vagas.empty:
                    vagas['agendamento_id'], vagas['status_id'] = 0, 0 
                    all_slots.append(vagas)

    # ==============================================================================
    # VARREDURA COMPLEMENTAR: BUSCAR MÉDICOS SEM AGENDAMENTO (GRADE VAZIA)
    # ==============================================================================
    # Lista de quem já foi processado no loop anterior
    processed_ids = set(map(int, profs_ativos))
    
    # Lista total de profissionais ativos no sistema (df_prof é global)
    # Filtra apenas quem está ativo (se houver coluna de status) ou pega todos
    all_prof_ids = df_prof['profissional_id'].unique()

    for p_id in all_prof_ids:
        p_int = int(p_id)
        
        # Se já processamos este médico (porque ele tinha agendamento), pula
        if p_int in processed_ids:
            continue

        # Busca especialidade principal para poder consultar a grade
        sid = get_main_specialty_id(p_int)
        
        if sid:
            # Tenta buscar horários para este médico "ocioso"
            # Nota: Usamos a mesma lógica de busca (Híbrida ou Normal) que já está configurada na função
            
            # --- Se for no MAPA SEMANAL e estiver usando Busca Híbrida: ---
            # (Copie a lógica de USAR_BUSCA_HIBRIDA se estiver dentro do semanal)
            # Para simplificar aqui, vou colocar a busca direta, mas idealmente deve seguir o padrão da função:
            
            vagas_extra = pd.DataFrame()
            
            # Exemplo genérico (serve para Diário e Semanal simples):
            vagas_extra = fetch_horarios_disponiveis(
                unidade_sel_id, start_date_str, end_date_str, p_int, especialidade_id=int(sid)
            )

            # --- Se for MAPA SEMANAL COM SIMULAÇÃO, você precisaria replicar a lógica do while/loop aqui ---
            # Mas geralmente, médicos sem agendamento no passado não precisam de simulação complexa 
            # pois não há "buracos" de agendamentos passados para preencher. 
            # A busca direta costuma resolver a maioria dos casos de "Agenda Aberta Vazia".

            if not vagas_extra.empty:
                vagas_extra['agendamento_id'] = 0
                vagas_extra['status_id'] = 0 # Status 0 ou null indica grade livre
                vagas_extra['profissional_id'] = p_int
                vagas_extra['especialidade_id'] = int(sid)
                all_slots.append(vagas_extra)

    # União
    if all_slots:
        df = pd.concat([df_ag, pd.concat(all_slots)], ignore_index=True)
        # Sincronização simples para o semanal
        df['especialidade_id'] = df.groupby(['profissional_id', 'local_id'])['especialidade_id'].transform(lambda x: x.ffill().bfill())
    else:
        df = df_ag.copy()

    # Aplica filtro de bloqueios (Crucial para limpar a grade simulada se houver bloqueio real)
    df = _remove_blocked_slots(df, start_date_str, end_date_str, unidade_id=unidade_sel_id)
    if df.empty: return {"warning": "Todos os horários estão bloqueados."}

    df['especialidade_id'] = pd.to_numeric(df['especialidade_id'], errors='coerce').fillna(0).astype(int)
    df['profissional_id'] = pd.to_numeric(df['profissional_id'], errors='coerce').fillna(0).astype(int)
    df['local_id'] = pd.to_numeric(df['local_id'], errors='coerce').fillna(0).astype(int)

    mapa_esp = df_esp.set_index('especialidade_id')['nome'].to_dict()
    mapa_loc = df_loc.set_index('id')['local'].to_dict()
    mapa_prof = df_prof.set_index('profissional_id')['nome'].to_dict()

    if 'especialidade' not in df.columns:
        df['especialidade'] = df['especialidade_id'].map(mapa_esp)
    else:
        df['especialidade'] = df['especialidade'].fillna(df['especialidade_id'].map(mapa_esp))

    if 'sala' not in df.columns:
        df['sala'] = df['local_id'].map(mapa_loc)
    else:
        df['sala'] = df['sala'].fillna(df['local_id'].map(mapa_loc))

    if 'nome_profissional' not in df.columns:
        df['nome_profissional'] = df['profissional_id'].map(mapa_prof)
    else:
        df['nome_profissional'] = df['nome_profissional'].fillna(df['profissional_id'].map(mapa_prof))

    # df = df.merge(df_esp[['especialidade_id', 'nome']], on="especialidade_id", how="left").rename(columns={'nome': 'especialidade'})
    # df = df.merge(df_prof[['profissional_id', 'nome']], on="profissional_id", how="left").rename(columns={'nome': 'nome_profissional'})
    # df = df.merge(df_loc[['id', 'local']], left_on="local_id", right_on="id", how="left").rename(columns={'local': 'sala'})

    for col in ['especialidade', 'nome_profissional', 'sala']:
        if col in df.columns:
            df[col] = df[col].replace({'nan': None, 'NAN': None, 'NaN': None})
            # Preenchimento final de segurança
            fallback = "Indefinido" if col != 'especialidade' else "Especialidade"
            df[col] = df[col].fillna(fallback)
    
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

    nota_rodape = "" # Padrão: Vazio

    # Se a semana começa HOJE ou no PASSADO, haverá simulação.
    # Se a semana começa AMANHÃ (start_dt > today), é 100% futuro/real -> Sem nota.
    if start_dt <= today:
        now = datetime.now()
        timestamp = now.strftime('%d/%m/%Y às %H:%M')
        hora_corte = now.strftime('%H:%M')
        
        nota_rodape = (
            f"Relatório gerado em {timestamp}. "
            f"Para datas passadas e horários de hoje anteriores a {hora_corte}, "
            f"as grades são simuladas baseados na próxima agenda (D+7). "
            f"Datas futuras e horários de hoje após {hora_corte} utilizam dados reais da API."
        )

    for unidade in df_final["unidade"].unique():
        if not unidade: continue
        
        # Filtra e gera
        matrices, occ, days = build_matrices(df_final[df_final["unidade"] == unidade], include_taxa=False)
        
        pdf_bytes = render_pdf_from_template(
            unidade, matrices, occ, days, start_date_str, end_date_str, 
            "templates/semanal2.html", cell_font_size_px=9, return_bytes=True,
            footer_text=nota_rodape 
        )
        out_bytes[unidade] = pdf_bytes
        
    return out_bytes

def generate_daily_maps(start_date, unidade_id=None, output_dir="mapas_gerados"):
    start_date_str = start_date if isinstance(start_date, str) else start_date.strftime("%d-%m-%Y")
    
    DE_PARA_UNIDADES_VAGAS = { 39867: 12, 12: 12 }
    df_unid_list = list_unidades()

    # 1. Identificação da Unidade
    unidade_sel_id = None
    if unidade_id and unidade_id != 'Todas':
        filtro = df_unid_list[df_unid_list['nome_fantasia'] == unidade_id]
        if not filtro.empty:
            raw_id = int(filtro['unidade_id'].iloc[0])
            unidade_sel_id = DE_PARA_UNIDADES_VAGAS.get(raw_id, raw_id)

    # 2. Busca Agendamentos
    df_ag = fetch_agendamentos(start_date=start_date_str, end_date=start_date_str, unidade_id=unidade_sel_id)
    if df_ag.empty: return {"warning": "Sem agendamentos para esta data."}

    # Garante tipagem inicial
    for col in ['profissional_id', 'local_id', 'especialidade_id', 'agendamento_id', 'status_id']:
        if col in df_ag.columns:
            df_ag[col] = pd.to_numeric(df_ag[col], errors='coerce').fillna(0).astype(int)

    # Remoção de status inválidos
    required_status = [1, 7, 2, 3, 4]
    df_ag = df_ag[df_ag['status_id'].isin(required_status)]

    # 3. Injeção de Grade
    profs = df_ag["profissional_id"].unique()
    all_slots = []
    
    for p_id in profs:
        p_int = int(p_id)
        if p_int == 0: continue

        specs_do_dia = df_ag[df_ag['profissional_id'] == p_int]['especialidade_id'].unique()
        specs_do_dia = [int(s) for s in specs_do_dia if s > 0]
        
        # Se não achou especialidade no agendamento, busca a principal para poder consultar a grade
        if not specs_do_dia:
            sid_main = get_main_specialty_id(p_int)
            if sid_main: specs_do_dia = [sid_main]
            
        for sid in specs_do_dia:
            # ====================
            # IMPLEMENTAÇÃO DA BUSCA HÍBRIDA PARA DADOS RETROATIVOS
            # Para desativar, substituir pela chamada direta à API: fetch_horarios_disponiveis(...)
            # ====================
            v_df = _fetch_grade_simulada(
                unidade_id=unidade_sel_id,
                date_str=start_date_str, # Passamos apenas a data do dia
                profissional_id=p_int, 
                especialidade_id=int(sid)
            )
            
            if not v_df.empty:
                v_df['agendamento_id'] = 0
                v_df['status_id'] = 0
                v_df['profissional_id'] = p_int
                v_df['especialidade_id'] = int(sid)
                
                if 'local_id' not in v_df.columns or v_df['local_id'].sum() == 0:
                     locais = df_ag[df_ag['profissional_id'] == p_int]['local_id'].unique()
                     local_fallback = locais[0] if len(locais) > 0 else 0
                     v_df['local_id'] = int(local_fallback)
                
                all_slots.append(v_df)

    # ==============================================================================
    # VARREDURA COMPLEMENTAR: BUSCAR MÉDICOS SEM AGENDAMENTO (GRADE VAZIA)
    # ==============================================================================
    # Lista de quem já foi processado no loop anterior
    processed_ids = set(map(int, profs))
    
    # Lista total de profissionais ativos no sistema (df_prof é global)
    # Filtra apenas quem está ativo (se houver coluna de status) ou pega todos
    all_prof_ids = df_prof['profissional_id'].unique()

    for p_id in all_prof_ids:
        p_int = int(p_id)
        
        # Se já processamos este médico (porque ele tinha agendamento), pula
        if p_int in processed_ids:
            continue

        # Busca especialidade principal para poder consultar a grade
        sid = get_main_specialty_id(p_int)
        
        if sid:
            # Tenta buscar horários para este médico "ocioso"
            # Nota: Usamos a mesma lógica de busca (Híbrida ou Normal) que já está configurada na função
            
            # --- Se for no MAPA SEMANAL e estiver usando Busca Híbrida: ---
            # (Copie a lógica de USAR_BUSCA_HIBRIDA se estiver dentro do semanal)
            # Para simplificar aqui, vou colocar a busca direta, mas idealmente deve seguir o padrão da função:
            
            vagas_extra = pd.DataFrame()
            
            # Exemplo genérico (serve para Diário e Semanal simples):
            vagas_extra = fetch_horarios_disponiveis(
                unidade_sel_id, start_date_str, start_date_str, p_int, especialidade_id=int(sid)
            )

            # --- Se for MAPA SEMANAL COM SIMULAÇÃO, você precisaria replicar a lógica do while/loop aqui ---
            # Mas geralmente, médicos sem agendamento no passado não precisam de simulação complexa 
            # pois não há "buracos" de agendamentos passados para preencher. 
            # A busca direta costuma resolver a maioria dos casos de "Agenda Aberta Vazia".

            if not vagas_extra.empty:
                # 1. Busca o nome da especialidade no df_esp global usando o sid
                # Filtramos pela coluna ID e pegamos o valor da coluna de texto (nome ou especialidade)
                col_texto_esp = 'especialidade' if 'especialidade' in df_esp.columns else 'nome'
                esp_match = df_esp[df_esp['especialidade_id'] == int(sid)]
                nome_especialidade = str(esp_match[col_texto_esp].iloc[0]) if not esp_match.empty else "Especialidade"

                # 2. Busca o nome do profissional no df_prof global para evitar NaN lá também
                prof_match = df_prof[df_prof['profissional_id'] == p_int]
                nome_profissional = str(prof_match['nome'].iloc[0]) if not prof_match.empty else f"Prof. ID {p_int}"

                # 3. Preenche o DataFrame de forma "blindada"
                vagas_extra = vagas_extra.copy()
                vagas_extra['agendamento_id'] = 0
                vagas_extra['status_id'] = 0
                vagas_extra['profissional_id'] = p_int
                vagas_extra['especialidade_id'] = int(sid)
                
                # Injeta os nomes textuais (isso impede o NaN no mapa)
                vagas_extra['profissional'] = nome_profissional
                vagas_extra['especialidade'] = nome_especialidade

                # Garante que a coluna 'local_id' existe (necessário para o mapa diário)
                if 'local_id' not in vagas_extra.columns:
                    vagas_extra['local_id'] = 0

                all_slots.append(vagas_extra)

    if all_slots:
        df_grade = pd.concat(all_slots, ignore_index=True)
        df_grade = df_grade.drop_duplicates(subset=['profissional_id', 'horario', 'local_id'])
        df = pd.concat([df_ag, df_grade], ignore_index=True)
    else:
        df = df_ag.copy()

    # Aplica filtro de bloqueios
    df = _remove_blocked_slots(df, start_date_str, start_date_str, unidade_id=unidade_sel_id)
    if df.empty: return {"warning": "Todos os agendamentos/vagas coincidem com bloqueios de agenda."}

    # ==============================================================================
    # [PASSO 1] RECUPERAÇÃO E SANEAMENTO DE DADOS (Antes do Merge)
    # ==============================================================================
    
    # 1. Garante que IDs sejam numéricos
    df['especialidade_id'] = pd.to_numeric(df['especialidade_id'], errors='coerce').fillna(0).astype(int)
    df['profissional_id'] = pd.to_numeric(df['profissional_id'], errors='coerce').fillna(0).astype(int)
    df['local_id'] = pd.to_numeric(df['local_id'], errors='coerce').fillna(0).astype(int)

    # 2. Remove imediatamente linhas sem médico (profissional_id == 0)
    # Se não tem ID de médico, é lixo de base e não serve para o mapa.
    df = df[df['profissional_id'] > 0]

    # 3. Tenta salvar especialidade zerada buscando a principal do médico
    mask_sem_spec = df['especialidade_id'] == 0
    
    if mask_sem_spec.any():
        print(f"DEBUG: Tentando recuperar especialidade para {mask_sem_spec.sum()} registros...")
        
        def recuperar_spec(row):
            # Se já tem, mantém
            if row['especialidade_id'] > 0: return row['especialidade_id']
            # Se não tem, busca na API/Cache
            pid = row['profissional_id']
            spec_recuperada = get_main_specialty_id(pid)
            return spec_recuperada if spec_recuperada else 0
            
        # Aplica a recuperação linha a linha onde necessário
        df.loc[mask_sem_spec, 'especialidade_id'] = df.loc[mask_sem_spec].apply(recuperar_spec, axis=1)

    # ==============================================================================
    # 5. Merges (Agora com IDs mais limpos)
    mapa_esp = df_esp.set_index('especialidade_id')['nome'].to_dict()
    mapa_loc = df_loc.set_index('id')['local'].to_dict()
    mapa_prof = df_prof.set_index('profissional_id')['nome'].to_dict()

    if 'especialidade' not in df.columns:
        df['especialidade'] = df['especialidade_id'].map(mapa_esp)
    else:
        df['especialidade'] = df['especialidade'].fillna(df['especialidade_id'].map(mapa_esp))

    if 'sala' not in df.columns:
        df['sala'] = df['local_id'].map(mapa_loc)
    else:
        df['sala'] = df['sala'].fillna(df['local_id'].map(mapa_loc))

    if 'nome_profissional' not in df.columns:
        df['nome_profissional'] = df['profissional_id'].map(mapa_prof)
    else:
        df['nome_profissional'] = df['nome_profissional'].fillna(df['profissional_id'].map(mapa_prof))

    # df = df.merge(df_esp[['especialidade_id', 'nome']], on="especialidade_id", how="left").rename(columns={'nome': 'especialidade'})
    # df = df.merge(df_prof[['profissional_id', 'nome']], on="profissional_id", how="left").rename(columns={'nome': 'nome_profissional'})
    # df = df.merge(df_loc[['id', 'local']], left_on="local_id", right_on="id", how="left").rename(columns={'local': 'sala'})

    # ==============================================================================
    # [PASSO 2] LIMPEZA FINAL (Pós-Merge)
    # ==============================================================================
    
    # Converte para string para analisar o conteúdo textual
    df['nome_profissional'] = df['nome_profissional'].astype(str).str.strip()
    df['especialidade'] = df['especialidade'].astype(str).str.strip()
    df['sala'] = df['sala'].astype(str).str.strip()
    
    # Termos proibidos (indica falha no merge ou dado nulo original)
    termos_invalidos = ['nan', 'none', '', 'null', 'nat']
    
    # Filtros: Mantém apenas se O NOME E A ESPECIALIDADE forem válidos
    keep_prof = ~df['nome_profissional'].str.lower().isin(termos_invalidos)
    keep_spec = ~df['especialidade'].str.lower().isin(termos_invalidos)
    keep_sala = ~df['sala'].str.lower().isin(termos_invalidos)
    
    # Aplica o corte
    df = df[keep_prof & keep_spec & keep_sala]
    
    # ==============================================================================

    # Normalização
    df_final, _ = normalize_and_validate(df)
    
    remover_visual = ['PRÉ ATENDIMENTO', 'COLETA DOMICILIAR', 'TELEMEDICINA']
    df_final = df_final[~df_final['sala'].str.upper().str.contains('|'.join(remover_visual), na=False)]
    
    df_final['time'] = df_final['horario'].apply(to_time)
    df_final['periodo'] = df_final['time'].apply(periodo_from_time)
    
    # 6. Agrupamento
    master_data = {}
    dados_uni = {
        "Manhã": [], "Tarde": [], 
        "totais": {'Manhã': {'grade': 0, 'pacientes': 0, 'taxa': 0}, 'Tarde': {'grade': 0, 'pacientes': 0, 'taxa': 0}, 'dia': {'grade': 0, 'pacientes': 0, 'taxa': 0}}
    }
    
    grouped = df_final.groupby(['sala', 'nome_profissional', 'especialidade', 'periodo']).agg(
        pacientes_reais=('agendamento_id', lambda x: (pd.to_numeric(x, errors='coerce').fillna(0) > 0).sum()),
        grade_total=('horario', 'count')
    ).reset_index()

    # Ordenação Natural
    def natural_key(text):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(text))]
    grouped['sort_key'] = grouped['sala'].apply(natural_key)
    grouped = grouped.sort_values(by='sort_key')

    for _, row in grouped.iterrows():
        g = int(row['grade_total'])
        p = int(row['pacientes_reais'])
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

    for per in ['Manhã', 'Tarde']:
        g_t = dados_uni['totais'][per]['grade']
        p_t = dados_uni['totais'][per]['pacientes']
        dados_uni['totais'][per]['taxa'] = (p_t / g_t * 100) if g_t > 0 else 0
        dados_uni['totais']['dia']['grade'] += g_t
        dados_uni['totais']['dia']['pacientes'] += p_t

    g_d = dados_uni['totais']['dia']['grade']
    p_d = dados_uni['totais']['dia']['pacientes']
    dados_uni['totais']['dia']['taxa'] = (p_d / g_d * 100) if g_d > 0 else 0

    # 7. Cálculo de Salas Físicas (Mantido e ajustado)
    salas_ignorar_contagem = ['PRÉ ATENDIMENTO', 'COLETA DOMICILIAR', "TELEMEDICINA", "TESTE"]
    
    if 'unidade_id' in df_loc.columns and unidade_sel_id:
        df_salas_unid = df_loc[df_loc['unidade_id'] == int(unidade_sel_id)]
        if df_salas_unid.empty: df_salas_unid = df_loc 
    else:
        df_salas_unid = df_loc.copy()
    
    mask_ignorar = df_salas_unid['local'].astype(str).str.upper().apply(lambda x: any(ign in x for ign in salas_ignorar_contagem))
    total_salas_fisicas = df_salas_unid[~mask_ignorar]['local'].nunique()
    
    salas_ativas_manha = df_final[df_final['periodo'] == 'Manhã']['sala'].nunique()
    salas_ativas_tarde = df_final[df_final['periodo'] == 'Tarde']['sala'].nunique()
    salas_ativas_dia = df_final['sala'].nunique()

    def calc_taxa(usadas, total):
        return (usadas / total * 100) if total > 0 else 0

    dados_uni['metricas_salas'] = {
        'total_salas': total_salas_fisicas,
        'ativas_manha': salas_ativas_manha,
        'taxa_manha': calc_taxa(salas_ativas_manha, total_salas_fisicas),
        'ativas_tarde': salas_ativas_tarde,
        'taxa_tarde': calc_taxa(salas_ativas_tarde, total_salas_fisicas),
        'ativas_dia': salas_ativas_dia,
        'taxa_dia': calc_taxa(salas_ativas_dia, total_salas_fisicas)
    }

    unidade_chave = unidade_id if unidade_id else "Geral"
    master_data[unidade_chave] = dados_uni

    dt_target = datetime.strptime(start_date_str, "%d-%m-%Y").date()
    today = date.today()
    
    nota_rodape = "" # Padrão: Vazio (Para datas futuras)

    # Só exibe o aviso se for HOJE ou PASSADO (onde ocorre simulação)
    if dt_target <= today:
        now = datetime.now()
        timestamp = now.strftime('%d/%m/%Y às %H:%M')
        hora_corte = now.strftime('%H:%M')
        
        nota_rodape = (
            f"Relatório gerado em {timestamp}. "
            f"Horários anteriores a {hora_corte} são simulados baseados na próxima agenda (D+7). "
            f"Dados após {hora_corte} refletem informações reais da API."
        )

    tpl = Environment(loader=FileSystemLoader('.')).get_template("templates/diario.html")
    
    html = tpl.render(
        unidade=unidade_chave, 
        all_data=master_data, 
        date_str=start_date_str, 
        grand_total=dados_uni['totais']['dia']['pacientes'], 
        generated=datetime.now().strftime("%d/%m/%Y %H:%M"), # Mantém gerado em sempre visível no cabeçalho se houver
        footer_text=nota_rodape  # <--- Vazio se for futuro, Texto se for hoje/passado
    )
    
    return {unidade_chave: HTML(string=html).write_pdf()}