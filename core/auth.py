import json
import bcrypt
import streamlit as st
from pathlib import Path

USERS_FILE = Path(__file__).resolve().parent.parent / "auth" / "users.json"

def load_users():
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def authenticate(username, password):
    """
    Autentica o usuário usando st.secrets em vez de users.json
    """
    users_db = st.secrets.get("users")

    if not users_db:
        st.error("Erro de configuração: Banco de usuários não encontrado nos Secrets.")
        return False, None

    # Verifica se o usuário existe
    if username in users_db:
        user_data = users_db[username]
        stored_password = user_data["password"]
        role = user_data["role"]

        # COMPARAÇÃO DE SENHA      
        if bcrypt.checkpw(password.encode('utf-8'), stored_password.encode('utf-8')):
            return True, role

    return False, None


def create_user(username, password, role="user"):
    """Cria usuário com senha criptografada (use na página de gestão)."""
    users = load_users()

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    users[username] = {"password": hashed, "role": role}

    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)

    return True
