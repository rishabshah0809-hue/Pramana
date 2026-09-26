"""Shared look and feel for every page: styling, footer, friendly errors."""

import streamlit as st

from app.errors import FriendlyError

FOOTER_TEXT = "Personal research tool. Not investment advice."

_CSS = """
<style>
  .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px; }
  .mosaic-subtitle { color: #8B949E; margin-top: -0.6rem; }
  .mosaic-footer {
      position: fixed; left: 0; bottom: 0; width: 100%;
      padding: 0.4rem 1rem; text-align: center; font-size: 0.8rem;
      color: #8B949E; background: #0E1117; border-top: 1px solid #30363D;
      z-index: 999;
  }
</style>
"""


def apply_style() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def footer() -> None:
    st.markdown(f'<div class="mosaic-footer">{FOOTER_TEXT}</div>', unsafe_allow_html=True)


def show_error(err: FriendlyError) -> None:
    st.error(f"**{err.message}**\n\nWhat to do: {err.fix}")


# ---------------------------------------------------------------------------
# Formatting helpers (display only; values come from services)
# ---------------------------------------------------------------------------

def fmt_inr(amount) -> str:
    """Indian digit grouping: 1234567.891 -> ₹12,34,567.89"""
    from decimal import ROUND_HALF_UP, Decimal

    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if d < 0 else ""
    whole, frac = f"{abs(d):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}₹{whole}.{frac}"


def fmt_signed(amount, pct=False) -> str:
    from decimal import ROUND_HALF_UP, Decimal

    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "+" if d > 0 else ""
    return f"{sign}{d}%" if pct else f"{sign}{fmt_inr(d)}"


def unknown_text(v) -> str:
    label = "Unknown" if v.state == "unknown" else "Not applicable"
    return f"{label} — {v.reason}"


CONTENT_BADGE = {
    "current": ("Content current", "green"), "partial": ("Content partly current", "orange"),
    "stale": ("Content stale", "orange"), "no_data": ("No data yet", "gray"),
    "timestamp_unknown": ("Content age unknown", "gray"),
}

STATUS_BADGE = {
    # fetch status
    "ok": ("Fetch OK", "green"), "stale": ("Fetch stale", "orange"),
    "missing": ("Fetch returned nothing", "orange"), "blocked": ("Blocked by source", "red"),
    "timeout": ("Timed out", "red"), "error": ("Fetch error", "red"),
    "never_run": ("Never fetched", "gray"),
    # content status
    "current": ("Content current", "green"), "partial": ("Content partly current", "orange"),
    "no_data": ("No data yet", "gray"), "timestamp_unknown": ("Content age unknown", "gray"),
}
