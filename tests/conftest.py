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


BS = chr(92)  # a backslash


def text_pdf(pages: list[list[str]]) -> bytes:
    """FIXTURE: a small PDF whose pages contain the given lines as real (selectable) text."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        body = "BT /F1 11 Tf 14 TL 50 780 Td " + " ".join(
            "(" + ln.replace(BS, BS + BS).replace("(", BS + "(").replace(")", BS + ")") + ") Tj T*"
            for ln in lines) + " ET"
        objs.append(f"<< /Length {len(body)} >>\nstream\n{body}\nendstream")
        content_id = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


class FakeAI:
    """FIXTURE stand-in for Groq and Gemini: returns scripted answers, records every call.
    answers: {task_prompt_name: callable(user_text) -> json string, or an LLMFailure}."""

    def __init__(self, monkeypatch, answers: dict):
        from app.llm import backends

        self.answers, self.calls = answers, []
        for provider in ("groq", "gemini"):
            monkeypatch.setitem(backends.BACKENDS, provider, self._backend(provider))

    def _backend(self, provider):
        from app.llm.backends import LLMFailure, Raw

        def generate(model, system, user, schema, schema_name, temperature, max_tokens,
                     thinking_level=None):
            self.calls.append((provider, model, schema_name, user))
            answer = self.answers[schema_name]
            if isinstance(answer, dict):
                answer = answer.get(provider)
            out = answer(user) if callable(answer) else answer
            if isinstance(out, LLMFailure):
                raise out
            return Raw(out, 1000, 200)
        return generate
