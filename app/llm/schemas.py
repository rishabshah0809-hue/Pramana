"""The exact shapes every AI answer must have (brief Section 8: Pydantic validates all AI output).

Each Pydantic model has a matching plain JSON schema, written out by hand so it meets
Groq's strict mode (every field required, no extra fields) and Gemini's JSON mode.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SIGNAL_TYPES = {
    "management_guidance": "Management guidance",
    "demand_commentary": "Demand commentary",
    "cost_margin": "Cost and margin",
    "capex_expansion": "Capex and expansion",
    "governance_red_flag": "Governance red flag",
    "ownership_change": "Ownership change",
    "order_win": "Order win or contract",
    "credit_rating": "Credit rating action",
    "regulatory_legal": "Regulatory or legal",
    "tone_shift": "Tone shift",
    # Brief amendment A1 (owner, 26 Sep 2026): reported results had no type in Section 5.
    "financial_results": "Financial results",
}
# 14.15: what kind of statement it is. "Verified" only proves the quote exists.
CLAIM_TYPES = {
    "fact": "Fact", "reported_metric": "Reported metric", "company_claim": "Company claim",
    "guidance": "Guidance", "target": "Target", "commitment": "Commitment",
    "forecast": "Forecast", "opinion": "Opinion", "market_pricing": "Market pricing",
}
DIRECTIONS = ("positive", "negative", "neutral")

SignalType = Literal[tuple(SIGNAL_TYPES)]  # type: ignore[valid-type]
ClaimType = Literal[tuple(CLAIM_TYPES)]    # type: ignore[valid-type]


class ExtractedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: int
    signal_type: SignalType
    direction: Literal["positive", "negative", "neutral"]
    strength: int = Field(ge=1, le=5)
    claim_type: ClaimType
    claim: str = Field(min_length=5, max_length=400)
    quote: str = Field(min_length=5, max_length=1500)
    company_mentioned: str | None


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ExtractedItem]


class CrossCheckOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: Literal["yes", "partly", "no"]


class SummarySentence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    chunk_ids: list[int]


class SummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sentences: list[SummarySentence]


def _obj(props: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(props),
            "properties": props}


EXTRACTION_SCHEMA = _obj({"items": {"type": "array", "items": _obj({
    "chunk_id": {"type": "integer"},
    "signal_type": {"type": "string", "enum": list(SIGNAL_TYPES)},
    "direction": {"type": "string", "enum": list(DIRECTIONS)},
    "strength": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
    "claim_type": {"type": "string", "enum": list(CLAIM_TYPES)},
    "claim": {"type": "string"},
    "quote": {"type": "string"},
    "company_mentioned": {"type": ["string", "null"]},
})}})
CROSSCHECK_SCHEMA = _obj({"answer": {"type": "string", "enum": ["yes", "partly", "no"]}})
SUMMARY_SCHEMA = _obj({"sentences": {"type": "array", "items": _obj({
    "text": {"type": "string"},
    "chunk_ids": {"type": "array", "items": {"type": "integer"}},
})}})

SCHEMAS = {
    "extract": (ExtractionOutput, EXTRACTION_SCHEMA),
    "crosscheck": (CrossCheckOutput, CROSSCHECK_SCHEMA),
    "summarize": (SummaryOutput, SUMMARY_SCHEMA),
}
