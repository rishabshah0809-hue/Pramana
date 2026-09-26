"""Basic setup checks shown on the dashboard (database, settings, keys)."""

from dataclasses import dataclass

from app import paths
from app.config import load_config
from app.errors import FriendlyError
from app.keys import key_source
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
            Check(
                "Database", False,
                "Not created yet. What to do: reload this page; if it stays, restart the app.",
            )
        )

    source = key_source()
    where = ".env file" if source == ".env" else ("Streamlit secrets" if source else None)
    from app.adapters.registry import AI_PROVIDERS
    from app.keys import get_key

    missing = [p.name for p in AI_PROVIDERS.values() if not get_key(p.key_name)]
    if not missing:
        checks.append(Check("Keys", True, f"Groq and Gemini keys found ({where})"))
    else:
        checks.append(Check("Keys", False,
                            f"No key for {', '.join(missing)}. What to do: paste it into .env "
                            f"(see README). Until then the AI steps wait in the queue."))

    return checks
