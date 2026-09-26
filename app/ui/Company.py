"""Company page (Screen 2): price, filings timeline, shareholding trend and large deals.

Only stored, real data is shown. AI summaries and signals arrive in Milestone 3.
"""

import altair as alt
import streamlit as st

from app.adapters import bulk_block
from app.adapters.shareholding import CATEGORY_LABELS as SHP_LABELS
from app.errors import FriendlyError, report
from app.services import companies, conflicts, filings, health, holdings, prices, watchlist
from app.timeutil import fmt_ist, from_iso
from app.ui.common import fmt_inr, fmt_signed, show_error, unknown_text

st.title("Company")

CHART_CATEGORIES = ("promoter", "fii", "dii", "public")


def _pick_company() -> dict | None:
    items = watchlist.list_items()
    wanted = st.query_params.get("isin")
    if wanted and not any(i["isin"] == wanted for i in items):
        c = companies.get(wanted)
        if c:
            items = [{"isin": c["isin"], "name": c["name"], "nse_symbol": c["nse_symbol"]}] + items
    if not items:
        st.info("Add companies to your watchlist to see their pages.")
        st.page_link("app/ui/Watchlist.py", label="Go to Watchlist", icon=":material/list:")
        return None
    index = next((n for n, i in enumerate(items) if i["isin"] == wanted), 0)
    pick = st.selectbox("Company", items, index=index, format_func=lambda i: i["name"])
    if pick["isin"] != wanted:
        st.query_params["isin"] = pick["isin"]
    return companies.get(pick["isin"])


def _price(c: dict):
    q = prices.company_quote(c["isin"])
    cols = st.columns([1, 2])
    with cols[0]:
        if q and q.price.is_known:
            st.markdown(f"### {fmt_inr(q.price.value)}")
            if q.change.is_known:
                st.markdown(f"{fmt_signed(q.change.value)} ({fmt_signed(q.change_pct.value, pct=True)})"
                            f" vs previous close")
            st.caption(f"{q.price.source} · bar from {fmt_ist(q.price.event_time)} · fetched "
                       f"{fmt_ist(q.price.fetched_time)} · {q.freshness_note}")
        elif q:
            st.markdown(f"**Price:** {unknown_text(q.price)}")
    with cols[1]:
        closes = prices.daily_closes(c["isin"])
        if len(closes) >= 2:
            data = [{"Date": from_iso(r["timestamp"]).date().isoformat(), "Close": r["close"]}
                    for r in closes]
            chart = alt.Chart(alt.Data(values=data)).mark_line(point=True).encode(
                x=alt.X("Date:T", title=None), y=alt.Y("Close:Q", scale=alt.Scale(zero=False),
                                                         title="Close (₹)"),
                tooltip=["Date:T", "Close:Q"])
            st.altair_chart(chart, height=180)
            st.caption(f"Daily closes stored by this app ({len(closes)} sessions, Delayed · Yahoo, "
                       f"tier 2). The chart grows as prices are fetched each day.")
        else:
            st.caption("Price chart: not enough stored daily closes yet (needs at least 2).")


def _feed_warnings():
    for sid in ("announcements", "shareholding", "insider_sast"):
        h = health.source_health(sid)
        if h.fetch_status in ("blocked", "timeout", "error", "missing"):
            st.warning(f"**{h.name}:** the last check had a problem — {h.fetch_note} Showing "
                       f"what was stored earlier.")


def _timeline(c: dict):
    st.subheader("Filings")
    on_watchlist = any(i["isin"] == c["isin"] for i in watchlist.list_items())
    cats = ["all"] + list(filings.CATEGORY_LABELS)
    cat = st.selectbox("Type", cats, format_func=lambda k: "All types" if k == "all"
                       else filings.CATEGORY_LABELS[k])
    rows = filings.company_filings(c["isin"], None if cat == "all" else cat)
    if not rows:
        st.caption("Unknown — no filings stored yet for this company. The exchange feeds only list "
                   "recent filings, so this fills up from the day the app started checking them. "
                   "For older filings, use **Document Viewer → Add a filing**.")
        return
    st.caption(f"{len(rows)} filing(s), newest first. Times are when the exchange published them.")
    for r in rows:
        with st.container(border=True):
            seen = "uploaded" if r["kind"] == "manual" else "first seen"
            when = (fmt_ist(from_iso(r["published_at"])) if r["published_at"]
                    else f"Published time unknown ({seen} {fmt_ist(from_iso(r['first_seen_at']))})")
            where = r["exchange"] or "Uploaded by you"
            label = filings.CATEGORY_LABELS.get(r["category"], r["category"])
            st.markdown(f"**{r['subject'] or label}**  \n:blue-badge[{label}] :gray-badge[{where}] · "
                        f"{when}")
            if r["document_id"]:
                st.page_link("app/ui/DocumentViewer.py", label="Open the original filing",
                             query_params={"doc": r["document_id"]}, icon=":material/description:")
            elif not r["url"]:
                st.caption("This feed item has no file of its own; the text above is all the "
                           "exchange published.")
            elif not on_watchlist:
                st.caption("Not downloaded: files are downloaded only for watchlist companies.")
            elif r["last_failure"]:
                st.caption(f"Not downloaded yet — last try: {r['last_failure']}")
            else:
                st.caption("Not downloaded yet — it will be fetched at the next check.")


def _shareholding(c: dict):
    st.subheader("Shareholding")
    rows = holdings.series(c["isin"])
    known = [r for r in rows if r["category"] in CHART_CATEGORIES and r["percent"] is not None]
    if not rows:
        st.caption("Unknown — no shareholding-pattern filing has been read for this company yet. "
                   "They are filed quarterly; to fill in past quarters, upload the XBRL (.xml) "
                   "file under **Document Viewer → Add a filing** with type 'Shareholding pattern'.")
        return
    if known:
        data = [{"As on": r["as_of_date"], "Holder": SHP_LABELS[r["category"]],
                 "Percent": float(r["percent"])} for r in known]
        chart = alt.Chart(alt.Data(values=data)).mark_line(point=True).encode(
            x=alt.X("As on:T", title=None), y=alt.Y("Percent:Q", title="% of shares"),
            color=alt.Color("Holder:N", title=None), tooltip=["As on:T", "Holder:N", "Percent:Q"])
        st.altair_chart(chart, height=240)
        dates = sorted({r["as_of_date"] for r in known})
        if len(dates) == 1:
            st.caption("Only one filing so far, so the trend has a single point per holder.")
    for conflict in conflicts.open_conflicts(c["isin"]):
        vals = "; ".join(f"{v['source']} (tier {v['tier']}): {v['value']}% [doc {v['document_id']}]"
                         for v in conflict["values"])
        st.warning(f"**Conflict · {conflict['figure']}** — sources disagree: {vals}. Showing "
                   f"{conflict['displayed_source']} (highest trust).")
        if st.button("Mark as reviewed", key=f"conflict-{conflict['id']}"):
            conflicts.mark_reviewed(conflict["id"])
            st.rerun()
    table = []
    for r in rows:
        if r["category"] == "promoter_pledged":
            value = {"true": "Yes — see the filing", "false": "No"}.get(r["source_text"].lower(),
                                                                         r["source_text"])
        elif r["percent"] is None:
            value = f"Unknown — {r['source_text']}"
        else:
            value = f"{r['percent'].normalize():f}%"
        table.append({"As on": r["as_of_date"] or "Unknown", "Holder":
                      SHP_LABELS.get(r["category"], r["category"]), "Value": value,
                      "As written in the filing": r["source_text"],
                      "Document": f"#{r['document_id']}", "Fetched": fmt_ist(from_iso(r["fetched_at"]))})
    st.dataframe(table, hide_index=True)
    for doc_id in sorted({r["document_id"] for r in rows}, reverse=True)[:4]:
        st.page_link("app/ui/DocumentViewer.py", label=f"Open shareholding filing #{doc_id}",
                     query_params={"doc": doc_id}, icon=":material/description:")


def _deals(c: dict):
    st.subheader("Bulk and block deals (NSE)")
    rows = bulk_block.company_deals(c["isin"])
    if not rows:
        st.caption("None stored for this company. NSE's daily files are checked each weekday "
                   "after the close.")
        return
    st.dataframe([{"Trade date": r["trade_date"], "Type": r["deal_type"].title(),
                   "Client": r["client_name"], "Side": r["side"],
                   "Quantity": r["quantity_text"], "Price (₹)": r["price_text"],
                   "Source": f"NSE {r['deal_type']}.csv · doc #{r['document_id']}"} for r in rows],
                 hide_index=True)


try:
    c = _pick_company()
    if c:
        ids = " · ".join(x for x in [f"NSE `{c['nse_symbol']}`" if c["nse_symbol"] else None,
                                     f"BSE `{c['bse_code']}`" if c["bse_code"] else None,
                                     f"ISIN {c['isin']}"] if x)
        st.markdown(f"## {c['name']}  \n{ids}")
        _price(c)
        _feed_warnings()
        tabs = st.tabs(["Filings", "Shareholding", "Large deals"])
        with tabs[0]:
            _timeline(c)
        with tabs[1]:
            _shareholding(c)
        with tabs[2]:
            _deals(c)
        st.caption("Summaries, pledges-as-signals and insider signals arrive in Milestone 3. "
                   "Nothing here is written by AI.")
except FriendlyError as err:
    show_error(err)
except Exception as exc:  # never show a traceback to the owner
    show_error(report(exc))
