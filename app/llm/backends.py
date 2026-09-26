"""The two AI providers behind one shape: generate(...) -> Raw, or an LLMFailure.

Every provider problem becomes one of a few plain kinds, so callers can decide what to do:
rate_limited, quota, unavailable, offline, timeout, bad_key, model_missing, invalid_output.
Retries are left to the queue (the SDKs' own retries are switched off).
"""

import re
from dataclasses import dataclass

from app.adapters.registry import AI_PROVIDERS
from app.keys import get_key
from app.net import check_url_allowed


@dataclass
class Raw:
    text: str
    tokens_in: int
    tokens_out: int


class LLMFailure(Exception):
    def __init__(self, kind: str, message: str, retry_after: float | None = None,
                 per_day: bool = False):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retry_after = retry_after
        self.per_day = per_day


def _key(provider: str) -> str:
    key = get_key(AI_PROVIDERS[provider].key_name)
    if not key:
        raise LLMFailure("bad_key", f"No {AI_PROVIDERS[provider].name} key is set up.")
    return key


def groq_generate(model: str, system: str, user: str, schema: dict, schema_name: str,
                  temperature: float, max_tokens: int, thinking_level: str | None = None) -> Raw:
    """thinking_level, if set, is sent as Groq's reasoning_effort (low / medium / high)."""
    import groq

    check_url_allowed("https://api.groq.com/openai/v1/chat/completions")
    client = groq.Groq(api_key=_key("groq"), max_retries=0, timeout=90)
    try:
        resp = client.chat.completions.create(
            model=model, temperature=temperature, max_completion_tokens=max_tokens,
            **({"reasoning_effort": thinking_level} if thinking_level else {}),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {
                "name": schema_name, "strict": True, "schema": schema}})
    except groq.RateLimitError as exc:
        after = exc.response.headers.get("retry-after") if exc.response is not None else None
        text = str(exc).lower()
        raise LLMFailure("rate_limited", "Groq asked the app to slow down.",
                         float(after) if after else 60.0,
                         per_day="per day" in text or "tpd" in text or "rpd" in text) from exc
    except groq.AuthenticationError as exc:
        raise LLMFailure("bad_key", "Groq did not accept the API key.") from exc
    except groq.PermissionDeniedError as exc:
        raise LLMFailure("bad_key", "Groq refused access for this key.") from exc
    except groq.NotFoundError as exc:
        raise LLMFailure("model_missing", f"Groq no longer offers the model '{model}'.") from exc
    except groq.APITimeoutError as exc:
        raise LLMFailure("timeout", "Groq did not answer in time.") from exc
    except groq.APIConnectionError as exc:
        raise LLMFailure("offline", "Could not reach Groq. Check your internet connection.") from exc
    except groq.BadRequestError as exc:
        if "json_validate_failed" in str(exc):
            raise LLMFailure("invalid_output", "Groq's answer was not valid JSON.") from exc
        raise LLMFailure("unavailable", "Groq rejected the request.") from exc
    except groq.APIStatusError as exc:
        raise LLMFailure("unavailable", f"Groq had a problem on its side ({exc.status_code}).") from exc
    usage = resp.usage
    return Raw(resp.choices[0].message.content or "", getattr(usage, "prompt_tokens", 0) or 0,
               getattr(usage, "completion_tokens", 0) or 0)


def _gemini_retry(exc) -> tuple[float | None, bool]:
    """Seconds to wait (RetryInfo) and whether a per-day quota was hit (QuotaFailure)."""
    text = str(getattr(exc, "details", "")) + " " + str(getattr(exc, "message", ""))
    m = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", text)
    return (float(m.group(1)) if m else None), bool(re.search(r"PerDay|per day", text))


def gemini_generate(model: str, system: str, user: str, schema: dict, schema_name: str,
                    temperature: float, max_tokens: int, thinking_level: str | None = None) -> Raw:
    import httpx
    from google import genai
    from google.genai import errors, types

    check_url_allowed("https://generativelanguage.googleapis.com/v1beta/models")
    client = genai.Client(api_key=_key("gemini"), http_options=types.HttpOptions(
        timeout=120_000, retry_options=types.HttpRetryOptions(attempts=1)))
    config = types.GenerateContentConfig(
        system_instruction=system, temperature=temperature, max_output_tokens=max_tokens,
        response_mime_type="application/json", response_json_schema=schema,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level)
        if thinking_level else None)
    try:
        resp = client.models.generate_content(model=model, contents=user, config=config)
    except errors.ClientError as exc:
        if exc.code == 429:
            wait, per_day = _gemini_retry(exc)
            raise LLMFailure("rate_limited", "Gemini asked the app to slow down.", wait or 60.0,
                             per_day) from exc
        if exc.code in (401, 403) or "API key" in str(exc.message):
            raise LLMFailure("bad_key", "Gemini did not accept the API key.") from exc
        if exc.code == 404:
            raise LLMFailure("model_missing", f"Gemini no longer offers '{model}'.") from exc
        raise LLMFailure("unavailable", "Gemini rejected the request.") from exc
    except errors.ServerError as exc:
        raise LLMFailure("unavailable", "Gemini is busy or having problems right now.") from exc
    except httpx.TimeoutException as exc:
        raise LLMFailure("timeout", "Gemini did not answer in time.") from exc
    except (httpx.TransportError, OSError) as exc:
        raise LLMFailure("offline", "Could not reach Gemini. Check your internet connection.") from exc
    u = resp.usage_metadata
    out = (getattr(u, "candidates_token_count", 0) or 0) + (getattr(u, "thoughts_token_count", 0) or 0)
    return Raw(resp.text or "", getattr(u, "prompt_token_count", 0) or 0, out)


BACKENDS = {"groq": groq_generate, "gemini": gemini_generate}
