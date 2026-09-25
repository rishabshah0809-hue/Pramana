import pytest

from app.config import load_config
from app.errors import FriendlyError


def test_real_config_loads():
    config = load_config()
    assert config["watchlist"] == []
    assert config["market_hours"] == {"open": "09:15", "close": "15:30"}


def test_config_has_no_filled_model_names_yet():
    ai = load_config()["ai"]
    for provider in ai.values():
        for key, value in provider.items():
            if key != "temperature":
                assert value == "", f"{key} should be an empty slot in M0"


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
