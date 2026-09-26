"""Free-tier limits, respected automatically (brief Section 3).

Usage is counted from the audit log's record of every AI call (step 9). Before each call the
app checks the model's per-minute and per-day request and token limits (with a safety
margin). A per-minute limit means "wait a moment"; a per-day limit means "stop and resume
at <time>". A provider's own "slow down" answer blocks that model until the time it names.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import load_config
from app.store import db
from app.timeutil import from_iso, now_utc, to_iso

PACIFIC = ZoneInfo("America/Los_Angeles")


@dataclass
class Verdict:
    ok: bool
    wait_seconds: float = 0.0        # a per-minute limit: fine after a short wait
    resume_at: datetime | None = None  # a per-day limit or a provider block
    reason: str = ""


def model_limits(model: str, cfg: dict | None = None) -> dict:
    ai = (cfg or load_config())["ai"]
    lim = dict(ai.get("limits", {}).get(model) or {})
    lim["margin"] = float(ai.get("safety_margin", 0.9))
    return lim


def _num(value) -> float | None:
    return None if value in (None, "") else float(value)


def day_start(model: str, now: datetime, lim: dict) -> datetime:
    if lim.get("day") == "pacific_midnight":
        local = now.astimezone(PACIFIC)
        return local.replace(hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(hours=24)


def day_resets_at(model: str, now: datetime, lim: dict, calls: list) -> datetime:
    if lim.get("day") == "pacific_midnight":
        return day_start(model, now, lim) + timedelta(days=1)
    return from_iso(calls[0][0]) + timedelta(hours=24) if calls else now


def _calls(model: str, since: datetime) -> list[tuple[str, int, str, str | None, int]]:
    """(time, tokens used, outcome, blocked_until, tokens reserved) for every call since `since`.
    Providers count a call's reserved answer length against per-minute limits, so the minute
    window uses the larger of used and reserved."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT timestamp, after FROM audit_log WHERE action = 'llm_call' AND timestamp >= ? "
            "AND json_extract(after, '$.model') = ? ORDER BY timestamp",
            (to_iso(since), model)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        a = json.loads(r["after"])
        out.append((r["timestamp"], int(a.get("tokens_in") or 0) + int(a.get("tokens_out") or 0),
                    a.get("outcome", "ok"), a.get("blocked_until"),
                    int(a.get("tokens_reserved") or 0)))
    return out


def usage(model: str, now: datetime | None = None) -> dict:
    now = now or now_utc()
    lim = model_limits(model)
    day = _calls(model, min(day_start(model, now, lim), now - timedelta(minutes=1)))
    day = [c for c in day if from_iso(c[0]) >= day_start(model, now, lim)]
    minute = [c for c in day if from_iso(c[0]) >= now - timedelta(minutes=1)]
    return {"model": model, "requests_day": len(day), "tokens_day": sum(c[1] for c in day),
            "requests_min": len(minute), "tokens_min": sum(max(c[1], c[4]) for c in minute),
            "errors_day": sum(c[2] not in ("ok", "invalid_output") for c in day),
            "limits": lim, "calls": day}


def check(model: str, est_tokens: int, now: datetime | None = None) -> Verdict:
    now = now or now_utc()
    lim = model_limits(model)
    u = usage(model, now)
    m = lim["margin"]
    for _, _, _, blocked, _ in reversed(u["calls"]):
        if blocked and from_iso(blocked) > now:
            return Verdict(False, resume_at=from_iso(blocked),
                           reason=f"{model} asked the app to slow down")
        if blocked:
            break
    rpd, tpd = _num(lim.get("rpd")), _num(lim.get("tpd"))
    if rpd is not None and u["requests_day"] + 1 > rpd * m:
        return Verdict(False, resume_at=day_resets_at(model, now, lim, u["calls"]),
                       reason=f"{model} daily request limit reached")
    if tpd is not None and u["tokens_day"] + est_tokens > tpd * m:
        return Verdict(False, resume_at=day_resets_at(model, now, lim, u["calls"]),
                       reason=f"{model} daily token limit reached")
    rpm, tpm = _num(lim.get("rpm")), _num(lim.get("tpm"))
    if (rpm is not None and u["requests_min"] + 1 > rpm * m) or \
            (tpm is not None and u["tokens_min"] + est_tokens > tpm * m):
        return Verdict(False, wait_seconds=61.0, reason=f"{model} per-minute limit reached")
    return Verdict(True)


def estimate_tokens(text: str, max_output: int) -> int:
    """A cautious guess (about 3.5 characters per token) plus the reserved answer length."""
    return int(len(text) / 3.5) + max_output
