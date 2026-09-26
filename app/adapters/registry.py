"""Every data source the app uses, and every internet host it may contact (brief 14.12).

A test checks that each host listed here also appears in DATA_SOURCES.md, and the
network guard (app/net.py) refuses any host that is not listed here.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    tier: int
    hosts: tuple[str, ...]
    terms_status: str
    terms_checked: str
    automated: bool  # False = the owner supplies the file by hand


NSE_HOSTS = ("nsearchives.nseindia.com", "archives.nseindia.com")
BSE_HOSTS = ("www.bseindia.com",)
FEED_TERMS = ("Official RSS feeds, published for automatic feed readers. Filing files are "
              "downloaded for watchlist companies only (owner's choice, 26 Sep 2026)")

SOURCES = {
    "nse_equity_list": Source(
        id="nse_equity_list",
        name="NSE equity list (downloaded by you)",
        tier=1,
        hosts=(),  # never fetched by the app: NSE's terms forbid automated collection
        terms_status="Manual download in your browser only (NSE terms forbid automation)",
        terms_checked="2026-09-25",
        automated=False,
    ),
    "bse_scrip_list": Source(
        id="bse_scrip_list",
        name="BSE list of scrips (downloaded by you)",
        tier=1,
        hosts=(),  # never fetched by the app: BSE's site is for personal, manual use
        terms_status="Manual download in your browser only",
        terms_checked="2026-09-26",
        automated=False,
    ),
    "yahoo_prices": Source(
        id="yahoo_prices",
        name="Yahoo Finance via yfinance (delayed prices)",
        tier=2,
        hosts=("query1.finance.yahoo.com", "query2.finance.yahoo.com",
               "fc.yahoo.com", "guce.yahoo.com", "consent.yahoo.com"),
        terms_status="Conflicts with Yahoo's terms (automated access); used by owner's "
                     "choice until Angel One is connected",
        terms_checked="2026-09-25",
        automated=True,
    ),
    "announcements": Source(
        id="announcements",
        name="Company announcements (NSE and BSE feeds)",
        tier=1,
        hosts=NSE_HOSTS + BSE_HOSTS,
        terms_status=FEED_TERMS,
        terms_checked="2026-09-26",
        automated=True,
    ),
    "shareholding": Source(
        id="shareholding",
        name="Shareholding patterns and pledges (NSE feeds)",
        tier=1,
        hosts=NSE_HOSTS,
        terms_status=FEED_TERMS,
        terms_checked="2026-09-26",
        automated=True,
    ),
    "insider_sast": Source(
        id="insider_sast",
        name="Insider trading and SAST disclosures (NSE feeds)",
        tier=1,
        hosts=NSE_HOSTS,
        terms_status=FEED_TERMS,
        terms_checked="2026-09-26",
        automated=True,
    ),
    "bulk_block": Source(
        id="bulk_block",
        name="Bulk and block deals (NSE daily files)",
        tier=1,
        hosts=("nsearchives.nseindia.com",),
        terms_status="Conflicts with NSE's terms (automated download of a daily report); "
                     "used by owner's choice on 26 Sep 2026",
        terms_checked="2026-09-26",
        automated=True,
    ),
}

# Filings that the owner downloads and uploads by hand (Document Viewer).
MANUAL_FILING_SOURCE = "manual_upload"


def allowed_hosts() -> set[str]:
    return {h for s in SOURCES.values() for h in s.hosts}
