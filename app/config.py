"""Loads config.yaml and checks it has the expected sections."""

from pathlib import Path

import yaml

from app import paths
from app.errors import FriendlyError

REQUIRED_SECTIONS = ("app", "watchlist", "market_hours", "schedules", "rate_limits", "ai")


def load_config(path: Path | None = None) -> dict:
    path = Path(path or paths.config_path())
    if not path.exists():
        raise FriendlyError(
            f"The settings file '{path.name}' is missing.",
            "Download the project again from GitHub, or restore config.yaml from the "
            "project folder's history.",
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", None)
        where = f" near line {line + 1}" if line is not None else ""
        raise FriendlyError(
            f"The settings file '{path.name}' has a typing mistake{where}.",
            "Undo your last edit to config.yaml. Spacing matters in this file: use "
            "spaces (not tabs) and keep the same indentation as the lines around it.",
        ) from exc
    if not isinstance(data, dict):
        raise FriendlyError(
            f"The settings file '{path.name}' is empty or not in the expected format.",
            "Restore config.yaml from the project on GitHub.",
        )
    missing = [s for s in REQUIRED_SECTIONS if s not in data]
    if missing:
        raise FriendlyError(
            f"The settings file '{path.name}' is missing these sections: {', '.join(missing)}.",
            "Restore config.yaml from the project on GitHub, then re-apply your changes.",
        )
    return data
