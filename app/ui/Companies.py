"""Company list: the owner uploads NSE's equity list (the app never downloads it)."""

import streamlit as st

from app.adapters.bse_scrip_list import DOWNLOAD_PAGE as BSE_PAGE
from app.adapters.nse_equity_list import DOWNLOAD_PAGE
from app.errors import FriendlyError, report
from app.services import companies
from app.timeutil import fmt_ist, from_iso
from app.ui.common import show_error

st.title("Company list")

try:
    last = companies.last_import()
    n = companies.company_count()
    if last:
        st.markdown(f"**{n:,} companies** · last imported {fmt_ist(from_iso(last['fetched_at']))}")
    else:
        st.markdown("**No company list imported yet.**")

    with st.expander("How to get the file (about 1 minute, once a month)", expanded=not last):
        st.markdown(
            f"NSE's terms don't allow apps to download from its website automatically, so "
            f"you download this one file yourself:\n\n"
            f"1. Open **[NSE — Securities available for trading]({DOWNLOAD_PAGE})** in your browser.\n"
            f"2. Under *Equity segment*, click **Securities available for Equity segment (.csv)**. "
            f"A file called **EQUITY_L.csv** downloads.\n"
            f"3. Upload that file below, without opening or editing it.\n\n"
            f"The original file is kept unchanged in `data/raw/nse_equity_list/`."
        )

    upload = st.file_uploader("Upload EQUITY_L.csv", type=["csv"])
    if upload is not None and st.button("Import this file", type="primary"):
        with st.spinner("Checking and importing…"):
            s = companies.import_equity_list(upload.getvalue(), upload.name)
        if s.already_imported:
            st.info("This exact file was imported before. Company details were re-checked.")
        st.success(f"Done: {s.added:,} added, {s.updated:,} updated, {s.unchanged:,} unchanged.")
        if s.not_in_new_list:
            st.warning(f"{s.not_in_new_list:,} companies from earlier lists are not in this file "
                       f"(possibly delisted or suspended). They are kept, not deleted.")
        if s.problems:
            with st.expander(f"{len(s.problems)} rows skipped"):
                st.write("\n".join(f"- {p}" for p in s.problems[:200]))
except FriendlyError as err:
    show_error(err)
except Exception as exc:
    show_error(report(exc))
