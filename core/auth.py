import json
import os
import tomllib
from pathlib import Path

import bcrypt
import streamlit as st

USERS_FILE = Path(__file__).resolve().parent.parent / "auth" / "users.json"


def load_users():
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_users_from_env():
    raw_toml = os.getenv("STREAMLIT_USERS_TOML", "").strip()
    if raw_toml:
        try:
            parsed = tomllib.loads(raw_toml)
            users = parsed.get("users")
            if isinstance(users, dict):
                return users
        except Exception:
            pass

    raw_json = os.getenv("STREAMLIT_USERS_JSON", "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                if "users" in parsed and isinstance(parsed.get("users"), dict):
                    return parsed["users"]
                return parsed
        except Exception:
            pass

    return None


def authenticate(username, password):
    """
    Authenticates using st.secrets first, then optional environment fallbacks.
    Always returns a 3-item tuple: (ok, role, name).
    """
    users_db = st.secrets.get("users")
    if not users_db:
        users_db = _load_users_from_env()

    if not users_db:
        st.error("Erro de configuracao: banco de usuarios nao encontrado.")
        return False, None, None

    if username in users_db:
        user_data = users_db[username]
        stored_password = user_data["password"]
        role = user_data["role"]
        name = user_data["name"]

        if bcrypt.checkpw(password.encode("utf-8"), stored_password.encode("utf-8")):
            return True, role, name

    return False, None, None


def create_user(username, password, role="user"):
    """Creates user with hashed password in local users file."""
    users = load_users()

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    users[username] = {"password": hashed, "role": role}

    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)

    return True
