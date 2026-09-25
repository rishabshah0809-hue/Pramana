"""Data Health: each source's fetch status, content age, errors and quality score."""

import streamlit as st

from app.errors import FriendlyError, report
from app.services import health
from app.services.status import setup_checks
from app.timeutil import fmt_ist, from_iso
from app.ui.common import STATUS_BADGE, show_error

st.title("Data Health")
st.caption("Fetch status (did the last download work?) and content age (how old is the data?) "
           "are shown separately, because a successful fetch can still return old data.")

try:
    for h in health.all_sources():
        with st.container(border=True):
            st.markdown(f"### {h.name}")
            st.caption(f"Trust tier {h.tier} · {'Automatic' if h.automated else 'Uploaded by you'}"
                       f" · Terms: {h.terms_status}")
            f_label, f_color = STATUS_BADGE.get(h.fetch_status, (h.fetch_status, "gray"))
            c_label, c_color = STATUS_BADGE.get(h.content_status, (h.content_status, "gray"))
            cols = st.columns(4)
            cols[0].markdown(f"**Fetch**  \n:{f_color}-badge[{f_label}]  \n{h.fetch_note}")
            cols[1].markdown(f"**Content**  \n:{c_color}-badge[{c_label}]  \n{h.content_note}")
            cols[2].markdown("**Last success**  \n" + (fmt_ist(from_iso(h.last_success))
                                                       if h.last_success else "Unknown — never"))
            cols[3].markdown(f"**Last 7 days**  \n{h.runs_7d} runs · {h.errors_7d} errors")

            st.markdown("**Quality score:** " + ("Unknown — not enough data yet" if h.score is None
                                                 else f"**{h.score:.0f} / 100**"))
            def pct(x):
                return "Unknown" if x is None else f"{x * 100:.0f}%"
            st.caption(f"Formula: {health.FORMULA}.  \nInputs now: success rate {pct(h.success_rate)}"
                       f" · freshness {pct(h.freshness)} · validation {pct(h.validation_rate)}")
            hist = health.score_history(h.source_id)
            if len(hist) > 1:
                st.line_chart({"Quality score": [r["score"] for r in hist]}, height=140)

    st.subheader("AI providers")
    st.caption("Not connected yet — Groq and Gemini arrive in Milestone 3.")

    st.subheader("Setup check")
    for check in setup_checks():
        st.markdown(f"{'✅' if check.ok else '⚠️'} **{check.label}** — {check.detail}")
except FriendlyError as err:
    show_error(err)
except Exception as exc:
    show_error(report(exc))
