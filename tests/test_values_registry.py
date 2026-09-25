import re
from pathlib import Path

import pytest

from app.adapters.registry import SOURCES, allowed_hosts
from app.errors import FriendlyError
from app.net import check_url_allowed
from app.services.values import known, not_applicable, unknown, Value

ROOT = Path(__file__).resolve().parent.parent


def test_unknown_needs_reason_and_no_value():
    assert unknown("not fetched yet").reason == "not fetched yet"
    with pytest.raises(ValueError):
        Value("unknown", value=0, reason="x")
    with pytest.raises(ValueError):
        Value("unknown")
    with pytest.raises(ValueError):
        Value("known")
    assert not_applicable("no promoter").state == "not_applicable"
    assert known(5).is_known


def test_every_registered_host_is_listed_in_data_sources():
    text = (ROOT / "DATA_SOURCES.md").read_text()
    for host in allowed_hosts():
        assert host in text, f"{host} missing from DATA_SOURCES.md"
    for src in SOURCES.values():
        assert re.match(r"\d{4}-\d{2}-\d{2}", src.terms_checked)


def test_nse_is_never_contacted_automatically():
    assert SOURCES["nse_equity_list"].hosts == ()
    assert not any("nseindia" in h or "bseindia" in h for h in allowed_hosts())


def test_network_guard_blocks_unlisted_hosts():
    check_url_allowed("https://query1.finance.yahoo.com/v8/finance/chart/X")
    with pytest.raises(FriendlyError, match="not an approved data source"):
        check_url_allowed("https://www.screener.in/company/X/")
