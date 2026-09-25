"""Gets the app ready on first page load: logging, keys, database.

This lets the dashboard run the same way whether it is started by start.py,
by `streamlit run streamlit_app.py`, or on Streamlit Community Cloud.
"""

import streamlit as st

from app import paths
from app.errors import setup_logging
from app.keys import load_env_file
from app.store.db import init_db


@st.cache_resource(show_spinner=False)
def _prepare(db_path: str) -> bool:
    setup_logging().info("Preparing Mosaic India (database at %s)", db_path)
    load_env_file()
    init_db()
    return True


def ensure_ready() -> None:
    """Safe to call on every page load; the real work runs once per database."""
    _prepare(str(paths.db_path()))
