"""Watchlist actions. Every change is written to the audit log (brief 14.11)."""

from app.errors import FriendlyError
from app.services import audit
from app.store import db


def list_items() -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT w.company AS isin, c.nse_symbol, c.name, w.added_on, w.notes "
            "FROM watchlist w JOIN companies c ON c.isin = w.company ORDER BY c.name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add(isin: str, notes: str = "", max_companies: int = 50) -> None:
    conn = db.connect()
    try:
        with conn:
            company = conn.execute("SELECT name FROM companies WHERE isin = ?", (isin,)).fetchone()
            if company is None:
                raise FriendlyError("That company isn't in your company list.",
                                    "Import the latest NSE list on the Company list page first.")
            if conn.execute("SELECT 1 FROM watchlist WHERE company = ?", (isin,)).fetchone():
                raise FriendlyError(f"{company['name']} is already on your watchlist.",
                                    "No action needed.")
            count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
            if count >= max_companies:
                raise FriendlyError(
                    f"Your watchlist already has {count} companies (the limit is {max_companies}).",
                    "Remove a company first, or raise watchlist.max_companies in config.yaml.")
            conn.execute("INSERT INTO watchlist (company, notes) VALUES (?, ?)", (isin, notes or None))
            audit.log(conn, "user", "watchlist_add", isin, after={"notes": notes or None})
    finally:
        conn.close()


def remove(isin: str) -> None:
    conn = db.connect()
    try:
        with conn:
            row = conn.execute("SELECT added_on, notes FROM watchlist WHERE company = ?",
                               (isin,)).fetchone()
            if row is None:
                return
            conn.execute("DELETE FROM watchlist WHERE company = ?", (isin,))
            audit.log(conn, "user", "watchlist_remove", isin, before=dict(row))
    finally:
        conn.close()
