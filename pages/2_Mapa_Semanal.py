import streamlit as st
from datetime import date, timedelta
from core.gerar_mapas_wrapper import gerar_mapas_wrapper
from core.api_client import (
    list_unidades
)

if not st.session_state.get("logged_in", False):
    st.switch_page("Home.py")   # Redireciona para login
    st.stop()

st.set_page_config(page_title="Mapa semanal", page_icon="📆", layout="wide")

st.title("📅 Gerar Mapa de Salas - Semanal")
st.write("Selecione a data de ínicio da semana desejada para gerar o mapa de salas em PDF.")

# ================================================
# Seleção da data inicial (deve ser segunda-feira)
# ================================================
def is_monday(d):
    return d.weekday() == 0

default_monday = date.today()
while default_monday.weekday() != 0:
    default_monday -= timedelta(days=-1)

col1, col2 = st.columns(2)
with col1:
    week_start = st.date_input("Data inicial", value=default_monday, format='DD/MM/YYYY')
    start_date = week_start.strftime("%d-%m-%Y")

with col2:
    df_unid = list_unidades()
    unidades_opcoes = ["Todas"] + list(df_unid['nome_fantasia'])
    unidade_sel = st.selectbox("Gerar mapa para qual unidade?", unidades_opcoes)

if not is_monday(week_start):
    st.warning("⚠️ A data selecionada não é uma segunda-feira.")
    st.stop()

# ================================================
# Botão para gerar
# ================================================
botao = st.button("Gerar Mapas Semanais")
st.divider()

if botao:
    with st.spinner("Gerando PDFs... (isso pode levar alguns segundos)"):
        try:
            results = gerar_mapas_wrapper(
                tipo='semanal',
                unidade_id=unidade_sel,
                week_start=start_date
            )

            # Verifica se 'results' é um dicionário e tem conteúdo
            if not isinstance(results, dict) or not results:
                 st.warning("Nenhum mapa gerado. Verifique se há agendamentos para esta semana.")
            elif "warning" in results:
                 st.warning(results["warning"])
            else:
                st.success(f"Mapas gerados com sucesso! ({len(results)} unidades)")

            
            # Tabs
            unit_names = list(results.keys())
            tabs = st.tabs(unit_names)

            # 3. Itera sobre as abas e os dados ao mesmo tempo
            for i, unidade in enumerate(unit_names):
                pdf_bytes = results[unidade]
                
                with tabs[i]:
                    st.header(f"Unidade: {unidade}")
                    
                    col_dl, col_view = st.columns([1, 4])
                    
                    with col_dl:
                        st.download_button(
                            label=f"📥 Baixar PDF ({unidade})",
                            data=pdf_bytes,
                            file_name=f"Mapa_Semanal_{unidade}_{start_date}.pdf",
                            mime="application/pdf",
                            key=f"btn_{i}" # Key única necessária dentro de loops
                        )
                    
                    st.write("---")
                    st.write("Visualização")
                    
                    # Verifica se a função st.pdf existe (dependendo da biblioteca usada)
                    # Se você usa 'streamlit-pdf-viewer', isso funcionará.
                    # Caso contrário, pode ser necessário usar iframe base64.
                    try:
                        st.pdf(pdf_bytes, height=800)
                    except AttributeError:
                        # Fallback caso st.pdf não exista no ambiente
                        import base64
                        b64 = base64.b64encode(pdf_bytes).decode('utf-8')
                        pdf_display = f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="800" type="application/pdf"></iframe>'
                        st.markdown(pdf_display, unsafe_allow_html=True)
        
        except Exception as e:
            st.error(f"Erro ao gerar mapas: {e}")
    