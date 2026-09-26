"""Shareholding trend for the Company page: one displayed value per date and category.

If several filings give a value for the same date and category, the highest-trust source is
displayed (14.6); a later filing from the same source replaces an earlier one (a revision).
Disagreements between sources are recorded as conflicts and shown, never averaged.
"""

from decimal import Decimal

from app.services.conflicts import rank
from app.store import db


def series(isin: str) -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT s.as_of_date, s.category, s.percent, s.source_text, s.document_id, "
            "d.source, d.published_at, d.fetched_at FROM shareholding s "
            "JOIN documents d ON d.id = s.document_id WHERE s.company = ? ORDER BY s.id",
            (isin,)).fetchall()
    finally:
        conn.close()
    chosen: dict[tuple, dict] = {}
    for r in rows:
        key = (r["as_of_date"], r["category"])
        cur = chosen.get(key)
        # Lower rank wins; among equal rank, the later row (a revision) wins.
        if cur is None or rank(r["source"]) <= rank(cur["source"]):
            chosen[key] = dict(r)
    out = []
    for (as_of, category), r in sorted(chosen.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        out.append(r | {"percent": Decimal(r["percent"]) if r["percent"] is not None else None})
    return out
