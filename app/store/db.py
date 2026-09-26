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

SCHEMA_VERSION = 3

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
        interval    TEXT,               -- '1d' daily bar, '15m' intraday bar
        is_delayed  INTEGER NOT NULL DEFAULT 0,
        currency    TEXT,
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

# Operational tables (not part of the brief's 13 core tables): source health history.
OPERATIONAL_TABLES = {
    "adapter_runs": f"""
        id              INTEGER PRIMARY KEY,
        adapter         TEXT NOT NULL,
        started_at      TEXT NOT NULL,
        finished_at     TEXT,
        fetch_status    TEXT NOT NULL
                        CHECK (fetch_status IN ('running', 'ok', 'missing', 'blocked',
                                                'timeout', 'error')),
        items_received  INTEGER NOT NULL DEFAULT 0,
        items_valid     INTEGER NOT NULL DEFAULT 0,
        message         TEXT,           -- plain-English summary, never a traceback
        created_at      TEXT NOT NULL DEFAULT {_NOW}
    """,
    "quality_scores": f"""
        id                 INTEGER PRIMARY KEY,
        adapter            TEXT NOT NULL,
        computed_at        TEXT NOT NULL,
        score              REAL,        -- NULL when inputs are unknown
        success_rate       REAL,
        freshness          REAL,
        validation_rate    REAL,
        note               TEXT,
        created_at         TEXT NOT NULL DEFAULT {_NOW}
    """,
}

# Filings ingestion (M2, schema version 3). All append-only: nothing here is edited in place.
FILING_TABLES = {
    # One row per item seen in an exchange feed (the feed file itself is in documents).
    "filings": f"""
        id                 INTEGER PRIMARY KEY,
        adapter            TEXT NOT NULL,
        exchange           TEXT NOT NULL CHECK (exchange IN ('NSE', 'BSE')),
        feed               TEXT NOT NULL,
        category           TEXT NOT NULL,
        company            TEXT REFERENCES companies(isin),  -- NULL = not matched (14.4)
        match_method       TEXT,        -- isin | bse_code | nse_symbol | exact_name
        company_name_raw   TEXT NOT NULL,
        company_name_norm  TEXT NOT NULL,
        exchange_code      TEXT,        -- BSE scrip code, when the feed gives one
        subject            TEXT,
        url                TEXT,        -- the filing's own file, NULL if the feed gives none
        published_at       TEXT,        -- UTC; NULL = Unknown (14.2)
        published_raw      TEXT,        -- exactly as the feed wrote it
        feed_document_id   INTEGER NOT NULL REFERENCES documents(id),
        item_key           TEXT NOT NULL UNIQUE,
        first_seen_at      TEXT NOT NULL,
        created_at         TEXT NOT NULL DEFAULT {_NOW}
    """,
    # Corrections and superseded filings (14.5). The latest row per document is current.
    "document_status": f"""
        id             INTEGER PRIMARY KEY,
        document_id    INTEGER NOT NULL REFERENCES documents(id),
        status         TEXT NOT NULL CHECK (status IN ('original', 'revised', 'corrected',
                                                       'cancelled', 'superseded')),
        superseded_by  INTEGER REFERENCES documents(id),
        reason         TEXT NOT NULL,
        set_by         TEXT NOT NULL CHECK (set_by IN ('system', 'user')),
        created_at     TEXT NOT NULL DEFAULT {_NOW}
    """,
    # Shareholding pattern figures, exact decimals kept as text next to the source text (14.6).
    "shareholding": f"""
        id            INTEGER PRIMARY KEY,
        company       TEXT NOT NULL REFERENCES companies(isin),
        as_of_date    TEXT,              -- event time: the date the pattern is "as on"
        category      TEXT NOT NULL,     -- promoter | fii | dii | public | ...
        percent       TEXT,              -- Decimal as text, in percent; NULL = Unknown
        source_text   TEXT NOT NULL,     -- the value exactly as written in the filing
        document_id   INTEGER NOT NULL REFERENCES documents(id),
        created_at    TEXT NOT NULL DEFAULT {_NOW},
        UNIQUE (document_id, category)
    """,
    "bulk_block_deals": f"""
        id              INTEGER PRIMARY KEY,
        deal_type       TEXT NOT NULL CHECK (deal_type IN ('bulk', 'block')),
        trade_date      TEXT NOT NULL,   -- event time
        nse_symbol      TEXT NOT NULL,
        security_name   TEXT,
        company         TEXT REFERENCES companies(isin),
        client_name     TEXT NOT NULL,
        side            TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
        quantity        INTEGER NOT NULL,
        quantity_text   TEXT NOT NULL,
        price           TEXT NOT NULL,   -- Decimal as text
        price_text      TEXT NOT NULL,
        remarks         TEXT,
        document_id     INTEGER NOT NULL REFERENCES documents(id),
        row_key         TEXT NOT NULL UNIQUE,
        created_at      TEXT NOT NULL DEFAULT {_NOW}
    """,
    # Every download attempt, including "unchanged since last time".
    "fetch_log": f"""
        id             INTEGER PRIMARY KEY,
        adapter        TEXT NOT NULL,
        url            TEXT NOT NULL,
        fetched_at     TEXT NOT NULL,
        http_status    INTEGER,
        outcome        TEXT NOT NULL CHECK (outcome IN ('new', 'new_version', 'unchanged',
                                                        'not_modified', 'failed', 'skipped')),
        content_hash   TEXT,
        document_id    INTEGER REFERENCES documents(id),
        etag           TEXT,
        last_modified  TEXT,
        message        TEXT,
        created_at     TEXT NOT NULL DEFAULT {_NOW}
    """,
    # Cross-source disagreements (14.6): never resolved silently.
    "number_conflicts": f"""
        id                INTEGER PRIMARY KEY,
        company           TEXT NOT NULL REFERENCES companies(isin),
        figure            TEXT NOT NULL,     -- e.g. 'shareholding:promoter:2026-06-30'
        values_json       TEXT NOT NULL,     -- every source, tier, value and document
        tolerance         TEXT NOT NULL,
        displayed_source  TEXT NOT NULL,     -- highest-trust source, shown with a badge
        conflict_key      TEXT NOT NULL UNIQUE,
        created_at        TEXT NOT NULL DEFAULT {_NOW}
    """,
    "conflict_reviews": f"""
        id           INTEGER PRIMARY KEY,
        conflict_id  INTEGER NOT NULL REFERENCES number_conflicts(id),
        note         TEXT,
        created_at   TEXT NOT NULL DEFAULT {_NOW}
    """,
}

# Columns added after schema version 1, applied to older databases on start.
_ADDED_COLUMNS = {
    "prices": [("interval", "TEXT"), ("is_delayed", "INTEGER NOT NULL DEFAULT 0"),
               ("currency", "TEXT")],
}

# Raw facts are append-only: new versions are inserted, old rows never change.
APPEND_ONLY_TABLES = ("documents", "passages", "prices", "audit_log", "quality_scores",
                      *FILING_TABLES)


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
            for name, columns in {**TABLES, **OPERATIONAL_TABLES, **FILING_TABLES}.items():
                conn.execute(f"CREATE TABLE IF NOT EXISTS {name} ({columns})")
            for name, cols in _ADDED_COLUMNS.items():
                existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({name})")}
                for col, decl in cols:
                    if col not in existing:
                        conn.execute(f"ALTER TABLE {name} ADD COLUMN {col} {decl}")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_prices_company_ts "
                "ON prices (company, interval, timestamp)"
            )
            for index in (
                "idx_runs_adapter ON adapter_runs (adapter, started_at)",
                "idx_documents_url ON documents (url, version)",
                "idx_filings_company ON filings (company, published_at)",
                "idx_filings_code ON filings (exchange_code)",
                "idx_filings_name ON filings (company_name_norm)",
                "idx_filings_url ON filings (url)",
                "idx_shareholding_company ON shareholding (company, as_of_date)",
                "idx_deals_company ON bulk_block_deals (company, trade_date)",
                "idx_fetch_log_url ON fetch_log (url, id)",
                "idx_status_document ON document_status (document_id, id)",
            ):
                conn.execute(f"CREATE INDEX IF NOT EXISTS {index}")
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
