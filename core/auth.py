import json
import bcrypt
import streamlit as st


def load_users():
    try:
        return json.loads(st.secrets["USERS_JSON"])
    except KeyError:
        st.error("Secret USERS_JSON não configurada.")
        return {}


def authenticate(username: str, password: str):
    users = load_users()
    user = users.get(username)

    if not user:
        return None

    if bcrypt.checkpw(
        password.encode("utf-8"),
        user["password_hash"].encode("utf-8")
    ):
        return {
            "username": username,
            "name": user["name"],
            "role": user["role"]
        }

    return None
