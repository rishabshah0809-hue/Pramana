"""Plain-English errors and logging.

The owner never sees a traceback. Every problem is shown as a short message
plus a suggested fix; the technical details go to logs/mosaic.log.
"""

import logging
import os
import re
import sqlite3
from logging.handlers import RotatingFileHandler

from app import paths

LOG_FILE_NAME = "mosaic.log"
_ENV_SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PIN|PASSWORD)", re.IGNORECASE)


class FriendlyError(Exception):
    """An error the owner can understand: what went wrong, and what to do."""

    def __init__(self, message: str, fix: str):
        super().__init__(message)
        self.message = message
        self.fix = fix

    def __str__(self) -> str:
        return f"{self.message}\nWhat to do: {self.fix}"


def explain(exc: BaseException) -> FriendlyError:
    """Turn any exception into a FriendlyError. Never includes a traceback."""
    if isinstance(exc, FriendlyError):
        return exc
    log_hint = f"the log file at {paths.log_dir() / LOG_FILE_NAME}"
    if isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower():
        return FriendlyError(
            "The database is busy (another copy of Pramana may be open).",
            "Close any other Pramana windows or terminals, then run start.py again.",
        )
    if isinstance(exc, sqlite3.DatabaseError):
        return FriendlyError(
            "The database file could not be read.",
            f"Restart Pramana. If it happens again, send Claude the last lines of {log_hint}.",
        )
    if isinstance(exc, PermissionError):
        return FriendlyError(
            "Pramana was not allowed to read or write one of its files.",
            "Make sure the project folder is not open in another program and that it "
            "is not in a read-only location, then try again.",
        )
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return FriendlyError(
            "Could not connect to the internet.",
            "Check your Wi-Fi or network connection, then try again.",
        )
    return FriendlyError(
        "Something unexpected went wrong.",
        f"Restart Pramana. If it happens again, send Claude the on-screen message "
        f"and the last lines of {log_hint}.",
    )


class RedactSecretsFilter(logging.Filter):
    """Removes any API key / token values from log lines, as a safety net."""

    def filter(self, record: logging.LogRecord) -> bool:
        secrets = [
            value
            for name, value in os.environ.items()
            if _ENV_SECRET_NAME.search(name) and value and len(value) >= 6
        ]
        if secrets:
            text = record.getMessage()
            for value in secrets:
                text = text.replace(value, "[REDACTED]")
            record.msg, record.args = text, None
        return True


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Send detailed logs to logs/mosaic.log (rotating, max ~5 MB x 5 files)."""
    logger = logging.getLogger("mosaic")
    if any(getattr(h, "_mosaic", False) for h in logger.handlers):
        return logger
    paths.log_dir().mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        paths.log_dir() / LOG_FILE_NAME, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    handler._mosaic = True
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactSecretsFilter())
    logger.addHandler(handler)
    logger.setLevel(level)
    return logger


def report(exc: BaseException, logger: logging.Logger | None = None) -> FriendlyError:
    """Log full details of an error and return the plain-English version."""
    (logger or logging.getLogger("mosaic")).error("Error: %s", exc, exc_info=exc)
    return explain(exc)
