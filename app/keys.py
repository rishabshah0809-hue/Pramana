"""Reads API keys. Never stores, logs or displays their values.

Order: environment / .env file (local use), then Streamlit secrets
(.streamlit/secrets.toml locally, or the Secrets box on Streamlit Cloud).
"""

import os

from dotenv import load_dotenv

from app import paths


def load_env_file() -> None:
    if paths.env_path().exists():
        load_dotenv(paths.env_path(), override=False)


def _streamlit_secrets():
    try:
        import streamlit as st

        return dict(st.secrets)
    except Exception:  # no secrets file / not running under Streamlit
        return {}


def get_key(name: str) -> str | None:
    value = os.environ.get(name) or _streamlit_secrets().get(name)
    return str(value) if value else None


def key_source() -> str | None:
    """Where keys are configured: '.env', 'streamlit secrets', or None."""
    if paths.env_path().exists():
        return ".env"
    if _streamlit_secrets():
        return "streamlit secrets"
    return None
