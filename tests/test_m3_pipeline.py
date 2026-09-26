"""M3: each Section 6 step on its own, then end to end — with FIXTURE PDFs and fake AI
backends (no real AI call, no quota used)."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from app.llm import client, limits
from app.llm.backends import LLMFailure
from app.processing import chunk, label, pipeline, structured_signals, summarize, validate
from app.services import documents, signals, watchlist
from app.services.audit import log as audit_log
from app.services.matching import Matcher
from app.store import db
from app.timeutil import now_utc, to_iso
from tests.conftest import FIXTURES, FakeAI, text_pdf

ALPHA, BETA = "INE0FXA01011", "INE0FXB01019"
PAGE1 = ["FIXTURE Alpha Limited - Outcome of Board Meeting",
         "The Board approved allotment of 1,21,92,125 equity shares at Rs. 14.33 per share.",
         "The Company received an order worth Rs. 250 crore from FIXTURE Railways."]
PAGE2 = ["Please take the above on record.", "Yours faithfully, FIXTURE Company Secretary"]


def add_doc(isin=ALPHA, pages=(PAGE1, PAGE2), category="results", name="FIXTURE_doc.pdf"):
    doc_id, _ = documents.add_manual(text_pdf(list(pages)), name, isin, category,
                                     "FIXTURE outcome of board meeting", None, None)
    return doc_id


def extraction(items):
    return lambda user: json.dumps({"items": items(user) if callable(items) else items})


def chunk_id(user):
    return int(user.split("[CHUNK ")[1].split("]")[0])


# --- step a: chunk -------------------------------------------------------------------

def test_chunks_keep_page_and_offsets(imported):
    doc_id = add_doc()
    counts = chunk.chunk_document(doc_id)
    assert counts == {"text": 2}
    conn = db.connect()
    rows = conn.execute("SELECT * FROM passages WHERE document_id = ? ORDER BY page",
                        (doc_id,)).fetchall()
    conn.close()
    assert [r["page"] for r in rows] == [1, 2]
    assert "1,21,92,125" in rows[0]["text"]
    assert chunk.chunk_document(doc_id) == {"text": 2}      # never chunked twice


def test_scanned_page_is_not_sent_to_ai(imported):
    from tests.conftest import fixture_pdf

    doc_id, _ = documents.add_manual(fixture_pdf(2), "FIXTURE_scan.pdf", ALPHA, "results",
                                     "FIXTURE scanned", None, None)
    assert chunk.chunk_document(doc_id) == {"no_text": 2}


def test_split_page_never_exceeds_limit():
    text = ("Line of words. " * 50 + "\r\n") * 20
    spans = chunk.split_page(text, 500)
    assert all(e - s <= 500 for s, e in spans)
    assert "".join(text[s:e] for s, e in spans).replace(" ", "") != ""


# --- step c: validate ----------------------------------------------------------------

def test_verbatim_ignores_only_whitespace():
    src = "Allotment of 1,21,92,125 (One Crore)  equity\r\nshares at Rs. 14.33"
    assert validate.find_verbatim("1,21,92,125 (One Crore) equity shares", src) is not None
    assert validate.find_verbatim("1,21,92,125 (one crore) equity shares", src) is None  # case
    assert validate.find_verbatim("1,21,92,126 (One Crore)", src) is None
    s, e = validate.find_verbatim("equity shares", src)
    assert src[s:e] == "equity\r\nshares"


def test_numbers_are_compared_exactly():
    q = "allotment of 1,21,92,125 equity shares at Rs. 14.33 aggregating Rs. 17,47,13,151"
    assert validate.missing_numbers("allotted 12192125 shares at Rs.14.33", q) == []
    assert validate.missing_numbers("aggregating Rs. 17.47 crore", q) == ["17.47"]
    assert validate.missing_numbers("up 12.5% year on year", q) == ["12.5"]
    assert validate.missing_numbers("FY27 guidance", q) == []   # "FY27" is a label, not a number


def item(**kw):
    base = {"chunk_id": 1, "signal_type": "ownership_change", "direction": "neutral",
            "strength": 3, "claim_type": "fact", "claim": "The board approved an allotment.",
            "quote": "The Board approved allotment of 1,21,92,125 equity shares",
            "company_mentioned": None}
    return base | kw


def test_validation_rules(imported):
    conn = db.connect()
    m = Matcher(conn)
    text = "The Board approved allotment of 1,21,92,125 equity shares at Rs. 14.33 per share."
    ok = validate.validate_item(item(), {1: text}, ALPHA, m, conn)
    assert ok.ok and ok.company == ALPHA and text[ok.span[0]:ok.span[1]].startswith("The Board")
    assert "required format" in validate.validate_item({"claim": 1}, {1: text}, ALPHA, m).reasons[0]
    assert not validate.validate_item(item(chunk_id=9), {1: text}, ALPHA, m).ok
    bad_quote = validate.validate_item(item(quote="The Board approved 2 crore shares"), {1: text},
                                       ALPHA, m)
    assert "word-for-word" in bad_quote.reasons[0]
    bad_num = validate.validate_item(item(claim="Allotment of 99 shares."), {1: text}, ALPHA, m)
    assert "99" in bad_num.reasons[0]
    other = validate.validate_item(item(company_mentioned="Fixture Beta Limited"), {1: text},
                                   ALPHA, m, conn)
    assert other.ok and other.company == BETA                  # exact match to another company
    fuzzy = validate.validate_item(item(company_mentioned="Fixture Betta Limited"), {1: text},
                                   ALPHA, m, conn)
    assert not fuzzy.ok and fuzzy.suggestion == BETA           # suggested, never accepted
    conn.close()


# --- step e: label -------------------------------------------------------------------

def test_labels():
    assert label.label("yes")[0] == "verified"
    assert label.label("partly")[0] == "needs_review"
    assert label.label("no")[0] == "needs_review"
    assert label.label(None)[0] == "unverified"


# --- privacy guardrail -----------------------------------------------------------------

def test_only_public_filing_text_can_reach_an_ai(imported, monkeypatch):
    FakeAI(monkeypatch, {"extract": extraction([])})
    with pytest.raises(client.PrivateDataError):
        client.call("extraction", "extract", {"chunk": "my private thesis note"})
    with pytest.raises(client.PrivateDataError):
        client.PublicText([(1, 1, "anything")])
    with pytest.raises(client.PrivateDataError):
        client.ClaimText.from_extraction("claim", "not public text")
    conn = db.connect()
    with conn:   # a passage from a document that is not a public source
        did = conn.execute("INSERT INTO documents (source, url, fetched_at, content_hash, "
                           "file_path) VALUES ('owner_notes', 'x', 'x', 'x', 'x')").lastrowid
        pid = conn.execute("INSERT INTO passages (document_id, char_start, char_end, text) "
                           "VALUES (?, 0, 4, 'note')", (did,)).lastrowid
    conn.close()
    with pytest.raises(client.PrivateDataError):
        client.PublicText.from_passages([pid])


def test_ai_code_never_reads_owner_tables():
    """M4 guardrail: nothing under app/llm or app/processing touches theses, claims or evidence."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "app"
    for folder in ("llm", "processing"):
        for f in (root / folder).rglob("*.py"):
            text = f.read_text(encoding="utf-8").lower()
            for table in ("theses", "from claims", "evidence", "street_view", "user_weight"):
                assert table not in text, f"{f.name} mentions {table}"


def test_prompts_live_in_versioned_files():
    p = client.load_prompt("extract", "v1")
    assert "If it is not stated in the text, return nothing" in p.system
    assert "{chunk}" in p.user
    assert client.load_prompt("crosscheck", "v1").user.startswith(
        "Does this passage support this claim? Yes, partly or no?")


# --- end to end ------------------------------------------------------------------------

def good_item(user):
    return [{"chunk_id": chunk_id(user), "signal_type": "ownership_change", "direction": "neutral",
             "strength": 3, "claim_type": "fact",
             "claim": "The board approved allotment of 1,21,92,125 equity shares at Rs. 14.33.",
             "quote": "The Board approved allotment of 1,21,92,125 equity shares at Rs. 14.33 "
                      "per share.", "company_mentioned": None},
            {"chunk_id": chunk_id(user), "signal_type": "order_win", "direction": "positive",
             "strength": 4, "claim_type": "commitment", "claim": "An order worth Rs. 300 crore.",
             "quote": "The Company received an order worth Rs. 250 crore",
             "company_mentioned": None}]


def run_with(monkeypatch, crosscheck_answer):
    ai = FakeAI(monkeypatch, {
        "extract": lambda u: json.dumps({"items": good_item(u) if "Board" in u else []}),
        "crosscheck": json.dumps({"answer": crosscheck_answer})
        if isinstance(crosscheck_answer, str) else crosscheck_answer,
        "summarize": json.dumps({"sentences": []})})
    return ai, pipeline.run_queue()


def test_end_to_end_verified_and_rejected(imported, monkeypatch):
    watchlist.add(ALPHA)
    doc_id = add_doc()
    ai, run = run_with(monkeypatch, "yes")
    assert run.status == "ok", run.message
    assert run.signals["verified"] == 1 and run.rejected == 1   # 300 is not in the quote
    s = signals.feed()[0]
    assert s["current_status"] == "verified" and s["claim_type"] == "fact"
    assert s["quote"].startswith("The Board approved")
    assert s["provider"] == "groq" and s["cross_check"] == "yes"
    # Cross-check went to the other provider, and only asked the fixed question.
    check = [c for c in ai.calls if c[2] == "crosscheck"][0]
    assert check[0] == "gemini" and "Does this passage support this claim?" in check[3]
    # Rejected items are logged with reasons, never in the feed.
    rej = signals.rejected_log()
    assert "300" in rej[0]["reasons"][0]
    assert all(r["claim_text"] != "An order worth Rs. 300 crore." for r in signals.feed())
    # Every call is in the audit log with the fields step 9 asks for.
    conn = db.connect()
    rows = [json.loads(r["after"]) for r in conn.execute(
        "SELECT after FROM audit_log WHERE action = 'llm_call'")]
    vals = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'llm_validation'").fetchone()[0]
    conn.close()
    for r in rows:
        assert {"provider", "model", "prompt_version", "input_hash", "output", "outcome"} <= set(r)
    assert vals >= 1
    # Running again does nothing new.
    assert pipeline.run_queue().calls == 0


def test_disagreement_needs_review(imported, monkeypatch):
    watchlist.add(ALPHA)
    add_doc()
    run_with(monkeypatch, "partly")
    assert signals.feed()[0]["current_status"] == "needs_review"


def test_no_checker_means_unverified_then_retried(imported, monkeypatch):
    watchlist.add(ALPHA)
    add_doc()
    down = LLMFailure("unavailable", "Gemini is busy or having problems right now.")
    run_with(monkeypatch, {"gemini": down, "groq": down})
    assert signals.feed()[0]["current_status"] == "unverified"
    run_with(monkeypatch, "yes")                                # the checker is back
    assert signals.feed()[0]["current_status"] == "verified"


def test_invalid_json_is_rejected_not_saved(imported, monkeypatch):
    watchlist.add(ALPHA)
    add_doc()
    FakeAI(monkeypatch, {"extract": "{not json", "crosscheck": "{}", "summarize": "{}"})
    run = pipeline.run_queue()
    assert run.rejected >= 1 and signals.feed() == []
    assert "required format" in signals.rejected_log()[0]["reasons"][0]


def test_queue_puts_watchlist_first(imported):
    watchlist.add(BETA)
    add_doc(ALPHA, name="FIXTURE_a.pdf")
    add_doc(BETA, name="FIXTURE_b.pdf")
    conn = db.connect()
    for d in pipeline.documents_to_chunk(conn, pipeline._categories()):
        chunk.chunk_document(d)
    pending = pipeline.pending_passages(conn, pipeline._categories(), "extract_v1")
    conn.close()
    assert pending[0]["company"] == BETA                        # watchlist company first


def test_daily_limit_waits_and_shows_on_data_health(imported, monkeypatch):
    watchlist.add(ALPHA)
    add_doc()
    conn = db.connect()
    with conn:   # FIXTURE usage: both extraction models are at their daily request limit
        for model in ("openai/gpt-oss-120b", "gemini-3.8-flash"):
            lim = limits.model_limits(model)
            for _ in range(int(float(lim["rpd"]) * lim["margin"]) + 1):
                audit_log(conn, "ai", "llm_call", "fixture", after={
                    "provider": "x", "model": model, "outcome": "ok", "tokens_in": 1,
                    "tokens_out": 1})
    conn.close()
    FakeAI(monkeypatch, {"extract": extraction([]), "crosscheck": "{}", "summarize": "{}"})
    run = pipeline.run_queue()
    assert run.status == "waiting" and run.resume_at is not None
    assert "waiting" in run.message and "Traceback" not in run.message
    q = signals.queue_state()
    assert q.state == "waiting" and q.passages == 2 and q.watchlist_passages == 2
    assert "daily request limit" in q.waiting_reason


def test_provider_slow_down_blocks_until_named_time(imported, monkeypatch):
    watchlist.add(ALPHA)
    add_doc()
    slow = LLMFailure("rate_limited", "Groq asked the app to slow down.", retry_after=120)
    ai = FakeAI(monkeypatch, {"extract": {"groq": slow, "gemini": json.dumps({"items": []})},
                              "crosscheck": "{}", "summarize": "{}"})
    pipeline.run_queue()
    assert limits.check("openai/gpt-oss-120b", 10).ok is False  # blocked for ~2 minutes
    assert any(c[0] == "gemini" for c in ai.calls)               # fallback took over


def test_summary_strips_uncited_and_unmatched_numbers(imported, monkeypatch):
    doc_id = add_doc()
    chunk.chunk_document(doc_id)
    conn = db.connect()
    pids = [r["id"] for r in conn.execute("SELECT id FROM passages WHERE document_id = ? "
                                          "ORDER BY page", (doc_id,))]
    conn.close()
    FakeAI(monkeypatch, {"summarize": json.dumps({"sentences": [
        {"text": "The board approved an allotment of 1,21,92,125 shares.", "chunk_ids": [pids[0]]},
        {"text": "Revenue grew 40%.", "chunk_ids": [pids[0]]},          # number not in chunk
        {"text": "The company is doing well.", "chunk_ids": []},        # no citation
        {"text": "Something else.", "chunk_ids": [999999]}]})})         # not this document
    res = summarize.summarize_document(doc_id)
    assert res["ok"] and res["kept"] == 1 and res["removed"] == 3
    assert res["coverage"] == Decimal("0.25")
    s = signals.summaries_for(doc_id)
    assert s["sentences"][0]["chunk_ids"] == [pids[0]] and len(s["removed"]) == 3


def test_structured_signals_from_shareholding_and_deals(with_bse):
    from app.adapters import bulk_block
    from tests.conftest import FakeClient

    watchlist.add(ALPHA)
    shp = (FIXTURES / "FIXTURE_SHP.xml").read_text()
    older = shp.replace("2026-06-30", "2026-03-31").replace(">0.5125<", ">0.5310<") \
               .replace(">0.4875<", ">0.4690<")
    documents.add_manual(older.encode(), "FIXTURE_mar.xml", ALPHA, "shareholding", "FIXTURE", None, None)
    documents.add_manual(shp.encode(), "FIXTURE_jun.xml", ALPHA, "shareholding", "FIXTURE", None, None)
    bulk_block.run(client=FakeClient({
        bulk_block.FILES["bulk"]: (FIXTURES / "FIXTURE_bulk.csv").read_bytes(),
        bulk_block.FILES["block"]: (FIXTURES / "FIXTURE_block.csv").read_bytes()}))
    added = structured_signals.build_all()
    assert added["shareholding"] == 1 and added["deals"] == 2
    rows = signals.feed(company=ALPHA)
    promoter = next(r for r in rows if "Promoter" in r["claim_text"])
    assert "51.25% as on 2026-06-30, down from 53.1% as on 2026-03-31" in promoter["claim_text"]
    assert promoter["provider"] == "code" and promoter["claim_type"] == "fact"
    assert promoter["current_status"] == "verified" and "0.5125" in promoter["quote"]
    deal = next(r for r in rows if "FIXTURE CAPITAL" in r["claim_text"])
    assert deal["quote"].startswith("25-SEP-2026,FXALPHA")
    assert structured_signals.build_all() == {"shareholding": 0, "insider": 0, "deals": 0}


def test_superseded_source_flags_signal(imported, monkeypatch):
    watchlist.add(ALPHA)
    doc_id = add_doc()
    run_with(monkeypatch, "yes")
    documents.set_status(doc_id, "superseded", "FIXTURE: a corrected filing was issued")
    pipeline.flag_superseded()
    s = signals.feed()[0]
    assert s["current_status"] == "needs_review"
    assert "superseded" in signals.get(s["id"])["history"][-1]["reason"]


def test_owner_review_is_appended_and_audited(imported, monkeypatch):
    watchlist.add(ALPHA)
    add_doc()
    run_with(monkeypatch, "no")
    sid = signals.feed()[0]["id"]
    signals.set_by_owner(sid, "verified", "FIXTURE: checked by hand")
    hist = signals.get(sid)["history"]
    assert [h["status"] for h in hist] == ["needs_review", "verified"]
    assert hist[-1]["set_by"] == "user"


def test_highlight_draws_on_the_page(imported, monkeypatch):
    watchlist.add(ALPHA)
    doc_id = add_doc()
    run_with(monkeypatch, "yes")
    s = signals.get(signals.feed()[0]["id"])
    data = documents.content(documents.get(doc_id))
    png = documents.highlight_png(data, None, s["page"], s["passage_start"] + s["quote_start"],
                                  s["passage_start"] + s["quote_end"])
    assert png and png[:4] == b"\x89PNG"


def test_typographic_variants_count_as_the_same():
    src = "Non‑Promoter company’s shares"
    assert validate.find_verbatim("Non-Promoter company's shares", src) == (0, len(src))
    assert validate.find_verbatim("Non-Promoter", "Non–Promoter") is None   # en dash differs
