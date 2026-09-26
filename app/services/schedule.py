"""When each exchange feed is due (settings in config.yaml, schedules section).

The scheduler ticks every 5 minutes; these functions decide which feeds a tick checks.
NSE's feeds keep only 10-20 items and ask to be re-read every 5 minutes, so they are
checked every 5 minutes on busy weekday hours and every 30 minutes otherwise (owner's
choice, 26 Sep 2026). BSE's feed: every 15 minutes in market hours, hourly otherwise.
"""

from datetime import datetime

from app.timeutil import IST, market_is_open, parse_holidays

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _day_set(spec: str) -> set[int]:
    out = set()
    for part in spec.lower().replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-")
            out |= set(range(_DAYS.index(a), _DAYS.index(b) + 1))
        elif part:
            out.add(_DAYS.index(part))
    return out


def _slot(now: datetime) -> int:
    """Minutes since midnight IST, rounded down to the 5-minute tick."""
    local = now.astimezone(IST)
    m = local.hour * 60 + local.minute
    return m - m % 5


def nse_every_minutes(now: datetime, cfg: dict) -> int:
    s = cfg["schedules"]["nse_feeds"]
    local = now.astimezone(IST)
    start, end = s["busy_hours"].split("-")
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    minute = local.hour * 60 + local.minute
    busy = local.weekday() in _day_set(s["busy_days"]) and sh * 60 + sm <= minute < eh * 60 + em
    return int(s["busy_every_minutes"] if busy else s["quiet_every_minutes"])


def bse_every_minutes(now: datetime, cfg: dict) -> int:
    s = cfg["schedules"]["bse_feed"]
    open_now = market_is_open(now, cfg["market_hours"]["open"], cfg["market_hours"]["close"],
                              parse_holidays(cfg.get("market_holidays")))
    return int(s["market_every_minutes"] if open_now else s["other_every_minutes"])


def nse_due(now: datetime, cfg: dict) -> bool:
    return _slot(now) % nse_every_minutes(now, cfg) == 0


def bse_due(now: datetime, cfg: dict) -> bool:
    return _slot(now) % bse_every_minutes(now, cfg) == 0
