"""Pramana redesign: the services behind the new Command Center tiles and grid (FIXTURE data)."""

from datetime import datetime, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.adapters import announcements
from app.services import conflicts, filings, watchlist
from app.ui.common import FOOTER_TEXT, gauge, sparkline
from tests.test_m2_adapters import ALPHA, nse_only_client

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")
LONG_AGO = datetime(2000, 1, 1, tzinfo=timezone.utc)


def test_watchlist_activity_lists_stored_filings(with_bse):
    watchlist.add(ALPHA)
    announcements.run(client=nse_only_client())
    rows = filings.watchlist_activity([ALPHA], LONG_AGO)
    assert rows and all(r["isin"] == ALPHA and r["at"] for r in rows)
    assert {r["category"] for r in rows} <= set(filings.CATEGORY_LABELS)
    assert filings.watchlist_activity([ALPHA], datetime(2999, 1, 1, tzinfo=timezone.utc)) == []


def test_open_count_is_zero_without_conflicts(imported):
    assert conflicts.open_count([ALPHA]) == 0
    assert conflicts.open_count([]) == 0


def test_command_center_with_data_shows_tiles_and_activity(with_bse):
    watchlist.add(ALPHA)
    announcements.run(client=nse_only_client())
    at = AppTest.from_file(APP).run(timeout=60)
    assert not at.exception
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    for words in ("Filings today", "Open conflicts", "Filing activity", "Insufficient evidence",
                  FOOTER_TEXT):
        assert words in text


def test_display_helpers_never_invent_values():
    assert sparkline([]) == "" and sparkline([101.5]) == ""   # needs two stored points
    assert "Unknown" in gauge(None)
    assert ">92<" in gauge(92)
