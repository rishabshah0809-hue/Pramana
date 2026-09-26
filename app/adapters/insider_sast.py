"""Insider trading (SEBI PIT, Regulation 7) and SAST disclosures from NSE's official RSS
feeds (trust tier 1).

Feeds: Insider Trading, SAST Regulation 29 (acquisitions) and SAST Regulation 31
(promoter encumbrance). BSE's insider and SAST items arrive in its Corporate Announcements
feed and are tagged by the announcements adapter. Files are stored and shown as filed;
turning them into buy/sell signals is Milestone 3.
"""

from app.adapters.feeds import Feed
from app.services import filings, ingest

SOURCE_ID = "insider_sast"
NSE_RSS = "https://nsearchives.nseindia.com/content/RSS/"

FEEDS = [
    Feed("nse_insider_trading", "NSE", NSE_RSS + "InsiderTrading.xml",
         "NSE Insider Trading feed", "insider"),
    Feed("nse_sast_reg29", "NSE", NSE_RSS + "Sast_Regulation29.xml",
         "NSE SAST Regulation 29 feed", "sast"),
    Feed("nse_sast_reg31", "NSE", NSE_RSS + "Sast_Regulation31.xml",
         "NSE SAST Regulation 31 (encumbrance) feed", "pledge"),
]


def run(client=None, now=None) -> ingest.RunSummary:
    return ingest.run_feeds(SOURCE_ID, FEEDS, filings.classify, client=client, now=now)
