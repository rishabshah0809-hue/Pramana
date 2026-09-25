import sqlite3

import pytest

from app import paths
from app.store import db


def test_creates_all_13_tables(temp_dirs):
    db.init_db()
    assert set(db.table_names()) >= set(db.TABLES)
    assert len(db.TABLES) == 13


def test_wal_mode_and_raw_folder(temp_dirs):
    db.init_db()
    conn = db.connect()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
    assert paths.raw_dir().is_dir()


def test_running_setup_twice_is_safe(temp_dirs):
    db.init_db()
    db.init_db()
    assert set(db.table_names()) >= set(db.TABLES)


def test_every_table_has_created_at(temp_dirs):
    db.init_db()
    conn = db.connect()
    for name in db.TABLES:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({name})")]
        assert "created_at" in cols, name
    conn.close()


def _insert_document(conn):
    # FIXTURE: made-up test row, only ever written to a throwaway test database.
    conn.execute(
        "INSERT INTO documents (source, url, fetched_at, content_hash, file_path) "
        "VALUES ('fixture', 'https://example.test/doc', '2026-01-01T00:00:00Z', 'abc', 'x.pdf')"
    )


@pytest.mark.parametrize("sql", [
    "UPDATE documents SET url = 'changed'",
    "DELETE FROM documents",
])
def test_raw_documents_are_append_only(temp_dirs, sql):
    db.init_db()
    conn = db.connect()
    with conn:
        _insert_document(conn)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(sql)
    conn.close()


def test_passage_needs_a_real_document(temp_dirs):
    db.init_db()
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO passages (document_id, char_start, char_end, text) VALUES (999, 0, 1, 'x')"
        )
    conn.close()


def test_signal_needs_a_passage(temp_dirs):
    db.init_db()
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO signals (company, type, direction, strength, claim_text, status) "
            "VALUES ('X', 't', 'positive', 3, 'c', 'verified')"
        )
    conn.close()
