from app import keys


def test_env_value_is_read(monkeypatch):
    # FIXTURE: fake key value used only in this test
    monkeypatch.setenv("GROQ_API_KEY", "fixture-value")
    assert keys.get_key("GROQ_API_KEY") == "fixture-value"


def test_missing_key_is_none(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(keys, "_streamlit_secrets", lambda: {})
    assert keys.get_key("GEMINI_API_KEY") is None


def test_streamlit_secrets_used_when_no_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(keys, "_streamlit_secrets", lambda: {"GEMINI_API_KEY": "fixture-secret"})
    assert keys.get_key("GEMINI_API_KEY") == "fixture-secret"
