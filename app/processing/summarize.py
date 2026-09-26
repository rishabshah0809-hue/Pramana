"""Step f — Summarize with citations.

The model gets a document's chunks and must cite chunk IDs on every sentence. Code then
removes any sentence that:
- has no citation, or cites a chunk that isn't part of this document's text, or
- contains a number that is not written in one of the chunks it cites (step g: numbers
  are copies from the filing, checked by code — never calculated or retyped).
The summary keeps its citation coverage: sentences kept / sentences written.
"""

import json
from decimal import Decimal

from app.config import load_config
from app.llm import client
from app.processing.validate import numbers_in
from app.store import db


def _passages(document_id: int) -> list:
    conn = db.connect()
    try:
        return conn.execute("SELECT id, page, text FROM passages WHERE document_id = ? AND "
                            "kind = 'text' ORDER BY member, page, char_start",
                            (document_id,)).fetchall()
    finally:
        conn.close()


def check_sentences(sentences: list[dict], texts: dict[int, str]) -> tuple[list, list]:
    kept, removed = [], []
    for s in sentences:
        cited = [c for c in s["chunk_ids"] if c in texts]
        text = " ".join(s["text"].split())
        if not text:
            continue
        if not s["chunk_ids"]:
            removed.append({"text": text, "reason": "No citation"})
            continue
        if len(cited) != len(set(s["chunk_ids"])):
            removed.append({"text": text, "reason": "Cites a chunk that is not in this document"})
            continue
        have = {n for c in cited for n in numbers_in(texts[c])}
        missing = [f"{n:f}" for n in numbers_in(text) if n not in have]
        if missing:
            removed.append({"text": text, "reason": "Numbers not in the cited chunk: "
                            + ", ".join(missing)})
            continue
        kept.append({"text": text, "chunk_ids": sorted(set(cited))})
    return kept, removed


def summarize_document(document_id: int) -> dict:
    """Raises client.AIUnavailable when no provider can take the call now."""
    rows = _passages(document_id)
    if not rows:
        return {"ok": False, "message": "This document has no readable text to summarise."}
    limit = int(load_config()["ai"]["processing"].get("summary_max_chars", 120000))
    chosen, used = [], 0
    for r in rows:
        if chosen and used + len(r["text"]) > limit:
            break
        chosen.append(r)
        used += len(r["text"])
    total_chars = sum(len(r["text"]) for r in rows)
    public = client.PublicText.from_passages([r["id"] for r in chosen])
    result = client.call("summary", "summarize", {"chunks": public})
    if result.parsed is None:
        client.log_validation(result.call_id, {"step": "summary", "ok": False,
                                               "reason": result.problem})
        return {"ok": False, "message": f"The summary answer was unusable: {result.problem}"}
    texts = {r["id"]: r["text"] for r in chosen}
    kept, removed = check_sentences([s.model_dump() for s in result.parsed.sentences], texts)
    total = len(kept) + len(removed)
    coverage = (Decimal(len(kept)) / Decimal(total)) if total else Decimal(0)
    conn = db.connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO summaries (document_id, sentences_json, removed_json, coverage, "
                "chars_summarised, chars_total, provider, model, prompt_version, call_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (document_id, json.dumps(kept), json.dumps(removed), str(coverage), used,
                 total_chars, result.provider, result.model, result.prompt.label, result.call_id))
    finally:
        conn.close()
    client.log_validation(result.call_id, {"step": "summary", "kept": len(kept),
                                           "removed": removed, "coverage": str(coverage)})
    return {"ok": True, "summary_id": cur.lastrowid, "kept": len(kept), "removed": len(removed),
            "coverage": coverage}
