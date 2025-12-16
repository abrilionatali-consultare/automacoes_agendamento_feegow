import streamlit as st

st.set_page_config(
    page_icon='🏠',
    layout='centered', 
    page_title='Relatório de Agendamentos',
    initial_sidebar_state='expanded'    
)

from Home import main

def run():
    main()

if __name__ == "__main__":
    run()