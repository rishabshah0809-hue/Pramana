"""Document Viewer (Screen 6): the original filing exactly as fetched, with its source,
published time, fetch time, version and status. Citation highlighting arrives in M3."""

import streamlit as st

from app.errors import FriendlyError, report
from app.services import documents, filings, watchlist
from app.services.rawstore import STATUSES
from app.timeutil import IST, fmt_ist, from_iso
from app.ui.common import card_head, esc, md, page_header, show_error, tag

page_header("Document Viewer", "The original filing exactly as fetched, with its source, times, "
                               "version and status.", crumb="Research")

PAGES_PER_VIEW = 5
STATUS_BADGE = {"original": ("Original", "green"), "revised": ("Revised", "orange"),
                "corrected": ("Corrected", "orange"), "cancelled": ("Cancelled", "red"),
                "superseded": ("Superseded", "red")}


def _time(value, unknown_reason):
    return fmt_ist(from_iso(value)) if value else f"Unknown — {unknown_reason}"


def _show_pdf(data: bytes, key: str):
    total = documents.pdf_page_count(data)
    st.caption(f"{total} page(s). Shown as images of the original pages.")
    if total > PAGES_PER_VIEW:
        start = st.number_input("From page", min_value=1, max_value=total, value=1,
                                step=PAGES_PER_VIEW, key=f"page-{key}")
    else:
        start = 1
    for i, png in enumerate(documents.pdf_pages_png(data, int(start), PAGES_PER_VIEW)):
        st.image(png, caption=f"Page {int(start) + i} of {total}")


def _show_bytes(data: bytes, name: str, key: str, feed_label: str = "stored feed"):
    kind = documents.kind_of(data, name)
    if kind == "pdf":
        _show_pdf(data, key)
    elif kind == "zip":
        members = documents.zip_members(data)
        st.caption(f"A zip file with {len(members)} file(s), as filed with the exchange.")
        if members:
            pick = st.selectbox("File inside the zip", [m["name"] for m in members],
                                key=f"zip-{key}")
            _show_bytes(documents.zip_member(data, pick), pick, f"{key}-{pick}")
    elif kind == "xml":
        if data.lstrip(b"\xef\xbb\xbf \r\n\t")[:200].find(b"<rss") != -1:
            st.dataframe(documents.feed_items(data, feed_label), hide_index=True)
        else:
            st.caption("Structured (XBRL/XML) filing: each reported item and its value, as filed.")
            st.dataframe(documents.xml_facts(data), hide_index=True)
        with st.expander("Raw XML"):
            st.code(data[:200_000].decode("utf-8", errors="replace"), language="xml")
    elif kind == "csv":
        rows = documents.csv_rows(data)
        if rows:
            st.dataframe([dict(zip(rows[0], r)) for r in rows[1:]], hide_index=True)
    elif kind == "html":
        st.caption("Web-page filing, shown as plain text.")
        st.text(documents.html_text(data)[:100_000])
    else:
        st.info("This file type can't be shown here. Use 'Download original' to open it.")


def _viewer(doc_id: int):
    doc = documents.get(doc_id)
    if doc is None:
        st.warning("That document isn't in the register.")
        return
    f = doc["filing"]
    title = (f and f["subject"]) or documents.filename(doc)
    status = doc["status"]
    label, color = STATUS_BADGE[status["status"]]
    md(card_head(title, f"{doc['company_name'] or 'Not linked to a company'} · "
                        f"{documents.filename(doc)}", "doc", tag(label, color)))
    if status["status"] == "superseded" and status["superseded_by"]:
        st.error(f"**Superseded** by document {status['superseded_by']}. {status['reason']}")
        st.page_link("app/ui/DocumentViewer.py", label="Open the newer document",
                     query_params={"doc": status["superseded_by"]}, icon=":material/arrow_forward:")
    elif status["status"] != "original":
        st.warning(f"**{label}.** {status['reason']}")

    def cell(name, value, unknown=False):
        return f'<div class="{"unk" if unknown else ""}"><small>{esc(name)}</small><b>{esc(value)}</b></div>'

    source = doc["source"] + (f" · {f['exchange']} ({f['feed']})" if f else "")
    md('<div class="pm-kv">'
       + cell("Company", doc["company_name"] or "Not linked to a company", not doc["company_name"])
       + cell("Type", filings.CATEGORY_LABELS.get(doc["type"], doc["type"]))
       + cell("Source", source)
       + cell("Published", _time(doc["published_at"], "the source gave no published time"),
              not doc["published_at"])
       + cell("Fetched", fmt_ist(from_iso(doc["fetched_at"])))
       + cell("Version", f"{doc['version']} · {label}") + "</div>")
    st.caption(f"Original URL: {doc['url']}  \nSHA-256: `{doc['content_hash']}` · Stored as "
               f"`data/{doc['file_path']}`  \nTerms: {doc['licence'] or 'Unknown'}")
    if f and f["published_raw"]:
        st.caption(f"Published time exactly as the exchange wrote it: {f['published_raw']} (IST)")

    data = documents.content(doc)
    b1, b2 = st.columns(2)
    b1.download_button("Download original", data, file_name=documents.filename(doc),
                       icon=":material/download:")
    if doc["url"].startswith("http") and b2.button("Re-fetch from source",
                                                   icon=":material/refresh:"):
        with st.spinner("Downloading again…"):
            result = documents.refetch(doc_id)
        (st.info if result.outcome == "unchanged" else st.success)(result.message)
        if result.outcome == "new_version":
            st.page_link("app/ui/DocumentViewer.py", label="Open the new version",
                         query_params={"doc": result.document_id})

    vers = documents.versions(doc["url"])
    if len(vers) > 1:
        with st.expander(f"All versions ({len(vers)}) — none are ever overwritten"):
            for v in vers:
                st.page_link("app/ui/DocumentViewer.py", query_params={"doc": v["id"]},
                             label=f"Version {v['version']} · fetched "
                                   f"{fmt_ist(from_iso(v['fetched_at']))} · "
                                   f"{v['content_hash'][:12]}")

    st.divider()
    _show_bytes(data, documents.filename(doc), str(doc_id),
                feed_label=f"{f['feed']} feed" if f else "stored feed")
    st.divider()

    with st.expander("Change this document's status (corrections and superseded filings)"):
        for h in documents.history(doc_id):
            st.caption(f"{fmt_ist(from_iso(h['created_at']))} · {h['status']} · by {h['set_by']}"
                       f" · {h['reason']}")
        with st.form(f"status-{doc_id}"):
            new = st.selectbox("New status", STATUSES)
            newer = st.number_input("Replaced by document number (only for 'superseded')",
                                    min_value=0, step=1, value=0)
            reason = st.text_input("Why? (required)")
            if st.form_submit_button("Save status"):
                documents.set_status(doc_id, new, reason, int(newer) or None)
                st.success("Saved. The earlier status is kept in the history above.")
                st.rerun()


def _upload():
    st.caption("For older filings the feeds no longer list: download the file from NSE or BSE in "
               "your browser, then upload it here. It is stored unchanged, like any fetched file.")
    items = watchlist.list_items()
    if not items:
        st.info("Add companies to your watchlist first.")
        return
    with st.form("manual-upload", clear_on_submit=True):
        company = st.selectbox("Company", items, format_func=lambda i: i["name"])
        category = st.selectbox("Type of filing", list(filings.CATEGORY_LABELS),
                                format_func=filings.CATEGORY_LABELS.get)
        subject = st.text_input("Subject, as shown on the exchange website")
        url = st.text_input("The file's web address on NSE/BSE (optional, but recommended)")
        date = st.date_input("Published date shown on the exchange website", value=None)
        up = st.file_uploader("The file (PDF, XML, ZIP, HTML or CSV)",
                              type=["pdf", "xml", "zip", "html", "htm", "csv"])
        if st.form_submit_button("Store this filing", type="primary"):
            if up is None:
                raise FriendlyError("No file was chosen.", "Choose the file, then press Store.")
            from datetime import datetime, time

            published = datetime.combine(date, time(0, 0), IST) if date else None
            doc_id, msg = documents.add_manual(up.getvalue(), up.name, company["isin"], category,
                                               subject, url, published)
            st.success(msg)
            st.page_link("app/ui/DocumentViewer.py", label="Open it",
                         query_params={"doc": doc_id})


try:
    doc_param = st.query_params.get("doc")
    tab_view, tab_list, tab_upload = st.tabs(["Document", "All documents", "Add a filing"])
    with tab_view:
        if doc_param and str(doc_param).isdigit():
            with st.container(border=True, key="card-doc"):
                _viewer(int(doc_param))
        else:
            st.info("Open a filing from a company's page, or pick one under **All documents**.")
    with tab_list, st.container(border=True, key="card-alldocs"):
        items = watchlist.list_items()
        pick = st.selectbox("Company", [None] + items,
                            format_func=lambda i: "All companies" if i is None else i["name"])
        docs = documents.recent(company=pick["isin"] if pick else None)
        if not docs:
            st.caption("No filing files stored yet. They are downloaded for watchlist companies "
                       "as new filings appear in the exchange feeds.")
        for d in docs:
            when = d["published_at"] or d["fetched_at"]
            st.page_link("app/ui/DocumentViewer.py", query_params={"doc": d["id"]},
                         label=f"{fmt_ist(from_iso(when))} · {d['company_name'] or '—'} · "
                               f"{filings.CATEGORY_LABELS.get(d['type'], d['type'])} · "
                               f"v{d['version']} · #{d['id']}")
    with tab_upload, st.container(border=True, key="card-upload"):
        md(card_head("Add a filing", None, "upload"))
        _upload()
except FriendlyError as err:
    show_error(err)
except Exception as exc:  # never show a traceback to the owner
    show_error(report(exc))
