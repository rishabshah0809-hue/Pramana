import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def temp_dirs(tmp_path, monkeypatch):
    """Point the app at a throwaway folder so tests never touch real data."""
    monkeypatch.setenv("MOSAIC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MOSAIC_LOG_DIR", str(tmp_path / "logs"))
    return tmp_path
