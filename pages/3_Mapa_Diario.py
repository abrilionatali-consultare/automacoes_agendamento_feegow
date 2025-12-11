import streamlit as st
from datetime import date
from core.gerar_mapas_wrapper import gerar_mapas_wrapper
from core.api_client import list_unidades

if not st.session_state.get("logged_in", False):
    st.switch_page("Home.py")   # Redireciona para login
    st.stop()

st.set_page_config(page_title="Mapa diário", page_icon="📆", layout="wide")

st.title("📅 Gerar Mapa de Salas - Diário")
st.write("Gera relatórios de ocupação: um consolidado geral e arquivos individuais por unidade.")

col1, col2 = st.columns(2)

with col1:
    target_date_dt = st.date_input("Selecione a Data", value=date.today(), format='DD/MM/YYYY')
    target_date_str = target_date_dt.strftime("%d-%m-%Y")

with col2:
    df_unid = list_unidades()
    unidades_opcoes = ["Todas"] + list(df_unid['nome_fantasia'])
    unidade_sel = st.selectbox("Unidade", unidades_opcoes)

st.divider()

if st.button("Gerar Mapa Diário"):
    with st.spinner("Gerando relatório..."):
        try:
            results = gerar_mapas_wrapper(
                tipo='diario',
                unidade_id=unidade_sel,
                week_start=target_date_str
            )

            if isinstance(results, dict) and "warning" in results:
                st.warning(results["warning"])
            
            elif isinstance(results, dict) and "Geral" in results:
                st.success("Relatórios gerados com sucesso!")

                st.subheader("📊 Relatório Geral (Todas as Unidades)")
                pdf_geral= results["Geral"]

                col_g1, col_g2 = st.columns([1, 5])
                with col_g1:
                    st.download_button(
                            label="📥 Baixar PDF Geral",
                            data=pdf_geral,
                            file_name=f"Mapa_Diario_GERAL_{target_date_str}.pdf",
                            mime="application/pdf",
                            type="primary"
                        )

                st.divider()

                # --- 2. Abas Individuais ---
                st.subheader("🏢 Relatórios Individuais")
                
                individuais = results["Individual"]
                unit_names = list(individuais.keys())
                
                if unit_names:
                    tabs = st.tabs(unit_names)
                    
                    for i, unidade in enumerate(unit_names):
                        pdf_bytes = individuais[unidade]
                        
                        with tabs[i]:
                            c1, c2 = st.columns([1, 4])
                            with c1:
                                st.download_button(
                                    label=f"📥 PDF - {unidade}",
                                    data=pdf_bytes,
                                    file_name=f"Mapa_Diario_{unidade}_{target_date_str}.pdf",
                                    mime="application/pdf",
                                    key=f"btn_ind_{i}"
                                )
                            
                            # Visualização
                            try:
                                st.write("Visualização:")
                                st.pdf(pdf_bytes, height=600)
                            except AttributeError:
                                import base64
                                b64 = base64.b64encode(pdf_bytes).decode('utf-8')
                                href = f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="600"></iframe>'
                                st.markdown(href, unsafe_allow_html=True)
                else:
                    st.info("Apenas uma unidade foi selecionada ou processada.")

        except Exception as e:
            st.error(f"Erro ao gerar mapa: {e}")