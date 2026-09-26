"""Data Health: each source's fetch status, content age, errors and quality score."""

import streamlit as st

from app.errors import FriendlyError, report
from app.services import filings, health, signals
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


def _ai_queue():
    """Brief Section 3: limits are respected by queuing. Shows queued vs current, and why."""
    from app.processing import pipeline

    q = signals.queue_state()
    label, tone = {"current": ("Current — nothing waiting", "green"),
                   "queued": ("Queued — working through it", "orange"),
                   "waiting": ("Waiting — a free-tier limit was reached", "red")}[q.state]
    with st.container(border=True, key="card-ai-queue"):
        md(card_head("AI queue", "Filings waiting to be read by AI, watchlist companies first",
                     "chip", tag(label, tone)))
        oldest = fmt_ist(from_iso(q.oldest)) if q.oldest else "—"
        md(f'<div class="pm-two"><div><small>Waiting</small><span class="pm-meta">'
           f'{q.passages} passage(s) from {q.documents} document(s) · {q.watchlist_passages} '
           f'from watchlist companies · {q.summaries} summary(ies)</span></div><div><small>'
           f'Oldest waiting document fetched</small><span class="pm-meta">{esc(oldest)}</span>'
           f'</div></div>')
        if q.state == "waiting":
            when = fmt_ist(q.resume_at) if q.resume_at else "when the limit resets"
            st.warning(f"**Paused:** {q.waiting_reason}. Resumes by itself after {when}. "
                       f"Nothing is lost — the work stays queued.")
        runs = signals.queue_runs(5)
        if runs:
            st.caption("Recent runs:  \n" + "  \n".join(
                f"{fmt_ist(from_iso(r['started_at']))} — {r['message']}" for r in runs))
        if st.button("Run the AI queue now", icon=":material/play_arrow:"):
            with st.spinner("Reading filings… (stops early if a free-tier limit is reached)"):
                run = pipeline.run_queue()
            (st.success if run.status == "ok" else st.warning)(run.message)


def _ai_providers():
    md(card_head("AI providers", "Calls today against each free-tier limit", "chip"))
    for p in signals.provider_status():
        u, lim = p["usage"], p["usage"]["limits"]

        def of(used, key):
            v = lim.get(key)
            return f"{used:,} / {int(float(v)):,}" if v not in (None, "") else f"{used:,} / no limit published"
        v = p["verdict"]
        state = (tag("Available", "green") if v.ok else
                 tag("Paused until " + fmt_ist(v.resume_at), "red") if v.resume_at else
                 tag("Per-minute limit — a short wait", "orange"))
        placeholder = tag("limits are placeholders", "orange") if p["placeholder"] else ""
        md(f'<div class="pm-row"><div style="min-width:0"><div class="n">{esc(p["model"])}</div>'
           f'<div class="pm-meta">{esc(", ".join(p["roles"]) or "not in use")}</div>'
           f'<div class="pm-tags" style="margin-top:5px">{state}{placeholder}</div></div></div>')
        last_ok = fmt_ist(from_iso(p["last_ok"])) if p["last_ok"] else "never"
        err = (f" · last problem {fmt_ist(from_iso(p['last_error']['timestamp']))}: "
               f"{p['last_error']['msg']}") if p["last_error"] else ""
        st.caption(f"Today: requests {of(u['requests_day'], 'rpd')} · tokens "
                   f"{of(u['tokens_day'], 'tpd')} · errors {u['errors_day']} · last success "
                   f"{last_ok}{err}")
    st.caption("Only public filing text is ever sent. Gemini's free tier may use inputs to "
               "improve Google's products, so nothing private is sent to it.")


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

    _ai_queue()
    left, right = st.columns(2, gap="medium")
    with left, st.container(border=True, key="card-ai"):
        _ai_providers()
    with right, st.container(border=True, key="card-setup"):
        md(card_head("Setup check", None, "check"))
        for check in setup_checks():
            st.markdown(f"{'✅' if check.ok else '⚠️'} **{check.label}** — {check.detail}")
except FriendlyError as err:
    show_error(err)
except Exception as exc:
    show_error(report(exc))
