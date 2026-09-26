"""The golden manifest is well formed, and every expected key quote is word-for-word in its
filing (checked when the filings have been downloaded with `python -m tests.golden.fetch`)."""

import hashlib
from pathlib import Path

import pytest
import yaml

from app.llm.schemas import CLAIM_TYPES, SIGNAL_TYPES

HERE = Path(__file__).resolve().parent / "golden"
DOCS = yaml.safe_load((HERE / "manifest.yaml").read_text(encoding="utf-8"))["documents"]


def test_manifest_is_well_formed():
    assert len({d["id"] for d in DOCS}) == len(DOCS) == 20
    for d in DOCS:
        assert d["url"].startswith("https://") and len(d["sha256"]) == 64
        assert d["status"] in ("draft", "confirmed")
        for e in d.get("expected") or []:
            types = e["signal_type"] if isinstance(e["signal_type"], list) else [e["signal_type"]]
            assert all(t in SIGNAL_TYPES for t in types), d["id"]
            assert e.get("claim_type", "any") in ("any", *CLAIM_TYPES), d["id"]
            assert e.get("direction", "any") in ("any", "positive", "negative", "neutral")
            assert e["key_quote"].strip()


@pytest.mark.parametrize("d", DOCS, ids=[d["id"] for d in DOCS])
def test_key_quotes_are_verbatim(d):
    path = HERE / "docs" / d["file"]
    if not path.exists():
        pytest.skip("golden filings not downloaded (python -m tests.golden.fetch)")
    from app.processing.chunk import pages_of

    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == d["sha256"]
    text = " ".join(" ".join(p.text.split()) for p in pages_of(data, d["file"]))
    for e in d.get("expected") or []:
        assert " ".join(e["key_quote"].split()) in text, e["key_quote"]
