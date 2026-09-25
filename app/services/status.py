"""Basic setup checks shown on the dashboard (database, settings, keys file)."""

from dataclasses import dataclass

from app import paths
from app.config import load_config
from app.errors import FriendlyError
from app.store import db


@dataclass
class Check:
    label: str
    ok: bool
    detail: str


def setup_checks() -> list[Check]:
    checks = []

    try:
        load_config()
        checks.append(Check("Settings (config.yaml)", True, "Loaded"))
    except FriendlyError as exc:
        checks.append(Check("Settings (config.yaml)", False, str(exc)))

    if paths.db_path().exists():
        found = set(db.table_names()) & set(db.TABLES)
        ok = len(found) == len(db.TABLES)
        checks.append(
            Check("Database", ok, f"{len(found)} of {len(db.TABLES)} tables ready")
        )
    else:
        checks.append(
            Check("Database", False, "Not created yet. What to do: run start.py to create it.")
        )

    if paths.env_path().exists():
        checks.append(Check("Keys file (.env)", True, "Found (no keys are needed yet)"))
    else:
        checks.append(
            Check("Keys file (.env)", False, "Missing. What to do: run start.py to create it.")
        )

    return checks
