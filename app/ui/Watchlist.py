"""Watchlist: search the company list, add and remove companies."""

import streamlit as st

from app.config import load_config
from app.errors import FriendlyError, report
from app.services import companies, watchlist
from app.timeutil import fmt_ist, from_iso
from app.ui.common import show_error

st.title("Watchlist")

try:
    max_n = int(load_config()["watchlist"]["max_companies"])
    items = watchlist.list_items()
    st.caption(f"{len(items)} of {max_n} companies. Every change is recorded in the audit log.")

    if companies.company_count() == 0:
        st.info("Import NSE's company list first.")
        st.page_link("app/ui/Companies.py", label="Go to Company list", icon=":material/upload_file:")
    else:
        st.subheader("Add a company")
        query = st.text_input("Search by name, NSE symbol or ISIN", placeholder="e.g. HDFC BANK or TCS")
        for c in companies.search(query):
            row = st.columns([6, 1])
            code = c["nse_symbol"] or f"BSE {c['bse_code']}"
            row[0].markdown(f"**{c['name']}** · `{code}` · {c['isin']}")
            if row[1].button("Add", key=f"add-{c['isin']}"):
                try:
                    watchlist.add(c["isin"], max_companies=max_n)
                    st.toast(f"Added {c['name']}")
                    st.rerun()
                except FriendlyError as err:
                    show_error(err)
        if query and not companies.search(query):
            st.caption("No match in your company list.")

    st.subheader("Your companies")
    if not items:
        st.caption("None yet.")
    for it in items:
        row = st.columns([6, 1])
        row[0].markdown(f"**{it['name']}** · `{it['nse_symbol'] or '—'}` · added "
                        f"{fmt_ist(from_iso(it['added_on']))}")
        row[0].page_link("app/ui/Company.py", label="Open company page",
                         query_params={"isin": it["isin"]}, icon=":material/domain:")
        confirm_key = f"confirm-{it['isin']}"
        if st.session_state.get(confirm_key):
            c1, c2 = row[1].columns(2)
            if c1.button("Yes", key=f"yes-{it['isin']}", help="Confirm removal"):
                watchlist.remove(it["isin"])
                st.session_state.pop(confirm_key, None)
                st.rerun()
            if c2.button("No", key=f"no-{it['isin']}"):
                st.session_state.pop(confirm_key, None)
                st.rerun()
        elif row[1].button("Remove", key=f"rm-{it['isin']}"):
            st.session_state[confirm_key] = True
            st.rerun()
except FriendlyError as err:
    show_error(err)
except Exception as exc:
    show_error(report(exc))
