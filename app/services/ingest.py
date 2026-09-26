"""One check of a feed adapter: download each feed, store it raw, index its items, then
download the filing files for watchlist companies (owner's decision, 26 Sep 2026).

Every failure is caught and recorded as a plain-English fetch status (14.3); one broken
feed never stops the others, and nothing here ever raises into the dashboard.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from app.adapters.feeds import (Feed, FeedFormatError, FeedItem, company_from_title,
                                parse_published, parse_rss)
from app.adapters.polite import FetchFailed, PoliteClient
from app.adapters.registry import SOURCES
from app.config import load_config
from app.errors import FriendlyError, report
from app.services import filings, health, rawstore
from app.services.matching import Matcher, norm_name
from app.store import db
from app.timeutil import from_iso, now_utc, to_iso

log = logging.getLogger("mosaic.ingest")
MAX_FAILED_TRIES = 3  # a filing file that failed this often is not retried automatically


@dataclass
class RunSummary:
    ran: bool
    status: str           # ok | missing | blocked | timeout | error | skipped
    message: str
    new_items: int = 0
    files: int = 0


def item_key(feed: Feed, item: FeedItem) -> str:
    raw = "|".join([feed.id, item.title, item.link or "", item.description or "",
                    item.pub_raw or "", item.scripcode or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def start_run(adapter: str, started) -> int | None:
    conn = db.connect()
    try:
        busy = conn.execute(
            "SELECT 1 FROM adapter_runs WHERE adapter = ? AND fetch_status = 'running' "
            "AND started_at > ?", (adapter, to_iso(started - timedelta(minutes=10)))).fetchone()
        if busy:
            return None
        with conn:
            return conn.execute("INSERT INTO adapter_runs (adapter, started_at, fetch_status) "
                                "VALUES (?, ?, 'running')", (adapter, to_iso(started))).lastrowid
    finally:
        conn.close()


def finish_run(adapter: str, run_id: int, status: str, received: int, valid: int,
               message: str) -> None:
    finished = now_utc()
    conn = db.connect()
    try:
        with conn:
            conn.execute("UPDATE adapter_runs SET finished_at = ?, fetch_status = ?, "
                         "items_received = ?, items_valid = ?, message = ? WHERE id = ?",
                         (to_iso(finished), status, received, valid, message, run_id))
    finally:
        conn.close()
    health.record_quality(adapter, now=finished)


def _fetch_feed(client, adapter: str, feed: Feed, matcher: Matcher, classify, keep, fetched):
    """Returns (new_items, received, valid). Raises FetchFailed / FeedFormatError."""
    conn = db.connect()
    try:
        etag, modified = rawstore.validators(conn, feed.url)
    finally:
        conn.close()
    try:
        resp = client.get(feed.url, etag=etag, last_modified=modified)
    except FetchFailed as exc:
        conn = db.connect()
        try:
            with conn:
                rawstore.log_fetch(conn, adapter, feed.url, now_utc(), "failed",
                                   http_status=exc.http_status, message=exc.message)
        finally:
            conn.close()
        raise
    conn = db.connect()
    try:
        with conn:
            if resp.not_modified:
                rawstore.log_fetch(conn, adapter, feed.url, fetched, "not_modified",
                                   http_status=304, etag=resp.etag,
                                   last_modified=resp.last_modified)
                return 0, 0, 0
            saved = rawstore.save(conn, source=adapter, url=feed.url, content=resp.content,
                                  doc_type="feed_snapshot", fetched_at=fetched,
                                  licence=SOURCES[adapter].terms_status,
                                  filename_hint=f"{feed.id}.xml", compress=True)
            rawstore.log_fetch(conn, adapter, feed.url, fetched, saved.outcome, http_status=200,
                               content_hash=saved.content_hash, document_id=saved.document_id,
                               etag=resp.etag, last_modified=resp.last_modified)
        # Parse only after the raw file is safely stored.
        items, received = parse_rss(resp.content, feed.label)
        new = 0
        with conn:
            for it in items:
                if keep is not None and not keep(feed, it, matcher):
                    continue
                name = company_from_title(it.title)
                isin, method = matcher.match(bse_code=it.scripcode, name=name)
                category = feed.category or classify(it.description or "")
                published = parse_published(it.pub_raw)
                cur = conn.execute(
                    "INSERT OR IGNORE INTO filings (adapter, exchange, feed, category, company, "
                    "match_method, company_name_raw, company_name_norm, exchange_code, subject, "
                    "url, published_at, published_raw, feed_document_id, item_key, first_seen_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (adapter, feed.exchange, feed.id, category, isin, method, it.title,
                     norm_name(name), it.scripcode, it.description, it.link,
                     to_iso(published) if published else None, it.pub_raw, saved.document_id,
                     item_key(feed, it), to_iso(fetched)))
                new += cur.rowcount
        return new, received, len(items)
    finally:
        conn.close()


def download_pending(client, adapter: str, on_file: Callable | None = None,
                     limit: int | None = None) -> tuple[int, list[str]]:
    """Download filing files for watchlist companies that aren't stored yet.
    Returns (files saved, plain-English problems)."""
    cfg = load_config().get("rate_limits", {}).get("exchanges", {}) or {}
    limit = limit if limit is not None else int(cfg.get("attachments_per_run", 25))
    pending = filings.pending_downloads(adapter, MAX_FAILED_TRIES)[:limit]
    saved_count, problems = 0, []
    for f in pending:
        fetched = now_utc()
        try:
            resp = client.get(f["url"])
        except (FetchFailed, FriendlyError) as exc:
            msg = getattr(exc, "message", str(exc))
            conn = db.connect()
            try:
                with conn:
                    rawstore.log_fetch(conn, adapter, f["url"], fetched, "failed",
                                       http_status=getattr(exc, "http_status", None), message=msg)
            finally:
                conn.close()
            problems.append(f"{f['company_name_raw']}: {msg}")
            continue
        conn = db.connect()
        try:
            with conn:
                published = f["published_at"]
                saved = rawstore.save(
                    conn, source=adapter, url=f["url"], content=resp.content,
                    doc_type=f["category"], fetched_at=fetched, company=f["isin"],
                    licence=SOURCES[adapter].terms_status,
                    published_at=from_iso(published) if published else None)
                rawstore.log_fetch(conn, adapter, f["url"], fetched, saved.outcome,
                                   http_status=resp.http_status, content_hash=saved.content_hash,
                                   document_id=saved.document_id, etag=resp.etag,
                                   last_modified=resp.last_modified)
                if saved.outcome != "unchanged":
                    status = filings.status_from_subject(f["subject"])
                    if status:
                        rawstore.set_status(conn, saved.document_id, status[0], "system",
                                            status[1])
            if on_file is not None and saved.outcome != "unchanged":
                try:
                    on_file(saved.document_id, resp.content, f)
                except FriendlyError as exc:
                    problems.append(f"{f['company_name_raw']}: {exc.message}")
                except Exception as exc:  # noqa: BLE001 — the raw file is safe; log and go on
                    problems.append(f"{f['company_name_raw']}: {report(exc, log).message}")
            saved_count += saved.outcome != "unchanged"
        finally:
            conn.close()
    return saved_count, problems


def run_feeds(adapter: str, feeds: list[Feed], classify: Callable[[str], str],
              keep: Callable | None = None, on_file: Callable | None = None, client=None,
              download: bool = True, now=None) -> RunSummary:
    started = now or now_utc()
    run_id = start_run(adapter, started)
    if run_id is None:
        return RunSummary(False, "skipped", "A check of this source is already running.")
    received = valid = new_items = files = 0
    failures: list[tuple[Feed, str, str]] = []
    try:
        client = client or PoliteClient()
        conn = db.connect()
        try:
            matcher = Matcher(conn)
        finally:
            conn.close()
        for feed in feeds:
            try:
                n, r, v = _fetch_feed(client, adapter, feed, matcher, classify, keep, now_utc())
                new_items, received, valid = new_items + n, received + r, valid + v
            except FetchFailed as exc:
                failures.append((feed, exc.status, exc.message))
            except FeedFormatError as exc:
                failures.append((feed, "error", exc.message))
            except Exception as exc:  # noqa: BLE001 — one broken feed never stops the rest
                failures.append((feed, "error", report(exc, log).message))
        problems: list[str] = []
        if download and len(failures) < len(feeds):
            files, problems = download_pending(client, adapter, on_file)
    except Exception as exc:  # noqa: BLE001 — never raise into the scheduler or dashboard
        err = report(exc, log)
        finish_run(adapter, run_id, "error", received, valid, err.message)
        return RunSummary(True, "error", err.message)

    ok_feeds = len(feeds) - len(failures)
    parts = [f"{ok_feeds} of {len(feeds)} feeds checked: {new_items} new item(s)"
             + (f", {files} filing file(s) saved" if files else "") + "."]
    parts += [f"{feed.label}: {msg}" for feed, _, msg in failures]
    if problems:
        parts.append(f"{len(problems)} filing file(s) could not be downloaded, e.g. "
                     f"{problems[0]}")
    status = "ok" if not failures else failures[0][1]
    message = " ".join(parts)
    finish_run(adapter, run_id, status, received, valid, message)
    return RunSummary(True, status, message, new_items, files)
