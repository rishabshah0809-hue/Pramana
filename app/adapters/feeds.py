"""Reads the exchanges' official RSS feeds (NSE and BSE publish these for feed readers).

The feed file itself is stored before it is read (rawstore). A feed that no longer looks
like RSS — for example a web page sent instead of the feed — raises FeedFormatError so the
Data Health page can flag the adapter instead of the app crashing.
"""

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

from defusedxml import ElementTree as SafeET

from app.errors import FriendlyError
from app.timeutil import IST


@dataclass(frozen=True)
class Feed:
    id: str
    exchange: str            # NSE | BSE
    url: str
    label: str               # shown on screen, e.g. "NSE Insider Trading feed"
    category: str | None     # fixed category, or None = decide from the subject line


@dataclass(frozen=True)
class FeedItem:
    title: str               # the company name, as the exchange wrote it
    link: str | None         # the filing's own file
    description: str | None  # the exchange's subject line
    pub_raw: str | None      # published time exactly as written
    scripcode: str | None    # BSE scrip code (BSE feed only)


class FeedFormatError(FriendlyError):
    def __init__(self, label: str, detail: str):
        super().__init__(
            f"The {label} has changed its format ({detail}), so new items could not be read.",
            "Nothing is lost: earlier filings are still here and the raw file was saved. "
            "Data Health shows this until it is fixed. If it lasts more than a day, tell Claude.")


def _text(el, tag: str) -> str | None:
    child = el.find(tag)
    if child is None or child.text is None:
        return None
    value = " ".join(child.text.split())
    return value or None


def parse_rss(content: bytes, label: str) -> tuple[list[FeedItem], int]:
    """Returns (valid items, items received). Items without a company name are dropped."""
    try:
        root = SafeET.fromstring(content)
    except Exception as exc:  # noqa: BLE001 — any parse failure means the format changed
        raise FeedFormatError(label, "the file is not valid XML") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise FeedFormatError(label, "it is no longer an RSS feed")
    raw_items = root.find("channel").findall("item")
    items = []
    for it in raw_items:
        title = _text(it, "title")
        if not title:
            continue
        items.append(FeedItem(title=title, link=_text(it, "link"),
                              description=_text(it, "description"),
                              pub_raw=_text(it, "pubDate"), scripcode=_text(it, "scripcode")))
    return items, len(raw_items)


def parse_published(raw: str | None) -> datetime | None:
    """Exchange feed times. NSE and BSE announcement feeds write IST without a zone
    ("26-Sep-2026 02:11:54"); BSE notices use standard RSS dates. Anything else is Unknown."""
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=IST)
        except ValueError:
            pass
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else None


def company_from_title(title: str) -> str:
    """BSE titles end with the scrip code in brackets: 'Sharika Enterprises Ltd (540786)'."""
    t = title.strip()
    if t.endswith(")") and "(" in t:
        head, _, tail = t.rpartition("(")
        if tail[:-1].strip().isdigit():
            return head.strip()
    return t
