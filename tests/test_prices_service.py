"""Price service tests. All prices are FIXTURES (made up); times are fixed."""

from datetime import datetime
from decimal import Decimal

from app.services import health, prices, watchlist
from app.store import db
from app.timeutil import IST
from tests.conftest import fake_yahoo_frame

DAILY = {"FXALPHA": [("2026-09-24", 100, 105, 99, 104, 1000),
                     ("2026-09-25", 104, 110, 103, 108.5, 1200)]}
INTRA = {"FXALPHA": [("2026-09-25 14:15", 108, 109, 107.5, 108.4, 40)]}


def dl(tickers, period, interval):
    return fake_yahoo_frame(DAILY if interval == "1d" else INTRA, interval)


def count(sql):
    conn = db.connect()
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def test_empty_watchlist_skips(imported):
    assert prices.refresh(downloader=dl).status == "skipped"


def test_refresh_stores_and_dedupes(imported):
    watchlist.add("INE0FXA01011")
    s = prices.refresh(downloader=dl)
    assert s.ran and s.status == "ok"
    assert count("SELECT COUNT(*) FROM prices") == 3
    prices.refresh(downloader=dl)
    assert count("SELECT COUNT(*) FROM prices") == 3        # identical rows not duplicated
    assert count("SELECT COUNT(*) FROM prices WHERE is_delayed = 1 AND fetched_at IS NOT NULL") == 3
    assert count("SELECT COUNT(*) FROM quality_scores WHERE adapter = 'yahoo_prices'") == 2


def test_retries_then_reports_failure(imported):
    watchlist.add("INE0FXA01011")
    calls, waits = [], []

    def boom(*a):
        calls.append(1)
        raise ConnectionError("offline")

    s = prices.refresh(downloader=boom, sleep=waits.append)
    assert s.status == "error" and "internet" in s.message
    assert len(calls) == 3 and waits == [2, 4]


def test_quote_during_market_hours(imported):
    watchlist.add("INE0FXA01011")
    prices.refresh(downloader=dl)
    q = prices.watchlist_quotes(now=datetime(2026, 9, 25, 14, 40, tzinfo=IST))[0]
    assert q.price.value == Decimal("108.4")                # latest 15-min bar
    assert q.change.value == Decimal("4.4")                  # exact: 108.4 - 104
    assert q.change_pct.value.quantize(Decimal("0.01")) == Decimal("4.23")
    assert q.freshness == "current"
    assert q.price.event_time.astimezone(IST).strftime("%H:%M") == "14:15"
    assert q.price.fetched_time is not None


def test_quote_after_close_uses_daily_close(imported):
    watchlist.add("INE0FXA01011")
    prices.refresh(downloader=dl)
    q = prices.watchlist_quotes(now=datetime(2026, 9, 25, 18, 0, tzinfo=IST))[0]
    assert q.price.value == Decimal("108.5") and q.freshness == "current"


def test_old_prices_are_stale(imported):
    watchlist.add("INE0FXA01011")
    prices.refresh(downloader=dl)
    q = prices.watchlist_quotes(now=datetime(2026, 9, 29, 18, 0, tzinfo=IST))[0]  # next Tuesday
    assert q.freshness == "stale" and "expected" in q.freshness_note


def test_no_price_is_unknown_with_reason(imported):
    watchlist.add("INE0FXB01019")
    q = prices.watchlist_quotes()[0]
    assert q.price.state == "unknown" and "Refresh" in q.price.reason
    assert q.change.state == "unknown"


def test_quality_score_formula(imported):
    watchlist.add("INE0FXA01011")
    prices.refresh(downloader=dl, now=None)
    q = health.compute_quality("yahoo_prices",
                               now=datetime(2026, 9, 25, 18, 0, tzinfo=IST).astimezone())
    # success 100%, freshness current (1.0), validation 3/3 -> 100
    assert q["success_rate"] == 1.0 and q["validation_rate"] == 1.0


def test_quality_unknown_without_runs(db_ready):
    q = health.compute_quality("yahoo_prices")
    assert q["score"] is None and "Unknown" in q["note"]


def test_health_statuses(imported):
    h = health.source_health("yahoo_prices")
    assert h.fetch_status == "never_run" and h.score is None
    lst = health.source_health("nse_equity_list")
    assert lst.fetch_status == "ok" and lst.content_status == "current"


def test_unknown_reason_explains_failed_fetch(imported):
    watchlist.add("INE0FXA01011")

    def boom(*a):
        raise ConnectionError("offline")

    prices.refresh(downloader=boom, sleep=lambda s: None)
    q = prices.watchlist_quotes()[0]
    assert q.price.reason.startswith("Last fetch failed") and "internet" in q.price.reason
