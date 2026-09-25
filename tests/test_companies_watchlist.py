import json

import pytest

from app import paths
from app.errors import FriendlyError
from app.services import companies, watchlist
from app.store import db
from tests.conftest import FIXTURES


def _rows(sql, *args):
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def test_import_stores_raw_file_and_companies(imported):
    assert companies.company_count() == 3
    doc = _rows("SELECT * FROM documents WHERE source = 'nse_equity_list'")[0]
    raw = paths.data_dir() / doc["file_path"]
    assert raw.read_bytes() == (FIXTURES / "FIXTURE_EQUITY_L.csv").read_bytes()
    assert doc["content_hash"] and doc["fetched_at"] and doc["published_at"] is None
    assert _rows("SELECT action FROM audit_log WHERE action = 'import_company_list'")
    run = _rows("SELECT * FROM adapter_runs WHERE adapter = 'nse_equity_list'")[0]
    assert run["fetch_status"] == "ok" and run["items_valid"] == 3


def test_reimport_same_file_is_detected(imported):
    s = companies.import_equity_list((FIXTURES / "FIXTURE_EQUITY_L.csv").read_bytes(), "again.csv")
    assert s.already_imported and s.unchanged == 3
    assert len(_rows("SELECT id FROM documents")) == 1


def test_renamed_company_is_updated_and_audited(imported):
    changed = (FIXTURES / "FIXTURE_EQUITY_L.csv").read_bytes().replace(
        b"Fixture Beta Limited", b"Fixture Beta Renamed Limited")
    s = companies.import_equity_list(changed, "renamed.csv")
    assert s.updated == 1
    entry = _rows("SELECT * FROM audit_log WHERE action = 'company_updated'")[0]
    assert json.loads(entry["before"])["name"] == "Fixture Beta Limited"
    assert json.loads(entry["after"])["name"] == "Fixture Beta Renamed Limited"


def test_search(imported):
    assert companies.search("FXBETA")[0]["nse_symbol"] == "FXBETA"
    assert companies.search("gamma")[0]["nse_symbol"] == "FXGAMMA"
    assert companies.search("") == []


def test_watchlist_add_remove_is_audited(imported):
    watchlist.add("INE0FXA01011", notes="fixture note")
    assert [w["nse_symbol"] for w in watchlist.list_items()] == ["FXALPHA"]
    watchlist.remove("INE0FXA01011")
    assert watchlist.list_items() == []
    actions = [r["action"] for r in _rows("SELECT action FROM audit_log ORDER BY id")]
    assert "watchlist_add" in actions and "watchlist_remove" in actions


def test_watchlist_rules_are_plain_english(imported):
    watchlist.add("INE0FXA01011")
    with pytest.raises(FriendlyError, match="already"):
        watchlist.add("INE0FXA01011")
    with pytest.raises(FriendlyError, match="limit"):
        watchlist.add("INE0FXB01019", max_companies=1)
    with pytest.raises(FriendlyError, match="company list"):
        watchlist.add("INE0FXZ99999")
