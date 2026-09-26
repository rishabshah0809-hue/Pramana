"""Watchlist: search the company list, add and remove companies."""

import streamlit as st

from app.config import load_config
from app.errors import FriendlyError, report
from app.services import companies, watchlist
from app.timeutil import fmt_ist, from_iso
from app.ui.common import card_head, esc, initials, md, page_header, show_error

try:
    max_n = int(load_config()["watchlist"]["max_companies"])
    items = watchlist.list_items()
    page_header("Watchlist", f"{len(items)} of {max_n} companies. Every change is recorded in the "
                             f"audit log.", crumb="Research")

    left, right = st.columns([3, 2], gap="medium")
    with left, st.container(border=True, key="card-yours"):
        md(card_head("Your companies", "Open a company's filings, shareholding and deals", "list"))
        if not items:
            st.caption("None yet.")
        for it in items:
            row = st.columns([6, 2], vertical_alignment="center")
            with row[0]:
                md(f'<div class="pm-wc-top"><div class="pm-av">{initials(it["name"])}</div><div>'
                   f'<div class="pm-wc-name">{esc(it["name"])}</div><div class="pm-wc-id">'
                   f'{esc(it["nse_symbol"] or "—")} · added '
                   f'{esc(fmt_ist(from_iso(it["added_on"])))}</div></div></div>')
                st.page_link("app/ui/Company.py", label="Open company page",
                             query_params={"isin": it["isin"]}, icon=":material/arrow_forward:")
            confirm_key = f"confirm-{it['isin']}"
            if st.session_state.get(confirm_key):
                c1, c2 = row[1].columns(2)
                if c1.button("Yes", key=f"yes-{it['isin']}", help="Confirm removal",
                             type="primary"):
                    watchlist.remove(it["isin"])
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
                if c2.button("No", key=f"no-{it['isin']}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            elif row[1].button("Remove", key=f"rm-{it['isin']}", width="stretch"):
                st.session_state[confirm_key] = True
                st.rerun()
            st.divider()

    with right, st.container(border=True, key="card-add"):
        md(card_head("Add a company", "Searches the company list you imported", "plus"))
        if companies.company_count() == 0:
            st.info("Import NSE's company list first.")
            st.page_link("app/ui/Companies.py", label="Go to Company list",
                         icon=":material/upload_file:")
        else:
            query = st.text_input("Search by name, NSE symbol or ISIN",
                                  placeholder="e.g. HDFC BANK or TCS")
            for c in companies.search(query):
                row = st.columns([5, 1], vertical_alignment="center")
                code = c["nse_symbol"] or f"BSE {c['bse_code']}"
                row[0].markdown(f'<div class="pm-wc-name">{esc(c["name"])}</div><div class='
                                f'"pm-wc-id">{esc(code)} · {esc(c["isin"])}</div>',
                                unsafe_allow_html=True)
                if row[1].button("Add", key=f"add-{c['isin']}", type="primary"):
                    try:
                        watchlist.add(c["isin"], max_companies=max_n)
                        st.toast(f"Added {c['name']}")
                        st.rerun()
                    except FriendlyError as err:
                        show_error(err)
            if query and not companies.search(query):
                st.caption("No match in your company list.")
except FriendlyError as err:
    show_error(err)
except Exception as exc:
    show_error(report(exc))
