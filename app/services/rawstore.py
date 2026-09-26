"""Raw document store (brief Section 4, principle 6, Section 7 lineage).

Every file is saved exactly as received, BEFORE anything reads it, under
data/raw/<source>/<IST date>/, with its URL, published time, fetch time and SHA-256 hash.
Files are never overwritten: a changed file becomes a new version beside the old one, and
the old version is marked "superseded" (14.5). An identical re-download adds no new copy;
it is recorded in fetch_log as "unchanged".
"""

import gzip
import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from app import paths
from app.timeutil import IST, fmt_ist, to_iso

STATUSES = ("original", "revised", "corrected", "cancelled", "superseded")


@dataclass
class Saved:
    document_id: int
    version: int
    outcome: str        # new | new_version | unchanged
    content_hash: str


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_stem(url: str, hint: str | None) -> tuple[str, str]:
    name = hint or PurePosixPath(urlparse(url).path).name or "document"
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, "bin"
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem)[:60].strip("_") or "document"
    ext = re.sub(r"[^A-Za-z0-9]+", "", ext)[:8].lower() or "bin"
    return stem, ext


def latest_version(conn: sqlite3.Connection, url: str):
    return conn.execute("SELECT * FROM documents WHERE url = ? ORDER BY version DESC, id DESC "
                        "LIMIT 1", (url,)).fetchone()


def save(conn: sqlite3.Connection, *, source: str, url: str, content: bytes, doc_type: str,
         fetched_at: datetime, licence: str, company: str | None = None,
         published_at: datetime | None = None, filename_hint: str | None = None,
         compress: bool = False) -> Saved:
    """Store a raw file and register it. The caller owns the transaction."""
    digest = sha256(content)
    prior = latest_version(conn, url)
    if prior is not None and prior["content_hash"] == digest:
        return Saved(prior["id"], prior["version"], "unchanged", digest)

    stem, ext = _safe_stem(url, filename_hint)
    folder = paths.raw_dir() / source / fetched_at.astimezone(IST).strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{stem}_{digest[:12]}.{ext}{'.gz' if compress else ''}"
    if not target.exists():  # same name means same content: never overwrite
        with open(target, "xb") as fh:
            fh.write(gzip.compress(content, mtime=0) if compress else content)

    version = 1 if prior is None else prior["version"] + 1
    doc_id = conn.execute(
        "INSERT INTO documents (source, url, type, company, published_at, fetched_at, "
        "content_hash, file_path, version, licence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (source, url, doc_type, company, to_iso(published_at) if published_at else None,
         to_iso(fetched_at), digest, target.relative_to(paths.data_dir()).as_posix(),
         version, licence)).lastrowid
    if prior is not None:
        set_status(conn, prior["id"], "superseded", "system",
                   f"A newer version (version {version}) of this file was downloaded on "
                   f"{fmt_ist(fetched_at)}.", superseded_by=doc_id)
    return Saved(doc_id, version, "new" if prior is None else "new_version", digest)


def read(file_path: str) -> bytes:
    """The original bytes of a stored file (stored feed snapshots are gzip-compressed)."""
    full = paths.data_dir() / Path(file_path)
    data = full.read_bytes()
    return gzip.decompress(data) if full.suffix == ".gz" else data


def log_fetch(conn: sqlite3.Connection, adapter: str, url: str, fetched_at: datetime,
              outcome: str, *, http_status: int | None = None, content_hash: str | None = None,
              document_id: int | None = None, etag: str | None = None,
              last_modified: str | None = None, message: str | None = None) -> None:
    conn.execute(
        "INSERT INTO fetch_log (adapter, url, fetched_at, http_status, outcome, content_hash, "
        "document_id, etag, last_modified, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (adapter, url, to_iso(fetched_at), http_status, outcome, content_hash, document_id,
         etag, last_modified, message))


def validators(conn: sqlite3.Connection, url: str) -> tuple[str | None, str | None]:
    """ETag / Last-Modified from the last good download, for "only if changed" requests."""
    r = conn.execute("SELECT etag, last_modified FROM fetch_log WHERE url = ? AND outcome IN "
                     "('new', 'new_version', 'unchanged') ORDER BY id DESC LIMIT 1",
                     (url,)).fetchone()
    return (r["etag"], r["last_modified"]) if r else (None, None)


def set_status(conn: sqlite3.Connection, document_id: int, status: str, set_by: str,
               reason: str, superseded_by: int | None = None) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status}")
    conn.execute("INSERT INTO document_status (document_id, status, superseded_by, reason, "
                 "set_by) VALUES (?, ?, ?, ?, ?)",
                 (document_id, status, superseded_by, reason, set_by))


def current_status(conn: sqlite3.Connection, document_id: int) -> dict:
    r = conn.execute("SELECT status, superseded_by, reason, set_by, created_at FROM "
                     "document_status WHERE document_id = ? ORDER BY id DESC LIMIT 1",
                     (document_id,)).fetchone()
    if r is None:
        return {"status": "original", "superseded_by": None, "reason": None, "set_by": None,
                "created_at": None}
    return dict(r)
