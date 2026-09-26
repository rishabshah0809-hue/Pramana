"""Step b — Extract: send ONE passage to the extraction model (Groq, temperature 0, strict
JSON schema; Gemini as fallback). Returns the raw items; nothing is saved here."""

from dataclasses import dataclass

from app.llm import client


@dataclass
class Extraction:
    result: client.LLMResult
    public: client.PublicText
    items: list[dict]                  # raw items as returned, before any validation
    problem: str | None                # set when the whole answer was unusable


def extract_passage(passage_id: int) -> Extraction:
    """Raises client.AIUnavailable if no provider can take the call now."""
    public = client.PublicText.from_passages([passage_id])
    result = client.call("extraction", "extract", {"chunk": public})
    if result.parsed is None:
        return Extraction(result, public, [], result.problem or "The answer was not valid JSON")
    items = [i.model_dump() for i in result.parsed.items]
    return Extraction(result, public, items, None)
