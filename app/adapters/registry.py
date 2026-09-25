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
}


def allowed_hosts() -> set[str]:
    return {h for s in SOURCES.values() for h in s.hosts}
