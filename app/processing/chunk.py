"""Step a — Chunk: split a stored document into passages, keeping page and character offsets.

- Text comes from pypdfium2, the same engine the Document Viewer uses to draw pages, so a
  passage's offsets can be highlighted on the page image.
- A passage never crosses a page and is at most ai.processing.chunk_chars long; it breaks
  at blank lines, then line ends, then sentence ends.
- Offsets are positions in that page's extracted text (for a zip, in that member file's page).
- A page with no text layer (a scanned image) is recorded as kind 'no_text' and is never
  sent to an AI: its words can't be checked against the source.
"""

import io
import zipfile
from dataclasses import dataclass

from app.config import load_config
from app.services import documents, rawstore
from app.store import db

EXTRACTION_VERSION = "pdfium-1"
# pdfium writes U+FFFE / U+FFFF where a PDF's font maps a hyphen oddly ("Non\ufffePromoter").
# Each becomes a plain hyphen: one character for one, so offsets and highlights stay exact.
_PDFIUM_FIXES = str.maketrans({"\ufffe": "-", "\uffff": "-"})
MIN_PAGE_CHARS = 40  # fewer real characters than this = treated as no text layer


@dataclass
class PageText:
    member: str | None   # file inside a zip, or None
    page: int            # 1-based
    text: str


def pages_of(data: bytes, name: str = "", member: str | None = None) -> list[PageText]:
    kind = documents.kind_of(data, name)
    if kind == "pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(data)
        try:
            out = []
            for i in range(len(pdf)):
                tp = pdf[i].get_textpage()
                out.append(PageText(member, i + 1, tp.get_text_range().translate(_PDFIUM_FIXES)))
                tp.close()
            return out
        finally:
            pdf.close()
    if kind == "zip":
        out = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.is_dir() or info.file_size > documents.MAX_ZIP_MEMBER:
                    continue
                if info.filename.lower().endswith((".pdf", ".htm", ".html")):
                    out += pages_of(z.read(info), info.filename, info.filename)
        return out
    if kind == "html":
        return [PageText(member, 1, documents.html_text(data))]
    return []  # XML / CSV are structured data: read by code, not by AI


def split_page(text: str, max_chars: int) -> list[tuple[int, int]]:
    """(start, end) spans covering the page's text, each at most max_chars long."""
    spans, start, n = [], 0, len(text)
    while start < n:
        while start < n and text[start].isspace():
            start += 1
        if start >= n:
            break
        end = min(start + max_chars, n)
        if end < n:
            window = text[start:end]
            for sep in ("\r\n\r\n", "\n\n", "\r\n", "\n", ". "):
                cut = window.rfind(sep)
                if cut > max_chars // 3:
                    end = start + cut + len(sep)
                    break
        stop = end
        while stop > start and text[stop - 1].isspace():
            stop -= 1
        if stop > start:
            spans.append((start, stop))
        start = end
    return spans


def chunk_document(document_id: int) -> dict:
    """Create passages for a document once per extraction version. Returns counts."""
    conn = db.connect()
    try:
        existing = conn.execute(
            "SELECT kind, COUNT(*) n FROM passages WHERE document_id = ? AND extraction_version = ? "
            "GROUP BY kind", (document_id, EXTRACTION_VERSION)).fetchall()
        if existing:
            return {r["kind"]: r["n"] for r in existing}
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    finally:
        conn.close()
    if doc is None:
        return {}
    max_chars = int(load_config()["ai"]["processing"].get("chunk_chars", 3000))
    data = rawstore.read(doc["file_path"])
    pages = pages_of(data, doc["file_path"].removesuffix(".gz"))
    rows = []
    for p in pages:
        if len("".join(p.text.split())) < MIN_PAGE_CHARS:
            rows.append((p.page, 0, 0, "", p.member, "no_text"))
            continue
        for s, e in split_page(p.text, max_chars):
            rows.append((p.page, s, e, p.text[s:e], p.member, "text"))
    if not rows:
        rows.append((None, 0, 0, "", None, "no_text"))
    conn = db.connect()
    try:
        with conn:
            conn.executemany(
                "INSERT INTO passages (document_id, page, char_start, char_end, text, member, "
                "kind, extraction_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(document_id, *r, EXTRACTION_VERSION) for r in rows])
    finally:
        conn.close()
    counts: dict = {}
    for r in rows:
        counts[r[5]] = counts.get(r[5], 0) + 1
    return counts
