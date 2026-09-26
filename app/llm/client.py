"""LLMClient: the one way the app talks to an AI model (brief Sections 6 and 8).

- Provider, model, temperature and limits come from config.yaml (ai.tasks, ai.limits).
- Prompts are versioned files in app/llm/prompts/ (<name>_<version>.md), never inline.
- Privacy guardrail: a prompt can only be filled with PublicText (built from passages of
  stored public filings) or ClaimText (a claim an AI extracted from such a passage). Plain
  strings — such as a future thesis note or user weight — are refused before any call.
- Every call is written to the audit log: provider, model, prompt version, input hash,
  output, outcome, tokens and time (step 9). The validation result is logged separately
  when the code checks the answer (log_validation).
"""

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from app.adapters.registry import AI_PROVIDERS, MANUAL_FILING_SOURCE, SOURCES
from app.config import load_config
from app.errors import FriendlyError
from app.llm import limits
from app.llm.backends import BACKENDS, LLMFailure
from app.llm.schemas import SCHEMAS
from app.services import audit
from app.store import db
from app.timeutil import fmt_ist, now_utc, to_iso

log = logging.getLogger("mosaic.llm")
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
# Document sources whose text is public: the exchange adapters and filings the owner
# downloaded from the exchanges' websites.
PUBLIC_SOURCES = frozenset(set(SOURCES) | {MANUAL_FILING_SOURCE})
_TOKEN = object()


class PrivateDataError(FriendlyError):
    def __init__(self, what: str):
        super().__init__(f"Blocked: the app tried to send {what} to an AI provider.",
                         "Only public filing text may be sent. This is a safety stop; tell "
                         "Claude which screen you were on.")


class PublicText:
    """Text that is safe to send: passages of stored public filings, with their chunk IDs."""

    def __init__(self, blocks: list[tuple[int, int | None, str]], _token=None):
        if _token is not _TOKEN:
            raise PrivateDataError("text that did not come from a stored public filing")
        self.blocks = blocks  # (passage id, page, text)

    @classmethod
    def from_passages(cls, passage_ids: list[int]) -> "PublicText":
        conn = db.connect()
        try:
            rows = conn.execute(
                f"SELECT p.id, p.page, p.text, d.source FROM passages p JOIN documents d "
                f"ON d.id = p.document_id WHERE p.id IN ({','.join('?' * len(passage_ids))})",
                passage_ids).fetchall()
        finally:
            conn.close()
        by_id = {r["id"]: r for r in rows}
        missing = [p for p in passage_ids if p not in by_id]
        if missing or not passage_ids:
            raise PrivateDataError("a passage that isn't in the document store")
        for r in rows:
            if r["source"] not in PUBLIC_SOURCES:
                raise PrivateDataError(f"text from a non-public source ({r['source']})")
        return cls([(i, by_id[i]["page"], by_id[i]["text"]) for i in passage_ids], _TOKEN)

    def ids(self) -> list[int]:
        return [b[0] for b in self.blocks]

    def render(self) -> str:
        return "\n\n".join(f"[CHUNK {pid}]" + (f" (page {page})" if page else "") + f"\n{text}"
                           for pid, page, text in self.blocks)


class ClaimText:
    """A claim an AI extracted from a public passage (used only for the cross-check)."""

    def __init__(self, text: str, source: PublicText, _token=None):
        if _token is not _TOKEN or not isinstance(source, PublicText):
            raise PrivateDataError("a claim that was not extracted from a public filing")
        self.text = " ".join(text.split())

    @classmethod
    def from_extraction(cls, claim: str, source: PublicText) -> "ClaimText":
        return cls(claim, source, _TOKEN)

    def render(self) -> str:
        return self.text


@dataclass
class Prompt:
    name: str
    version: str
    system: str
    user: str

    @property
    def label(self) -> str:
        return f"{self.name}_{self.version}"


def load_prompt(name: str, version: str | None = None) -> Prompt:
    version = version or load_config()["ai"]["prompts"][name]
    path = PROMPT_DIR / f"{name}_{version}.md"
    if not path.exists():
        raise FriendlyError(f"The AI instructions file '{path.name}' is missing.",
                            "Restore app/llm/prompts/ from GitHub, or fix ai.prompts in "
                            "config.yaml.")
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"^## (SYSTEM|USER)\s*$", text, flags=re.MULTILINE)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return Prompt(name, version, sections["SYSTEM"], sections["USER"])


@dataclass
class LLMResult:
    call_id: int
    provider: str
    model: str
    prompt: Prompt
    parsed: object | None          # the validated Pydantic object, or None if invalid
    raw_text: str
    problem: str | None = None     # why parsed is None


class AIUnavailable(FriendlyError):
    """No provider could take the call now (limits, outages, keys). Work stays queued."""

    def __init__(self, reasons: list[str], resume_at: datetime | None):
        when = f" It will try again after {fmt_ist(resume_at)}." if resume_at else ""
        super().__init__("The AI step is waiting: " + "; ".join(reasons) + "." + when,
                         "Nothing to do — the work stays in the queue and resumes by itself. "
                         "Data Health shows the queue.")
        self.reasons = reasons
        self.resume_at = resume_at


def _record_call(provider, model, prompt: Prompt, task, input_hash, output, outcome,
                 tokens_in=0, tokens_out=0, blocked_until=None, message=None,
                 reserved=0) -> int:
    conn = db.connect()
    try:
        with conn:
            audit.log(conn, "ai", "llm_call", f"{task}:{prompt.label}", after={
                "provider": provider, "model": model, "prompt_version": prompt.label,
                "input_hash": input_hash, "output": output, "outcome": outcome,
                "tokens_in": tokens_in, "tokens_out": tokens_out,
                "blocked_until": blocked_until, "message": message,
                "tokens_reserved": reserved})
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()


def log_validation(call_id: int, result: dict) -> None:
    """Step 9: the code's verdict on a call's output, linked to the call."""
    conn = db.connect()
    try:
        with conn:
            audit.log(conn, "system", "llm_validation", f"audit_log:{call_id}", after=result)
    finally:
        conn.close()


def call(task: str, prompt_name: str, parts: dict, exclude_provider: str | None = None,
         now=None, sleep=time.sleep) -> LLMResult:
    """Run one AI task. Raises AIUnavailable if no allowed provider can answer right now."""
    for key, value in parts.items():
        if not isinstance(value, (PublicText, ClaimText)):
            raise PrivateDataError(f"'{key}' as plain text")
    cfg = load_config()
    prompt = load_prompt(prompt_name)
    user = prompt.user.format(**{k: v.render() for k, v in parts.items()})
    input_hash = hashlib.sha256((prompt.label + "\n" + prompt.system + "\n" + user)
                                .encode("utf-8")).hexdigest()
    model_cls, schema = SCHEMAS[prompt_name]
    default_max = int(cfg["ai"].get("processing", {}).get("max_output_tokens", 2000))
    reasons, resume = [], []
    for role in ("primary", "fallback"):
        spec = cfg["ai"]["tasks"][task].get(role)
        if not spec or spec["provider"] == exclude_provider:
            continue
        provider, model = spec["provider"], spec["model"]
        max_out = int(spec.get("max_output_tokens", default_max))
        est = limits.estimate_tokens(prompt.system + user, max_out)
        verdict = limits.check(model, est, now)
        if not verdict.ok and verdict.wait_seconds and verdict.wait_seconds <= 65:
            sleep(verdict.wait_seconds)
            verdict = limits.check(model, est)
        if not verdict.ok:
            reasons.append(verdict.reason)
            if verdict.resume_at:
                resume.append(verdict.resume_at)
            continue
        try:
            raw = BACKENDS[provider](model, prompt.system, user, schema, prompt_name,
                                     float(spec.get("temperature", 0)), max_out,
                                     spec.get("thinking_level"))
        except LLMFailure as exc:
            blocked = None
            if exc.kind == "rate_limited":
                until = now_utc() + timedelta(seconds=exc.retry_after or 60)
                if exc.per_day:
                    lim = limits.model_limits(model, cfg)
                    until = max(until, limits.day_resets_at(model, now_utc(), lim, []))
                blocked = to_iso(until)
                resume.append(until)
            call_id = _record_call(provider, model, prompt, task, input_hash, None, exc.kind,
                                   blocked_until=blocked, message=exc.message, reserved=est)
            log.warning("AI call failed (%s %s): %s", provider, model, exc.message)
            if exc.kind == "invalid_output":
                return LLMResult(call_id, provider, model, prompt, None, "", exc.message)
            reasons.append(f"{AI_PROVIDERS[provider].name}: {exc.message}")
            continue
        try:
            parsed = model_cls.model_validate_json(raw.text)
            problem, outcome = None, "ok"
        except ValidationError as exc:
            parsed, outcome = None, "invalid_output"
            problem = f"The answer did not match the required format ({exc.error_count()} problem(s))."
        call_id = _record_call(provider, model, prompt, task, input_hash, raw.text, outcome,
                               raw.tokens_in, raw.tokens_out, reserved=est)
        return LLMResult(call_id, provider, model, prompt, parsed, raw.text, problem)
    raise AIUnavailable(reasons or ["no AI provider is set up for this task"],
                        min(resume) if resume else None)
