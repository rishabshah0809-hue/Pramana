import pytest

import start


def test_old_python_gives_plain_english():
    with pytest.raises(start.StartupProblem) as info:
        start.check_python_version((3, 9))
    assert "3.11" in info.value.message
    assert "python.org" in info.value.fix


def test_current_python_is_fine():
    start.check_python_version((3, 11))


def test_env_file_created_from_example(tmp_path, monkeypatch):
    (tmp_path / ".env.example").write_text("GROQ_API_KEY=\n")
    monkeypatch.setattr(start, "PROJECT_ROOT", tmp_path)
    assert start.ensure_env_file() is True
    assert (tmp_path / ".env").read_text() == "GROQ_API_KEY=\n"
    assert start.ensure_env_file() is False  # never overwrites your keys


def test_missing_env_example_is_plain_english(tmp_path, monkeypatch):
    monkeypatch.setattr(start, "PROJECT_ROOT", tmp_path)
    with pytest.raises(start.StartupProblem, match="env.example"):
        start.ensure_env_file()


def test_main_never_shows_traceback(monkeypatch, capsys, tmp_path):
    def boom():
        raise RuntimeError("internal detail")
    monkeypatch.setattr(start, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(start, "check_python_version", boom)
    assert start.main() == 1
    out = capsys.readouterr().out
    assert "PROBLEM:" in out and "WHAT TO DO:" in out
    assert "Traceback" not in out and "internal detail" not in out
    assert "internal detail" in (tmp_path / "logs" / "startup-error.log").read_text()
