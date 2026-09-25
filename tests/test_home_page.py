from pathlib import Path

from streamlit.testing.v1 import AppTest

from app import paths
from app.services import prices, watchlist
from app.ui.common import FOOTER_TEXT, fmt_inr, fmt_signed
from tests.conftest import fake_yahoo_frame

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def run(page=None):
    at = AppTest.from_file(APP)
    if page:
        at.switch_page(page)
    return at.run(timeout=30)


def all_text(at):
    return " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)


def test_dashboard_loads_empty_and_creates_database(temp_dirs):
    at = run()
    assert not at.exception
    assert paths.db_path().exists()  # works without start.py (e.g. Streamlit Cloud)
    assert at.title[0].value == "Mosaic India"
    assert "Start here" in at.info[0].value
    assert FOOTER_TEXT in all_text(at)
    assert "Insufficient evidence" in all_text(at)     # no invented signals


def test_dashboard_shows_prices_with_source_and_times(imported):
    # FIXTURE prices
    daily = {"FXALPHA": [("2026-09-24", 100, 105, 99, 104, 1000),
                         ("2026-09-25", 104, 110, 103, 108.5, 1200)]}
    intra = {"FXALPHA": [("2026-09-25 14:15", 108, 109, 107.5, 108.4, 40)]}
    watchlist.add("INE0FXA01011")
    watchlist.add("INE0FXB01019")
    prices.refresh(downloader=lambda t, p, i: fake_yahoo_frame(daily if i == "1d" else intra, i))
    at = run()
    assert not at.exception
    text = all_text(at)
    assert "Fixture Alpha Limited" in text and "Delayed · Yahoo" in text
    assert "Fetched" in text and "IST" in text
    assert "Unknown — No price fetched yet" in text or "Unknown" in text  # FXBETA has no data


def test_other_pages_load(imported):
    for page in ("app/ui/Watchlist.py", "app/ui/Companies.py", "app/ui/DataHealth.py"):
        at = run(page)
        assert not at.exception, page
        assert FOOTER_TEXT in all_text(at)
    at = run("app/ui/DataHealth.py")
    assert "Formula" in all_text(at) and "Trust tier" in all_text(at)


def test_dashboard_shows_plain_english_if_setup_fails(temp_dirs, monkeypatch):
    # Point the data folder at a file, so the database cannot be created.
    blocker = temp_dirs / "not-a-folder"
    blocker.write_text("fixture")
    monkeypatch.setenv("MOSAIC_DATA_DIR", str(blocker))
    at = run()
    assert not at.exception
    assert at.error and "What to do" in at.error[0].value
    assert "Traceback" not in at.error[0].value


def test_indian_number_format():
    assert fmt_inr(1234567.891) == "₹12,34,567.89"
    assert fmt_inr(999) == "₹999.00"
    assert fmt_signed(-4.4) == "-₹4.40"
    assert fmt_signed(4.2345, pct=True) == "+4.23%"
