"""M2 schedules and screens (FIXTURE data only)."""

from datetime import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.adapters import announcements, bulk_block
from app.config import load_config
from app.services import filings, health, schedule, watchlist
from app.timeutil import IST
from app.ui.common import FOOTER_TEXT
from tests.conftest import FIXTURES, FakeClient, fixture_pdf
from tests.test_m2_adapters import ALPHA, nse_only_client

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def at(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=IST)


def test_nse_feed_schedule(temp_dirs):
    cfg = load_config()
    # Friday 26 Sep 2026 is a weekday in the busy window: every 5 minutes.
    assert schedule.nse_due(at(2026, 9, 25, 10, 5), cfg)
    assert schedule.nse_due(at(2026, 9, 25, 21, 55), cfg)
    # Nights and weekends: every 30 minutes.
    assert not schedule.nse_due(at(2026, 9, 25, 22, 5), cfg)
    assert schedule.nse_due(at(2026, 9, 25, 22, 30), cfg)
    assert not schedule.nse_due(at(2026, 9, 26, 10, 5), cfg)   # Saturday
    assert schedule.nse_due(at(2026, 9, 26, 10, 0), cfg)


def test_bse_feed_schedule(temp_dirs):
    cfg = load_config()
    assert schedule.bse_due(at(2026, 9, 25, 10, 15), cfg)       # market hours: every 15 min
    assert not schedule.bse_due(at(2026, 9, 25, 10, 5), cfg)
    assert not schedule.bse_due(at(2026, 9, 25, 18, 15), cfg)   # after hours: hourly
    assert schedule.bse_due(at(2026, 9, 25, 18, 0), cfg)


def test_deals_session_waits_for_evening_files(temp_dirs):
    cfg = load_config()
    assert health.last_deals_session(at(2026, 9, 25, 12, 0), cfg).isoformat() == "2026-09-24"
    assert health.last_deals_session(at(2026, 9, 25, 19, 0), cfg).isoformat() == "2026-09-25"


def run(page, **params):
    t = AppTest.from_file(APP)
    t.switch_page(page)
    for k, v in params.items():
        t.query_params[k] = v
    return t.run(timeout=60)


def text(t):
    return " ".join([m.value for m in t.markdown] + [c.value for c in t.caption]
                    + [w.value for w in t.warning] + [i.value for i in t.info])


def test_pages_load_with_no_data(imported):
    for page in ("app/ui/Company.py", "app/ui/DocumentViewer.py", "app/ui/DataHealth.py",
                 "app/ui/Companies.py"):
        t = run(page)
        assert not t.exception, page
        assert FOOTER_TEXT in text(t)


def test_company_page_and_viewer_show_real_stored_documents(with_bse):
    watchlist.add(ALPHA)
    announcements.run(client=nse_only_client())
    bulk_block.run(client=FakeClient({
        bulk_block.FILES["bulk"]: (FIXTURES / "FIXTURE_bulk.csv").read_bytes(),
        bulk_block.FILES["block"]: (FIXTURES / "FIXTURE_block.csv").read_bytes()}))
    t = run("app/ui/Company.py", isin=ALPHA)
    assert not t.exception
    body = text(t)
    assert "Fixture Alpha Limited" in body and "Financial Results" in body
    assert "Open the original filing" in str(t) or t.get("page_link")

    doc_id = next(r["document_id"] for r in filings.company_filings(ALPHA)
                  if r["category"] == "results")
    t = run("app/ui/DocumentViewer.py", doc=str(doc_id))
    assert not t.exception
    body = text(t)
    assert "Published" in body and "Fetched" in body and "IST" in body
    assert "announcements" in body and "SHA-256" in body
    assert len(t.get("image")) >= 1                    # the PDF pages are shown


def test_data_health_lists_new_adapters_and_errors(with_bse):
    from app.adapters.polite import FetchFailed

    down = FetchFailed("error", "Could not reach NSE. Check your internet connection.")
    announcements.run(client=FakeClient({f.url: down for f in announcements.FEEDS}))
    t = run("app/ui/DataHealth.py")
    assert not t.exception
    body = text(t)
    for name in ("Company announcements", "Shareholding patterns", "Insider trading",
                 "Bulk and block deals"):
        assert name in body
    assert "Could not reach NSE" in body and "1 errors" in body
