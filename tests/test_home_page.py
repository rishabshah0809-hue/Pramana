from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.store import db
from app.ui.common import FOOTER_TEXT

HOME = str(Path(__file__).resolve().parent.parent / "app" / "ui" / "Home.py")


def test_home_page_loads_empty(temp_dirs):
    db.init_db()
    at = AppTest.from_file(HOME).run(timeout=30)
    assert not at.exception
    assert at.title[0].value == "Mosaic India"
    assert "No companies yet" in at.info[0].value
    assert any(FOOTER_TEXT in m.value for m in at.markdown)
    assert any("13 of 13 tables ready" in m.value for m in at.markdown)


def test_home_page_without_database_explains_what_to_do(temp_dirs):
    at = AppTest.from_file(HOME).run(timeout=30)
    assert not at.exception
    assert any("run start.py" in m.value for m in at.markdown)
