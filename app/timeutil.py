"""Time helpers. Stored times are UTC ISO-8601 ("...Z"); shown times are IST."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def from_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def fmt_ist(dt: datetime | None, with_date: bool = True) -> str:
    if dt is None:
        return "Unknown"
    local = dt.astimezone(IST)
    return local.strftime("%d %b %Y, %H:%M IST" if with_date else "%H:%M IST")


def _hhmm(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


def is_trading_day(d: date, holidays: set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def market_is_open(now: datetime, open_: str, close: str, holidays: set[date]) -> bool:
    local = now.astimezone(IST)
    return is_trading_day(local.date(), holidays) and _hhmm(open_) <= local.time() <= _hhmm(close)


def expected_last_session(now: datetime, open_: str, holidays: set[date]) -> date:
    """The most recent trading session that has started as of `now` (IST)."""
    local = now.astimezone(IST)
    d = local.date()
    if not (is_trading_day(d, holidays) and local.time() >= _hhmm(open_)):
        d -= timedelta(days=1)
        while not is_trading_day(d, holidays):
            d -= timedelta(days=1)
    return d


def parse_holidays(values) -> set[date]:
    out = set()
    for v in values or []:
        out.add(v if isinstance(v, date) else date.fromisoformat(str(v)))
    return out
