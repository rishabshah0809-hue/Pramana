"""Data Health: each source's fetch status, content age, errors and quality score."""

import streamlit as st

from app.errors import FriendlyError, report
from app.services import filings, health
from app.services.status import setup_checks
from app.timeutil import fmt_ist, from_iso
from app.ui import charts
from app.ui.common import (CONTENT_BADGE, STATUS_BADGE, card_head, esc, gauge, md, page_header,
                           show_error, tag)

page_header("Data Health", "Fetch status (did the last download work?) and content age (how old "
                           "is the data?) are shown separately, because a successful fetch can "
                           "still return old data.", crumb="Setup")


def check_now(source_id: str):
    """Run one source now (the background scheduler also runs them on their schedules)."""
    from app.adapters import announcements, bulk_block, insider_sast, shareholding
    from app.services import prices

    runners = {"yahoo_prices": prices.refresh, "announcements": announcements.run,
               "shareholding": shareholding.run, "insider_sast": insider_sast.run,
               "bulk_block": bulk_block.run}
    return runners[source_id]()


try:
    sources = health.all_sources()
    cols = st.columns(2, gap="medium")
    for n, h in enumerate(sources):
        with cols[n % 2], st.container(border=True, key=f"card-{h.source_id}"):
            kind = "Automatic" if h.automated else "Uploaded by you"
            md(card_head(h.name, right=gauge(h.score),
                         below=f'<div class="pm-tags" style="margin-top:8px">'
                               f'{tag(f"Trust tier {h.tier}", "blue")}{tag(kind, "gray")}</div>'))
            if h.source_id == "bulk_block":
                from app.adapters.bulk_block import TERMS_WARNING

                st.badge(TERMS_WARNING, icon=":material/warning:", color="red")
            st.caption(f"Trust tier {h.tier} · {kind} · Terms: {h.terms_status}")
            f_label, f_tone = STATUS_BADGE.get(h.fetch_status, (h.fetch_status, "gray"))
            c_label, c_tone = CONTENT_BADGE.get(h.content_status, (h.content_status, "gray"))
            last = fmt_ist(from_iso(h.last_success)) if h.last_success else "Unknown — never"
            md(f'<div class="pm-two"><div><small>Fetch</small>{tag(f_label, f_tone)}<div '
               f'class="pm-meta" style="margin-top:6px">{esc(h.fetch_note)}</div></div><div><small>'
               f'Content</small>{tag(c_label, c_tone)}<div class="pm-meta" style="margin-top:6px">'
               f'{esc(h.content_note)}</div></div></div>'
               f'<div class="pm-two"><div><small>Last success</small><span class="pm-meta">'
               f'{esc(last)}</span></div><div><small>Last 7 days</small><span class="pm-meta">'
               f'{h.runs_7d} runs · {h.errors_7d} errors</span></div></div>')

            def pct(x):
                return "Unknown" if x is None else f"{x * 100:.0f}%"
            st.caption("Quality score: " + ("Unknown — not enough data yet" if h.score is None
                                            else f"{h.score:.0f} / 100")
                       + f"  \nFormula: {health.FORMULA}.  \nInputs now: success rate "
                         f"{pct(h.success_rate)} · freshness {pct(h.freshness)} · validation "
                         f"{pct(h.validation_rate)}")
            hist = health.score_history(h.source_id)
            if len(hist) > 1:
                st.altair_chart(charts.score_area([r["score"] for r in hist]), theme=None)

    left, right = st.columns(2, gap="medium")
    with left, st.container(border=True, key="card-ai"):
        md(card_head("AI providers", "Groq and Gemini", "chip", tag("Milestone 3", "gray")))
        st.caption("Not connected yet — Groq and Gemini arrive in Milestone 3.")
    with right, st.container(border=True, key="card-setup"):
        md(card_head("Setup check", None, "check"))
        for check in setup_checks():
            st.markdown(f"{'✅' if check.ok else '⚠️'} **{check.label}** — {check.detail}")
except FriendlyError as err:
    show_error(err)
except Exception as exc:
    show_error(report(exc))
