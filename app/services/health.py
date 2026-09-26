"""Source health (brief 14.3): fetch status and content age kept separate, plus a
transparent quality score with its history.

Quality score = 40% x fetch success rate (last 7 days)
              + 30% x content freshness (current 1, partial 0.5, stale 0)
              + 30% x validation pass rate (last run)
"""

from dataclasses import dataclass
from datetime import timedelta

from app.adapters.registry import SOURCES
from app.config import load_config
from app.store import db
from app.timeutil import (IST, expected_last_session, from_iso, market_is_open, now_utc,
                          parse_holidays, to_iso)

FORMULA = ("40% × fetch success rate (last 7 days) + 30% × content freshness "
           "(current = 1, partial = 0.5, stale = 0) + 30% × validation pass rate (last run)")
FRESHNESS_POINTS = {"current": 1.0, "partial": 0.5, "stale": 0.0}
FEED_ADAPTERS = ("announcements", "shareholding", "insider_sast")


@dataclass
class SourceHealth:
    source_id: str
    name: str
    tier: int
    terms_status: str
    automated: bool
    fetch_status: str          # ok | stale | missing | blocked | timeout | error | never_run
    fetch_note: str
    content_status: str        # current | partial | stale | no_data
    content_note: str
    last_success: str | None   # ISO time
    runs_7d: int
    errors_7d: int
    score: float | None
    success_rate: float | None
    freshness: float | None
    validation_rate: float | None


def last_deals_session(now, cfg):
    """The latest session whose bulk/block files should be out by now (posted after close)."""
    holidays = parse_holidays(cfg.get("market_holidays"))
    session = expected_last_session(now, cfg["market_hours"]["open"], holidays)
    after = cfg["schedules"]["bulk_block_deals"]["after_close"]
    h, m = (int(x) for x in after.split(":"))
    local = now.astimezone(IST)
    if session == local.date() and (local.hour, local.minute) < (h, m):
        prev = local.replace(hour=0, minute=0) - timedelta(minutes=1)
        session = expected_last_session(prev, "00:00", holidays)
    return session


def _content(source_id: str, now) -> tuple[str, str]:
    cfg = load_config()
    if source_id == "yahoo_prices":
        from app.services import prices

        return prices.content_status(now)
    if source_id in FEED_ADAPTERS:
        from app.services import filings

        fresh = cfg.get("freshness", {})
        days = (fresh.get("shareholding_days", 30) if source_id == "shareholding"
                else fresh.get("filings_days", 3))
        return filings.content_status(source_id, now, int(days))
    if source_id == "bulk_block":
        from app.adapters import bulk_block

        return bulk_block.content_status(now, last_deals_session(now, cfg))
    if source_id in ("nse_equity_list", "bse_scrip_list"):
        days = int(cfg.get("freshness", {}).get("company_list_days", 35))
        who = "NSE" if source_id == "nse_equity_list" else "BSE"
        conn = db.connect()
        try:
            r = conn.execute("SELECT fetched_at FROM documents WHERE source = ? "
                             "ORDER BY id DESC LIMIT 1", (source_id,)).fetchone()
        finally:
            conn.close()
        if r is None:
            return "no_data", "No company list imported yet"
        age = (now - from_iso(r["fetched_at"])).days
        if age <= days:
            return "current", f"Imported {age} day(s) ago"
        return "stale", f"Imported {age} days ago — download a fresh list from {who}"
    return "no_data", "Unknown source"


def stale_after(source_id: str, now, cfg) -> timedelta | None:
    """How long without a successful fetch before the fetch status reads "stale"."""
    s = cfg["schedules"]
    holidays = parse_holidays(cfg.get("market_holidays"))
    open_now = market_is_open(now, cfg["market_hours"]["open"], cfg["market_hours"]["close"],
                              holidays)
    if source_id == "yahoo_prices":
        every = int(s["prices_delayed"]["every_minutes"])
        return timedelta(minutes=2 * every + 5) if open_now else None
    if source_id in FEED_ADAPTERS:
        from app.services import schedule

        every = schedule.nse_every_minutes(now, cfg)
        if source_id == "announcements":  # also carries the BSE feed
            every = max(every, schedule.bse_every_minutes(now, cfg))
        return timedelta(minutes=2 * every + 10)
    if source_id == "bulk_block":
        return timedelta(days=4)  # daily on weekdays; allows for a long weekend
    return None


def _runs(conn, source_id, now):
    return conn.execute(
        "SELECT fetch_status FROM adapter_runs WHERE adapter = ? AND started_at >= ? "
        "AND fetch_status != 'running'", (source_id, to_iso(now - timedelta(days=7)))).fetchall()


def compute_quality(source_id: str, now=None) -> dict:
    now = now or now_utc()
    conn = db.connect()
    try:
        runs = _runs(conn, source_id, now)
        last = conn.execute(
            "SELECT items_received, items_valid FROM adapter_runs WHERE adapter = ? "
            "AND fetch_status != 'running' ORDER BY id DESC LIMIT 1", (source_id,)).fetchone()
    finally:
        conn.close()
    success = (sum(r["fetch_status"] == "ok" for r in runs) / len(runs)) if runs else None
    content, _ = _content(source_id, now)
    fresh = FRESHNESS_POINTS.get(content)
    valid = (last["items_valid"] / last["items_received"]
             if last and last["items_received"] else None)
    parts = {"success_rate": success, "freshness": fresh, "validation_rate": valid}
    if None in parts.values():
        missing = [k.replace("_", " ") for k, v in parts.items() if v is None]
        return {**parts, "score": None, "note": "Unknown: no data yet for " + ", ".join(missing)}
    score = round(100 * (0.4 * success + 0.3 * fresh + 0.3 * valid), 1)
    return {**parts, "score": score, "note": None}


def record_quality(source_id: str, now=None) -> None:
    now = now or now_utc()
    q = compute_quality(source_id, now)
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO quality_scores (adapter, computed_at, score, success_rate, freshness, "
                "validation_rate, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source_id, to_iso(now), q["score"], q["success_rate"], q["freshness"],
                 q["validation_rate"], q["note"]))
    finally:
        conn.close()


def source_health(source_id: str, now=None) -> SourceHealth:
    now = now or now_utc()
    src = SOURCES[source_id]
    cfg = load_config()
    conn = db.connect()
    try:
        last = conn.execute(
            "SELECT fetch_status, message, started_at FROM adapter_runs WHERE adapter = ? "
            "AND fetch_status != 'running' ORDER BY id DESC LIMIT 1", (source_id,)).fetchone()
        last_ok = conn.execute(
            "SELECT finished_at FROM adapter_runs WHERE adapter = ? AND fetch_status = 'ok' "
            "ORDER BY id DESC LIMIT 1", (source_id,)).fetchone()
        runs = _runs(conn, source_id, now)
    finally:
        conn.close()

    if last is None:
        fetch, note = "never_run", ("Not imported yet" if not src.automated
                                    else "Never fetched yet — press 'Check now'")
    else:
        fetch, note = last["fetch_status"], last["message"] or ""
        limit = stale_after(source_id, now, cfg) if src.automated else None
        if fetch == "ok" and last_ok is not None and limit is not None                 and now - from_iso(last_ok["finished_at"]) > limit:
            fetch, note = "stale", ("No successful fetch recently. Is the background scheduler "
                                    "running? Restarting with start.py starts it.")
    content, content_note = _content(source_id, now)
    q = compute_quality(source_id, now)
    return SourceHealth(
        source_id, src.name, src.tier, src.terms_status, src.automated, fetch, note, content,
        content_note, last_ok["finished_at"] if last_ok else None, len(runs),
        sum(r["fetch_status"] != "ok" for r in runs), q["score"], q["success_rate"],
        q["freshness"], q["validation_rate"])


def all_sources(now=None) -> list[SourceHealth]:
    return [source_health(sid, now) for sid in SOURCES]


def score_history(source_id: str, limit: int = 200) -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT computed_at, score FROM quality_scores WHERE adapter = ? AND score IS NOT NULL "
            "ORDER BY id DESC LIMIT ?", (source_id, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()
