"""Company page (Screen 2): price, filings timeline, shareholding trend and large deals.

Only stored, real data is shown. AI summaries and signals arrive in Milestone 3.
"""

import streamlit as st

from app.adapters import bulk_block
from app.adapters.shareholding import CATEGORY_LABELS as SHP_LABELS
from app.errors import FriendlyError, report
from app.services import companies, conflicts, filings, health, holdings, prices, watchlist
from app.timeutil import fmt_ist, from_iso
from app.ui import charts
from app.ui.common import (card_head, esc, fmt_inr, fmt_signed, fresh, initials, md, page_header,
                           show_error, tag, unknown_text)

CHART_CATEGORIES = ("promoter", "fii", "dii", "public")


def _pick_company() -> dict | None:
    items = watchlist.list_items()
    wanted = st.query_params.get("isin")
    if wanted and not any(i["isin"] == wanted for i in items):
        c = companies.get(wanted)
        if c:
            items = [{"isin": c["isin"], "name": c["name"], "nse_symbol": c["nse_symbol"]}] + items
    if not items:
        page_header("Company", crumb="Research")
        st.info("Add companies to your watchlist to see their pages.")
        st.page_link("app/ui/Watchlist.py", label="Go to Watchlist", icon=":material/list:")
        return None
    index = next((n for n, i in enumerate(items) if i["isin"] == wanted), 0)
    head, pick_col = st.columns([3, 1], vertical_alignment="bottom")
    with pick_col:
        pick = st.selectbox("Company", items, index=index, format_func=lambda i: i["name"])
    if pick["isin"] != wanted:
        st.query_params["isin"] = pick["isin"]
    c = companies.get(pick["isin"])
    with head:
        ids = " · ".join(x for x in [f"NSE {c['nse_symbol']}" if c["nse_symbol"] else None,
                                     f"BSE {c['bse_code']}" if c["bse_code"] else None,
                                     f"ISIN {c['isin']}"] if x)
        md(f'<div class="pm-crumb" style="margin-bottom:.4rem">Company</div><div class="pm-wc-top"'
           f' style="gap:16px"><div class="pm-av big">{initials(c["name"])}</div><div>'
           f'<div style="font-size:30px;font-weight:700;letter-spacing:-.03em;line-height:1.15;'
           f'color:var(--ink)">{esc(c["name"])}</div><div class="pm-meta" style="margin-top:4px">'
           f'{esc(ids)}</div></div></div>')
    return c


def _price(c: dict):
    q = prices.company_quote(c["isin"])
    with st.container(border=True, key="card-price"):
        if q and q.price.is_known:
            line = ""
            if q.change.is_known:
                v = q.change.value
                tone, arrow = (("green", "▲") if v > 0 else ("red", "▼") if v < 0 else ("gray", "•"))
                line = (f'<span class="pm-pill pm-{tone}">{arrow} {fmt_signed(v)} '
                        f'({fmt_signed(q.change_pct.value, pct=True)})</span> '
                        f'<span class="pm-meta">vs previous close</span>')
            state = "current" if q.freshness == "current" else "stale"
            md(f'<div class="pm-bigpx pm-num">{fmt_inr(q.price.value)}<small>INR</small></div>'
               f'<div style="margin:12px 0 4px">{line}</div>'
               + fresh(f"{q.price.source} · bar from {fmt_ist(q.price.event_time)} · fetched "
                       f"{fmt_ist(q.price.fetched_time)} · {q.freshness_note}", state))
        elif q:
            md(f'<div style="font-size:15px"><b>Price:</b> {esc(unknown_text(q.price))}</div>')
        closes = prices.daily_closes(c["isin"])
        if len(closes) >= 2:
            data = [{"Date": from_iso(r["timestamp"]).date().isoformat(), "Close": float(r["close"])}
                    for r in closes]
            st.altair_chart(charts.price_area(data), theme=None)
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
    on_watchlist = any(i["isin"] == c["isin"] for i in watchlist.list_items())
    cats = ["all"] + list(filings.CATEGORY_LABELS)
    top = st.columns([1, 2], vertical_alignment="bottom")
    cat = top[0].selectbox("Type", cats, format_func=lambda k: "All types" if k == "all"
                           else filings.CATEGORY_LABELS[k])
    rows = filings.company_filings(c["isin"], None if cat == "all" else cat)
    if not rows:
        st.caption("Unknown — no filings stored yet for this company. The exchange feeds only list "
                   "recent filings, so this fills up from the day the app started checking them. "
                   "For older filings, use **Document Viewer → Add a filing**.")
        return
    top[1].caption(f"{len(rows)} filing(s), newest first. Times are when the exchange published "
                   f"them.")
    for r in rows:
        if r["published_at"]:
            local = fmt_ist(from_iso(r["published_at"]))
            when = local.replace(", ", "<br>").replace(" IST", "")
            unknown = ""
        else:
            when = "time<br>unknown"
            unknown = (f'<div class="pm-meta" style="margin-top:6px">Published time unknown (first '
                       f'seen {esc(fmt_ist(from_iso(r["first_seen_at"])))})</div>')
        where = r["exchange"] or "Uploaded by you"
        label = filings.CATEGORY_LABELS.get(r["category"], r["category"])
        cols = st.columns([4, 1.4], vertical_alignment="top")
        with cols[0]:
            md(f'<div class="pm-tl"><div class="when">{when}</div><div class="rail"><i></i></div>'
               f'<div><b>{esc(r["subject"] or label)}</b><div class="pm-tags">{tag(label, "blue")}'
               f'{tag(where, "navy" if not r["exchange"] else "gray")}</div>{unknown}</div></div>')
        with cols[1]:
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


def _conflicts(c: dict):
    for conflict in conflicts.open_conflicts(c["isin"]):
        vals = "; ".join(f"{v['source']} (tier {v['tier']}): {v['value']}% [doc {v['document_id']}]"
                         for v in conflict["values"])
        st.warning(f"**Conflict · {conflict['figure']}** — sources disagree: {vals}. Showing "
                   f"{conflict['displayed_source']} (highest trust).")
        if st.button("Mark as reviewed", key=f"conflict-{conflict['id']}"):
            conflicts.mark_reviewed(conflict["id"])
            st.rerun()


def _shareholding_chart(c: dict):
    with st.container(border=True, key="card-shp"):
        md(card_head("Shareholding", "% of shares, from XBRL filings read by code", "pie"))
        rows = holdings.series(c["isin"])
        known = [r for r in rows if r["category"] in CHART_CATEGORIES and r["percent"] is not None]
        if not known:
            st.caption("Unknown — no shareholding-pattern filing has been read for this company "
                       "yet.")
        else:
            order = [SHP_LABELS[k] for k in CHART_CATEGORIES]
            data = [{"As on": r["as_of_date"], "Holder": SHP_LABELS[r["category"]],
                     "Percent": float(r["percent"])} for r in known]
            st.altair_chart(charts.holder_lines(data, order), theme=None)
            if len({r["as_of_date"] for r in known}) == 1:
                st.caption("Only one filing so far, so the trend has a single point per holder.")
            st.caption("Lines, not stacked: 'Public (total)' already includes the institutions.")
        _conflicts(c)


def _shareholding_table(c: dict):
    rows = holdings.series(c["isin"])
    if not rows:
        st.caption("Unknown — no shareholding-pattern filing has been read for this company yet. "
                   "They are filed quarterly; to fill in past quarters, upload the XBRL (.xml) "
                   "file under **Document Viewer → Add a filing** with type 'Shareholding pattern'.")
        return
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
    st.caption("NSE's daily files are checked each weekday after the close.")


try:
    c = _pick_company()
    if c:
        _feed_warnings()
        left, right = st.columns([1.7, 1], gap="medium")
        with left:
            _price(c)
        with right:
            _shareholding_chart(c)
        with st.container(border=True, key="card-detail"):
            tabs = st.tabs(["Filings", "Shareholding", "Large deals"])
            with tabs[0]:
                _timeline(c)
            with tabs[1]:
                _shareholding_table(c)
            with tabs[2]:
                _deals(c)
            st.caption("Summaries, pledges-as-signals and insider signals arrive in Milestone 3. "
                       "Nothing here is written by AI.")
except FriendlyError as err:
    show_error(err)
except Exception as exc:  # never show a traceback to the owner
    show_error(report(exc))
