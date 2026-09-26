"""The golden-set scorer's own rules, on FIXTURE items (no AI calls)."""

from tests.golden import score as g

DOCS = [
    {"id": "D1", "status": "confirmed", "expected": [
        {"signal_type": "ownership_change", "direction": "any", "claim_type": "fact",
         "key_quote": "Allotment of 1,21,92,125"},
        {"signal_type": "order_win", "direction": "positive", "claim_type": "any",
         "key_quote": "order worth", "required": False}]},
    {"id": "D2", "status": "confirmed", "expected": []},
]


def it(doc, typ, quote, status="verified", fabricated=False, **kw):
    return {"doc_id": doc, "type": typ, "direction": kw.get("direction", "neutral"),
            "claim_type": kw.get("claim_type", "fact"), "claim": "FIXTURE claim", "quote": quote,
            "status": status, "fabricated": fabricated, "page": 1}


def test_matching_and_precision():
    items = [it("D1", "ownership_change", "1. Allotment of  1,21,92,125 equity shares"),
             it("D1", "order_win", "an order worth Rs. 5 crore", direction="positive")]
    r = g.score(DOCS, items, {})
    assert r["correct"] == 2 and r["precision"] == 1.0 and r["final"] and r["meets_target"]
    assert r["recall"] == 1.0


def test_unmatched_verified_waits_for_owner():
    extra = it("D2", "capex_expansion", "new plant commissioned")
    r = g.score(DOCS, [extra], {})
    assert not r["final"] and len(r["pending_judgement"]) == 1
    key = r["pending_judgement"][0]["key"]
    r = g.score(DOCS, [extra], {key: {"correct": False}})
    assert r["final"] and r["precision"] == 0.0 and not r["meets_target"]


def test_fabricated_quote_fails_target():
    items = [it("D1", "ownership_change", "Allotment of 1,21,92,125 shares", fabricated=True)]
    r = g.score(DOCS, items, {})
    assert r["fabricated"] == 1 and not r["meets_target"]


def test_draft_documents_keep_score_provisional():
    docs = [DOCS[0] | {"status": "draft"}]
    r = g.score(docs, [it("D1", "ownership_change", "Allotment of 1,21,92,125")], {})
    assert not r["final"] and r["draft_documents"] == ["D1"]


def test_wrong_type_or_direction_does_not_match():
    e = DOCS[0]["expected"][1]
    assert not g.matches(e, it("D1", "order_win", "an order worth", direction="negative"))
    assert not g.matches(e, it("D1", "demand_commentary", "an order worth"))


def test_expected_type_can_list_alternatives():
    e = {"signal_type": ["demand_commentary", "cost_margin"], "key_quote": "Revenue grew"}
    assert g.matches(e, it("D1", "cost_margin", "Revenue grew 54%"))
    assert not g.matches(e, it("D1", "order_win", "Revenue grew 54%"))
