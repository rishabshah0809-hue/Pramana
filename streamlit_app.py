"""Mosaic India dashboard — Streamlit entrypoint.

Run it any of these ways:
  python start.py                      (recommended; sets everything up for you)
  streamlit run streamlit_app.py       (if you already have the packages)
  Streamlit Community Cloud            (main file: streamlit_app.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

from app.bootstrap import ensure_ready  # noqa: E402
from app.errors import report  # noqa: E402
from app.ui.common import apply_style, footer, show_error  # noqa: E402

st.set_page_config(page_title="Mosaic India", page_icon=":material/insights:", layout="wide")
apply_style()

try:
    ensure_ready()
except Exception as exc:  # never show a traceback to the owner
    show_error(report(exc))
    footer()
    st.stop()

pages = [
    st.Page("app/ui/Home.py", title="Command Center", icon=":material/dashboard:", default=True),
    # Later milestones add pages here: Company, Signal Feed, Thesis Builder, ...
]
st.navigation(pages).run()
footer()
