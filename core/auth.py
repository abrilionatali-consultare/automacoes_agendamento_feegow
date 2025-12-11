import json
import bcrypt
from pathlib import Path

USERS_FILE = Path(__file__).resolve().parent.parent / "auth" / "users.json"

def load_users():
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def authenticate(username, password):
    users = load_users()

    if username not in users:
        return False, None

    stored_hash = users[username]["password"]

    if bcrypt.checkpw(password.encode(), stored_hash.encode()):
        return True, users[username]["role"]

    return False, None


def create_user(username, password, role="user"):
    """Cria usuário com senha criptografada (use na página de gestão)."""
    users = load_users()

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    users[username] = {"password": hashed, "role": role}

    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)

    return True
