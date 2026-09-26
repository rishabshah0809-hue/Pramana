"""Document Viewer support: look up stored documents, open the original bytes, re-fetch
(which appends a new version, never overwrites), manual uploads and 14.5 status changes.

Rendering helpers turn a stored file into something the screen can show: PDF pages as
images, the files inside a zip, XBRL facts as a table, CSV rows, or a feed's items.
"""

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from defusedxml import ElementTree as SafeET

from app.adapters.feeds import parse_rss
from app.adapters.polite import FetchFailed, PoliteClient
from app.adapters.registry import MANUAL_FILING_SOURCE
from app.errors import FriendlyError
from app.services import audit, filings, rawstore
from app.store import db
from app.timeutil import from_iso, now_utc

MAX_ZIP_MEMBER = 40 * 1024 * 1024
MANUAL_LICENCE = ("Downloaded and uploaded by you from the exchange website (personal use). "
                  "Published time as entered by you.")


def get(document_id: int) -> dict | None:
    conn = db.connect()
    try:
        r = conn.execute("SELECT d.*, c.name AS company_name FROM documents d LEFT JOIN companies "
                         "c ON c.isin = d.company WHERE d.id = ?", (document_id,)).fetchone()
        if r is None:
            return None
        out = dict(r)
        out["status"] = rawstore.current_status(conn, document_id)
        out["filing"] = None
        f = conn.execute("SELECT exchange, feed, category, subject, published_raw, company_name_raw "
                         "FROM filings WHERE url = ? ORDER BY id LIMIT 1",
                         (out["url"],)).fetchone()
        if f is not None:
            out["filing"] = dict(f)
        return out
    finally:
        conn.close()


def versions(url: str) -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute("SELECT id, version, fetched_at, content_hash FROM documents "
                            "WHERE url = ? ORDER BY version", (url,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def history(document_id: int) -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM document_status WHERE document_id = ? ORDER BY id",
                            (document_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def recent(limit: int = 200, company: str | None = None) -> list[dict]:
    conn = db.connect()
    try:
        where, args = ("WHERE d.type != 'feed_snapshot'", [])
        if company:
            where += " AND d.company = ?"
            args.append(company)
        rows = conn.execute(
            f"SELECT d.id, d.source, d.type, d.url, d.published_at, d.fetched_at, d.version, "
            f"c.name AS company_name FROM documents d LEFT JOIN companies c ON c.isin = d.company "
            f"{where} ORDER BY d.id DESC LIMIT ?", (*args, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def content(doc: dict) -> bytes:
    try:
        return rawstore.read(doc["file_path"])
    except FileNotFoundError:
        raise FriendlyError("The stored file for this document is missing from data/raw/.",
                            "Restore data/raw/ from your backup. If you have none, use "
                            "'Re-fetch from source' to download it again.")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def kind_of(data: bytes, name: str = "") -> str:
    head = data[:1024].lstrip()
    lower = name.lower()
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        return "zip"
    if head.startswith(b"<?xml") or head.startswith(b"<rss") or head.startswith(b"<xbrl") \
            or head.startswith(b"\xef\xbb\xbf<?xml") or lower.endswith(".xml"):
        return "xml"
    if lower.endswith(".csv"):
        return "csv"
    if b"<html" in head.lower() or lower.endswith((".htm", ".html")):
        return "html"
    return "other"


def pdf_page_count(data: bytes) -> int:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as exc:  # noqa: BLE001
        raise FriendlyError("This PDF could not be opened (it may be damaged or protected).",
                            "Use 'Download original' to open it in your own PDF reader.") from exc
    try:
        return len(pdf)
    finally:
        pdf.close()


def pdf_pages_png(data: bytes, first: int, count: int, scale: float = 1.4) -> list[bytes]:
    """Pages first..first+count-1 (1-based) as PNG images."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    out = []
    try:
        for i in range(first - 1, min(first - 1 + count, len(pdf))):
            image = pdf[i].render(scale=scale).to_pil()
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            out.append(buf.getvalue())
    finally:
        pdf.close()
    return out


def zip_members(data: bytes) -> list[dict]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return [{"name": i.filename, "size": i.file_size} for i in z.infolist()
                    if not i.is_dir()]
    except zipfile.BadZipFile as exc:
        raise FriendlyError("This zip file could not be opened (it may be damaged).",
                            "Use 'Download original' to open it on your computer.") from exc


def zip_member(data: bytes, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info = z.getinfo(name)
        if info.file_size > MAX_ZIP_MEMBER:
            raise FriendlyError("This file inside the zip is too large to show here.",
                                "Use 'Download original' to open it on your computer.")
        return z.read(info)


def xml_facts(data: bytes, limit: int = 3000) -> list[dict]:
    """XBRL facts as rows (element, context, value); other XML as element/text rows."""
    try:
        root = SafeET.fromstring(data)
    except Exception as exc:  # noqa: BLE001
        raise FriendlyError("This XML file could not be read.",
                            "Use 'Download original' to open it on your computer.") from exc
    rows = []
    skip = ("context", "unit", "schemaRef")
    # XBRL facts sit directly under the root; context and unit blocks are skipped whole.
    elements = list(root) if root.tag.rsplit("}", 1)[-1] == "xbrl" else root.iter()
    for el in elements:
        name = el.tag.rsplit("}", 1)[-1]
        if name in skip or el is root:
            continue
        text = (el.text or "").strip()
        if text and not len(el):
            rows.append({"element": name, "context": el.get("contextRef") or "", "value": text})
        if len(rows) >= limit:
            break
    return rows


def feed_items(data: bytes, label: str) -> list[dict]:
    items, _ = parse_rss(data, label)
    return [{"company": i.title, "subject": i.description, "published": i.pub_raw,
             "BSE code": i.scripcode, "link": i.link} for i in items]


def csv_rows(data: bytes, limit: int = 2000) -> list[list[str]]:
    text = data.decode("utf-8-sig", errors="replace")
    return list(csv.reader(io.StringIO(text)))[:limit]


def html_text(data: bytes) -> str:
    """Plain text of an HTML filing (shown as text; the page's own code is never run)."""
    import re
    from html import unescape

    text = data.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def filename(doc: dict) -> str:
    return PurePosixPath(doc["file_path"]).name.removesuffix(".gz")


def _original_name(doc: dict) -> str:
    """'report_1a2b3c4d5e6f.pdf' -> 'report.pdf' (the hash is added again on save)."""
    stem, _, ext = filename(doc).rpartition(".")
    return stem.rsplit("_", 1)[0] + "." + ext


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

@dataclass
class RefetchResult:
    outcome: str      # new_version | unchanged | not_modified
    message: str
    document_id: int


def refetch(document_id: int, client=None) -> RefetchResult:
    """Download the document's URL again. A changed file is saved as a new version beside
    the old one; an identical one only adds an "unchanged" line to the fetch log."""
    doc = get(document_id)
    if doc is None:
        raise FriendlyError("That document no longer exists in the register.", "Pick another.")
    if not doc["url"].startswith("http"):
        raise FriendlyError("This document was uploaded by you, so there is nothing to re-fetch.",
                            "Upload a newer copy instead if you have one.")
    client = client or PoliteClient()
    fetched = now_utc()
    try:
        resp = client.get(doc["url"])
    except FetchFailed as exc:
        conn = db.connect()
        try:
            with conn:
                rawstore.log_fetch(conn, doc["source"], doc["url"], fetched, "failed",
                                   http_status=exc.http_status, message=exc.message)
        finally:
            conn.close()
        raise FriendlyError(exc.message, "The stored copy is still here. Try again later.")
    conn = db.connect()
    try:
        with conn:
            saved = rawstore.save(
                conn, source=doc["source"], url=doc["url"], content=resp.content,
                doc_type=doc["type"], fetched_at=fetched, company=doc["company"],
                licence=doc["licence"] or "",
                published_at=from_iso(doc["published_at"]) if doc["published_at"] else None,
                filename_hint=_original_name(doc), compress=doc["file_path"].endswith(".gz"))
            rawstore.log_fetch(conn, doc["source"], doc["url"], fetched, saved.outcome,
                               http_status=resp.http_status, content_hash=saved.content_hash,
                               document_id=saved.document_id, etag=resp.etag,
                               last_modified=resp.last_modified)
            audit.log(conn, "user", "document_refetch", f"documents:{document_id}",
                      after={"outcome": saved.outcome, "document_id": saved.document_id})
    finally:
        conn.close()
    if saved.outcome == "unchanged":
        return RefetchResult("unchanged", "Downloaded again: the file is identical to the stored "
                             "copy, so no new version was needed. The check is recorded in the "
                             "fetch log.", saved.document_id)
    if doc["type"] == "shareholding":
        _maybe_store_shareholding(saved.document_id, resp.content, doc["company"])
    return RefetchResult("new_version", f"The file has changed. Saved as version {saved.version} "
                         f"beside the older version, which is now marked 'superseded'.",
                         saved.document_id)


def _maybe_store_shareholding(document_id: int, data: bytes, isin: str | None) -> int:
    from app.adapters import shareholding

    if not shareholding.is_shareholding_xbrl(data):
        return 0
    conn = db.connect()
    try:
        with conn:
            return shareholding.store_shareholding(conn, document_id, data, isin)
    finally:
        conn.close()


def add_manual(data: bytes, file_name: str, company: str, category: str, subject: str,
               source_url: str | None, published_at: datetime | None) -> tuple[int, str]:
    """A filing the owner downloaded from the exchange website and uploads here."""
    if not data:
        raise FriendlyError("The uploaded file is empty.", "Choose the file again.")
    if category not in filings.CATEGORY_LABELS:
        raise FriendlyError("Please choose what kind of filing this is.", "Pick a type.")
    url = (source_url or "").strip() or f"manual-upload:{PurePosixPath(file_name).name}"
    if url.startswith("http") and not url.startswith("https://"):
        url = "https://" + url.split("://", 1)[1]
    conn = db.connect()
    try:
        with conn:
            if conn.execute("SELECT 1 FROM companies WHERE isin = ?", (company,)).fetchone() is None:
                raise FriendlyError("That company isn't in your company list.", "Pick another.")
            saved = rawstore.save(conn, source=MANUAL_FILING_SOURCE, url=url, content=data,
                                  doc_type=category, fetched_at=now_utc(), company=company,
                                  published_at=published_at, licence=MANUAL_LICENCE,
                                  filename_hint=PurePosixPath(file_name).name)
            if saved.outcome != "unchanged":
                status = filings.status_from_subject(subject)
                if status:
                    rawstore.set_status(conn, saved.document_id, status[0], "system", status[1])
            audit.log(conn, "user", "document_upload", f"documents:{saved.document_id}",
                      after={"file": file_name, "company": company, "category": category,
                             "subject": subject, "outcome": saved.outcome})
    finally:
        conn.close()
    note = ""
    if category == "shareholding":
        try:
            n = _maybe_store_shareholding(saved.document_id, data, company)
            note = f" {n} shareholding figure(s) read from it." if n else ""
        except FriendlyError as exc:
            note = f" The file was stored, but its figures could not be read: {exc.message}"
    if saved.outcome == "unchanged":
        return saved.document_id, "This exact file was already stored; no new copy was made."
    return saved.document_id, f"Stored as version {saved.version}.{note}"


def set_status(document_id: int, status: str, reason: str, superseded_by: int | None = None):
    """An owner-made 14.5 status change. Appended, never edited; recorded in the audit log."""
    if not reason.strip():
        raise FriendlyError("Please say why you are changing the status.", "Add a short note.")
    conn = db.connect()
    try:
        with conn:
            before = rawstore.current_status(conn, document_id)
            if superseded_by is not None and conn.execute(
                    "SELECT 1 FROM documents WHERE id = ?", (superseded_by,)).fetchone() is None:
                raise FriendlyError(f"There is no document number {superseded_by}.",
                                    "Check the number shown on the newer document.")
            rawstore.set_status(conn, document_id, status, "user", reason.strip(), superseded_by)
            audit.log(conn, "user", "document_status", f"documents:{document_id}",
                      before={"status": before["status"]},
                      after={"status": status, "superseded_by": superseded_by,
                             "reason": reason.strip()})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Highlighting a cited passage on the original page (M3)
# ---------------------------------------------------------------------------

def _pdf_bytes(data: bytes, member: str | None) -> bytes:
    return zip_member(data, member) if member else data


def highlight_png(data: bytes, member: str | None, page: int, start: int, end: int,
                  scale: float = 1.6) -> bytes | None:
    """The page as an image with characters start..end of its extracted text marked in
    yellow. Offsets are the same ones the passage was cut with (same text engine)."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw

    raw = _pdf_bytes(data, member)
    if kind_of(raw, member or "") != "pdf":
        return None
    pdf = pdfium.PdfDocument(raw)
    try:
        pg = pdf[page - 1]
        _, height = pg.get_size()
        tp = pg.get_textpage()
        n = tp.count_rects(start, max(end - start, 1))
        rects = [tp.get_rect(i) for i in range(n)]
        tp.close()
        image = pg.render(scale=scale).to_pil().convert("RGBA")
    finally:
        pdf.close()
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for left, bottom, right, top in rects:
        draw.rectangle([left * scale - 2, (height - top) * scale - 2, right * scale + 2,
                        (height - bottom) * scale + 2], fill=(255, 200, 0, 110))
    out = io.BytesIO()
    Image.alpha_composite(image, overlay).convert("RGB").save(out, format="PNG")
    return out.getvalue()
