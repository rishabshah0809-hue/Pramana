"""Runs the Section 6 steps in order for queued work, and keeps the queue moving within the
free-tier limits (brief Section 3).

Queue order: documents of companies currently on the watchlist first, then by filing type
(ai.processing.categories order), then newest first. When a daily limit is reached the run
stops, the work stays queued, and it resumes after the limit resets. Nothing crashes.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.adapters.registry import SOURCES
from app.config import load_config
from app.errors import report
from app.llm import client
from app.processing import chunk, crosscheck, extract, label, structured_signals, summarize, validate
from app.services import ingest, rawstore
from app.services.matching import Matcher
from app.store import db
from app.timeutil import now_utc, to_iso

log = logging.getLogger("mosaic.pipeline")
QUEUE_ID = "ai_queue"


@dataclass
class QueueRun:
    status: str = "ok"                  # ok | waiting | error
    message: str = ""
    calls: int = 0
    signals: dict = field(default_factory=lambda: {"verified": 0, "needs_review": 0,
                                                   "unverified": 0})
    rejected: int = 0
    summaries: int = 0
    structured: dict = field(default_factory=dict)
    resume_at: datetime | None = None


def _categories() -> list[str]:
    return list(load_config()["ai"]["processing"].get("categories", []))


def _priority_sql(cats: list[str]) -> str:
    rank = " ".join(f"WHEN '{c}' THEN {i}" for i, c in enumerate(cats) if c.isidentifier())
    return (f"(CASE WHEN d.company IN (SELECT company FROM watchlist) THEN 0 ELSE 1 END), "
            f"(CASE d.type {rank} ELSE 99 END), COALESCE(d.published_at, d.fetched_at) DESC")


def _eligible_docs_sql(cats: list[str]) -> tuple[str, list]:
    marks = ",".join("?" * len(cats))
    return (f"d.company IS NOT NULL AND d.type IN ({marks}) AND d.source IN "
            f"({','.join('?' * len(PUBLIC))}) AND NOT EXISTS (SELECT 1 FROM documents n WHERE "
            f"n.url = d.url AND n.version > d.version)", [*cats, *PUBLIC])


PUBLIC = sorted(client.PUBLIC_SOURCES)


def documents_to_chunk(conn, cats) -> list[int]:
    where, args = _eligible_docs_sql(cats)
    return [r["id"] for r in conn.execute(
        f"SELECT d.id FROM documents d WHERE {where} AND NOT EXISTS (SELECT 1 FROM passages p "
        f"WHERE p.document_id = d.id AND p.extraction_version = ?) ORDER BY {_priority_sql(cats)}",
        (*args, chunk.EXTRACTION_VERSION))]


def pending_passages(conn, cats, prompt_version: str, limit: int | None = None) -> list:
    where, args = _eligible_docs_sql(cats)
    sql = (f"SELECT p.*, d.company, d.published_at, d.source, d.type AS doc_type, d.url "
           f"FROM passages p JOIN documents d ON d.id = p.document_id WHERE {where} "
           f"AND p.kind = 'text' AND NOT EXISTS (SELECT 1 FROM passage_extractions e WHERE "
           f"e.passage_id = p.id AND e.prompt_version = ? AND e.outcome IN ('done', "
           f"'invalid_output')) ORDER BY {_priority_sql(cats)}, p.member, p.page, p.char_start")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, (*args, prompt_version)).fetchall()


def _record_extraction(passage_id, version, call_id, outcome, n):
    conn = db.connect()
    try:
        with conn:
            conn.execute("INSERT INTO passage_extractions (passage_id, prompt_version, call_id, "
                         "outcome, items_found) VALUES (?, ?, ?, ?, ?)",
                         (passage_id, version, call_id, outcome, n))
    finally:
        conn.close()


def _save_rejection(p, raw_item, reasons, suggestion, result) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO extraction_rejections (document_id, passage_id, item_json, reasons, "
                "suggested_company, provider, model, prompt_version, call_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (p["document_id"], p["id"], json.dumps(raw_item, ensure_ascii=False),
                 json.dumps(reasons), suggestion, result.provider, result.model,
                 result.prompt.label, result.call_id))
    finally:
        conn.close()


def save_signal(p, v: validate.Validation, provider: str, model: str, prompt_label: str,
                call_id: int | None, cc: crosscheck.CrossCheck) -> int | None:
    status, reason = label.label(cc.answer)
    item = v.item
    s, e = v.span
    key = f"ai:{p['id']}:{s}:{e}:{item.signal_type}:{v.company}"
    conn = db.connect()
    try:
        with conn:
            if conn.execute("SELECT 1 FROM signals WHERE dedupe_key = ?", (key,)).fetchone():
                return None
            sid = conn.execute(
                "INSERT INTO signals (company, type, direction, strength, signal_date, claim_text, "
                "passage_id, status, model, prompt_version, document_id, claim_type, quote, "
                "quote_start, quote_end, source_tier, cross_check, provider, call_id, dedupe_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (v.company, item.signal_type, item.direction, item.strength,
                 (p["published_at"] or "")[:10] or None, " ".join(item.claim.split()), p["id"],
                 status, model, prompt_label, p["document_id"], item.claim_type,
                 p["text"][s:e], s, e, SOURCES[p["source"]].tier if p["source"] in SOURCES else 1,
                 cc.answer or "unavailable", provider, call_id, key)).lastrowid
            conn.execute("INSERT INTO signal_status (signal_id, status, reason, set_by, call_id) "
                         "VALUES (?, ?, ?, 'system', ?)", (sid, status, reason, cc.call_id))
            return sid
    finally:
        conn.close()


def process_passage(p, matcher: Matcher, run: QueueRun) -> None:
    """Steps b–e for one passage. Raises client.AIUnavailable when extraction can't run."""
    version = client.load_prompt("extract").label
    ex = extract.extract_passage(p["id"])
    run.calls += 1
    if ex.problem:
        _save_rejection(p, {"raw_answer": ex.result.raw_text[:4000]}, [ex.problem], None, ex.result)
        client.log_validation(ex.result.call_id, {"step": "extract", "ok": False,
                                                  "reason": ex.problem})
        _record_extraction(p["id"], version, ex.result.call_id, "invalid_output", 0)
        run.rejected += 1
        return
    verdicts = []
    conn = db.connect()
    try:
        for raw in ex.items:
            v = validate.validate_item(raw, {p["id"]: p["text"]}, p["company"], matcher, conn)
            verdicts.append(v)
    finally:
        conn.close()
    log_items = []
    for raw, v in zip(ex.items, verdicts):
        if not v.ok:
            _save_rejection(p, raw, v.reasons, v.suggestion, ex.result)
            run.rejected += 1
            log_items.append({"ok": False, "reasons": v.reasons})
            continue
        cc = crosscheck.crosscheck(p["id"], v.item.claim, ex.result.provider)
        if cc.call_id:
            run.calls += 1
        sid = save_signal(p, v, ex.result.provider, ex.result.model, ex.result.prompt.label,
                          ex.result.call_id, cc)
        status, _ = label.label(cc.answer)
        if sid:
            run.signals[status] += 1
        log_items.append({"ok": True, "signal_id": sid, "cross_check": cc.answer,
                          "status": status})
    client.log_validation(ex.result.call_id, {"step": "extract", "items": log_items})
    _record_extraction(p["id"], version, ex.result.call_id, "done", len(ex.items))


def retry_crosschecks(run: QueueRun, limit: int) -> None:
    """Signals that passed code checks while no checker was available get another try."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT s.id, s.passage_id, s.claim_text, s.provider FROM signals s WHERE s.provider "
            "!= 'code' AND (SELECT status FROM signal_status t WHERE t.signal_id = s.id ORDER BY "
            "t.id DESC LIMIT 1) = 'unverified' ORDER BY s.id LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    for r in rows:
        cc = crosscheck.crosscheck(r["passage_id"], r["claim_text"], r["provider"])
        if cc.answer is None:
            return  # still no checker available; try again next run
        run.calls += 1
        status, reason = label.label(cc.answer)
        conn = db.connect()
        try:
            with conn:
                conn.execute("INSERT INTO signal_status (signal_id, status, reason, set_by, "
                             "call_id) VALUES (?, ?, ?, 'ai', ?)", (r["id"], status, reason,
                                                                    cc.call_id))
        finally:
            conn.close()


def flag_superseded() -> int:
    """Section 7: signals from a superseded, corrected or cancelled document are re-flagged."""
    conn = db.connect()
    flagged = 0
    try:
        with conn:
            rows = conn.execute(
                "SELECT s.id, s.document_id FROM signals s WHERE s.document_id IS NOT NULL").fetchall()
            for r in rows:
                st = rawstore.current_status(conn, r["document_id"])
                if st["status"] not in ("superseded", "corrected", "cancelled"):
                    continue
                last = conn.execute("SELECT status, reason FROM signal_status WHERE signal_id = ? "
                                    "ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
                if last and last["status"] == "needs_review" and "source document" in last["reason"]:
                    continue
                conn.execute("INSERT INTO signal_status (signal_id, status, reason, set_by) VALUES "
                             "(?, 'needs_review', ?, 'system')",
                             (r["id"], f"The source document is now marked '{st['status']}'. "
                                       f"Re-check it against the newer filing."))
                flagged += 1
    finally:
        conn.close()
    return flagged


def summaries_due(conn) -> list[int]:
    auto = list(load_config()["ai"]["processing"].get("summary_auto", []))
    if not auto:
        return []
    cats = _categories()
    where, args = _eligible_docs_sql(cats)
    marks = ",".join("?" * len(auto))
    return [r["id"] for r in conn.execute(
        f"SELECT d.id FROM documents d WHERE {where} AND d.type IN ({marks}) AND EXISTS (SELECT 1 "
        f"FROM passages p WHERE p.document_id = d.id AND p.kind = 'text') AND NOT EXISTS (SELECT 1 "
        f"FROM summaries s WHERE s.document_id = d.id) ORDER BY {_priority_sql(cats)}",
        (*args, *auto))]


def run_queue(max_calls: int | None = None) -> QueueRun:
    """One pass of the AI queue. Never raises; problems become a plain message."""
    run = QueueRun()
    started = now_utc()
    run_id = ingest.start_run(QUEUE_ID, started)
    if run_id is None:
        return QueueRun("skipped", "The AI queue is already running.")
    cfg = load_config()["ai"]["processing"]
    max_calls = max_calls or int(cfg.get("max_calls_per_run", 40))
    cats = _categories()
    try:
        run.structured = structured_signals.build_all()
        conn = db.connect()
        try:
            to_chunk = documents_to_chunk(conn, cats)
        finally:
            conn.close()
        for doc_id in to_chunk:
            chunk.chunk_document(doc_id)
        flag_superseded()
        version = client.load_prompt("extract").label
        conn = db.connect()
        try:
            matcher = Matcher(conn)
            pending = pending_passages(conn, cats, version, limit=max_calls)
        finally:
            conn.close()
        for p in pending:
            if run.calls >= max_calls:
                break
            process_passage(p, matcher, run)
        if run.calls < max_calls:
            retry_crosschecks(run, max_calls - run.calls)
        conn = db.connect()
        try:
            due = summaries_due(conn)
        finally:
            conn.close()
        for doc_id in due:
            if run.calls >= max_calls:
                break
            try:
                if summarize.summarize_document(doc_id).get("ok"):
                    run.summaries += 1
                run.calls += 1
            except client.AIUnavailable:
                break  # summaries wait; extraction results are already saved
    except client.AIUnavailable as exc:
        run.status, run.resume_at = "waiting", exc.resume_at
        run.message = exc.message
    except Exception as exc:  # noqa: BLE001 — never crash the scheduler or dashboard
        run.status, run.message = "error", report(exc, log).message
    if not run.message:
        s = run.signals
        run.message = (f"{run.calls} AI call(s): {s['verified']} verified, {s['needs_review']} "
                       f"need review, {s['unverified']} unverified, {run.rejected} rejected; "
                       f"{run.summaries} summary(ies); "
                       f"{sum(run.structured.values()) if run.structured else 0} signal(s) from "
                       f"structured data.")
    fetch_status = {"ok": "ok", "waiting": "blocked", "error": "error"}[run.status]
    ingest.finish_run(QUEUE_ID, run_id, fetch_status, run.calls,
                      run.calls - run.rejected if run.calls >= run.rejected else 0, run.message)
    return run
