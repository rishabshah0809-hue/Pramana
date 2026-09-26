"""Reads BSE's "List of Scrips" file, which the owner downloads in their browser.

The app never downloads it: BSE's website is for personal, manual use. It maps each BSE
scrip code to its ISIN, so BSE announcements can be matched to companies by exact code
(14.4), and adds companies listed only on BSE.

BSE has used slightly different column names over time, so a few spellings are accepted.
If none fits, the upload stops with a message naming the columns it needs.
"""

import csv
import io
from dataclasses import dataclass

from app.adapters.nse_equity_list import isin_is_valid
from app.errors import FriendlyError

DOWNLOAD_PAGE = "https://www.bseindia.com/corporates/List_Scrips.html"
_ALIASES = {
    "code": ("SECURITY CODE", "SCRIP CODE", "SC_CODE", "SCRIP_CD", "BSE CODE"),
    "isin": ("ISIN NO", "ISIN", "ISIN NUMBER", "ISIN_NUMBER", "ISIN CODE"),
    "name": ("ISSUER NAME", "SECURITY NAME", "COMPANY NAME", "SCRIP NAME", "SC_NAME"),
    "symbol": ("SECURITY ID", "SCRIP ID", "SCRIP_ID"),
    "status": ("STATUS",),
    "instrument": ("INSTRUMENT",),
}


@dataclass(frozen=True)
class BseScrip:
    bse_code: str
    isin: str
    name: str
    bse_symbol: str | None


def parse(content: bytes) -> tuple[list[BseScrip], list[str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip().upper() for h in next(reader)]
    except StopIteration:
        raise FriendlyError("The uploaded file is empty.",
                            "Download the List of Scrips again from BSE and upload that file.")
    idx = {}
    for key, names in _ALIASES.items():
        for n in names:
            if n in header:
                idx[key] = header.index(n)
                break
    missing = [k for k in ("code", "isin", "name") if k not in idx]
    if missing:
        need = {"code": "Security Code", "isin": "ISIN No", "name": "Issuer Name"}
        raise FriendlyError(
            "This doesn't look like BSE's List of Scrips (it needs columns like "
            + ", ".join(f"'{need[k]}'" for k in missing) + ").",
            "On BSE's List of Scrips page choose Segment: Equity and Status: Active, click the "
            "download icon, and upload the file without editing it. If it still fails, send "
            "Claude the first line of the file.")
    scrips, problems, seen = [], [], set()
    for line_no, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue
        def cell(k):
            i = idx.get(k)
            return row[i].strip() if i is not None and i < len(row) else ""
        if "instrument" in idx and cell("instrument") and cell("instrument").lower() != "equity":
            continue
        if "status" in idx and cell("status") and cell("status").lower() != "active":
            continue
        code, isin, name = cell("code"), cell("isin").upper(), cell("name")
        if not code.isdigit():
            problems.append(f"Line {line_no}: '{code}' is not a BSE code, skipped.")
            continue
        if not isin_is_valid(isin):
            problems.append(f"Line {line_no}: '{isin}' is not a valid ISIN, skipped.")
            continue
        if not name:
            problems.append(f"Line {line_no}: name is blank, skipped.")
            continue
        if code in seen:
            problems.append(f"Line {line_no}: BSE code {code} appears twice, skipped.")
            continue
        seen.add(code)
        scrips.append(BseScrip(code, isin, name, cell("symbol") or None))
    if not scrips:
        raise FriendlyError("No active equity companies were found in the file.",
                            "On BSE's page choose Segment: Equity and Status: Active, then "
                            "download and upload the file again.")
    return scrips, problems
