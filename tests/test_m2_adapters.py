"""M2 adapters end to end with FIXTURE feeds and files (no internet)."""

from decimal import Decimal

from app.adapters import announcements, bulk_block, insider_sast, shareholding
from app.adapters.polite import FetchFailed
from app.services import companies, conflicts, documents, filings, health, holdings, watchlist
from app.store import db
from tests.conftest import FIXTURES, FakeClient, fixture_pdf

NSE_ANN = announcements.FEEDS[0].url
BSE_ANN = announcements.FEEDS[-1].url
ALPHA, BETA, DELTA = "INE0FXA01011", "INE0FXB01019", "INE0FXD01015"


def nse_only_client(extra=None):
    """FIXTURE: NSE announcements feed filled, other NSE feeds empty, BSE feed filled."""
    empty = b'<rss version="2.0"><channel><title>FIXTURE empty</title></channel></rss>'
    responses = {f.url: empty for f in announcements.FEEDS}
    responses[NSE_ANN] = (FIXTURES / "FIXTURE_nse_announcements.xml").read_bytes()
    responses[BSE_ANN] = (FIXTURES / "FIXTURE_bse_announcements.xml").read_bytes()
    pdf = fixture_pdf()
    for name in ("FIXTURE_FXALPHA_results.pdf", "FIXTURE_FXALPHA_revised.pdf",
                 "FIXTURE_FXBETA_transcript.pdf", "FIXTURE_UNKNOWN.pdf"):
        responses[f"https://nsearchives.nseindia.com/corporate/{name}"] = pdf
    for name in ("FIXTURE-alpha-order.pdf", "FIXTURE-delta-rating.pdf"):
        responses[f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}"] = pdf
    responses.update(extra or {})
    return FakeClient(responses)


def test_announcements_indexed_matched_and_downloaded_for_watchlist_only(with_bse):
    watchlist.add(ALPHA)
    c = nse_only_client()
    s = announcements.run(client=c)
    assert s.status == "ok", s.message
    alpha = filings.company_filings(ALPHA)
    subjects = {r["subject"] for r in alpha}
    assert any("Financial Results" in x for x in subjects)
    assert any("bagging of orders" in x for x in subjects)     # matched by BSE code
    assert {r["category"] for r in alpha} >= {"results", "board_meeting", "order"}
    assert all(r["document_id"] for r in alpha)                # files stored for the watchlist
    # Beta is not on the watchlist: indexed, but its file is never downloaded.
    beta = filings.company_filings(BETA)
    assert beta and beta[0]["document_id"] is None
    assert not any("FXBETA_transcript" in u for u in c.calls)
    assert not any("FIXTURE-nav" in u for u in c.calls)       # mutual-fund item skipped
    assert filings.unmatched_count("announcements") == 1      # "Unknown Fixture Company"

    # 14.5: the exchange's own words mark the revised filing.
    revised = next(r for r in alpha if "Revised" in (r["subject"] or ""))
    assert documents.get(revised["document_id"])["status"]["status"] == "revised"
    # Every stored document carries source, published and fetch time.
    doc = documents.get(alpha[0]["document_id"])
    assert doc["source"] == "announcements" and doc["fetched_at"] and doc["published_at"]
    assert doc["filing"]["exchange"] in ("NSE", "BSE")


def test_second_run_adds_nothing_new(with_bse):
    watchlist.add(ALPHA)
    announcements.run(client=nse_only_client())
    conn = db.connect()
    before = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    conn.close()
    s = announcements.run(client=nse_only_client())
    assert s.new_items == 0 and s.files == 0
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == before
    assert conn.execute("SELECT COUNT(*) FROM fetch_log WHERE outcome = 'unchanged'"
                        ).fetchone()[0] >= len(announcements.FEEDS)
    conn.close()


def test_unreachable_feed_is_flagged_not_crashed(with_bse):
    watchlist.add(ALPHA)
    c = nse_only_client({BSE_ANN: FetchFailed("error", "Could not reach BSE. Check your "
                                                       "internet connection.")})
    s = announcements.run(client=c)
    assert s.status == "error" and "Could not reach BSE" in s.message
    assert "5 of 6 feeds checked" in s.message                # the other feeds still worked
    h = health.source_health("announcements")
    assert h.fetch_status == "error" and h.errors_7d == 1 and "Could not reach BSE" in h.fetch_note


def test_changed_page_structure_is_flagged(with_bse):
    s = announcements.run(client=nse_only_client({NSE_ANN: b"<html>Maintenance</html>"}))
    assert s.status == "error" and "has changed its format" in s.message
    assert health.source_health("announcements").fetch_status == "error"


def test_everything_offline(with_bse):
    down = FetchFailed("error", "Could not reach NSE. Check your internet connection.")
    for mod in (announcements, shareholding, insider_sast):
        s = mod.run(client=FakeClient({f.url: down for f in mod.FEEDS}))
        assert s.status == "error" and "Could not reach" in s.message
    s = bulk_block.run(client=FakeClient({u: down for u in bulk_block.FILES.values()}))
    assert s.status == "error" and "Could not reach NSE" in s.message


def test_refetch_appends_versions(with_bse):
    watchlist.add(ALPHA)
    c = nse_only_client()
    announcements.run(client=c)
    doc_id = filings.company_filings(ALPHA)[0]["document_id"]
    doc = documents.get(doc_id)
    same = documents.refetch(doc_id, client=c)
    assert same.outcome == "unchanged" and "identical" in same.message
    c.responses[doc["url"]] = fixture_pdf(pages=3)            # the exchange changed the file
    new = documents.refetch(doc_id, client=c)
    assert new.outcome == "new_version" and new.document_id != doc_id
    assert [v["version"] for v in documents.versions(doc["url"])] == [1, 2]
    assert documents.get(doc_id)["status"]["status"] == "superseded"
    assert documents.pdf_page_count(documents.content(documents.get(doc_id))) == 2  # old kept
    assert documents.pdf_page_count(documents.content(documents.get(new.document_id))) == 3


def test_shareholding_parsed_exactly():
    shp = shareholding.parse_shp((FIXTURES / "FIXTURE_SHP.xml").read_bytes())
    vals = {v.category: v for v in shp.values}
    assert shp.isin == ALPHA and shp.as_of_date == "2026-06-30"
    assert vals["promoter"].percent == Decimal("51.2500") and vals["promoter"].source_text == "0.5125"
    assert vals["fii"].percent == Decimal("18.3000") and vals["dii"].percent == Decimal("11.4700")
    assert vals["government"].percent is None                 # not in this filing: Unknown
    assert vals["promoter_pledged"].source_text == "false"


def test_shareholding_feed_to_chart_and_conflict(with_bse):
    watchlist.add(ALPHA)
    shp_url = "https://nsearchives.nseindia.com/corporate/xbrl/SHP_FIXTURE_WEB.xml"
    feed = (b'<rss version="2.0"><channel><title>FIXTURE</title><item><title>Fixture Alpha '
            b'Limited</title><link>' + shp_url.encode() + b'</link><description>FIXTURE '
            b'shareholding</description><pubDate>21-Jul-2026 18:00:00</pubDate></item>'
            b'</channel></rss>')
    empty = b'<rss version="2.0"><channel><title>FIXTURE empty</title></channel></rss>'
    c = FakeClient({shareholding.FEEDS[0].url: feed, shareholding.FEEDS[1].url: empty,
                    shp_url: (FIXTURES / "FIXTURE_SHP.xml").read_bytes()})
    s = shareholding.run(client=c)
    assert s.status == "ok", s.message
    series = holdings.series(ALPHA)
    promoter = next(r for r in series if r["category"] == "promoter")
    assert promoter["percent"] == Decimal("51.2500") and promoter["source"] == "shareholding"

    # The owner uploads a different source's copy that disagrees: a conflict, never averaged.
    other = (FIXTURES / "FIXTURE_SHP.xml").read_text().replace(">0.5125<", ">0.5000<")
    documents.add_manual(other.encode(), "FIXTURE_bse_copy.xml", ALPHA, "shareholding",
                         "FIXTURE BSE copy", None, None)
    open_ = conflicts.open_conflicts(ALPHA)
    assert len(open_) == 1 and open_[0]["figure"] == "shareholding:promoter:2026-06-30"
    assert {v["value"] for v in open_[0]["values"]} == {"51.2500", "50.0000"}
    promoter = next(r for r in holdings.series(ALPHA) if r["category"] == "promoter")
    assert promoter["percent"] == Decimal("51.2500")          # the feed (higher trust) is shown
    conflicts.mark_reviewed(open_[0]["id"], "FIXTURE review")
    assert conflicts.open_conflicts(ALPHA) == []


def test_bulk_block_deals(with_bse):
    c = FakeClient({bulk_block.FILES["bulk"]: (FIXTURES / "FIXTURE_bulk.csv").read_bytes(),
                    bulk_block.FILES["block"]: (FIXTURES / "FIXTURE_block.csv").read_bytes()})
    s = bulk_block.run(client=c)
    assert s.status == "ok" and s.new_items == 4, s.message   # the "HOLD" row is rejected
    alpha = bulk_block.company_deals(ALPHA)
    assert {(d["side"], d["price"]) for d in alpha} == {("BUY", "92.25"), ("SELL", "93.10")}
    assert bulk_block.company_deals(BETA)[0]["deal_type"] == "block"
    assert bulk_block.run(client=c).new_items == 0            # re-run adds nothing
    bad = FakeClient({u: b"Symbol,Something\nX,Y\n" for u in bulk_block.FILES.values()})
    s = bulk_block.run(client=bad)
    assert s.status == "error" and "changed its format" in s.message


def test_bse_list_links_codes_and_adds_bse_only(with_bse):
    assert companies.get(ALPHA)["bse_code"] == "599001"
    assert companies.get(ALPHA)["name"] == "Fixture Alpha Limited"   # NSE name kept
    delta = companies.get(DELTA)
    assert delta and delta["nse_symbol"] is None and delta["bse_code"] == "599004"
    assert companies.get("INE0FXE01013") is None                     # suspended / debt skipped


def test_manual_upload_is_stored_raw(with_bse):
    watchlist.add(ALPHA)
    pdf = fixture_pdf()
    doc_id, msg = documents.add_manual(pdf, "FIXTURE old results.pdf", ALPHA,
                                       "results", "FIXTURE Q4 results", None, None)
    doc = documents.get(doc_id)
    assert doc["source"] == "manual_upload" and doc["published_at"] is None
    assert "entered by you" in doc["licence"]
    same_id, msg = documents.add_manual(pdf, "FIXTURE old results.pdf", ALPHA,
                                        "results", "FIXTURE Q4 results", None, None)
    assert same_id == doc_id and "already stored" in msg
    row = next(r for r in filings.company_filings(ALPHA) if r["kind"] == "manual")
    assert row["subject"] == "FIXTURE Q4 results"
