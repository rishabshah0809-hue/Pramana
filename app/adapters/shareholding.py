"""Shareholding patterns and promoter pledges from NSE's official RSS feeds (trust tier 1).

Feeds: Shareholding Pattern (links to each filing's XBRL file) and Reason for Encumbrance
(pledges). For watchlist companies the XBRL file is stored raw, then read by code — no AI —
for promoter, FII, DII and public holdings. Values are kept as exact decimals next to the
text they came from (14.6). Anything not found in the file is stored as Unknown.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree as SafeET

from app.adapters.feeds import Feed
from app.errors import FriendlyError
from app.services import filings, ingest

SOURCE_ID = "shareholding"
NSE_RSS = "https://nsearchives.nseindia.com/content/RSS/"

FEEDS = [
    Feed("nse_shareholding", "NSE", NSE_RSS + "Shareholding_Pattern.xml",
         "NSE Shareholding Pattern feed", "shareholding"),
    Feed("nse_encumbrance", "NSE", NSE_RSS + "Sast_ReasonForEncumbrance.xml",
         "NSE Reason for Encumbrance feed", "pledge"),
]

# XBRL category member -> our category. From the SEBI/BSE "in-bse-shp" taxonomy, checked
# against a real NSE filing on 26 Sep 2026.
CATEGORIES = {
    "promoter": "ShareholdingOfPromoterAndPromoterGroupMember",
    "public": "PublicShareholdingMember",
    "fii": "InstitutionsForeignMember",
    "dii": "InstitutionsDomesticMember",
    "non_institutions": "NonInstitutionsMember",
    "government": "GovernmentsMember",
}
CATEGORY_LABELS = {"promoter": "Promoter & promoter group", "public": "Public (total)",
                   "fii": "Foreign institutions (FII/FPI)", "dii": "Domestic institutions (DII)",
                   "non_institutions": "Non-institutions (retail, corporates, others)",
                   "government": "Government", "promoter_pledged": "Promoter shares pledged"}
_TOTAL = "ShareholdingPatternMember"
_PERCENT = "ShareholdingAsAPercentageOfTotalNumberOfShares"
_PLEDGE_FLAG = "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged"
_XBRLI = "{http://www.xbrl.org/2003/instance}"
_XBRLDI = "{http://xbrl.org/2006/xbrldi}"


@dataclass
class ShpValue:
    category: str
    percent: Decimal | None     # in percent (49.13), None = Unknown
    source_text: str            # exactly as written in the filing, or why it's unknown


@dataclass
class ShpFiling:
    isin: str | None
    nse_symbol: str | None
    bse_code: str | None
    company_name: str | None
    as_of_date: str | None
    values: list[ShpValue] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_shareholding_xbrl(content: bytes) -> bool:
    head = content[:4000]
    return b"xbrl" in head and b"shp" in head.lower()


def parse_shp(content: bytes) -> ShpFiling:
    try:
        root = SafeET.fromstring(content)
    except Exception as exc:  # noqa: BLE001
        raise FriendlyError("This shareholding file could not be read (it is not valid XBRL).",
                            "The original file is kept. Open it in the Document Viewer, or "
                            "tell Claude if this keeps happening.") from exc
    if _local(root.tag) != "xbrl":
        raise FriendlyError("This file is not a shareholding-pattern XBRL file.",
                            "Upload the XBRL (.xml) version of the shareholding pattern.")

    # Contexts with exactly one category member and no per-shareholder detail.
    member_of = {}
    for ctx in root.findall(f"{_XBRLI}context"):
        if ctx.find(f".//{_XBRLDI}typedMember") is not None:
            continue
        members = [(m.text or "").split(":")[-1] for m in ctx.findall(f".//{_XBRLDI}explicitMember")]
        if len(members) == 1:
            member_of[ctx.get("id")] = members[0]

    facts, pct_text = {}, {}
    for el in root:
        name = _local(el.tag)
        if name == _PERCENT and el.get("contextRef") in member_of:
            pct_text[member_of[el.get("contextRef")]] = (el.text or "").strip()
        elif name in ("ISIN", "Symbol", "ScripCode", "NameOfTheCompany", "DateOfReport",
                      _PLEDGE_FLAG) and name not in facts:
            facts[name] = (el.text or "").strip()

    out = ShpFiling(isin=facts.get("ISIN") or None, nse_symbol=facts.get("Symbol") or None,
                    bse_code=facts.get("ScripCode") or None,
                    company_name=facts.get("NameOfTheCompany") or None,
                    as_of_date=facts.get("DateOfReport") or None)

    # Percentages are written either as fractions of 1 or as percents; the total row says which.
    total_text = pct_text.get(_TOTAL)
    scale = None
    try:
        total = Decimal(total_text) if total_text else None
    except InvalidOperation:
        total = None
    if total == Decimal(1):
        scale = Decimal(100)
    elif total == Decimal(100):
        scale = Decimal(1)

    for cat, member in CATEGORIES.items():
        text = pct_text.get(member)
        if text is None:
            out.values.append(ShpValue(cat, None, "Not found in this filing"))
            continue
        if scale is None:
            out.values.append(ShpValue(cat, None, f"{text} (unit unclear: the total row reads "
                                                  f"'{total_text}', expected 1 or 100)"))
            continue
        try:
            out.values.append(ShpValue(cat, Decimal(text) * scale, text))
        except InvalidOperation:
            out.values.append(ShpValue(cat, None, f"'{text}' is not a number"))

    flag = facts.get(_PLEDGE_FLAG)
    if flag is not None:
        out.values.append(ShpValue("promoter_pledged", None, flag))
    return out


def store_shareholding(conn, document_id: int, content: bytes, expected_isin: str | None) -> int:
    """Read a stored SHP XBRL file and save its figures. Returns rows added."""
    from app.services import conflicts

    shp = parse_shp(content)
    if shp.isin is None:
        raise FriendlyError("The shareholding file does not say which company it is for (no "
                            "ISIN).", "Open the original file in the Document Viewer to check it.")
    known = conn.execute("SELECT 1 FROM companies WHERE isin = ?", (shp.isin,)).fetchone()
    if known is None:
        raise FriendlyError(f"The shareholding file is for ISIN {shp.isin}, which isn't in your "
                            f"company list.", "Import the latest NSE or BSE company list.")
    if expected_isin and expected_isin != shp.isin:
        raise FriendlyError(f"The shareholding file is for ISIN {shp.isin}, not the company it "
                            f"was filed under ({expected_isin}). It was stored but not used.",
                            "Open it in the Document Viewer to check which company it is for.")
    added = 0
    for v in shp.values:
        cur = conn.execute(
            "INSERT OR IGNORE INTO shareholding (company, as_of_date, category, percent, "
            "source_text, document_id) VALUES (?, ?, ?, ?, ?, ?)",
            (shp.isin, shp.as_of_date, v.category, None if v.percent is None else str(v.percent),
             v.source_text, document_id))
        added += cur.rowcount
    conflicts.check_shareholding(conn, shp.isin, shp.as_of_date)
    return added


def _on_file(document_id: int, content: bytes, filing: dict) -> None:
    if filing["category"] != "shareholding" or not is_shareholding_xbrl(content):
        return
    from app.store import db

    conn = db.connect()
    try:
        with conn:
            store_shareholding(conn, document_id, content, filing["isin"])
    finally:
        conn.close()


def run(client=None, now=None) -> ingest.RunSummary:
    return ingest.run_feeds(SOURCE_ID, FEEDS, filings.classify, on_file=_on_file, client=client,
                            now=now)
