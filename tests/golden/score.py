"""Golden-set scoring harness (brief Section 6: target >= 95% of Verified items correct,
0 fabricated quotes).

    python -m tests.golden.fetch      # once: download the filings
    python -m tests.golden.score      # run the real pipeline on them, then score

The real pipeline runs (real Groq and Gemini calls, real limits) in a throwaway database in
tests/golden/.run/ (git-ignored). If a daily limit is reached it stops; run it again later
and it continues where it left off. `--fresh` starts over; `--score-only` makes no AI calls.

Scoring:
- Fabricated quote: an AI signal whose quote is not word-for-word in the original file, or
  whose passage does not match the file at its recorded page and offsets. Re-checked here
  independently of the pipeline's own validation.
- Correct Verified item: matches an expected signal (same type, key quote inside its quote,
  direction and claim type where given) or the owner judged it correct.
- A final score is reported only when every document is confirmed by the owner and every
  unmatched Verified item has the owner's judgement. Until then it is marked PROVISIONAL.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
RUN = HERE / ".run"
RESULTS = HERE / "results"
JUDGEMENTS = HERE / "judgements.yaml"
TARGET = 0.95


def norm(text: str) -> str:
    return " ".join((text or "").split())


def item_key(doc_id: str, signal_type: str, quote: str) -> str:
    return f"{doc_id}:{signal_type}:" + hashlib.sha256(norm(quote).encode()).hexdigest()[:16]


def matches(expected: dict, item: dict) -> bool:
    allowed = expected["signal_type"]
    allowed = allowed if isinstance(allowed, list) else [allowed]
    if item["type"] not in allowed:
        return False
    if norm(expected["key_quote"]) not in norm(item["quote"]):
        return False
    if expected.get("direction", "any") not in ("any", item["direction"]):
        return False
    return expected.get("claim_type", "any") in ("any", item["claim_type"])


def score(docs: list[dict], items: list[dict], judgements: dict) -> dict:
    """docs: manifest documents. items: AI signals with doc_id, type, direction, claim_type,
    quote, status, fabricated. judgements: {item_key: {"correct": bool, ...}}."""
    by_doc = {d["id"]: d for d in docs}
    verified = [i for i in items if i["status"] == "verified"]
    correct, wrong, pending = [], [], []
    for i in verified:
        key = item_key(i["doc_id"], i["type"], i["quote"])
        exp = by_doc[i["doc_id"]].get("expected") or []
        if i["fabricated"]:
            wrong.append(i)
        elif key in judgements:
            (correct if judgements[key].get("correct") else wrong).append(i)
        elif any(matches(e, i) for e in exp):
            correct.append(i)
        else:
            pending.append(i | {"key": key})
    required = [(d["id"], e) for d in docs for e in (d.get("expected") or [])
                if e.get("required", True)]
    shown = [i for i in items if i["status"] in ("verified", "unverified", "needs_review")]
    found = sum(1 for doc_id, e in required
                if any(i["doc_id"] == doc_id and matches(e, i) for i in shown))
    drafts = [d["id"] for d in docs if d.get("status") != "confirmed"]
    judged = len(correct) + len(wrong)
    precision = (len(correct) / judged) if judged else None
    return {
        "documents": len(docs), "draft_documents": drafts,
        "verified": len(verified), "correct": len(correct), "wrong": len(wrong),
        "pending_judgement": pending,
        "precision": precision,
        "fabricated": sum(1 for i in items if i["fabricated"]),
        "recall": (found / len(required)) if required else None,
        "required_expected": len(required), "required_found": found,
        "by_status": {s: sum(1 for i in items if i["status"] == s)
                      for s in ("verified", "unverified", "needs_review", "rejected")},
        "final": not drafts and not pending,
        "meets_target": (precision is not None and precision >= TARGET
                         and not any(i["fabricated"] for i in items)),
    }


# ---------------------------------------------------------------------------
# Running the real pipeline
# ---------------------------------------------------------------------------

def _prepare_env(fresh: bool) -> None:
    if fresh and RUN.exists():
        shutil.rmtree(RUN)
    (RUN / "data").mkdir(parents=True, exist_ok=True)
    os.environ["MOSAIC_DATA_DIR"] = str(RUN / "data")
    os.environ["MOSAIC_LOG_DIR"] = str(RUN / "logs")
    sys.path.insert(0, str(HERE.parent.parent))


def _load_docs(docs: list[dict]) -> dict[str, int]:
    """Company rows, watchlist and the filing files, once. Returns {golden id: document id}."""
    from app.services import documents
    from app.store import db

    ids = {}
    for d in docs:
        path = HERE / "docs" / d["file"]
        if not path.exists():
            raise SystemExit(f"{d['id']}: file missing. Run `python -m tests.golden.fetch` first.")
        c = d["company"]
        conn = db.connect()
        try:
            with conn:
                conn.execute("INSERT OR IGNORE INTO companies (isin, nse_symbol, bse_code, name) "
                             "VALUES (?, ?, ?, ?)", (c["id"], c.get("nse_symbol"),
                                                     c.get("bse_code"), c["name"]))
                conn.execute("INSERT INTO watchlist (company) SELECT ? WHERE NOT EXISTS "
                             "(SELECT 1 FROM watchlist WHERE company = ?)", (c["id"], c["id"]))
            row = conn.execute("SELECT id FROM documents WHERE url = ? ORDER BY version DESC",
                               (d["url"],)).fetchone()
        finally:
            conn.close()
        if row:
            ids[d["id"]] = row["id"]
            continue
        doc_id, _ = documents.add_manual(path.read_bytes(), d["file"], c["id"], d["category"],
                                         d["title"], d["url"], None)
        ids[d["id"]] = doc_id
    return ids


def _collect(ids: dict[str, int]) -> list[dict]:
    """Every AI signal and rejection for the golden documents, with an independent re-check."""
    from app.processing import chunk, validate
    from app.services import documents
    from app.store import db

    by_doc = {v: k for k, v in ids.items()}
    out, pages_cache = [], {}
    conn = db.connect()
    try:
        rows = conn.execute(
            f"SELECT s.*, p.page, p.member, p.char_start, p.char_end, p.text AS ptext, "
            f"(SELECT t.status FROM signal_status t WHERE t.signal_id = s.id ORDER BY t.id DESC "
            f"LIMIT 1) AS cur FROM signals s JOIN passages p ON p.id = s.passage_id "
            f"WHERE s.provider != 'code' AND s.document_id IN ({','.join('?' * len(ids))})",
            list(ids.values())).fetchall()
        rejected = conn.execute(
            f"SELECT document_id, item_json, reasons FROM extraction_rejections WHERE document_id "
            f"IN ({','.join('?' * len(ids))})", list(ids.values())).fetchall()
    finally:
        conn.close()
    for r in rows:
        if r["document_id"] not in pages_cache:
            data = documents.content(documents.get(r["document_id"]))
            pages_cache[r["document_id"]] = {(p.member, p.page): p.text
                                             for p in chunk.pages_of(data, "doc")}
        page_text = pages_cache[r["document_id"]].get((r["member"], r["page"]), "")
        fabricated = (page_text[r["char_start"]:r["char_end"]] != r["ptext"]
                      or validate.find_verbatim(r["quote"], page_text) is None)
        out.append({"doc_id": by_doc[r["document_id"]], "signal_id": r["id"], "type": r["type"],
                    "direction": r["direction"], "claim_type": r["claim_type"],
                    "claim": r["claim_text"], "quote": r["quote"], "status": r["cur"],
                    "page": r["page"], "fabricated": fabricated})
    for r in rejected:
        item = json.loads(r["item_json"])
        out.append({"doc_id": by_doc[r["document_id"]], "type": item.get("signal_type"),
                    "direction": item.get("direction"), "claim_type": item.get("claim_type"),
                    "claim": item.get("claim"), "quote": item.get("quote") or "",
                    "status": "rejected", "reasons": json.loads(r["reasons"]),
                    "fabricated": False})
    return out


def _usage() -> dict:
    from app.store import db

    conn = db.connect()
    try:
        rows = conn.execute("SELECT json_extract(after, '$.model') m, COUNT(*) n, "
                            "SUM(json_extract(after, '$.tokens_in') + json_extract(after, "
                            "'$.tokens_out')) t FROM audit_log WHERE action = 'llm_call' "
                            "GROUP BY m").fetchall()
        return {r["m"]: {"calls": r["n"], "tokens": r["t"] or 0} for r in rows}
    finally:
        conn.close()


def _report(result: dict, items: list[dict], usage: dict, prompts: dict) -> str:
    p = result["precision"]
    head = "FINAL" if result["final"] else "PROVISIONAL"
    lines = [f"# Golden set score — {head}",
             f"Run: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · prompts {prompts}", "",
             f"- Verified items correct: **{'n/a' if p is None else f'{p:.1%}'}** "
             f"({result['correct']} correct, {result['wrong']} wrong, "
             f"{len(result['pending_judgement'])} waiting for your judgement) — target 95%",
             f"- Fabricated quotes: **{result['fabricated']}** — target 0",
             f"- Expected signals found: {result['required_found']} of "
             f"{result['required_expected']}",
             f"- Items by status: {result['by_status']}",
             f"- Documents still draft: {', '.join(result['draft_documents']) or 'none'}",
             f"- AI use: {usage}", "", "## Items waiting for your judgement"]
    for i in result["pending_judgement"]:
        lines += [f"- `{i['key']}` ({i['doc_id']}, page {i['page']}, {i['type']}, "
                  f"{i['direction']}, {i['claim_type']})", f"  - Claim: {i['claim']}",
                  f"  - Quote: “{norm(i['quote'])[:400]}”"]
    lines += ["", "## All items"]
    for i in items:
        extra = f" — rejected: {'; '.join(i.get('reasons', []))}" if i["status"] == "rejected" else ""
        lines.append(f"- {i['doc_id']} · {i['status']} · {i['type']} · {i['claim']}{extra}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--score-only", action="store_true")
    args = ap.parse_args()
    _prepare_env(args.fresh)

    from app.errors import setup_logging
    from app.keys import load_env_file
    from app.llm import client
    from app.store import db

    setup_logging()
    load_env_file()
    db.init_db()
    docs = yaml.safe_load((HERE / "manifest.yaml").read_text(encoding="utf-8"))["documents"]
    ids = _load_docs(docs)
    if not args.score_only:
        from app.processing import pipeline

        while True:
            run = pipeline.run_queue()
            print(f"queue: {run.status} — {run.message}")
            if run.status != "ok" or run.calls == 0:
                break
    judgements = {}
    if JUDGEMENTS.exists():
        judgements = yaml.safe_load(JUDGEMENTS.read_text(encoding="utf-8")) or {}
    items = _collect(ids)
    result = score(docs, items, judgements)
    prompts = {n: client.load_prompt(n).label for n in ("extract", "crosscheck")}
    RESULTS.mkdir(exist_ok=True)
    report = _report(result, items, _usage(), prompts)
    (RESULTS / "latest.md").write_text(report, encoding="utf-8")
    print(report.split("## Items waiting")[0])
    print(f"Full report: {RESULTS / 'latest.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
