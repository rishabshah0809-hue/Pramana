"""Company announcements from the exchanges' official RSS feeds (trust tier 1).

NSE: Announcements, Financial Results, Board Meetings, Annual Reports and Integrated Filing
(Financials) feeds. BSE: the Corporate Announcements feed, which carries every item's BSE
code. The filing type comes from fixed keyword rules on the exchange's own subject line
(app/services/filings.classify) — no AI.

BSE items also include insider (Reg 7) and SAST disclosures; they are tagged as such here,
so the BSE feed is downloaded only once per check.
"""

import re

from app.adapters.feeds import Feed
from app.services import filings, ingest

SOURCE_ID = "announcements"
NSE_RSS = "https://nsearchives.nseindia.com/content/RSS/"

FEEDS = [
    Feed("nse_announcements", "NSE", NSE_RSS + "Online_announcements.xml",
         "NSE Announcements feed", None),
    Feed("nse_financial_results", "NSE", NSE_RSS + "Financial_Results.xml",
         "NSE Financial Results feed", "results"),
    Feed("nse_board_meetings", "NSE", NSE_RSS + "Board_Meetings.xml",
         "NSE Board Meetings feed", "board_meeting"),
    Feed("nse_annual_reports", "NSE", NSE_RSS + "Annual_Reports.xml",
         "NSE Annual Reports feed", "annual_report"),
    Feed("nse_integrated_financials", "NSE", NSE_RSS + "Integrated_Filing_Financials.xml",
         "NSE Integrated Filing (Financials) feed", "results"),
    Feed("bse_announcements", "BSE", "https://www.bseindia.com/data/xml/announcements.xml",
         "BSE Corporate Announcements feed", None),
]

# The BSE feed is mostly mutual-fund NAV notices and debt items. Once BSE's list of scrips
# is uploaded, only codes on it are kept. Before that, six-digit codes starting with 5 are
# kept (the equity range, which mutual-fund schemes also use), minus NAV notices.
_BSE_EQUITY_CODE = re.compile(r"^5\d{5}$")
_NAV_NOTICE = re.compile(r"^\s*nav\b", re.IGNORECASE)


def keep(feed: Feed, item, matcher) -> bool:
    if feed.exchange != "BSE":
        return True
    code = item.scripcode or ""
    if matcher.by_bse:
        return code in matcher.by_bse
    return bool(_BSE_EQUITY_CODE.match(code)) and not _NAV_NOTICE.match(item.description or "")


def run(exchange: str | None = None, client=None, now=None) -> ingest.RunSummary:
    feeds = [f for f in FEEDS if exchange is None or f.exchange == exchange]
    return ingest.run_feeds(SOURCE_ID, feeds, filings.classify, keep=keep, client=client, now=now)
