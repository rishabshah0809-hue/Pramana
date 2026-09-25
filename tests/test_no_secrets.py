"""No API key may ever be committed (brief Section 11)."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),        # Groq
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),     # Google / Gemini
    re.compile(r"\d{8,10}:[A-Za-z0-9_-]{30,}"), # Telegram bot token
]


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [ROOT / f for f in out.stdout.splitlines()]


def test_env_file_is_not_tracked():
    assert ROOT / ".env" not in tracked_files()


def test_env_example_has_no_values():
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line and not line.startswith("#"):
            assert line.endswith("="), f"placeholder should be empty: {line}"


def test_no_key_patterns_in_tracked_files():
    for path in tracked_files():
        if not path.is_file() or path.suffix in {".pdf", ".png", ".db"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in KEY_PATTERNS:
            assert not pattern.search(text), f"possible API key in {path.name}"
