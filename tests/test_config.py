import pytest

from app.config import load_config
from app.errors import FriendlyError


def test_real_config_loads():
    config = load_config()
    assert config["watchlist"]["max_companies"] == 50
    assert config["market_holidays"] == []  # never invented; owner fills from NSE
    assert config["market_hours"] == {"open": "09:15", "close": "15:30"}


def test_ai_models_live_in_config_with_limits():
    ai = load_config()["ai"]
    for task in ("extraction", "crosscheck", "summary"):
        for role in ("primary", "fallback"):
            model = ai["tasks"][task][role]["model"]
            assert model and model in ai["limits"], f"{task}.{role} needs limits"
    # A second model must check the first one's work (Section 6).
    assert ai["tasks"]["crosscheck"]["primary"]["provider"] !=         ai["tasks"]["extraction"]["primary"]["provider"]
    assert ai["tasks"]["extraction"]["primary"]["temperature"] == 0


def test_broken_config_gives_plain_english(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text("app:\n  timezone: [unclosed\n")
    with pytest.raises(FriendlyError) as info:
        load_config(bad)
    assert "typing mistake" in info.value.message
    assert "Traceback" not in str(info.value)


def test_missing_config_gives_plain_english(tmp_path):
    with pytest.raises(FriendlyError, match="missing"):
        load_config(tmp_path / "nope.yaml")


def test_missing_section_is_reported(tmp_path):
    partial = tmp_path / "config.yaml"
    partial.write_text("app: {}\n")
    with pytest.raises(FriendlyError) as info:
        load_config(partial)
    assert "watchlist" in info.value.message
