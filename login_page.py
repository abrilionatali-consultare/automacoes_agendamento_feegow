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
        auth_result = authenticate(username, password)
        # Backward-compatible unpack in case older auth returns 2-tuple.
        if isinstance(auth_result, tuple) and len(auth_result) == 3:
            ok, role, name = auth_result
        elif isinstance(auth_result, tuple) and len(auth_result) == 2:
            ok, role = auth_result
            name = None
        else:
            ok, role, name = False, None, None

        if ok:
            # Salva nos cookies
            cookies["logged_in"] = "true"
            cookies["username"] = username
            cookies["role"] = role
            cookies["name"]= name
            cookies.save()

            # Salva no session_state
            st.session_state["logged_in"] = True
            st.session_state["username"] = username
            st.session_state["role"] = role
            st.session_state["name"] = name

            st.success("Login realizado com sucesso!")
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")

