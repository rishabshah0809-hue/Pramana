from pathlib import Path

from streamlit.testing.v1 import AppTest

from app import paths
from app.ui.common import FOOTER_TEXT

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def test_dashboard_loads_empty_and_creates_database(temp_dirs):
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert paths.db_path().exists()  # works without start.py (e.g. Streamlit Cloud)
    assert at.title[0].value == "Mosaic India"
    assert "No companies yet" in at.info[0].value
    assert any(FOOTER_TEXT in m.value for m in at.markdown)
    assert any("13 of 13 tables ready" in m.value for m in at.markdown)


def test_dashboard_shows_plain_english_if_setup_fails(temp_dirs, monkeypatch):
    # Point the data folder at a file, so the database cannot be created.
    blocker = temp_dirs / "not-a-folder"
    blocker.write_text("fixture")
    monkeypatch.setenv("MOSAIC_DATA_DIR", str(blocker))
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert at.error and "What to do" in at.error[0].value
    assert "Traceback" not in at.error[0].value
