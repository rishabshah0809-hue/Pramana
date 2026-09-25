"""Reads NSE's "Securities available for trading" equity list (EQUITY_L.csv).

The app never downloads this file: NSE's terms forbid automated collection. The owner
downloads it in their browser and uploads it on the Company list page.
"""

import csv
import io
import re
from dataclasses import dataclass

from app.errors import FriendlyError

DOWNLOAD_PAGE = "https://www.nseindia.com/market-data/securities-available-for-trading"
REQUIRED = ("SYMBOL", "NAME OF COMPANY", "ISIN NUMBER")
_ISIN_SHAPE = re.compile(r"^IN[A-Z0-9]{9}[0-9]$")


@dataclass(frozen=True)
class ListedCompany:
    isin: str
    nse_symbol: str
    name: str
    series: str | None


def isin_is_valid(isin: str) -> bool:
    """Shape check plus the ISO 6166 check digit."""
    if not _ISIN_SHAPE.match(isin):
        return False
    digits = "".join(str(int(c, 36)) for c in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10 == int(isin[-1])


def parse(content: bytes) -> tuple[list[ListedCompany], list[str]]:
    """Returns (companies, problems). Raises FriendlyError if it isn't the NSE file."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip().upper() for h in next(reader)]
    except StopIteration:
        raise FriendlyError("The uploaded file is empty.",
                            "Download EQUITY_L.csv again from NSE and upload that file.")
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise FriendlyError(
            "This doesn't look like NSE's equity list (columns missing: "
            + ", ".join(missing) + ").",
            "On the NSE page, download 'Securities available for Equity segment "
            "(.csv)' — the file is called EQUITY_L.csv — and upload it without editing it.",
        )
    idx = {c: header.index(c) for c in header}
    companies, problems, seen = [], [], set()
    for line_no, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        try:
            isin = row[idx["ISIN NUMBER"]].strip().upper()
            symbol = row[idx["SYMBOL"]].strip().upper()
            name = row[idx["NAME OF COMPANY"]].strip()
            series = row[idx["SERIES"]].strip().upper() if "SERIES" in idx else None
        except IndexError:
            problems.append(f"Line {line_no}: row is incomplete, skipped.")
            continue
        if not isin_is_valid(isin):
            problems.append(f"Line {line_no}: '{isin}' is not a valid ISIN, skipped.")
            continue
        if not symbol or not name:
            problems.append(f"Line {line_no}: symbol or name is blank, skipped.")
            continue
        if isin in seen:
            problems.append(f"Line {line_no}: ISIN {isin} appears twice, second copy skipped.")
            continue
        seen.add(isin)
        companies.append(ListedCompany(isin, symbol, name, series or None))
    if not companies:
        raise FriendlyError("No valid companies were found in the file.",
                            "Download EQUITY_L.csv again from NSE and upload it unedited.")
    return companies, problems
