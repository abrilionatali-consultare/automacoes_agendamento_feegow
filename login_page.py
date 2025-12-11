import streamlit as st
import os
from core.auth import authenticate

def login_page():

    # Usa o CookieManager criado no Home.py
    cookies = st.session_state.get("cookies")

    st.title("🔐 Login")
    st.write("Acesse o sistema usando suas credenciais.")

    username = st.text_input("Usuário")
    password = st.text_input("Senha", type="password")

    if st.button("Entrar"):
        ok, role = authenticate(username, password)

        if ok:
            # Salva nos cookies
            cookies["logged_in"] = "true"
            cookies["username"] = username
            cookies["role"] = role
            cookies.save()

            # Salva no session_state
            st.session_state["logged_in"] = True
            st.session_state["username"] = username
            st.session_state["role"] = role

            st.success("Login realizado com sucesso!")
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
