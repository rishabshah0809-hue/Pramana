"""Filings: company timelines, pending file downloads, corrections (14.5) and content age.

A filing is linked to a company when it is stored (exact IDs or exact names, 14.4). Items
that couldn't be linked then — for example before BSE's list was uploaded — are linked
when shown, using the same exact rules. Nothing is ever guessed.
"""

import json
import re
from datetime import datetime, timedelta

from app.services.matching import Matcher, norm_name
from app.store import db
from app.timeutil import from_iso

CATEGORY_LABELS = {
    "results": "Results", "board_meeting": "Board meeting", "presentation": "Investor presentation",
    "transcript": "Earnings-call transcript", "order": "Order won", "rating": "Credit rating",
    "shareholding": "Shareholding pattern", "pledge": "Pledge / encumbrance",
    "insider": "Insider trading", "sast": "Substantial acquisition (SAST)",
    "annual_report": "Annual report", "other": "Other announcement",
}

# Fixed keyword rules on the exchange's own subject line, checked in this order. No AI.
_RULES = [
    ("transcript", ("transcript",)),
    ("presentation", ("investor presentation", "analyst presentation", "earnings presentation",
                      "investors presentation")),
    ("insider", ("regulation 7(2)", "regulation 7 (2)", "reg. 7(2)", "insider trading",
                 "sebi (prohibition of insider trading)")),
    ("pledge", ("encumbrance", "pledge", "regulation 31")),
    ("sast", ("regulation 29", "substantial acquisition", "sast")),
    ("shareholding", ("shareholding pattern",)),
    ("board_meeting", ("board meeting", "outcome of board")),
    ("results", ("financial result", "quarterly result", "annual result", "audited result",
                 "unaudited result", "results for the quarter")),
    ("rating", ("credit rating", "rating agency", "revision in rating", "rating action")),
    ("order", ("bagging", "receipt of order", "receiving of order", "order received",
               "awarding of order", "order win", "letter of award", "work order",
               "orders/contracts")),
    ("annual_report", ("annual report",)),
]


def classify(subject: str) -> str:
    s = " ".join((subject or "").split()).casefold()
    for category, words in _RULES:
        if any(w in s for w in words):
            return category
    return "other"


_STATUS_WORDS = [
    ("cancelled", re.compile(r"\b(cancell?ed|cancellation|withdrawn|withdrawal)\b")),
    ("corrected", re.compile(r"\b(corrigendum|correction|corrected|rectified|erratum)\b")),
    ("revised", re.compile(r"\b(revised|revision|modified|amended)\b")),
]


def status_from_subject(subject: str | None):
    """14.5 status from the exchange's own words. Returns (status, reason) or None."""
    s = (subject or "").casefold()
    for status, pattern in _STATUS_WORDS:
        m = pattern.search(s)
        if m:
            return status, f"The exchange's subject line says '{m.group(0)}': \"{subject}\""
    return None


def _company_clause(conn, isin: str) -> tuple[str, tuple]:
    c = conn.execute("SELECT name, bse_code, aliases FROM companies WHERE isin = ?",
                     (isin,)).fetchone()
    if c is None:
        return "f.company = ?", (isin,)
    matcher = Matcher(conn)
    names = [n for n in {norm_name(c["name"])} if n and matcher.name_is_unique(n)]
    clause = "f.company = ?"
    args: list = [isin]
    if c["bse_code"]:
        clause += " OR (f.company IS NULL AND f.exchange_code = ?)"
        args.append(c["bse_code"])
    for n in names:
        clause += " OR (f.company IS NULL AND f.exchange_code IS NULL AND f.company_name_norm = ?)"
        args.append(n)
    return f"({clause})", tuple(args)


def company_filings(isin: str, category: str | None = None, limit: int = 300) -> list[dict]:
    """Newest first. Each row carries the stored file's document id if it has been downloaded."""
    conn = db.connect()
    try:
        clause, args = _company_clause(conn, isin)
        extra, more = ("AND f.category = ?", (category,)) if category else ("", ())
        rows = conn.execute(
            f"SELECT f.*, (SELECT d.id FROM documents d WHERE d.url = f.url "
            f"ORDER BY d.version DESC LIMIT 1) AS document_id, (SELECT l.message FROM fetch_log l "
            f"WHERE l.url = f.url AND l.outcome = 'failed' ORDER BY l.id DESC LIMIT 1) "
            f"AS last_failure FROM filings f WHERE {clause} "
            f"{extra} ORDER BY COALESCE(f.published_at, f.first_seen_at) DESC, f.id DESC LIMIT ?",
            (*args, *more, limit)).fetchall()
        manual = conn.execute(
            "SELECT d.*, (SELECT a.after FROM audit_log a WHERE a.action = 'document_upload' "
            "AND a.object = 'documents:' || d.id ORDER BY a.id LIMIT 1) AS upload_note "
            "FROM documents d WHERE d.company = ? AND d.source = 'manual_upload' "
            "ORDER BY d.id DESC", (isin,)).fetchall()
    finally:
        conn.close()
    out = [dict(r) | {"kind": "feed"} for r in rows]
    for d in manual:
        if category and d["type"] != category:
            continue
        try:
            subject = json.loads(d["upload_note"] or "{}").get("subject")
        except ValueError:
            subject = None
        out.append({"kind": "manual", "category": d["type"] or "other", "exchange": None,
                    "subject": subject or d["url"].removeprefix("manual-upload:"),
                    "published_at": d["published_at"], "first_seen_at": d["fetched_at"],
                    "url": d["url"], "document_id": d["id"], "published_raw": None,
                    "last_failure": None})
    out.sort(key=lambda r: r["published_at"] or r["first_seen_at"], reverse=True)
    return out[:limit]


def pending_downloads(adapter: str, max_failed: int) -> list[dict]:
    """Filing files for watchlist companies that haven't been stored yet, newest first."""
    conn = db.connect()
    try:
        out, seen = [], set()
        for w in conn.execute("SELECT company FROM watchlist").fetchall():
            clause, args = _company_clause(conn, w["company"])
            rows = conn.execute(
                f"SELECT f.* FROM filings f WHERE {clause} AND f.adapter = ? "
                f"AND f.url IS NOT NULL AND f.url LIKE 'http%' "
                f"AND NOT EXISTS (SELECT 1 FROM documents d WHERE d.url = f.url) "
                f"AND (SELECT COUNT(*) FROM fetch_log l WHERE l.url = f.url "
                f"     AND l.outcome = 'failed') < ? "
                f"ORDER BY COALESCE(f.published_at, f.first_seen_at) DESC",
                (*args, adapter, max_failed)).fetchall()
            for r in rows:
                if r["url"] not in seen:
                    seen.add(r["url"])
                    out.append(dict(r) | {"isin": w["company"]})
    finally:
        conn.close()
    out.sort(key=lambda r: r["published_at"] or r["first_seen_at"], reverse=True)
    return out


def unmatched_count(adapter: str) -> int:
    conn = db.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM filings WHERE adapter = ? AND company IS NULL",
                            (adapter,)).fetchone()[0]
    finally:
        conn.close()


def content_status(adapter: str, now: datetime, max_days: int) -> tuple[str, str]:
    """Content age (14.3) from the newest item's published time."""
    conn = db.connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM filings WHERE adapter = ?",
                             (adapter,)).fetchone()[0]
        newest = conn.execute("SELECT MAX(published_at) FROM filings WHERE adapter = ?",
                              (adapter,)).fetchone()[0]
    finally:
        conn.close()
    if not total:
        return "no_data", "No feed items stored yet"
    if newest is None:
        return "timestamp_unknown", f"{total} items stored; the feed gives no published times"
    age = max(now - from_iso(newest), timedelta(0))  # a slightly fast exchange clock
    hours = age.total_seconds() / 3600
    when = f"{hours:.0f} hour(s)" if hours < 48 else f"{age.days} days"
    if age.days < max_days:
        return "current", f"Newest item published {when} ago"
    return "stale", f"Newest item published {when} ago"
