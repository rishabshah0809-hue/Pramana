"""Signals for the screens: the feed and its filters, one signal with its source passage,
the owner's review actions, the rejected log, summaries, and the AI queue's state.

A signal's status is the latest row in signal_status (history is never overwritten).
Rejected items live in extraction_rejections and are never returned as signals.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.config import load_config
from app.errors import FriendlyError
from app.llm import limits
from app.llm.schemas import CLAIM_TYPES, SIGNAL_TYPES
from app.services import audit
from app.store import db
from app.timeutil import from_iso, now_utc

STATUS_LABELS = {"verified": ("Verified", "green"), "unverified": ("Unverified", "orange"),
                 "needs_review": ("Needs review", "red"), "rejected": ("Rejected", "gray")}
_CURRENT = ("(SELECT t.status FROM signal_status t WHERE t.signal_id = s.id "
            "ORDER BY t.id DESC LIMIT 1)")


def feed(company=None, types=None, direction=None, tiers=None, statuses=None, claim_types=None,
         date_from=None, date_to=None, limit: int = 300) -> list[dict]:
    where, args = ["1 = 1"], []
    if company:
        where.append("s.company = ?")
        args.append(company)
    for col, values in (("s.type", types), ("s.source_tier", tiers), ("s.claim_type", claim_types)):
        if values:
            where.append(f"{col} IN ({','.join('?' * len(values))})")
            args += list(values)
    if direction:
        where.append("s.direction = ?")
        args.append(direction)
    if statuses:
        where.append(f"{_CURRENT} IN ({','.join('?' * len(statuses))})")
        args += list(statuses)
    else:
        where.append(f"{_CURRENT} != 'rejected'")
    if date_from:
        where.append("COALESCE(s.signal_date, substr(s.created_at, 1, 10)) >= ?")
        args.append(str(date_from))
    if date_to:
        where.append("COALESCE(s.signal_date, substr(s.created_at, 1, 10)) <= ?")
        args.append(str(date_to))
    conn = db.connect()
    try:
        rows = conn.execute(
            f"SELECT s.*, {_CURRENT} AS current_status, c.name AS company_name, "
            f"d.source AS doc_source, d.type AS doc_type, p.page, p.member "
            f"FROM signals s JOIN companies c ON c.isin = s.company "
            f"JOIN passages p ON p.id = s.passage_id LEFT JOIN documents d ON d.id = s.document_id "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY COALESCE(s.signal_date, s.created_at) DESC, s.id DESC LIMIT ?",
            (*args, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get(signal_id: int) -> dict | None:
    conn = db.connect()
    try:
        r = conn.execute(
            f"SELECT s.*, {_CURRENT} AS current_status, c.name AS company_name, p.page, p.member, "
            f"p.text AS passage_text, p.kind AS passage_kind, p.char_start AS passage_start "
            f"FROM signals s JOIN companies c ON c.isin = s.company JOIN passages p "
            f"ON p.id = s.passage_id WHERE s.id = ?", (signal_id,)).fetchone()
        if r is None:
            return None
        out = dict(r)
        out["history"] = [dict(h) for h in conn.execute(
            "SELECT * FROM signal_status WHERE signal_id = ? ORDER BY id", (signal_id,))]
        return out
    finally:
        conn.close()


def for_document(document_id: int) -> list[dict]:
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute(
            f"SELECT s.*, {_CURRENT} AS current_status, p.page, p.member FROM signals s "
            f"JOIN passages p ON p.id = s.passage_id WHERE s.document_id = ? ORDER BY p.page, "
            f"s.quote_start", (document_id,))]
    finally:
        conn.close()


def set_by_owner(signal_id: int, status: str, note: str) -> None:
    """The owner's own judgement on a signal (e.g. after reviewing it). Appended and audited."""
    if status not in STATUS_LABELS:
        raise FriendlyError("Unknown status.", "Pick one of the listed options.")
    if not note.strip():
        raise FriendlyError("Please add a short note saying why.", "Add a note, then save.")
    conn = db.connect()
    try:
        with conn:
            before = conn.execute(f"SELECT {_CURRENT} FROM signals s WHERE s.id = ?",
                                  (signal_id,)).fetchone()[0]
            conn.execute("INSERT INTO signal_status (signal_id, status, reason, set_by) VALUES "
                         "(?, ?, ?, 'user')", (signal_id, status, f"By you: {note.strip()}"))
            audit.log(conn, "user", "signal_status", f"signals:{signal_id}",
                      before={"status": before}, after={"status": status, "note": note.strip()})
    finally:
        conn.close()


def rejected_log(limit: int = 200, document_id: int | None = None) -> list[dict]:
    conn = db.connect()
    try:
        where, args = ("WHERE r.document_id = ?", [document_id]) if document_id else ("", [])
        rows = conn.execute(
            f"SELECT r.*, c.name AS company_name FROM extraction_rejections r "
            f"JOIN documents d ON d.id = r.document_id LEFT JOIN companies c ON c.isin = d.company "
            f"{where} ORDER BY r.id DESC LIMIT ?", (*args, limit)).fetchall()
        return [dict(r) | {"reasons": json.loads(r["reasons"]),
                           "item": json.loads(r["item_json"])} for r in rows]
    finally:
        conn.close()


def match_suggestions() -> list[dict]:
    """14.4: rejected items with a suggested company, not yet decided by the owner."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT r.*, c.name AS suggested_name FROM extraction_rejections r JOIN companies c "
            "ON c.isin = r.suggested_company WHERE NOT EXISTS (SELECT 1 FROM "
            "company_match_reviews m WHERE m.rejection_id = r.id) ORDER BY r.id DESC").fetchall()
        return [dict(r) | {"item": json.loads(r["item_json"]),
                           "reasons": json.loads(r["reasons"])} for r in rows]
    finally:
        conn.close()


def decide_match(rejection_id: int, confirmed: bool) -> str:
    """The owner confirms or rejects a suggested company. A confirmed item is re-checked by
    the same code rules for that company and, if it passes, saved as Unverified; the queue
    then asks the cross-check model."""
    from app.processing import validate
    from app.services.matching import Matcher

    conn = db.connect()
    try:
        r = conn.execute("SELECT * FROM extraction_rejections WHERE id = ?",
                         (rejection_id,)).fetchone()
        if r is None:
            raise FriendlyError("That item no longer exists.", "Reload the page.")
        with conn:
            conn.execute("INSERT INTO company_match_reviews (rejection_id, decision, company) "
                         "VALUES (?, ?, ?)", (rejection_id, "confirmed" if confirmed else "rejected",
                                              r["suggested_company"]))
            audit.log(conn, "user", "company_match_review", f"extraction_rejections:{rejection_id}",
                      after={"confirmed": confirmed, "company": r["suggested_company"]})
        if not confirmed:
            return "Noted. The item stays rejected."
        p = conn.execute("SELECT p.*, d.published_at, d.source FROM passages p JOIN documents d "
                         "ON d.id = p.document_id WHERE p.id = ?", (r["passage_id"],)).fetchone()
        item = json.loads(r["item_json"])
        item["company_mentioned"] = None  # the owner confirmed which company it is
        v = validate.validate_item(item, {p["id"]: p["text"]}, r["suggested_company"],
                                   Matcher(conn), conn)
    finally:
        conn.close()
    if not v.ok:
        return "Confirmed, but the item still fails other checks: " + "; ".join(v.reasons)
    from app.processing import crosscheck, pipeline

    none = crosscheck.CrossCheck(None, None, None, None, "Waiting for the cross-check")
    sid = pipeline.save_signal(dict(p) | {"company": r["suggested_company"]}, v, r["provider"],
                               r["model"], r["prompt_version"], r["call_id"], none)
    return ("Confirmed. The signal was saved as Unverified; the cross-check runs with the next "
            "queue pass." if sid else "Confirmed. This signal already existed.")


def newest(limit: int = 20) -> list[dict]:
    return feed(statuses=["verified", "unverified", "needs_review"], limit=limit)


def summaries_for(document_id: int) -> dict | None:
    conn = db.connect()
    try:
        r = conn.execute("SELECT * FROM summaries WHERE document_id = ? ORDER BY id DESC LIMIT 1",
                         (document_id,)).fetchone()
        if r is None:
            return None
        return dict(r) | {"sentences": json.loads(r["sentences_json"]),
                          "removed": json.loads(r["removed_json"])}
    finally:
        conn.close()


def latest_summaries(company: str, limit: int = 10) -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT s.*, d.type AS doc_type, d.published_at, d.url FROM summaries s JOIN documents "
            "d ON d.id = s.document_id WHERE d.company = ? AND s.id = (SELECT MAX(id) FROM "
            "summaries x WHERE x.document_id = s.document_id) ORDER BY s.id DESC LIMIT ?",
            (company, limit)).fetchall()
        return [dict(r) | {"sentences": json.loads(r["sentences_json"])} for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# AI queue and provider status (Data Health)
# ---------------------------------------------------------------------------

@dataclass
class QueueState:
    state: str               # current | queued | waiting
    documents: int
    passages: int
    watchlist_passages: int
    summaries: int
    oldest: str | None       # ISO fetch time of the oldest waiting document
    waiting_reason: str | None
    resume_at: datetime | None


def queue_state(now=None) -> QueueState:
    from app.llm import client
    from app.processing import pipeline

    now = now or now_utc()
    cats = pipeline._categories()
    version = client.load_prompt("extract").label
    conn = db.connect()
    try:
        chunk_wait = pipeline.documents_to_chunk(conn, cats)
        pend = pipeline.pending_passages(conn, cats, version)
        sums = pipeline.summaries_due(conn)
        watch = {r["company"] for r in conn.execute("SELECT company FROM watchlist")}
        docs = {p["document_id"] for p in pend} | set(chunk_wait)
        oldest = None
        if docs:
            oldest = conn.execute(
                f"SELECT MIN(fetched_at) FROM documents WHERE id IN ({','.join('?' * len(docs))})",
                list(docs)).fetchone()[0]
    finally:
        conn.close()
    waiting, resume = None, None
    ext = load_config()["ai"]["tasks"]["extraction"]
    blocked = []
    for role in ("primary", "fallback"):
        m = ext[role]["model"]
        v = limits.check(m, 3000, now)
        if not v.ok and not v.wait_seconds:
            blocked.append(v)
    if pend and len(blocked) == 2:
        waiting = "; ".join(b.reason for b in blocked)
        resume = min((b.resume_at for b in blocked if b.resume_at), default=None)
    watch_pass = sum(1 for p in pend if p["company"] in watch)
    state = "current" if not pend and not chunk_wait and not sums else (
        "waiting" if waiting else "queued")
    return QueueState(state, len(docs), len(pend), watch_pass, len(sums), oldest, waiting, resume)


def provider_status(now=None) -> list[dict]:
    now = now or now_utc()
    ai = load_config()["ai"]
    out = []
    roles = {}
    for task, spec in ai["tasks"].items():
        for role in ("primary", "fallback"):
            if spec.get(role):
                roles.setdefault(spec[role]["model"], []).append(f"{task} ({role})")
    conn = db.connect()
    try:
        for model, lim in ai.get("limits", {}).items():
            u = limits.usage(model, now)
            last_ok = conn.execute(
                "SELECT MAX(timestamp) FROM audit_log WHERE action = 'llm_call' AND "
                "json_extract(after, '$.model') = ? AND json_extract(after, '$.outcome') = 'ok'",
                (model,)).fetchone()[0]
            last_err = conn.execute(
                "SELECT timestamp, json_extract(after, '$.message') AS msg FROM audit_log WHERE "
                "action = 'llm_call' AND json_extract(after, '$.model') = ? AND "
                "json_extract(after, '$.outcome') NOT IN ('ok', 'invalid_output') ORDER BY id DESC "
                "LIMIT 1", (model,)).fetchone()
            v = limits.check(model, 0, now)
            out.append({"model": model, "roles": roles.get(model, []), "usage": u,
                        "placeholder": bool(lim.get("placeholder")), "last_ok": last_ok,
                        "last_error": dict(last_err) if last_err else None, "verdict": v})
    finally:
        conn.close()
    return out


SIGNAL_TYPE_LABELS = SIGNAL_TYPES
CLAIM_TYPE_LABELS = CLAIM_TYPES


def queue_runs(limit: int = 5) -> list[dict]:
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT started_at, fetch_status, message FROM adapter_runs WHERE adapter = 'ai_queue' "
            "AND fetch_status != 'running' ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        conn.close()
