"""Yahoo adapter tests. All price numbers here are FIXTURES (made up)."""

from app.adapters import yahoo_prices
from tests.conftest import fake_yahoo_frame

DAILY = {"FXALPHA": [("2026-09-24", 100, 105, 99, 104, 1000),
                     ("2026-09-25", 104, 110, 103, 108.5, 1200)],
         "FXBETA": [("2026-09-25", 50, 49, 48, 50.5, 10)]}          # high < open: invalid
INTRA = {"FXALPHA": [("2026-09-25 14:00", 107, 109, 106, 108, 50),
                     ("2026-09-25 14:15", 108, 109, 107.5, 108.4, 40)]}


def downloader(tickers, period, interval):
    return fake_yahoo_frame(DAILY if interval == "1d" else INTRA, interval)


def test_parses_bars_and_drops_invalid_rows():
    r = yahoo_prices.fetch(["FXALPHA", "FXBETA", "FXGAMMA"], downloader=downloader)
    assert r.status == "ok"
    daily = [b for b in r.bars if b.interval == "1d"]
    intra = [b for b in r.bars if b.interval == "15m"]
    assert [b.close for b in daily] == [104, 108.5]
    assert len(intra) == 1 and intra[0].close == 108.4      # only the latest 15-min bar
    assert r.rows_received == 4 and r.rows_valid == 3
    assert set(r.no_data) == {"FXBETA", "FXGAMMA"}
    assert "2 of 3" not in r.message and "No data for" in r.message


def test_rate_limit_becomes_blocked():
    class YFRateLimitError(Exception):
        pass

    def boom(*a):
        raise YFRateLimitError("Too Many Requests. Rate limited.")

    r = yahoo_prices.fetch(["FXALPHA"], downloader=boom)
    assert r.status == "blocked" and "limiting" in r.message
    assert "Traceback" not in r.message


def test_offline_becomes_plain_english():
    def boom(*a):
        raise ConnectionError("Failed to resolve host")

    r = yahoo_prices.fetch(["FXALPHA"], downloader=boom)
    assert r.status == "error" and "internet" in r.message


def test_nothing_returned_is_missing():
    r = yahoo_prices.fetch(["FXALPHA"], downloader=lambda *a: fake_yahoo_frame({}, "1d"))
    assert r.status == "missing" and r.bars == []
