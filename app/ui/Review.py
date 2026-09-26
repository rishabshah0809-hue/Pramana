"""Needs review: signals the cross-check model disagreed with, and suggested company matches
(brief 14.4). Every decision is appended (never overwrites) and written to the audit log."""

import streamlit as st

from app.errors import FriendlyError, report
from app.services import signals
from app.ui.common import page_header, show_error, signal_card

page_header("Needs review", crumb="Research")
st.caption("Nothing here is shown as fact until you decide. Your decision is added to the "
           "signal's history — the original AI answer and the checks stay on record.")

try:
    pending = signals.feed(statuses=["needs_review"], limit=200)
    st.subheader(f"Signals to check ({len(pending)})")
    if not pending:
        st.caption("Nothing waiting.")
    for s in pending:
        signal_card(s)
        with st.form(f"review-{s['id']}"):
            note = st.text_input("Your note (required)", key=f"note-{s['id']}",
                                 placeholder="e.g. quote supports the claim; checker misread it")
            c1, c2 = st.columns(2)
            ok = c1.form_submit_button("The passage supports it — mark Verified (by you)")
            bad = c2.form_submit_button("It doesn't — reject it")
            if ok or bad:
                signals.set_by_owner(s["id"], "verified" if ok else "rejected", note)
                st.success("Saved.")
                st.rerun()

    st.subheader("Company matches to confirm (14.4)")
    st.caption("The AI named a company that is close to, but not exactly, a name in your company "
               "list. It is never linked automatically.")
    sugg = signals.match_suggestions()
    if not sugg:
        st.caption("Nothing waiting.")
    for r in sugg:
        with st.container(border=True):
            st.markdown(f"The filing mentions **{r['item'].get('company_mentioned')}**. Did it "
                        f"mean **{r['suggested_name']}** ({r['suggested_company']})?")
            st.caption(f"Claim: {r['item'].get('claim')}  \nQuote: “{r['item'].get('quote')}”")
            c1, c2 = st.columns(2)
            if c1.button("Yes, same company", key=f"yes-{r['id']}"):
                st.success(signals.decide_match(r["id"], True))
            if c2.button("No", key=f"no-{r['id']}"):
                st.info(signals.decide_match(r["id"], False))
except FriendlyError as err:
    show_error(err)
except Exception as exc:  # never show a traceback to the owner
    show_error(report(exc))
