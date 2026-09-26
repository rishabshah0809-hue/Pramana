"""Cross-source number checks (brief 14.6, principle 8).

When two sources report the same figure and differ by more than the tolerance in
config.yaml, a conflict is recorded. The highest-trust source's value is displayed with a
conflict badge listing every source; the conflict stays open until the owner reviews it.
Conflicts are never resolved silently and never averaged.
"""

import json
from decimal import Decimal

from app.adapters.registry import MANUAL_FILING_SOURCE, SOURCES
from app.config import load_config
from app.services import audit
from app.store import db

# Official exchange feeds rank above a file the owner uploaded by hand (same tier 1 filing,
# but the feed's provenance is recorded by the app itself).
_RANK = {sid: (s.tier, 0) for sid, s in SOURCES.items()}
_RANK[MANUAL_FILING_SOURCE] = (1, 1)


def rank(source: str) -> tuple[int, int]:
    return _RANK.get(source, (9, 9))


def _tolerance() -> Decimal:
    return Decimal(str(load_config().get("conflicts", {}).get("shareholding_percent_points",
                                                                "0.01")))


def check_shareholding(conn, company: str, as_of_date: str | None) -> int:
    """Compare each category across sources for one company and date. Returns conflicts added."""
    if as_of_date is None:
        return 0
    tol = _tolerance()
    rows = conn.execute(
        "SELECT s.category, s.percent, s.source_text, d.source, d.id AS document_id "
        "FROM shareholding s JOIN documents d ON d.id = s.document_id "
        "WHERE s.company = ? AND s.as_of_date = ? AND s.percent IS NOT NULL "
        "ORDER BY s.id", (company, as_of_date)).fetchall()
    latest: dict[tuple[str, str], dict] = {}
    for r in rows:  # later filings from the same source replace earlier ones (revisions)
        latest[(r["category"], r["source"])] = dict(r)
    added = 0
    for category in {c for c, _ in latest}:
        vals = [v for (c, _), v in latest.items() if c == category]
        if len({v["source"] for v in vals}) < 2:
            continue
        nums = [Decimal(v["percent"]) for v in vals]
        if max(nums) - min(nums) <= tol:
            continue
        vals.sort(key=lambda v: rank(v["source"]))
        figure = f"shareholding:{category}:{as_of_date}"
        key = figure + "|" + "|".join(f"{v['document_id']}" for v in vals)
        cur = conn.execute(
            "INSERT OR IGNORE INTO number_conflicts (company, figure, values_json, tolerance, "
            "displayed_source, conflict_key) VALUES (?, ?, ?, ?, ?, ?)",
            (company, figure, json.dumps([
                {"source": v["source"], "tier": rank(v["source"])[0], "value": v["percent"],
                 "text": v["source_text"], "document_id": v["document_id"]} for v in vals]),
             str(tol), vals[0]["source"], key))
        added += cur.rowcount
    return added


def open_conflicts(company: str) -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM number_conflicts n WHERE company = ? AND NOT EXISTS "
            "(SELECT 1 FROM conflict_reviews r WHERE r.conflict_id = n.id) ORDER BY id",
            (company,)).fetchall()
        return [dict(r) | {"values": json.loads(r["values_json"])} for r in rows]
    finally:
        conn.close()


def mark_reviewed(conflict_id: int, note: str = "") -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute("INSERT INTO conflict_reviews (conflict_id, note) VALUES (?, ?)",
                         (conflict_id, note or None))
            audit.log(conn, "user", "conflict_reviewed", f"number_conflicts:{conflict_id}",
                      after={"note": note or None})
    finally:
        conn.close()
