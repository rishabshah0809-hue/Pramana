"""Signals built by code from structured data — no AI involved (brief 14.15: `fact`).

- Shareholding: promoter / FII / DII stake change between consecutive filings, and the
  promoter-pledge flag turning on. Source: the shareholding XBRL file.
- Insider trading: each disclosed trade in NSE's insider-trading XBRL file.
- Bulk and block deals for watchlist companies. Source: the row in NSE's daily file.

Each signal points to a passage holding the exact text it came from (the XBRL facts or the
CSV row, with offsets in the stored raw file), so it opens like any other signal. Claims are
written by code from the stored text; every number is copied, not calculated — except the
size of a shareholding change, which is exact Decimal subtraction of two filed values.
"""

import csv
import io
import re
from decimal import Decimal

from app.adapters.registry import SOURCES
from app.adapters.shareholding import CATEGORIES, CATEGORY_LABELS
from app.config import load_config
from app.services import holdings, rawstore
from app.store import db

EXTRACTION_VERSION = "code-1"
_FACT = re.compile(r"<(?:[\w-]+:)?(\w+)\s[^>]*?contextRef=\"([^\"]+)\"[^>]*>([^<]*)</[^>]+>")
_CTX = re.compile(r"<(?:\w+:)?context\s+id=\"([^\"]+)\"(.*?)</(?:\w+:)?context>", re.S)
_MEMBER = re.compile(r"explicitMember[^>]*>(?:[\w-]+:)?(\w+)<")


def _passage(conn, document_id: int, text: str, start: int, end: int) -> int:
    row = conn.execute("SELECT id FROM passages WHERE document_id = ? AND kind = 'structured' "
                       "AND char_start = ? AND char_end = ?", (document_id, start, end)).fetchone()
    if row:
        return row["id"]
    return conn.execute(
        "INSERT INTO passages (document_id, page, char_start, char_end, text, member, kind, "
        "extraction_version) VALUES (?, NULL, ?, ?, ?, NULL, 'structured', ?)",
        (document_id, start, end, text[start:end], EXTRACTION_VERSION)).lastrowid


def _save(conn, *, key, company, document_id, passage_id, quote, signal_type, direction,
          strength, claim, signal_date, source) -> bool:
    if conn.execute("SELECT 1 FROM signals WHERE dedupe_key = ?", (key,)).fetchone():
        return False
    sid = conn.execute(
        "INSERT INTO signals (company, type, direction, strength, signal_date, claim_text, "
        "passage_id, status, model, prompt_version, document_id, claim_type, quote, quote_start, "
        "quote_end, source_tier, cross_check, provider, call_id, dedupe_key) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'verified', 'code', ?, ?, 'fact', ?, 0, ?, ?, "
        "'not_needed', 'code', NULL, ?)",
        (company, signal_type, direction, strength, signal_date, claim, passage_id,
         EXTRACTION_VERSION, document_id, quote, len(quote), SOURCES.get(source).tier
         if source in SOURCES else 1, key)).lastrowid
    conn.execute("INSERT INTO signal_status (signal_id, status, reason, set_by) VALUES "
                 "(?, 'verified', 'Built by code from structured exchange data (no AI)', "
                 "'system')", (sid,))
    return True


def _members(text: str) -> dict[str, str]:
    out = {}
    for cid, body in _CTX.findall(text):
        if "typedMember" in body:
            continue
        m = _MEMBER.findall(body)
        if len(m) == 1:
            out[cid] = m[0]
    return out


def _shareholding(conn) -> int:
    threshold = Decimal(str(load_config()["ai"]["structured_signals"]
                            .get("shareholding_change_points", "0.50")))
    added = 0
    companies = [r["company"] for r in conn.execute("SELECT DISTINCT company FROM shareholding")]
    for isin in companies:
        series = holdings.series(isin)
        by_cat: dict[str, list] = {}
        for r in series:
            by_cat.setdefault(r["category"], []).append(r)
        for cat, direction_up in (("promoter", "positive"), ("fii", "positive"),
                                  ("dii", "positive"), ("promoter_pledged", None)):
            rows = [r for r in by_cat.get(cat, []) if r["as_of_date"]]
            for old, new in zip(rows, rows[1:]):
                doc = conn.execute("SELECT * FROM documents WHERE id = ?",
                                   (new["document_id"],)).fetchone()
                text = rawstore.read(doc["file_path"]).decode("utf-8", errors="replace")
                members = _members(text)
                want = "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged" \
                    if cat == "promoter_pledged" else None
                span = None
                for m in _FACT.finditer(text):
                    name, ctx = m.group(1), m.group(2)
                    if (want and name == want) or (not want and name == "ShareholdingAsAPercentageOfTotalNumberOfShares"
                                                   and members.get(ctx) == CATEGORIES[cat]):
                        span = (m.start(), m.end())
                        break
                if span is None:
                    continue
                quote = text[span[0]:span[1]]
                if cat == "promoter_pledged":
                    if not (old["source_text"].lower() == "false" and new["source_text"].lower() == "true"):
                        continue
                    claim = (f"The shareholding pattern as on {new['as_of_date']} says promoter "
                             f"shares are pledged; the filing as on {old['as_of_date']} said they "
                             f"were not.")
                    stype, direction, strength = "governance_red_flag", "negative", 3
                else:
                    if old["percent"] is None or new["percent"] is None:
                        continue
                    change = new["percent"] - old["percent"]
                    if abs(change) < threshold:
                        continue
                    claim = (f"{CATEGORY_LABELS[cat]} holding was {new['percent'].normalize():f}% "
                             f"as on {new['as_of_date']}, "
                             f"{'up' if change > 0 else 'down'} from {old['percent'].normalize():f}% "
                             f"as on {old['as_of_date']} (change {change.normalize():+f} points, "
                             f"filed values).")
                    stype = "ownership_change"
                    direction = "positive" if change > 0 else "negative"
                    strength = 3 if abs(change) >= 2 else 2
                pid = _passage(conn, doc["id"], text, *span)
                added += _save(conn, key=f"code:shp:{isin}:{cat}:{old['document_id']}:{new['document_id']}",
                               company=isin, document_id=doc["id"], passage_id=pid, quote=quote,
                               signal_type=stype, direction=direction, strength=strength,
                               claim=claim, signal_date=new["as_of_date"], source=doc["source"])
    return added


INSIDER_FIELDS = ("CategoryOfPerson", "NameOfThePerson", "TypeOfInstrument",
                  "SecuritiesAcquiredOrDisposedNumberOfSecurity",
                  "SecuritiesAcquiredOrDisposedValueOfSecurity",
                  "SecuritiesAcquiredOrDisposedTransactionType",
                  "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate",
                  "DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate",
                  "ModeOfAcquisitionOrDisposal")


def insider_trades(text: str) -> list[dict]:
    """Each trade in an insider-trading XBRL file: its fields and the text span they occupy."""
    by_ctx: dict[str, dict] = {}
    for m in _FACT.finditer(text):
        name, ctx, value = m.group(1), m.group(2), m.group(3).strip()
        if name in INSIDER_FIELDS:
            t = by_ctx.setdefault(ctx, {"start": m.start(), "end": m.end()})
            t[name] = value
            t["start"], t["end"] = min(t["start"], m.start()), max(t["end"], m.end())
    return [t for t in by_ctx.values()
            if t.get("SecuritiesAcquiredOrDisposedTransactionType")
            and t.get("SecuritiesAcquiredOrDisposedNumberOfSecurity")]


def _insider(conn) -> int:
    added = 0
    docs = conn.execute("SELECT * FROM documents WHERE type = 'insider' AND company IS NOT NULL "
                        "AND file_path LIKE '%.xml'").fetchall()
    for doc in docs:
        text = rawstore.read(doc["file_path"]).decode("utf-8", errors="replace")
        for t in insider_trades(text):
            kind = t["SecuritiesAcquiredOrDisposedTransactionType"]
            k = kind.lower()
            if "pledge" in k or "invoke" in k or "revoke" in k:
                stype, direction = "governance_red_flag", "negative" if "creat" in k else "neutral"
            else:
                stype = "ownership_change"
                direction = "positive" if k.startswith("buy") or "acqui" in k else \
                    "negative" if k.startswith("sell") or "dispos" in k else "neutral"
            who = t.get("CategoryOfPerson", "Insider")
            claim = (f"{who} {t.get('NameOfThePerson', '')}: {kind} of "
                     f"{t['SecuritiesAcquiredOrDisposedNumberOfSecurity']} "
                     f"{t.get('TypeOfInstrument', 'securities')}"
                     + (f" worth ₹{t['SecuritiesAcquiredOrDisposedValueOfSecurity']}"
                        if t.get("SecuritiesAcquiredOrDisposedValueOfSecurity") else "")
                     + (f" ({t['ModeOfAcquisitionOrDisposal']})" if t.get("ModeOfAcquisitionOrDisposal") else "")
                     + (f", dated {t.get(INSIDER_FIELDS[6])}" if t.get(INSIDER_FIELDS[6]) else "") + ".")
            strength = 3 if "promoter" in who.lower() else 2
            pid = _passage(conn, doc["id"], text, t["start"], t["end"])
            added += _save(conn, key=f"code:insider:{doc['id']}:{t['start']}", company=doc["company"],
                           document_id=doc["id"], passage_id=pid, quote=text[t["start"]:t["end"]],
                           signal_type=stype, direction=direction, strength=strength,
                           claim=" ".join(claim.split()), signal_date=t.get(INSIDER_FIELDS[6]),
                           source=doc["source"])
    return added


def _deals(conn) -> int:
    only_watch = bool(load_config()["ai"]["structured_signals"].get("deals_watchlist_only", True))
    where = "AND b.company IN (SELECT company FROM watchlist)" if only_watch else ""
    rows = conn.execute(f"SELECT b.* FROM bulk_block_deals b WHERE b.company IS NOT NULL {where}"
                        ).fetchall()
    added, texts = 0, {}
    for r in rows:
        key = f"code:deal:{r['row_key']}"
        if conn.execute("SELECT 1 FROM signals WHERE dedupe_key = ?", (key,)).fetchone():
            continue
        if r["document_id"] not in texts:
            doc = conn.execute("SELECT * FROM documents WHERE id = ?", (r["document_id"],)).fetchone()
            texts[r["document_id"]] = (doc, rawstore.read(doc["file_path"]).decode("utf-8-sig", errors="replace"))
        doc, text = texts[r["document_id"]]
        span, pos = None, 0
        for line in text.splitlines(keepends=True):
            cells = [c.strip() for c in next(csv.reader(io.StringIO(line)), [])]
            if len(cells) >= 7 and cells[1].upper() == r["nse_symbol"] and cells[3] == r["client_name"] \
                    and cells[4].upper() == r["side"] and cells[5] == r["quantity_text"] \
                    and cells[6] == r["price_text"]:
                span = (pos, pos + len(line.rstrip("\r\n")))
                break
            pos += len(line)
        if span is None:
            continue
        verb = "bought" if r["side"] == "BUY" else "sold"
        claim = (f"{r['client_name']} {verb} {r['quantity_text']} shares at ₹{r['price_text']} "
                 f"in a {r['deal_type']} deal on {r['trade_date']} (NSE).")
        pid = _passage(conn, doc["id"], text, *span)
        added += _save(conn, key=key, company=r["company"], document_id=doc["id"], passage_id=pid,
                       quote=text[span[0]:span[1]], signal_type="ownership_change",
                       direction="positive" if r["side"] == "BUY" else "negative", strength=2,
                       claim=claim, signal_date=r["trade_date"], source=doc["source"])
    return added


def build_all() -> dict:
    conn = db.connect()
    try:
        with conn:
            return {"shareholding": _shareholding(conn), "insider": _insider(conn),
                    "deals": _deals(conn)}
    finally:
        conn.close()
