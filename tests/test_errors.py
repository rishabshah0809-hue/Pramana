import logging
import sqlite3

from app.errors import FriendlyError, RedactSecretsFilter, explain, report, setup_logging


def test_unknown_error_becomes_plain_english():
    err = explain(ValueError("x = y[0] IndexError deep internal detail"))
    assert isinstance(err, FriendlyError)
    assert "deep internal detail" not in str(err)
    assert "Traceback" not in str(err)
    assert err.fix


def test_known_errors_have_specific_messages():
    assert "busy" in explain(sqlite3.OperationalError("database is locked")).message
    assert "internet" in explain(ConnectionError()).message


def test_report_writes_details_to_log_not_screen(temp_dirs):
    setup_logging()
    try:
        raise RuntimeError("secret internal detail")
    except RuntimeError as exc:
        err = report(exc)
    for h in logging.getLogger("mosaic").handlers:
        h.flush()
    log_text = (temp_dirs / "logs" / "mosaic.log").read_text()
    assert "secret internal detail" in log_text
    assert "secret internal detail" not in str(err)


def test_keys_are_redacted_from_logs(monkeypatch):
    # FIXTURE: fake key value used only in this test
    monkeypatch.setenv("GROQ_API_KEY", "fixture-not-a-real-key-123")
    record = logging.LogRecord("mosaic", logging.INFO, "", 0,
                               "calling with %s", ("fixture-not-a-real-key-123",), None)
    RedactSecretsFilter().filter(record)
    assert "fixture-not-a-real-key" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()
