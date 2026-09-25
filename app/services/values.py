"""Known / Unknown / Not applicable values (brief 14.1).

An unknown value is never shown as blank, zero or "OK": it always carries a reason.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

KNOWN, UNKNOWN, NOT_APPLICABLE = "known", "unknown", "not_applicable"


@dataclass(frozen=True)
class Value:
    state: str
    value: Any = None
    reason: str | None = None
    source: str | None = None
    event_time: datetime | None = None      # when it happened / price time
    published_time: datetime | None = None  # when the source released it
    fetched_time: datetime | None = None    # when this app downloaded it

    def __post_init__(self):
        if self.state not in (KNOWN, UNKNOWN, NOT_APPLICABLE):
            raise ValueError(f"bad state {self.state}")
        if self.state == KNOWN and self.value is None:
            raise ValueError("a known value needs a value")
        if self.state != KNOWN and (self.value is not None or not self.reason):
            raise ValueError("unknown / not applicable values need a reason and no value")

    @property
    def is_known(self) -> bool:
        return self.state == KNOWN


def known(value, **kw) -> Value:
    return Value(KNOWN, value=value, **kw)


def unknown(reason: str) -> Value:
    return Value(UNKNOWN, reason=reason)


def not_applicable(reason: str) -> Value:
    return Value(NOT_APPLICABLE, reason=reason)
