"""Download the golden-set filings once into tests/golden/docs/ (git-ignored).

    python -m tests.golden.fetch

Uses the app's polite downloader (approved hosts only, 1 request per second, honest user
agent). A one-time exception to "watchlist only", approved by the owner on 26 Sep 2026.
Each file must match the SHA-256 in manifest.yaml; a mismatch is reported, never accepted.
"""

import hashlib
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
DOCS = HERE / "docs"
sys.path.insert(0, str(HERE.parent.parent))


def manifest() -> list[dict]:
    return yaml.safe_load((HERE / "manifest.yaml").read_text(encoding="utf-8"))["documents"]


def main() -> int:
    from app.adapters.polite import FetchFailed, PoliteClient

    DOCS.mkdir(exist_ok=True)
    client, problems = PoliteClient(), 0
    for d in manifest():
        target = DOCS / d["file"]
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == d["sha256"]:
            print(f"{d['id']}: already here")
            continue
        try:
            data = client.get(d["url"]).content
        except FetchFailed as exc:
            print(f"{d['id']}: could not download — {exc.message}")
            problems += 1
            continue
        digest = hashlib.sha256(data).hexdigest()
        if digest != d["sha256"]:
            print(f"{d['id']}: the file on the exchange has changed (hash {digest[:12]}…). "
                  f"Not saved. Tell Claude so the golden set can be updated.")
            problems += 1
            continue
        target.write_bytes(data)
        print(f"{d['id']}: saved {target.name} ({len(data):,} bytes)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
