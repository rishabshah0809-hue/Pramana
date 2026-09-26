"""Command Center: watchlist cards with price, change, timestamps and freshness, plus
filing activity and a data health summary. Every value comes from stored data."""

from datetime import timedelta

import streamlit as st

from app.config import load_config
from app.errors import FriendlyError, report
from app.services import companies, conflicts, filings, health, prices, watchlist
from app.timeutil import IST, fmt_ist, from_iso, now_utc
from app.ui.common import (APP_NAME, CONTENT_BADGE, STATUS_BADGE, card_head, empty_state, esc,
                           fmt_inr, fmt_signed, fresh, initials, kpi, md, page_header, show_error,
                           sparkline, tag, unknown_text)

page_header(APP_NAME, "Command Center · evidence-first research on Indian stocks",
            crumb="Command Center")

# Activity grid colours, most important filing type first (a day shows its top type).
ACTIVITY = [("results", "Results", "#03045E"), ("board_meeting", "Board meeting", "#0077B6"),
            ("shareholding", "Shareholding pattern", "#00B4D8"),
            ("insider", "Insider trading / SAST", "#90E0EF"), ("sast", None, "#90E0EF"),
            ("other", "Other types", "#AEBBCD")]
WEEKS = 26


def _watch_card(q):
    with st.container(border=True, key=f"cardsub-{q.isin}"):
        ids = " · ".join(x for x in (q.symbol, q.isin) if x)
        head = (f'<div class="pm-wc-top"><div class="pm-av">{initials(q.name)}</div><div>'
                f'<div class="pm-wc-name">{esc(q.name)}</div><div class="pm-wc-id">{esc(ids)}</div>'
                f'</div></div>')
        if q.price.is_known:
            body = f'<div class="pm-px pm-num">{fmt_inr(q.price.value)}</div>'
            if q.change.is_known:
                v = q.change.value
                tone, arrow = (("green", "▲") if v > 0 else ("red", "▼") if v < 0 else ("gray", "•"))
                body += (f'<span class="pm-pill pm-{tone}">{arrow} {fmt_signed(v)} '
                         f'({fmt_signed(q.change_pct.value, pct=True)})</span> '
                         f'<span class="pm-meta">vs previous close</span>')
            else:
                body += f'<div class="pm-meta">Day change: {esc(unknown_text(q.change))}</div>'
            closes = [float(r["close"]) for r in prices.daily_closes(q.isin)][-30:]
            spark = sparkline(closes, dim=q.freshness != "current")
            spark = (f'<div style="margin-top:10px">{spark}</div>' if spark else
                     '<div class="pm-meta" style="margin-top:10px">Trend line appears after '
                     'two stored daily closes.</div>')
            state = "current" if q.freshness == "current" else "stale"
            label = "Current" if q.freshness == "current" else "Stale"
            foot = (f'<div class="pm-wc-foot">{fresh(f"{label} · {q.freshness_note}", state)}'
                    f'<div class="pm-meta" style="margin-top:4px">{esc(q.price.source)} · price bar '
                    f'from {esc(fmt_ist(q.price.event_time))}<br>Fetched '
                    f'{esc(fmt_ist(q.price.fetched_time))}</div></div>')
            md(head + body + spark + foot)
        else:
            md(head + f'<div style="margin:12px 0 6px;font-size:13.5px;color:var(--ink2)"><b>Price:'
                      f'</b> {esc(unknown_text(q.price))}</div>'
               + f'<div class="pm-wc-foot">{fresh("No price stored", "none")}</div>')
        st.page_link("app/ui/Company.py", label="Filings and shareholding",
                     query_params={"isin": q.isin}, icon=":material/arrow_forward:")


def _activity_grid(isins: list[str], now):
    today = now.astimezone(IST).date()
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=WEEKS - 1)
    since = now - timedelta(days=(today - start).days + 1)
    rows = filings.watchlist_activity(isins, since)
    rank = {cat: i for i, (cat, _, _) in enumerate(ACTIVITY)}
    colour = {cat: c for cat, _, c in ACTIVITY}
    by_day: dict = {}
    for r in rows:
        day = from_iso(r["at"]).astimezone(IST).date()
        by_day.setdefault(day, []).append(r["category"])
    cells = []
    for i in range(WEEKS * 7):
        day = start + timedelta(days=i)
        cats = by_day.get(day, [])
        if day > today:
            cells.append('<i style="opacity:.35"></i>')
        elif cats:
            top = min(cats, key=lambda c: rank.get(c, len(ACTIVITY)))
            names = ", ".join(sorted({filings.CATEGORY_LABELS.get(c, c) for c in cats}))
            cells.append(f'<i style="background:{colour.get(top, "#AEBBCD")}" title="'
                         f'{day:%d %b %Y}: {len(cats)} filing(s) — {esc(names)}"></i>')
        else:
            cells.append(f'<i title="{day:%d %b %Y}: none stored"></i>')
    legend = "".join(f'<span><i style="background:{c}"></i>{esc(label)}</span>'
                     for _, label, c in ACTIVITY if label)
    legend += '<span><i style="background:#EDF2F7;border:1px solid #D3DEEA"></i>None stored</span>'
    return rows, (f'<div class="pm-dm">{"".join(cells)}</div><div class="pm-legend">{legend}</div>'
                  f'<div class="pm-meta" style="margin-top:8px">{start:%d %b %Y} to {today:%d %b %Y}'
                  f' · one dot per day, coloured by the most important filing type that day</div>')


try:
    if companies.company_count() == 0:
        st.info("**Start here:** import NSE's company list so you can build your watchlist.")
        st.page_link("app/ui/Companies.py", label="Go to Company list", icon=":material/upload_file:")
    elif not watchlist.list_items():
        st.info("**Your watchlist is empty.** Add the companies you want to track.")
        st.page_link("app/ui/Watchlist.py", label="Go to Watchlist", icon=":material/list:")
    else:
        cfg = load_config()
        now = now_utc()
        items = watchlist.list_items()
        isins = [i["isin"] for i in items]

        top = st.columns([3, 1], vertical_alignment="center")
        result = None
        with top[1]:
            if st.button("Refresh prices now", icon=":material/refresh:", width="stretch",
                         type="primary"):
                with st.spinner("Fetching delayed prices from Yahoo…"):
                    result = prices.refresh()
        with top[0]:
            md('<div class="pm-sub" style="margin:0">Prices: <b>Delayed · Yahoo (trust tier 2)'
               '</b> — about 15 minutes behind the market. Live prices arrive when Angel One is '
               'connected.</div>')
        if result is not None:
            (st.success if result.status == "ok" else st.warning)(result.message)

        # --- summary tiles -------------------------------------------------------------
        sources = health.all_sources(now)
        auto = [h for h in sources if h.automated]
        current = sum(h.content_status == "current" for h in auto)
        attention = sum(h.content_status != "current" or h.fetch_status != "ok" for h in auto)
        rows, grid = _activity_grid(isins, now)
        today = now.astimezone(IST).date()
        todays = sorted(r["at"] for r in rows if from_iso(r["at"]).astimezone(IST).date() == today)
        n_conf = conflicts.open_count(isins)
        tol = cfg["conflicts"]["shareholding_percent_points"]
        max_n = int(cfg["watchlist"]["max_companies"])

        k = st.columns(4)
        k[0].markdown(kpi("Watchlist", len(items), f"of {max_n}",
                          "Every change is recorded in the audit log", hero=True),
                      unsafe_allow_html=True)
        k[1].markdown(kpi("Filings today", len(todays), "",
                          f"Newest published {fmt_ist(from_iso(todays[-1]), with_date=False)}"
                          if todays else "None published today yet", tag("NSE + BSE feeds", "blue")),
                      unsafe_allow_html=True)
        k[2].markdown(kpi("Automatic sources current", current, f"/ {len(auto)}",
                          "Content age, not just fetch status",
                          tag(f"{attention} need a look", "orange") if attention
                          else tag("All good", "green")), unsafe_allow_html=True)
        k[3].markdown(kpi("Open conflicts", n_conf, "",
                          f"Sources differ by more than {tol} points",
                          tag("Review", "orange") if n_conf else tag("None", "gray")),
                      unsafe_allow_html=True)
        st.write("")

        # --- watchlist + side column ---------------------------------------------------
        left, right = st.columns([2, 1], gap="medium")
        with left, st.container(border=True, key="card-watchlist"):
            md(card_head("Your watchlist",
                         "Price vs previous close, with its bar time, fetch time and freshness",
                         "trend"))
            quotes = prices.watchlist_quotes()
            cols = st.columns(3)
            for i, q in enumerate(quotes):
                with cols[i % 3]:
                    _watch_card(q)
        with right:
            with st.container(border=True, key="card-signals"):
                md(card_head("Newest signals", "Verified extracts from filings", "pulse",
                             tag("Milestone 3", "gray")))
                md(empty_state("Insufficient evidence",
                               "Signals are extracted from filings starting in Milestone 3. "
                               "Nothing is shown until real signals exist."))
            with st.container(border=True, key="card-health"):
                md(card_head("Data health", "Fetch status · content age · quality", "health"))
                out = []
                for h in sources:
                    f_label, f_tone = STATUS_BADGE.get(h.fetch_status, (h.fetch_status, "gray"))
                    c_label, c_tone = CONTENT_BADGE.get(h.content_status,
                                                        (h.content_status, "gray"))
                    score = ("—<small>unknown</small>" if h.score is None
                             else f"{h.score:.0f}<small>/100</small>")
                    out.append(f'<div class="pm-row"><div style="min-width:0"><div class="n">'
                               f'{esc(h.name)}</div><div class="pm-tags" style="margin-top:5px">'
                               f'{tag(f_label, f_tone)}{tag(c_label, c_tone)}</div></div>'
                               f'<div class="pm-score pm-num">{score}</div></div>')
                md("".join(out))
                st.page_link("app/ui/DataHealth.py", label="Open Data Health",
                             icon=":material/arrow_forward:")

        # --- filing activity -----------------------------------------------------------
        with st.container(border=True, key="card-activity"):
            md(card_head("Filing activity",
                         f"Filings stored for your watchlist over the last {WEEKS} weeks. The "
                         "exchange feeds only list recent filings, so this fills up from the day "
                         "the app started checking.", "calendar"))
            md(grid)

    if companies.company_count() == 0 or not watchlist.list_items():
        with st.container(border=True, key="card-signals-empty"):
            md(card_head("Newest signals", "Verified extracts from filings", "pulse"))
            md(empty_state("Insufficient evidence",
                           "Signals are extracted from filings starting in Milestone 3. Nothing "
                           "is shown until real signals exist."))
    st.caption(f"Page loaded {fmt_ist(now_utc())}")
except FriendlyError as err:
    show_error(err)
except Exception as exc:  # never show a traceback to the owner
    show_error(report(exc))
