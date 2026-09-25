"""Price refresh and latest quotes for the watchlist.

- Refresh: fetch delayed prices, retry politely, store append-only, record the run and
  the source's quality score (brief 14.3).
- Quotes: latest price, day change (exact decimal maths, 14.6), timestamps (14.2),
  freshness, and Known/Unknown values with reasons (14.1).
"""

import logging
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.adapters import yahoo_prices
from app.config import load_config
from app.services import health
from app.services.values import Value, known, not_applicable, unknown
from app.store import db
from app.timeutil import (IST, expected_last_session, from_iso, market_is_open, now_utc,
                          parse_holidays, to_iso)

log = logging.getLogger("mosaic.prices")
SOURCE_ID = yahoo_prices.SOURCE_ID
SOURCE_LABEL = "Delayed · Yahoo"


@dataclass
class RefreshSummary:
    ran: bool
    status: str
    message: str


def _settings():
    cfg = load_config()
    return {
        "open": cfg["market_hours"]["open"],
        "close": cfg["market_hours"]["close"],
        "holidays": parse_holidays(cfg.get("market_holidays")),
        "fresh_minutes": int(cfg.get("freshness", {}).get("intraday_price_minutes", 45)),
        "attempts": int(cfg.get("rate_limits", {}).get(SOURCE_ID, {}).get("max_attempts", 3)),
    }


def refresh(downloader=yahoo_prices._download, sleep=_time.sleep, now=None) -> RefreshSummary:
    s = _settings()
    conn = db.connect()
    try:
        symbols = [r["nse_symbol"] for r in conn.execute(
            "SELECT c.nse_symbol FROM watchlist w JOIN companies c ON c.isin = w.company "
            "WHERE c.nse_symbol IS NOT NULL")]
        if not symbols:
            return RefreshSummary(False, "skipped", "Your watchlist is empty — nothing to refresh.")
        started = now or now_utc()
        busy = conn.execute(
            "SELECT 1 FROM adapter_runs WHERE adapter = ? AND fetch_status = 'running' "
            "AND started_at > ?", (SOURCE_ID, to_iso(started - timedelta(minutes=5)))).fetchone()
        if busy:
            return RefreshSummary(False, "skipped", "A price refresh is already running.")
        with conn:
            run_id = conn.execute(
                "INSERT INTO adapter_runs (adapter, started_at, fetch_status) VALUES (?, ?, 'running')",
                (SOURCE_ID, to_iso(started))).lastrowid
    finally:
        conn.close()

    result = None
    for attempt in range(s["attempts"]):
        result = yahoo_prices.fetch(symbols, downloader=downloader)
        if result.status == "ok":
            break
        if result.error is not None:
            log.warning("Yahoo attempt %d failed: %r", attempt + 1, result.error)
        if attempt < s["attempts"] - 1:
            sleep(2 ** (attempt + 1))

    fetched = now_utc()
    conn = db.connect()
    try:
        with conn:
            for b in result.bars:
                isin = conn.execute("SELECT isin FROM companies WHERE nse_symbol = ?",
                                    (b.symbol,)).fetchone()
                if isin is None:
                    continue
                ts = to_iso(b.start)
                same = conn.execute(
                    "SELECT 1 FROM prices WHERE company = ? AND interval = ? AND timestamp = ? "
                    "AND source = ? AND close = ? AND volume = ?",
                    (isin[0], b.interval, ts, SOURCE_ID, b.close, b.volume)).fetchone()
                if same:
                    continue  # identical row already stored; new versions are appended
                conn.execute(
                    "INSERT INTO prices (company, timestamp, open, high, low, close, volume, "
                    "source, fetched_at, interval, is_delayed, currency) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'INR')",
                    (isin[0], ts, b.open, b.high, b.low, b.close, b.volume, SOURCE_ID,
                     to_iso(fetched), b.interval))
            conn.execute(
                "UPDATE adapter_runs SET finished_at = ?, fetch_status = ?, items_received = ?, "
                "items_valid = ?, message = ? WHERE id = ?",
                (to_iso(fetched), result.status, result.rows_received, result.rows_valid,
                 result.message, run_id))
    finally:
        conn.close()
    health.record_quality(SOURCE_ID, now=fetched)
    return RefreshSummary(True, result.status, result.message)


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------

@dataclass
class Quote:
    isin: str
    symbol: str | None
    name: str
    price: Value
    change: Value            # absolute change vs previous close (Decimal)
    change_pct: Value        # percent change (Decimal)
    freshness: str           # current | stale | no_data | not_applicable
    freshness_note: str


def _D(x) -> Decimal:
    return Decimal(str(x))


def _latest(conn, isin, interval):
    return conn.execute(
        "SELECT * FROM prices WHERE company = ? AND interval = ? AND source = ? "
        "ORDER BY timestamp DESC, id DESC LIMIT 1", (isin, interval, SOURCE_ID)).fetchone()


def quote_for(conn, row, s, now) -> Quote:
    isin, symbol, name = row["isin"], row["nse_symbol"], row["name"]
    if not symbol:
        na = not_applicable("Not listed on NSE (no NSE symbol)")
        return Quote(isin, symbol, name, na, na, na, "not_applicable", na.reason)

    daily, intra = _latest(conn, isin, "1d"), _latest(conn, isin, "15m")
    if daily is None and intra is None:
        last = conn.execute(
            "SELECT fetch_status, message FROM adapter_runs WHERE adapter = ? "
            "AND fetch_status != 'running' ORDER BY id DESC LIMIT 1", (SOURCE_ID,)).fetchone()
        if last is None:
            u = unknown("No price fetched yet — press 'Refresh prices now'")
        elif last["fetch_status"] != "ok":
            u = unknown(f"Last fetch failed: {last['message']}")
        else:
            u = unknown(f"Yahoo returned no data for {symbol}.NS")
        return Quote(isin, symbol, name, u, u, u, "no_data", u.reason)

    open_now = market_is_open(now, s["open"], s["close"], s["holidays"])
    use_intra = False
    if intra is not None:
        intra_day = from_iso(intra["timestamp"]).astimezone(IST).date()
        daily_day = from_iso(daily["timestamp"]).astimezone(IST).date() if daily else None
        use_intra = open_now and (daily_day is None or intra_day >= daily_day)
    used = intra if use_intra else (daily or intra)
    bar_start = from_iso(used["timestamp"])
    session = bar_start.astimezone(IST).date()
    price = known(_D(used["close"]), source=SOURCE_LABEL,
                  event_time=bar_start, fetched_time=from_iso(used["fetched_at"]))

    prev = conn.execute(
        "SELECT close FROM prices WHERE company = ? AND interval = '1d' AND source = ? "
        "AND timestamp < ? ORDER BY timestamp DESC, id DESC LIMIT 1",
        (isin, SOURCE_ID, to_iso(datetime.combine(session, datetime.min.time(), IST)))).fetchone()
    if prev is None:
        change = change_pct = unknown("Previous close not fetched yet")
    else:
        diff = price.value - _D(prev["close"])
        change = known(diff, source=SOURCE_LABEL)
        change_pct = known(diff / _D(prev["close"]) * 100, source=SOURCE_LABEL)

    if open_now:
        fresh = use_intra and now - bar_start <= timedelta(minutes=s["fresh_minutes"] + 15)
        note = ("Delayed ~15 min" if fresh else
                f"Older than {s['fresh_minutes']} minutes during market hours")
    else:
        expected = expected_last_session(now, s["open"], s["holidays"])
        fresh = session >= expected
        note = ("Last close" if fresh else
                f"Latest price is from {session:%d %b}; expected {expected:%d %b}")
    return Quote(isin, symbol, name, price, change, change_pct,
                 "current" if fresh else "stale", note)


def watchlist_quotes(now=None) -> list[Quote]:
    s, now = _settings(), now or now_utc()
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT c.isin, c.nse_symbol, c.name FROM watchlist w "
            "JOIN companies c ON c.isin = w.company ORDER BY c.name").fetchall()
        return [quote_for(conn, r, s, now) for r in rows]
    finally:
        conn.close()


def content_status(now=None) -> tuple[str, str]:
    """Aggregate content age over the watchlist: current | partial | stale | no_data."""
    quotes = [q for q in watchlist_quotes(now) if q.freshness != "not_applicable"]
    if not quotes:
        return "no_data", "No watchlist companies with an NSE symbol yet"
    current = sum(q.freshness == "current" for q in quotes)
    if current == len(quotes):
        return "current", f"All {current} prices are current"
    if current:
        return "partial", f"{current} of {len(quotes)} prices are current"
    if all(q.freshness == "no_data" for q in quotes):
        return "no_data", "No prices fetched yet"
    return "stale", "No price is current"
