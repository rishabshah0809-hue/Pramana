"""Command Center (home page). Empty in M0 — the watchlist arrives in M1."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app.errors import report, setup_logging  # noqa: E402
from app.services.status import setup_checks  # noqa: E402
from app.ui.common import footer, page_setup, show_error  # noqa: E402

page_setup("Command Center")
setup_logging()

st.title("Mosaic India")
st.markdown(
    '<p class="mosaic-subtitle">Command Center · evidence-first research on Indian stocks</p>',
    unsafe_allow_html=True,
)

try:
    st.info(
        "**No companies yet.** Your watchlist, prices and data health arrive in the "
        "next step (Milestone 1). Nothing shown here is ever made up — until real data "
        "is fetched, this page stays empty."
    )

    st.subheader("Setup check")
    for check in setup_checks():
        icon = "✅" if check.ok else "⚠️"
        st.markdown(f"{icon} **{check.label}** — {check.detail}")
except Exception as exc:  # never show a traceback to the owner
    show_error(report(exc))

footer()
