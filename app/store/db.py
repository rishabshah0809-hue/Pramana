"""SQLite database: creates the 13 core tables from the product brief (Section 9).

Principles enforced here:
- Every row carries created_at (UTC).
- Point-in-time storage: raw facts (documents, passages, prices, audit_log)
  can never be updated or deleted; new versions are appended instead.
- Lineage: a passage needs a document, a signal needs a passage.
"""

import sqlite3
from pathlib import Path

from app import paths

SCHEMA_VERSION = 1

_NOW = "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"

TABLES = {
    "companies": f"""
        isin         TEXT PRIMARY KEY,
        nse_symbol   TEXT,
        bse_code     TEXT,
        name         TEXT NOT NULL,
        aliases      TEXT,              -- JSON list of alternative names
        sector       TEXT,
        industry     TEXT,
        created_at   TEXT NOT NULL DEFAULT {_NOW}
    """,
    "documents": f"""
        id            INTEGER PRIMARY KEY,
        source        TEXT NOT NULL,
        url           TEXT NOT NULL,
        type          TEXT,
        company       TEXT REFERENCES companies(isin),
        published_at  TEXT,
        fetched_at    TEXT NOT NULL,
        content_hash  TEXT NOT NULL,
        file_path     TEXT NOT NULL,
        version       INTEGER NOT NULL DEFAULT 1,
        licence       TEXT,             -- source type and licence terms (brief Section 12)
        created_at    TEXT NOT NULL DEFAULT {_NOW}
    """,
    "passages": f"""
        id           INTEGER PRIMARY KEY,
        document_id  INTEGER NOT NULL REFERENCES documents(id),
        page         INTEGER,
        char_start   INTEGER NOT NULL,
        char_end     INTEGER NOT NULL,
        text         TEXT NOT NULL,
        created_at   TEXT NOT NULL DEFAULT {_NOW}
    """,
    "relationships": f"""
        id                 INTEGER PRIMARY KEY,
        company_a          TEXT NOT NULL REFERENCES companies(isin),
        company_b          TEXT NOT NULL REFERENCES companies(isin),
        type               TEXT NOT NULL
                           CHECK (type IN ('supplier', 'customer', 'subsidiary', 'competitor')),
        source_passage_id  INTEGER NOT NULL REFERENCES passages(id),
        created_at         TEXT NOT NULL DEFAULT {_NOW}
    """,
    "people": f"""
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL,
        role        TEXT,
        company     TEXT REFERENCES companies(isin),
        from_date   TEXT,
        to_date     TEXT,
        created_at  TEXT NOT NULL DEFAULT {_NOW}
    """,
    "watchlist": f"""
        id          INTEGER PRIMARY KEY,
        company     TEXT NOT NULL REFERENCES companies(isin),
        added_on    TEXT NOT NULL DEFAULT {_NOW},
        notes       TEXT,
        created_at  TEXT NOT NULL DEFAULT {_NOW}
    """,
    "prices": f"""
        id          INTEGER PRIMARY KEY,
        company     TEXT NOT NULL REFERENCES companies(isin),
        timestamp   TEXT NOT NULL,      -- source timestamp
        open        REAL,
        high        REAL,
        low         REAL,
        close       REAL,
        volume      REAL,
        source      TEXT NOT NULL,
        fetched_at  TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT {_NOW}
    """,
    "signals": f"""
        id              INTEGER PRIMARY KEY,
        company         TEXT NOT NULL REFERENCES companies(isin),
        type            TEXT NOT NULL,
        direction       TEXT NOT NULL CHECK (direction IN ('positive', 'negative', 'neutral')),
        strength        INTEGER NOT NULL CHECK (strength BETWEEN 1 AND 5),
        signal_date     TEXT,
        claim_text      TEXT NOT NULL,
        passage_id      INTEGER NOT NULL REFERENCES passages(id),
        status          TEXT NOT NULL
                        CHECK (status IN ('verified', 'unverified', 'needs_review', 'rejected')),
        model           TEXT,
        prompt_version  TEXT,
        created_at      TEXT NOT NULL DEFAULT {_NOW}
    """,
    "theses": f"""
        id             INTEGER PRIMARY KEY,
        company        TEXT NOT NULL REFERENCES companies(isin),
        statement      TEXT NOT NULL,
        horizon        TEXT,
        my_view        TEXT,
        street_view    TEXT,
        status         TEXT,
        kill_criteria  TEXT,
        created_at     TEXT NOT NULL DEFAULT {_NOW}
    """,
    "claims": f"""
        id          INTEGER PRIMARY KEY,
        thesis_id   INTEGER NOT NULL REFERENCES theses(id),
        statement   TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT {_NOW}
    """,
    "evidence": f"""
        id           INTEGER PRIMARY KEY,
        claim_id     INTEGER NOT NULL REFERENCES claims(id),
        signal_id    INTEGER NOT NULL REFERENCES signals(id),
        stance       TEXT NOT NULL CHECK (stance IN ('for', 'against')),
        user_weight  REAL,
        note         TEXT,
        created_at   TEXT NOT NULL DEFAULT {_NOW}
    """,
    "alerts": f"""
        id            INTEGER PRIMARY KEY,
        rule          TEXT NOT NULL,
        company       TEXT REFERENCES companies(isin),
        triggered_at  TEXT NOT NULL,
        signal_id     INTEGER REFERENCES signals(id),
        seen          INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL DEFAULT {_NOW}
    """,
    "audit_log": f"""
        id          INTEGER PRIMARY KEY,
        timestamp   TEXT NOT NULL DEFAULT {_NOW},
        actor       TEXT NOT NULL CHECK (actor IN ('system', 'ai', 'user')),
        action      TEXT NOT NULL,
        object      TEXT,
        before      TEXT,
        after       TEXT,
        created_at  TEXT NOT NULL DEFAULT {_NOW}
    """,
}

# Raw facts are append-only: new versions are inserted, old rows never change.
APPEND_ONLY_TABLES = ("documents", "passages", "prices", "audit_log")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or paths.db_path())
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path | None = None) -> Path:
    """Create the database and all tables if they don't exist. Safe to run many times."""
    path = Path(path or paths.db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    paths.raw_dir().mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        with conn:
            for name, columns in TABLES.items():
                conn.execute(f"CREATE TABLE IF NOT EXISTS {name} ({columns})")
            for name in APPEND_ONLY_TABLES:
                for op in ("UPDATE", "DELETE"):
                    conn.execute(
                        f"""CREATE TRIGGER IF NOT EXISTS {name}_no_{op.lower()}
                        BEFORE {op} ON {name}
                        BEGIN
                            SELECT RAISE(ABORT, '{name} is append-only: add a new version instead');
                        END"""
                    )
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    finally:
        conn.close()
    return path


def table_names(path: Path | None = None) -> list[str]:
    conn = connect(path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]
    finally:
        conn.close()
