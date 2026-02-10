import streamlit as st


def _safe_secrets():
    try:
        return st.secrets
    except Exception:
        return None


def get_secret(key, default=None):
    secrets = _safe_secrets()
    if secrets is None:
        return default
    try:
        return secrets.get(key, default)
    except Exception:
        return default


def get_secret_section(section_name, default=None):
    secrets = _safe_secrets()
    if secrets is None:
        return default
    try:
        section = secrets.get(section_name, default)
        return section
    except Exception:
        return default

