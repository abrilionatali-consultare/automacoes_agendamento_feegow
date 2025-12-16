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
        auth = authenticate(username, password)

        if auth:
            cookies["logged_in"] = "true"
            cookies["username"] = auth["username"]
            cookies["role"] = auth["role"]
            cookies["name"] = auth["name"]
            cookies.save()

            st.session_state.update(auth)
            st.session_state["logged_in"] = True

            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
