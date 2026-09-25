"""Command Center: watchlist cards with price, change, timestamps and freshness."""

import streamlit as st

from app.errors import FriendlyError, report
from app.services import companies, health, prices, watchlist
from app.timeutil import fmt_ist, now_utc
from app.ui.common import STATUS_BADGE, fmt_inr, fmt_signed, show_error, unknown_text

st.title("Mosaic India")
st.markdown('<p class="mosaic-subtitle">Command Center · evidence-first research on Indian stocks</p>',
            unsafe_allow_html=True)

try:
    if companies.company_count() == 0:
        st.info("**Start here:** import NSE's company list so you can build your watchlist.")
        st.page_link("app/ui/Companies.py", label="Go to Company list", icon=":material/upload_file:")
    elif not watchlist.list_items():
        st.info("**Your watchlist is empty.** Add the companies you want to track.")
        st.page_link("app/ui/Watchlist.py", label="Go to Watchlist", icon=":material/list:")
    else:
        top = st.columns([3, 1])
        result = None
        with top[1]:
            if st.button("Refresh prices now", icon=":material/refresh:", width="stretch"):
                with st.spinner("Fetching delayed prices from Yahoo…"):
                    result = prices.refresh()
        if result is not None:
            (st.success if result.status == "ok" else st.warning)(result.message)
        with top[0]:
            st.caption("Prices: **Delayed · Yahoo (trust tier 2)** — about 15 minutes behind the "
                       "market. Live prices arrive when Angel One is connected.")

        quotes = prices.watchlist_quotes()
        cols = st.columns(3)
        for i, q in enumerate(quotes):
            with cols[i % 3].container(border=True):
                st.markdown(f"**{q.name}**  \n`{q.symbol or '—'}` · {q.isin}")
                if q.price.is_known:
                    st.markdown(f"### {fmt_inr(q.price.value)}")
                    if q.change.is_known:
                        color = "green" if q.change.value > 0 else ("red" if q.change.value < 0 else "gray")
                        st.markdown(f":{color}[{fmt_signed(q.change.value)} "
                                    f"({fmt_signed(q.change_pct.value, pct=True)})] vs previous close")
                    else:
                        st.caption(f"Day change: {unknown_text(q.change)}")
                    label, color = (("Current", "green") if q.freshness == "current"
                                    else ("Stale", "orange"))
                    st.badge(f"{label} · {q.freshness_note}", color=color)
                    st.caption(f"{q.price.source} · price bar from {fmt_ist(q.price.event_time)}  \n"
                               f"Fetched {fmt_ist(q.price.fetched_time)}")
                else:
                    st.markdown(f"**{unknown_text(q.price)}**")

    st.subheader("Newest signals")
    st.caption("Insufficient evidence — signals are extracted from filings starting in "
               "Milestone 3. Nothing is shown until real signals exist.")

    st.subheader("Data health")
    for h in health.all_sources():
        f_label, f_color = STATUS_BADGE.get(h.fetch_status, (h.fetch_status, "gray"))
        c_label, c_color = STATUS_BADGE.get(h.content_status, (h.content_status, "gray"))
        score = "Unknown" if h.score is None else f"{h.score:.0f}/100"
        st.markdown(f"**{h.name}** · :{f_color}-badge[{f_label}] :{c_color}-badge[{c_label}] "
                    f"· quality {score}")
    st.page_link("app/ui/DataHealth.py", label="Open Data Health", icon=":material/monitor_heart:")
    st.caption(f"Page loaded {fmt_ist(now_utc())}")
except FriendlyError as err:
    show_error(err)
except Exception as exc:  # never show a traceback to the owner
    show_error(report(exc))
