"""Signal Feed (Screen 3): every extracted signal, filterable, each opening its exact
highlighted source passage. Rejected items are never shown as signals."""

from datetime import date, timedelta

import streamlit as st

from app.errors import FriendlyError, report
from app.services import signals, watchlist
from app.ui.common import page_header, show_error, signal_card

page_header("Signal Feed", crumb="Research")
st.caption("**Verified** = the quote is word-for-word in the filing, every number matched, "
           "and a second AI model agreed. It proves the source says it — not that it is true; "
           "the claim-type badge says what kind of statement it is. **Needs review** = the "
           "second model disagreed. **Unverified** = passed the code checks, second check pending.")

try:
    q = signals.queue_state()
    if q.state != "current":
        st.info(f"AI queue: **{q.passages} passage(s)** from {q.documents} document(s) waiting"
                + (f" — {q.waiting_reason}" if q.waiting_reason else "") + ". Details on Data Health.")

    with st.expander("Filters", expanded=True):
        c1, c2, c3 = st.columns(3)
        companies = watchlist.list_items()
        company = c1.selectbox("Company", [None] + companies,
                               format_func=lambda c: "All companies" if c is None else c["name"])
        types = c2.multiselect("Signal type", list(signals.SIGNAL_TYPE_LABELS),
                               format_func=signals.SIGNAL_TYPE_LABELS.get)
        direction = c3.selectbox("Direction", [None, "positive", "negative", "neutral"],
                                 format_func=lambda d: "Any" if d is None else d.title())
        c4, c5, c6 = st.columns(3)
        statuses = c4.multiselect("Status", ["verified", "unverified", "needs_review"],
                                  default=["verified", "unverified", "needs_review"],
                                  format_func=lambda s: signals.STATUS_LABELS[s][0])
        tiers = c5.multiselect("Source tier", [1, 2, 3], format_func=lambda t: f"Tier {t}")
        claim_types = c6.multiselect("Claim type", list(signals.CLAIM_TYPE_LABELS),
                                     format_func=signals.CLAIM_TYPE_LABELS.get)
        span = st.date_input("Date range", value=(date.today() - timedelta(days=90), date.today()))

    date_from, date_to = (span if isinstance(span, tuple) and len(span) == 2 else (None, None))
    rows = signals.feed(company=company["isin"] if company else None, types=types,
                        direction=direction, tiers=tiers, statuses=statuses or None,
                        claim_types=claim_types, date_from=date_from, date_to=date_to)
    st.caption(f"{len(rows)} signal(s), newest first.")
    if not rows:
        st.info("Insufficient evidence — no signals match yet. Signals appear as filings of your "
                "watchlist companies are read. Nothing is ever filled in to make the feed look busy.")
    for s in rows:
        signal_card(s)

    with st.expander("Rejected log — items that failed the code checks (never shown as fact)"):
        rej = signals.rejected_log(limit=100)
        if not rej:
            st.caption("Nothing rejected yet.")
        for r in rej:
            claim = r["item"].get("claim") or "(the answer could not be read)"
            st.markdown(f"**{r['company_name'] or '—'}** · {claim}  \n"
                        + "  \n".join(f"✗ {x}" for x in r["reasons"]))
            st.caption(f"{r['model']} · {r['prompt_version']} · document #{r['document_id']}")
except FriendlyError as err:
    show_error(err)
except Exception as exc:  # never show a traceback to the owner
    show_error(report(exc))
