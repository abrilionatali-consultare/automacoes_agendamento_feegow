import streamlit as st
from datetime import date
from core.gerar_mapas_wrapper import gerar_mapas_wrapper
from core.api_client import list_unidades

# 1. Verificação de Login
if not st.session_state.get("logged_in", False):
    st.switch_page("Home.py")
    st.stop()

# 2. Configuração da Página
st.set_page_config(page_title="Mapa Diário", page_icon="📆", layout="wide")

st.title("📅 Gerar Mapa de Salas - Diário")
st.write("Selecione a data e a unidade desejada para gerar o relatório de ocupação diária.")

# 3. Inputs de Usuário (Mesmo padrão da página semanal)
col1, col2 = st.columns(2)

with col1:
    target_date_dt = st.date_input("Selecione a Data", value=date.today(), format='DD/MM/YYYY')
    target_date_str = target_date_dt.strftime("%d-%m-%Y")

with col2:
    df_unid = list_unidades()
    # Removida a opção "Todas" conforme solicitado
    unidades_opcoes = list(df_unid['nome_fantasia'])
    unidade_sel = st.selectbox("Unidade", unidades_opcoes)

if target_date_dt == date.today():
    st.warning(
        """
        **⚠️ Atenção: Visualizando Data Atual**
        
        A API de disponibilidade remove da grade os horários que já passaram (ex: horários da manhã).
        * **Consequência:** A coluna 'Grade' mostrará apenas o que *sobra* do dia, fazendo a taxa de ocupação parecer artificialmente alta (ex: 100%).
        * **Recomendação:** Para ver a capacidade total real, gere o mapa para datas futuras (D+1).
        """
    )

# 4. Botão de Ação
botao = st.button("Gerar Mapa Diário")
st.divider()

# 5. Processamento e Exibição de Resultados
if botao:
    with st.spinner("Gerando relatório diário..."):
        try:
            results = gerar_mapas_wrapper(
                tipo='diario',
                unidade_id=unidade_sel,
                week_start=target_date_str
            )

            if not isinstance(results, dict) or not results:
                 st.warning("Nenhum dado encontrado para a data e unidade selecionadas.")
            elif "warning" in results:
                 st.warning(results["warning"])
            else:
                # [CORREÇÃO]: Interface simplificada focada apenas na unidade
                st.success(f"Mapa Diário de {unidade_sel} gerado com sucesso!")

                # Pegamos o PDF da unidade selecionada (única chave no dicionário)
                pdf_bytes = results[unidade_sel]
                
                st.subheader("Visualização")
                
                try:
                    st.pdf(pdf_bytes, height=800)
                except AttributeError:
                    import base64
                    b64 = base64.b64encode(pdf_bytes).decode('utf-8')
                    pdf_display = f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="800" type="application/pdf"></iframe>'
                    st.markdown(pdf_display, unsafe_allow_html=True)

                col_dl, col_view = st.columns([1, 4])
                
                with col_dl:
                    st.download_button(
                        label=f"📥 Baixar Mapa - {unidade_sel}",
                        data=pdf_bytes,
                        file_name=f"Mapa_Diario_{unidade_sel}_{target_date_str}.pdf",
                        mime="application/pdf",
                        type="primary"
                    )
                            
        except Exception as e:
            st.error(f"Erro ao gerar mapa diário: {e}")