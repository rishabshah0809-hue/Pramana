import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def temp_dirs(tmp_path, monkeypatch):
    """Point the app at a throwaway folder so tests never touch real data."""
    monkeypatch.setenv("MOSAIC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MOSAIC_LOG_DIR", str(tmp_path / "logs"))
    return tmp_path


FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def db_ready(temp_dirs):
    from app.store import db

    db.init_db()
    return temp_dirs


@pytest.fixture
def imported(db_ready):
    """FIXTURE company list imported into a throwaway database."""
    from app.services import companies

    companies.import_equity_list((FIXTURES / "FIXTURE_EQUITY_L.csv").read_bytes(),
                                 "FIXTURE_EQUITY_L.csv")
    return db_ready


def fake_yahoo_frame(data: dict, interval: str):
    """FIXTURE: build a DataFrame shaped like yfinance.download(group_by='ticker').

    data = {"FXALPHA": [(timestamp_ist_str, open, high, low, close, volume), ...]}
    """
    import pandas as pd

    frames = {}
    for sym, rows in data.items():
        idx = pd.DatetimeIndex([pd.Timestamp(r[0], tz="Asia/Kolkata") for r in rows])
        frames[f"{sym}.NS"] = pd.DataFrame(
            [r[1:] for r in rows], index=idx,
            columns=["Open", "High", "Low", "Close", "Volume"])
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1)


class FakeClient:
    """FIXTURE stand-in for the polite exchange downloader: serves fixture bytes by URL,
    or raises the FetchFailed / exception given for that URL. Records every URL asked for."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url, etag=None, last_modified=None):
        from app.adapters.polite import Response

        self.calls.append(url)
        value = self.responses.get(url)
        if value is None:
            from app.adapters.polite import FetchFailed

            raise FetchFailed("missing", "FIXTURE: no such file.", 404)
        if isinstance(value, Exception):
            raise value
        return Response(url, 200, value)


def fixture_pdf(pages: int = 2) -> bytes:
    """FIXTURE: a small blank PDF made on the fly."""
    import io

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(200, 300)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


@pytest.fixture
def with_bse(imported):
    """FIXTURE company list plus FIXTURE BSE list (links BSE codes, adds a BSE-only company)."""
    from app.services import companies

    companies.import_bse_list((FIXTURES / "FIXTURE_List_of_Scrips.csv").read_bytes(),
                              "FIXTURE_List_of_Scrips.csv")
    return imported
