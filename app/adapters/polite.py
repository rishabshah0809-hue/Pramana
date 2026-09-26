"""Polite downloads from NSE and BSE (brief Section 4).

- Only hosts listed in the source registry can be contacted (app/net.py).
- A clear user agent, at most one request per second per website, waits of 2 s, 4 s,
  8 s between retries, and "only send it if it changed" requests where the site supports them.
- Every failure becomes a FetchFailed with a fetch status (14.3) and a plain-English message.
"""

import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import load_config
from app.net import check_url_allowed

SITE_NAMES = {"nsearchives.nseindia.com": "NSE", "archives.nseindia.com": "NSE",
              "www.bseindia.com": "BSE"}

_last_request: dict[str, float] = {}
_lock = threading.Lock()


@dataclass
class Response:
    url: str
    http_status: int
    content: bytes
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


class FetchFailed(Exception):
    """status is one of the 14.3 fetch states: missing | blocked | timeout | error."""

    def __init__(self, status: str, message: str, http_status: int | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.http_status = http_status


def site_name(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return SITE_NAMES.get(host, host or "the website")


def _settings() -> dict:
    s = load_config().get("rate_limits", {}).get("exchanges", {}) or {}
    return {
        "gap": float(s.get("min_seconds_between_requests", 1.0)),
        "attempts": int(s.get("max_attempts", 3)),
        "timeout": float(s.get("timeout_seconds", 30)),
        "max_bytes": int(float(s.get("max_file_mb", 40)) * 1024 * 1024),
        "user_agent": str(s.get("user_agent") or "MosaicIndia (personal research tool)"),
    }


def _http_failure(code: int, site: str) -> FetchFailed:
    if code == 404 or code == 410:
        return FetchFailed("missing", f"{site} says this file doesn't exist (it may have been "
                                      f"moved or withdrawn).", code)
    if code == 429:
        return FetchFailed("blocked", f"{site} asked the app to slow down. The app will wait and "
                                      f"try again at the next scheduled check.", code)
    if code in (401, 403):
        return FetchFailed("blocked", f"{site} refused the request (it may be limiting automated "
                                      f"access). The app will try again at the next scheduled "
                                      f"check.", code)
    if code >= 500:
        return FetchFailed("error", f"{site} had a problem on its side (error {code}). The app "
                                    f"will try again later.", code)
    return FetchFailed("error", f"{site} gave an unexpected answer (code {code}). The app will "
                                f"try again later.", code)


class PoliteClient:
    def __init__(self, session=None, sleep=time.sleep, clock=time.monotonic):
        if session is None:
            import requests

            session = requests.Session()
        self.session = session
        self.sleep = sleep
        self.clock = clock
        self.s = _settings()

    def _wait_turn(self, host: str) -> None:
        with _lock:
            last = _last_request.get(host)
            now = self.clock()
            if last is not None and now - last < self.s["gap"]:
                self.sleep(self.s["gap"] - (now - last))
            _last_request[host] = self.clock()

    def _once(self, url: str, headers: dict, site: str) -> Response:
        import requests

        try:
            r = self.session.get(url, headers=headers, timeout=self.s["timeout"], stream=True)
        except requests.Timeout as exc:
            raise FetchFailed("timeout", f"{site} did not answer in time. Check your internet; "
                                         f"the app will try again.") from exc
        except (requests.ConnectionError, ConnectionError, OSError) as exc:
            raise FetchFailed("error", f"Could not reach {site}. Check your internet "
                                       f"connection.") from exc
        try:
            if r.status_code == 304:
                return Response(url, 304, b"", r.headers.get("ETag"),
                                r.headers.get("Last-Modified"), not_modified=True)
            if r.status_code != 200:
                raise _http_failure(r.status_code, site)
            chunks, size = [], 0
            for chunk in r.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > self.s["max_bytes"]:
                    raise FetchFailed("error", f"This file from {site} is larger than "
                                               f"{self.s['max_bytes'] // (1024 * 1024)} MB, so it "
                                               f"was skipped. You can open it on {site}'s website.")
                chunks.append(chunk)
            return Response(url, 200, b"".join(chunks), r.headers.get("ETag"),
                            r.headers.get("Last-Modified"))
        except requests.RequestException as exc:
            raise FetchFailed("error", f"The download from {site} was interrupted. The app will "
                                       f"try again.") from exc
        finally:
            r.close()

    def get(self, url: str, etag: str | None = None, last_modified: str | None = None) -> Response:
        check_url_allowed(url)
        host = (urlparse(url).hostname or "").lower()
        site = site_name(url)
        headers = {"User-Agent": self.s["user_agent"], "Accept-Encoding": "gzip, deflate"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        failure = None
        for attempt in range(self.s["attempts"]):
            self._wait_turn(host)
            try:
                return self._once(url, headers, site)
            except FetchFailed as exc:
                failure = exc
                # Retrying won't help a missing file, a refusal or an oversized file.
                if exc.status in ("missing", "blocked") or "larger than" in exc.message:
                    break
            if attempt < self.s["attempts"] - 1:
                self.sleep(2 ** (attempt + 1))
        raise failure
