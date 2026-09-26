"""Bulk and block deals from NSE's daily report files (trust tier 1).

Terms note (DATA_SOURCES.md): these are daily report files, not feeds, and downloading them
automatically conflicts with NSE's terms. The owner chose to do it anyway on 26 Sep 2026.
Two small files are downloaded once each weekday after the close.
"""

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.adapters.polite import FetchFailed, PoliteClient
from app.adapters.registry import SOURCES
from app.errors import FriendlyError, report
from app.services import ingest, rawstore
from app.services.matching import Matcher
from app.store import db
from app.timeutil import now_utc

SOURCE_ID = "bulk_block"
FILES = {
    "bulk": "https://nsearchives.nseindia.com/content/equities/bulk.csv",
    "block": "https://nsearchives.nseindia.com/content/equities/block.csv",
}
_COLUMNS = {"date": "DATE", "symbol": "SYMBOL", "name": "SECURITY NAME", "client": "CLIENT NAME",
            "side": "BUY/SELL", "qty": "QUANTITY TRADED",
            "price": "TRADE PRICE / WGHT. AVG. PRICE", "remarks": "REMARKS"}
_REQUIRED = ("date", "symbol", "client", "side", "qty", "price")


@dataclass(frozen=True)
class Deal:
    deal_type: str
    trade_date: str         # ISO date
    nse_symbol: str
    security_name: str | None
    client_name: str
    side: str
    quantity: int
    quantity_text: str
    price: Decimal
    price_text: str
    remarks: str | None

    def key(self) -> str:
        raw = "|".join([self.deal_type, self.trade_date, self.nse_symbol, self.client_name,
                        self.side, self.quantity_text, self.price_text, self.remarks or ""])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DealsFormatError(FriendlyError):
    def __init__(self, deal_type: str, detail: str):
        super().__init__(f"NSE's {deal_type}-deals file has changed its format ({detail}).",
                         "Nothing is lost: the raw file was saved. Data Health shows this until "
                         "it is fixed. If it lasts more than a day, tell Claude.")


def parse(content: bytes, deal_type: str) -> tuple[list[Deal], int]:
    """Returns (valid deals, rows received). An empty day ("NO RECORDS") gives no deals."""
    text = content.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise DealsFormatError(deal_type, "the file is empty")
    header = [h.strip().upper() for h in rows[0]]
    idx = {k: header.index(v) for k, v in _COLUMNS.items() if v in header}
    missing = [_COLUMNS[k] for k in _REQUIRED if k not in idx]
    if missing:
        raise DealsFormatError(deal_type, "missing columns: " + ", ".join(missing))
    deals = []
    body = rows[1:]
    for r in body:
        def cell(k):
            i = idx.get(k)
            return r[i].strip() if i is not None and i < len(r) else ""
        try:
            trade_date = datetime.strptime(cell("date").title(), "%d-%b-%Y").date().isoformat()
            qty_text, price_text = cell("qty"), cell("price")
            qty = int(qty_text.replace(",", ""))
            price = Decimal(price_text.replace(",", ""))
        except (ValueError, InvalidOperation):
            continue  # e.g. a "NO RECORDS" line, or a damaged row
        side = cell("side").upper()
        if side not in ("BUY", "SELL") or qty <= 0 or price <= 0 or not cell("symbol") \
                or not cell("client"):
            continue
        remarks = cell("remarks")
        deals.append(Deal(deal_type, trade_date, cell("symbol").upper(), cell("name") or None,
                          cell("client"), side, qty, qty_text, price, price_text,
                          None if remarks in ("", "-") else remarks))
    return deals, len(body)


def run(client=None, now=None) -> ingest.RunSummary:
    started = now or now_utc()
    run_id = ingest.start_run(SOURCE_ID, started)
    if run_id is None:
        return ingest.RunSummary(False, "skipped", "A check of this source is already running.")
    client = client or PoliteClient()
    received = valid = added = 0
    failures: list[tuple[str, str]] = []
    for deal_type, url in FILES.items():
        fetched = now_utc()
        conn = db.connect()
        try:
            try:
                resp = client.get(url)
            except FetchFailed as exc:
                with conn:
                    rawstore.log_fetch(conn, SOURCE_ID, url, fetched, "failed",
                                       http_status=exc.http_status, message=exc.message)
                failures.append((exc.status, f"{deal_type.title()} deals: {exc.message}"))
                continue
            with conn:
                saved = rawstore.save(conn, source=SOURCE_ID, url=url, content=resp.content,
                                      doc_type=f"{deal_type}_deals_csv", fetched_at=fetched,
                                      licence=SOURCES[SOURCE_ID].terms_status,
                                      filename_hint=f"{deal_type}.csv")
                rawstore.log_fetch(conn, SOURCE_ID, url, fetched, saved.outcome,
                                   http_status=resp.http_status, content_hash=saved.content_hash,
                                   document_id=saved.document_id)
            deals, n = parse(resp.content, deal_type)  # only after the raw file is stored
            received, valid = received + n, valid + len(deals)
            matcher = Matcher(conn)
            with conn:
                for d in deals:
                    isin, _ = matcher.match(nse_symbol=d.nse_symbol)
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO bulk_block_deals (deal_type, trade_date, "
                        "nse_symbol, security_name, company, client_name, side, quantity, "
                        "quantity_text, price, price_text, remarks, document_id, row_key) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (d.deal_type, d.trade_date, d.nse_symbol, d.security_name, isin,
                         d.client_name, d.side, d.quantity, d.quantity_text, str(d.price),
                         d.price_text, d.remarks, saved.document_id, d.key()))
                    added += cur.rowcount
        except DealsFormatError as exc:
            failures.append(("error", exc.message))
        except Exception as exc:  # noqa: BLE001 — never crash the scheduler or dashboard
            failures.append(("error", report(exc).message))
        finally:
            conn.close()
    status = "ok" if not failures else failures[0][0]
    message = " ".join([f"{len(FILES) - len(failures)} of {len(FILES)} files checked: "
                        f"{added} new deal(s)."] + [m for _, m in failures])
    ingest.finish_run(SOURCE_ID, run_id, status, received, valid, message)
    return ingest.RunSummary(True, status, message, added)


def company_deals(isin: str, limit: int = 100) -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM bulk_block_deals WHERE company = ? "
                            "ORDER BY trade_date DESC, id DESC LIMIT ?", (isin, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def content_status(now, last_session) -> tuple[str, str]:
    conn = db.connect()
    try:
        newest = conn.execute("SELECT MAX(trade_date) FROM bulk_block_deals").fetchone()[0]
        runs_ok = conn.execute("SELECT MAX(finished_at) FROM adapter_runs WHERE adapter = ? "
                               "AND fetch_status = 'ok'", (SOURCE_ID,)).fetchone()[0]
    finally:
        conn.close()
    if newest is None:
        if runs_ok:
            return "current", "Files checked; no deals stored yet"
        return "no_data", "No deals stored yet"
    if newest >= last_session.isoformat():
        return "current", f"Deals up to {newest}"
    return "stale", f"Newest deals are from {newest}; expected {last_session.isoformat()}"
