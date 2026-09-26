"""M2: feed parsing, polite downloads, the raw store and company matching.
Everything here uses FIXTURE data; no test contacts the internet."""

from datetime import datetime, timezone

import pytest

from app.adapters import feeds, polite
from app.adapters.feeds import FeedFormatError, parse_published, parse_rss
from app.errors import FriendlyError
from app.services import filings, rawstore
from app.services.matching import Matcher, norm_name
from app.store import db
from tests.conftest import FIXTURES


def test_parses_nse_and_bse_feeds():
    items, received = parse_rss((FIXTURES / "FIXTURE_nse_announcements.xml").read_bytes(), "x")
    assert received == 5 and len(items) == 4          # the item without a company is dropped
    assert items[1].title == "FIXTURE BETA LIMITED"   # stray newline removed
    bse, _ = parse_rss((FIXTURES / "FIXTURE_bse_announcements.xml").read_bytes(), "x")  # has BOM
    assert bse[0].scripcode == "599001"
    assert feeds.company_from_title(bse[0].title) == "Fixture Alpha Ltd"


def test_feed_format_change_is_plain_english():
    with pytest.raises(FeedFormatError) as e:
        parse_rss(b"<html><body>Access denied</body></html>", "NSE Insider Trading feed")
    assert "NSE Insider Trading feed has changed its format" in e.value.message
    assert "Traceback" not in str(e.value)
    with pytest.raises(FeedFormatError):
        parse_rss(b"not xml at all", "x")


def test_published_times_are_ist_or_unknown():
    assert parse_published("26-Sep-2026 02:11:54").utcoffset().total_seconds() == 5.5 * 3600
    assert parse_published("25-Sep-2026 16:45").minute == 45
    assert parse_published("Fri, 25 Sep 2026 17:16:51 GMT").tzinfo is not None
    assert parse_published("") is None and parse_published(None) is None
    assert parse_published("sometime") is None      # never guessed


def test_classification_uses_exchange_subject_only():
    assert filings.classify("Transcript of earnings call") == "transcript"
    assert filings.classify("Intimation of bagging of orders/contracts") == "order"
    assert filings.classify("Credit Rating update") == "rating"
    assert filings.classify("Disclosure under Regulation 7(2)") == "insider"
    assert filings.classify("Financial Results for the quarter") == "results"
    assert filings.classify("Something else") == "other"
    assert filings.status_from_subject("Revised outcome of board meeting")[0] == "revised"
    assert filings.status_from_subject("Corrigendum to notice")[0] == "corrected"
    assert filings.status_from_subject("Outcome of board meeting") is None


class FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status_code, self.body, self.headers = status, body, headers or {}

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def get(self, url, headers=None, timeout=None, stream=None):
        self.calls.append(headers)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


URL = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"


def client(outcomes, sleeps):
    return polite.PoliteClient(session=FakeSession(outcomes), sleep=sleeps.append,
                               clock=lambda: 1000.0)


def test_offline_retries_then_plain_english(temp_dirs):
    sleeps = []
    c = client([ConnectionError("down")] * 3, sleeps)
    with pytest.raises(polite.FetchFailed) as e:
        c.get(URL)
    assert e.value.status == "error" and "Could not reach NSE" in e.value.message
    assert [s for s in sleeps if s >= 2] == [2, 4]    # waits 2 s then 4 s between tries


def test_http_errors_become_fetch_statuses(temp_dirs):
    for code, status, words in [(403, "blocked", "refused"), (429, "blocked", "slow down"),
                                (404, "missing", "doesn't exist"), (503, "error", "problem")]:
        with pytest.raises(polite.FetchFailed) as e:
            client([FakeResponse(code)] * 3, []).get(URL)
        assert e.value.status == status and words in e.value.message


def test_polite_headers_and_not_modified(temp_dirs):
    s = FakeSession([FakeResponse(304, headers={"ETag": "abc"})])
    r = polite.PoliteClient(session=s, sleep=lambda x: None).get(URL, etag="abc")
    assert r.not_modified
    assert "MosaicIndia" in s.calls[0]["User-Agent"] and s.calls[0]["If-None-Match"] == "abc"


def test_unlisted_host_is_refused(temp_dirs):
    with pytest.raises(FriendlyError, match="not an approved data source"):
        client([], []).get("https://www.nseindia.com/api/corporate-announcements")


def test_raw_store_versions_never_overwrite(db_ready):
    t = datetime(2026, 9, 26, 5, 0, tzinfo=timezone.utc)
    conn = db.connect()
    try:
        with conn:
            a = rawstore.save(conn, source="announcements", url="https://x/f.pdf", content=b"v1",
                              doc_type="results", fetched_at=t, licence="FIXTURE")
            same = rawstore.save(conn, source="announcements", url="https://x/f.pdf",
                                 content=b"v1", doc_type="results", fetched_at=t,
                                 licence="FIXTURE")
            b = rawstore.save(conn, source="announcements", url="https://x/f.pdf", content=b"v2",
                              doc_type="results", fetched_at=t, licence="FIXTURE")
        assert (a.outcome, same.outcome, b.outcome) == ("new", "unchanged", "new_version")
        assert same.document_id == a.document_id and b.version == 2
        rows = conn.execute("SELECT file_path FROM documents ORDER BY id").fetchall()
        assert [rawstore.read(r["file_path"]) for r in rows] == [b"v1", b"v2"]  # both kept
        old = rawstore.current_status(conn, a.document_id)
        assert old["status"] == "superseded" and old["superseded_by"] == b.document_id
        for sql in ("UPDATE documents SET url = 'y'", "DELETE FROM documents",
                    "UPDATE document_status SET reason = 'y'", "DELETE FROM document_status"):
            with pytest.raises(Exception, match="append-only"):
                with conn:
                    conn.execute(sql)
    finally:
        conn.close()


def test_matching_is_exact_only(with_bse):
    conn = db.connect()
    try:
        m = Matcher(conn)
    finally:
        conn.close()
    assert m.match(isin="INE0FXA01011") == ("INE0FXA01011", "isin")
    assert m.match(bse_code="599001") == ("INE0FXA01011", "bse_code")
    assert m.match(name="  FIXTURE   beta limited ") == ("INE0FXB01019", "exact_name")
    assert m.match(name="Fixture Alpha Ltd") == ("INE0FXA01011", "exact_name")  # BSE alias
    assert m.match(name="Fixture Alpha") == (None, None)       # close is not good enough
    assert m.match(name="Fixture Alpah Limited") == (None, None)
    assert norm_name(" A  B ") == "a b"


def test_bse_feed_filter_skips_fund_notices(with_bse):
    from app.adapters import announcements
    from app.adapters.feeds import FeedItem

    bse = announcements.FEEDS[-1]
    conn = db.connect()
    try:
        m = Matcher(conn)
    finally:
        conn.close()
    item = lambda code, subject: FeedItem("FIXTURE", None, subject, None, code)  # noqa: E731
    assert announcements.keep(bse, item("599001", "Outcome of board meeting"), m)
    assert not announcements.keep(bse, item("538429", "NAV of 25th September 2026"), m)
    m.by_bse = {}   # before BSE's list is uploaded: equity-range codes, minus NAV notices
    assert announcements.keep(bse, item("538000", "Outcome of board meeting"), m)
    assert not announcements.keep(bse, item("538429", "NAV of 25th September 2026"), m)
    assert not announcements.keep(bse, item("9000379", "Anything"), m)
