"""Shared look and feel for every page: styling, footer, friendly errors."""

import streamlit as st

from app.errors import FriendlyError

FOOTER_TEXT = "Personal research tool. Not investment advice."

_CSS = """
<style>
  .block-container { padding-top: 2rem; max-width: 1200px; }
  .mosaic-subtitle { color: #8B949E; margin-top: -0.6rem; }
  .mosaic-footer {
      position: fixed; left: 0; bottom: 0; width: 100%;
      padding: 0.4rem 1rem; text-align: center; font-size: 0.8rem;
      color: #8B949E; background: #0E1117; border-top: 1px solid #30363D;
      z-index: 999;
  }
</style>
"""


def page_setup(title: str) -> None:
    st.set_page_config(page_title=f"{title} · Mosaic India", layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)


def footer() -> None:
    st.markdown(f'<div class="mosaic-footer">{FOOTER_TEXT}</div>', unsafe_allow_html=True)


def show_error(err: FriendlyError) -> None:
    st.error(f"**{err.message}**\n\nWhat to do: {err.fix}")
