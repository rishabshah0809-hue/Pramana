"""Step c — Validate in code. Nothing an AI returns is saved until it passes every check here.

An item is rejected if:
- it doesn't match the required format (JSON / schema),
- it cites a chunk it wasn't given,
- its quote isn't found verbatim in the chunk (owner's rules, 26 Sep 2026: every character
  must match exactly, except that runs of spaces and line breaks count as one space, hyphen
  variants count as "-" and curly single quotes as "'"),
- any number in the claim isn't in the quote (compared as exact decimals, 14.6:
  "1,21,92,125" equals "12192125"; "17.47 crore" does not equal "17,47,13,151"),
- the company can't be matched by exact name (14.4). A close-but-not-exact name is kept as a
  suggestion for the owner's review queue, never accepted automatically.
"""

import difflib
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from app.llm.schemas import ExtractedItem
from app.services.matching import Matcher, norm_name

MIN_QUOTE_WORDS = 3
_NUMBER = re.compile(r"(?<![\w])(\d[\d,]*(?:\.\d+)?)")


# Owner's rule (26 Sep 2026): typographic variants are rendering artifacts, not content.
# Hyphen variants count as "-" and curly single quotes as "'" (one character for one).
_TYPOGRAPHIC = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u00ad": "-",
                              "\u2018": "'", "\u2019": "'", "\u02bc": "'", "\u2032": "'"})


def _collapse(text: str) -> tuple[str, list[int]]:
    """Text with each run of whitespace turned into one space, plus where each character came from."""
    out, where, in_space = [], [], False
    text = text.translate(_TYPOGRAPHIC)
    for i, ch in enumerate(text):
        if ch.isspace():
            if not in_space and out:
                out.append(" ")
                where.append(i)
            in_space = True
        else:
            out.append(ch)
            where.append(i)
            in_space = False
    return "".join(out), where


def find_verbatim(quote: str, text: str) -> tuple[int, int] | None:
    """(start, end) of the quote in the original text, or None if it isn't there."""
    q = " ".join(quote.translate(_TYPOGRAPHIC).split())
    if not q:
        return None
    collapsed, where = _collapse(text)
    i = collapsed.find(q)
    if i < 0:
        return None
    return where[i], where[i + len(q) - 1] + 1


def numbers_in(text: str) -> list[Decimal]:
    out = []
    for m in _NUMBER.finditer(text or ""):
        raw = m.group(1).rstrip(",").replace(",", "")
        try:
            out.append(Decimal(raw))
        except InvalidOperation:
            continue
    return out


def missing_numbers(claim: str, quote: str) -> list[str]:
    have = set(numbers_in(quote))
    return [f"{n:f}" for n in numbers_in(claim) if n not in have]


@dataclass
class Validation:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    item: ExtractedItem | None = None
    span: tuple[int, int] | None = None     # quote position in the passage text
    company: str | None = None              # ISIN
    suggestion: str | None = None           # ISIN suggested for the owner's review (14.4)


def suggest_company(name: str, conn) -> str | None:
    rows = conn.execute("SELECT isin, name FROM companies").fetchall()
    names = {norm_name(r["name"]): r["isin"] for r in rows}
    close = difflib.get_close_matches(norm_name(name), list(names), n=1, cutoff=0.85)
    return names[close[0]] if close else None


def validate_item(raw: dict, passages: dict[int, str], doc_company: str | None, matcher: Matcher,
                  conn=None) -> Validation:
    """passages: {chunk id: chunk text} that were sent with the call."""
    try:
        item = ExtractedItem.model_validate(raw)
    except ValidationError as exc:
        fields = sorted({str(e["loc"][0]) for e in exc.errors() if e.get("loc")})
        return Validation(False, [f"Not in the required format (fields: {', '.join(fields) or '?'})"])
    reasons: list[str] = []
    text = passages.get(item.chunk_id)
    span = None
    if text is None:
        reasons.append(f"Cites chunk {item.chunk_id}, which it was not given")
    else:
        span = find_verbatim(item.quote, text)
        if span is None:
            reasons.append("The quote is not found word-for-word in the chunk")
    if len(item.quote.split()) < MIN_QUOTE_WORDS:
        reasons.append(f"The quote is shorter than {MIN_QUOTE_WORDS} words")
    missing = missing_numbers(item.claim, item.quote)
    if missing:
        reasons.append("Numbers in the claim are not in the quote: " + ", ".join(missing))

    company, suggestion = doc_company, None
    if item.company_mentioned and item.company_mentioned.strip():
        found, _ = matcher.match(name=item.company_mentioned)
        if found:
            company = found
        else:
            company = None
            if conn is not None:
                suggestion = suggest_company(item.company_mentioned, conn)
            reasons.append(f"Company '{item.company_mentioned}' could not be matched exactly"
                           + (" (a possible match was sent to your review queue)"
                              if suggestion else ""))
    if company is None and not reasons:
        reasons.append("The document is not linked to a company")
    return Validation(not reasons, reasons, item, span, company, suggestion)
