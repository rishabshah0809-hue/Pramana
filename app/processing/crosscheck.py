"""Step d — Cross-check: a second model is asked ONLY "Does this passage support this claim?
Yes, partly or no?". It must be a different provider from the one that extracted the claim."""

from dataclasses import dataclass

from app.llm import client


@dataclass
class CrossCheck:
    answer: str | None       # yes | partly | no | None (no checker available)
    provider: str | None
    model: str | None
    call_id: int | None
    note: str


def crosscheck(passage_id: int, claim: str, extractor_provider: str) -> CrossCheck:
    public = client.PublicText.from_passages([passage_id])
    claim_text = client.ClaimText.from_extraction(claim, public)
    try:
        r = client.call("crosscheck", "crosscheck", {"passage": public, "claim": claim_text},
                        exclude_provider=extractor_provider)
    except client.AIUnavailable as exc:
        return CrossCheck(None, None, None, None, exc.message)
    if r.parsed is None:
        return CrossCheck(None, r.provider, r.model, r.call_id,
                          f"The checker's answer was unusable: {r.problem}")
    return CrossCheck(r.parsed.answer, r.provider, r.model, r.call_id,
                      f"{r.model} answered '{r.parsed.answer}'")
