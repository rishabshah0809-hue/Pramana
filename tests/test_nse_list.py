import pytest

from app.adapters.nse_equity_list import isin_is_valid, parse
from app.errors import FriendlyError
from tests.conftest import FIXTURES


def test_isin_check_digit():
    assert isin_is_valid("INE002A01018")       # public ISIN, used only to test the algorithm
    assert not isin_is_valid("INE002A01019")    # wrong check digit
    assert not isin_is_valid("US0378331005")    # not an Indian ISIN


def test_parse_fixture_list():
    companies, problems = parse((FIXTURES / "FIXTURE_EQUITY_L.csv").read_bytes())
    assert [c.nse_symbol for c in companies] == ["FXALPHA", "FXBETA", "FXGAMMA"]
    assert companies[0].name == "Fixture Alpha Limited"
    assert any("not a valid ISIN" in p for p in problems)
    assert any("appears twice" in p for p in problems)


def test_wrong_file_is_plain_english():
    with pytest.raises(FriendlyError) as info:
        parse(b"Date,Open,Close\n2026-01-01,1,2\n")
    assert "EQUITY_L.csv" in info.value.fix


def test_empty_file_is_plain_english():
    with pytest.raises(FriendlyError):
        parse(b"")
