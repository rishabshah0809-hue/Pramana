"""Command Center (home page). Empty in M0 — the watchlist arrives in M1.

Opened through streamlit_app.py, which handles page setup, styling and footer.
"""

import streamlit as st

from app.errors import report
from app.services.status import setup_checks
from app.ui.common import show_error

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
