"""Company master: import NSE's list, search companies (brief 14.4: ISIN is the key)."""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from app import paths
from app.adapters import bse_scrip_list, nse_equity_list
from app.adapters.registry import SOURCES
from app.services import audit, health, rawstore
from app.store import db
from app.timeutil import IST, now_utc, to_iso

SOURCE_ID = "nse_equity_list"


@dataclass
class ImportSummary:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    not_in_new_list: int = 0
    already_imported: bool = False
    problems: list[str] = field(default_factory=list)


def import_equity_list(content: bytes, filename: str) -> ImportSummary:
    """Store the raw file (never modified), then add/update companies by ISIN."""
    companies, problems = nse_equity_list.parse(content)
    summary = ImportSummary(problems=problems)
    fetched = now_utc()
    digest = hashlib.sha256(content).hexdigest()

    conn = db.connect()
    try:
        with conn:
            run_id = conn.execute(
                "INSERT INTO adapter_runs (adapter, started_at, fetch_status) VALUES (?, ?, 'running')",
                (SOURCE_ID, to_iso(fetched)),
            ).lastrowid
            if conn.execute("SELECT 1 FROM documents WHERE source = ? AND content_hash = ?",
                            (SOURCE_ID, digest)).fetchone():
                summary.already_imported = True
            else:
                folder = paths.raw_dir() / SOURCE_ID / fetched.astimezone(IST).strftime("%Y-%m-%d")
                folder.mkdir(parents=True, exist_ok=True)
                raw_file = folder / f"EQUITY_L_{digest[:12]}.csv"
                raw_file.write_bytes(content)
                conn.execute(
                    "INSERT INTO documents (source, url, type, published_at, fetched_at, "
                    "content_hash, file_path, licence) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)",
                    (SOURCE_ID, f"manual-upload:{Path(filename).name}", "equity_list",
                     to_iso(fetched), digest,
                     str(raw_file.relative_to(paths.data_dir())),
                     SOURCES[SOURCE_ID].terms_status),
                )

            existing = {r["isin"]: dict(r) for r in conn.execute(
                "SELECT isin, nse_symbol, name FROM companies")}
            for c in companies:
                old = existing.get(c.isin)
                if old is None:
                    conn.execute(
                        "INSERT INTO companies (isin, nse_symbol, name) VALUES (?, ?, ?)",
                        (c.isin, c.nse_symbol, c.name))
                    summary.added += 1
                elif (old["nse_symbol"], old["name"]) != (c.nse_symbol, c.name):
                    conn.execute("UPDATE companies SET nse_symbol = ?, name = ? WHERE isin = ?",
                                 (c.nse_symbol, c.name, c.isin))
                    audit.log(conn, "system", "company_updated", c.isin,
                              before={"nse_symbol": old["nse_symbol"], "name": old["name"]},
                              after={"nse_symbol": c.nse_symbol, "name": c.name})
                    summary.updated += 1
                else:
                    summary.unchanged += 1
            new_isins = {c.isin for c in companies}
            summary.not_in_new_list = sum(
                1 for isin, row in existing.items() if row["nse_symbol"] and isin not in new_isins)

            audit.log(conn, "user", "import_company_list", filename,
                      after={"added": summary.added, "updated": summary.updated,
                             "unchanged": summary.unchanged, "skipped_rows": len(problems),
                             "sha256": digest})
            conn.execute(
                "UPDATE adapter_runs SET finished_at = ?, fetch_status = 'ok', "
                "items_received = ?, items_valid = ?, message = ? WHERE id = ?",
                (to_iso(now_utc()), len(companies) + len(problems), len(companies),
                 f"Imported {len(companies)} companies from {Path(filename).name}", run_id),
            )
    finally:
        conn.close()
    health.record_quality(SOURCE_ID)
    return summary


BSE_SOURCE_ID = "bse_scrip_list"


def import_bse_list(content: bytes, filename: str) -> ImportSummary:
    """Store the raw file, then link BSE codes to companies by ISIN; add BSE-only companies.
    A company's NSE name is kept; a different BSE name is added as an alias (14.4)."""
    scrips, problems = bse_scrip_list.parse(content)
    summary = ImportSummary(problems=problems)
    fetched = now_utc()
    conn = db.connect()
    try:
        with conn:
            run_id = conn.execute(
                "INSERT INTO adapter_runs (adapter, started_at, fetch_status) VALUES (?, ?, 'running')",
                (BSE_SOURCE_ID, to_iso(fetched))).lastrowid
            saved = rawstore.save(conn, source=BSE_SOURCE_ID,
                                  url=f"manual-upload:{Path(filename).name}", content=content,
                                  doc_type="bse_scrip_list", fetched_at=fetched,
                                  licence=SOURCES[BSE_SOURCE_ID].terms_status,
                                  filename_hint="List_of_Scrips.csv")
            summary.already_imported = saved.outcome == "unchanged"
            existing = {r["isin"]: dict(r) for r in conn.execute(
                "SELECT isin, bse_code, name, aliases FROM companies")}
            for s in scrips:
                old = existing.get(s.isin)
                if old is None:
                    conn.execute("INSERT INTO companies (isin, bse_code, name) VALUES (?, ?, ?)",
                                 (s.isin, s.bse_code, s.name))
                    summary.added += 1
                    continue
                aliases = json.loads(old["aliases"] or "[]")
                new_aliases = aliases + ([s.name] if s.name != old["name"]
                                         and s.name not in aliases else [])
                if old["bse_code"] != s.bse_code or new_aliases != aliases:
                    conn.execute("UPDATE companies SET bse_code = ?, aliases = ? WHERE isin = ?",
                                 (s.bse_code, json.dumps(new_aliases) if new_aliases else None,
                                  s.isin))
                    audit.log(conn, "system", "company_updated", s.isin,
                              before={"bse_code": old["bse_code"], "aliases": aliases},
                              after={"bse_code": s.bse_code, "aliases": new_aliases})
                    summary.updated += 1
                else:
                    summary.unchanged += 1
            audit.log(conn, "user", "import_bse_list", filename,
                      after={"added": summary.added, "updated": summary.updated,
                             "unchanged": summary.unchanged, "skipped_rows": len(problems),
                             "sha256": saved.content_hash})
            conn.execute(
                "UPDATE adapter_runs SET finished_at = ?, fetch_status = 'ok', "
                "items_received = ?, items_valid = ?, message = ? WHERE id = ?",
                (to_iso(now_utc()), len(scrips) + len(problems), len(scrips),
                 f"Imported {len(scrips)} BSE companies from {Path(filename).name}", run_id))
    finally:
        conn.close()
    health.record_quality(BSE_SOURCE_ID)
    return summary


def get(isin: str) -> dict | None:
    conn = db.connect()
    try:
        r = conn.execute("SELECT * FROM companies WHERE isin = ?", (isin,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def company_count() -> int:
    conn = db.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    finally:
        conn.close()


def search(query: str, limit: int = 20) -> list[dict]:
    q = query.strip()
    if not q:
        return []
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT isin, nse_symbol, bse_code, name FROM companies "
            "WHERE nse_symbol LIKE ? OR name LIKE ? OR isin = ? OR bse_code = ? "
            "ORDER BY (nse_symbol = ?) DESC, (nse_symbol LIKE ?) DESC, name LIMIT ?",
            (f"{q.upper()}%", f"%{q}%", q.upper(), q, q.upper(), f"{q.upper()}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def last_import(source_id: str = SOURCE_ID) -> dict | None:
    conn = db.connect()
    try:
        r = conn.execute(
            "SELECT fetched_at, url FROM documents WHERE source = ? ORDER BY id DESC LIMIT 1",
            (source_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()
