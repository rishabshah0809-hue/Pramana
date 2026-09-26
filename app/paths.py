"""Where Pramana keeps its files.

MOSAIC_DATA_DIR / MOSAIC_LOG_DIR / MOSAIC_CONFIG can override the defaults
(used by tests so they never touch the owner's real data).
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return Path(os.environ.get("MOSAIC_DATA_DIR", PROJECT_ROOT / "data"))


def raw_dir() -> Path:
    return data_dir() / "raw"


def db_path() -> Path:
    return data_dir() / "mosaic.db"


def log_dir() -> Path:
    return Path(os.environ.get("MOSAIC_LOG_DIR", PROJECT_ROOT / "logs"))


def config_path() -> Path:
    return Path(os.environ.get("MOSAIC_CONFIG", PROJECT_ROOT / "config.yaml"))


def env_path() -> Path:
    return PROJECT_ROOT / ".env"


def env_example_path() -> Path:
    return PROJECT_ROOT / ".env.example"
