"""Pramana dashboard — Streamlit entrypoint.

Run it any of these ways:
  python start.py                      (recommended; sets everything up for you)
  streamlit run streamlit_app.py       (if you already have the packages)
  Streamlit Community Cloud            (main file: streamlit_app.py)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app.bootstrap import ensure_ready  # noqa: E402
from app.errors import report  # noqa: E402
from app.ui.common import APP_NAME, apply_style, footer, show_error, sidebar_extras  # noqa: E402

ASSETS = ROOT / "app" / "ui" / "assets"

st.set_page_config(page_title=APP_NAME, page_icon=str(ASSETS / "icon.svg"), layout="wide")
apply_style()
st.logo(str(ASSETS / "logo.svg"), size="large", icon_image=str(ASSETS / "icon.svg"))

try:
    ensure_ready()
except Exception as exc:  # never show a traceback to the owner
    show_error(report(exc))
    footer()
    st.stop()

pages = {
    "Research": [
        st.Page("app/ui/Home.py", title="Command Center", icon=":material/space_dashboard:",
                default=True),
        st.Page("app/ui/Watchlist.py", title="Watchlist", icon=":material/format_list_bulleted:"),
        st.Page("app/ui/Company.py", title="Company", icon=":material/domain:"),
        st.Page("app/ui/DocumentViewer.py", title="Document Viewer", icon=":material/description:"),
    ],
    "Setup": [
        st.Page("app/ui/Companies.py", title="Company list", icon=":material/upload_file:"),
        st.Page("app/ui/DataHealth.py", title="Data Health", icon=":material/monitor_heart:"),
    ],
    # Later milestones add pages here: Signal Feed, Thesis Builder, ...
}
st.navigation(pages).run()
sidebar_extras()
footer()
