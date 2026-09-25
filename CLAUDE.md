# CLAUDE.md — Mosaic India

The full product brief is in **[PRODUCT_BRIEF.md](PRODUCT_BRIEF.md)**. It is the source of truth. Read it before any work, including **Section 14 (v1.1 enhancements)**, which adds requirements to milestones M1–M6.

## Non-negotiable principles (brief Section 2)

These override every feature request. If a task conflicts with them, stop and flag it to the owner.

1. **The AI never supplies facts.** Every number, date, name and quote comes from ingested source data. AI only reads, extracts, classifies and summarises stored data.
2. **Every claim is traceable** to its source document, exact passage, fetch time and processing steps.
3. **Verify before display.** Code checks AI output before saving: quotes must exist verbatim in the source, numbers must appear in the cited passage.
4. **"Unknown" is a valid answer.** Show "insufficient evidence" rather than guess. Empty states beat invented content.
5. **Show freshness everywhere.** Every data point shows source timestamp and fetch timestamp. Stale data is visibly marked.
6. **Point-in-time storage.** Raw data is never overwritten; new versions are appended.
7. **Contradictions are first-class.** Evidence against a thesis is shown as prominently as evidence for it.
8. **Official sources outrank secondary sources.** Filings > news > blogs. Conflicts are flagged, never silently resolved.

## Owner's operating rules

1. Build one milestone at a time, in order M0 → M6 (brief Section 10). Never start the next one early.
2. Before coding a milestone, post a short plain-English plan and wait for "go ahead".
3. Never fabricate data, sample values or fake API responses in the running app. Fixtures only in `tests/`, labelled as fixtures.
4. If a data source is paid, blocked or ToS-restricted, STOP and propose a free alternative. Never silently substitute or skip.
5. The owner is non-technical and cannot debug. Every on-screen error is plain English with a suggested fix — never a traceback (use `app/errors.py`; details go to `logs/`).
6. After each milestone: run tests, then give a numbered click/run list to confirm it works.
7. Update `README.md`, `ARCHITECTURE.md`, `DATA_SOURCES.md` at the end of every milestone. Commit after each working step.
8. If anything conflicts with the principles above, stop and flag it.

## Git branches

- Only two branches exist: **`main`** and **`experiment`**. Never create any other branch.
- All work happens on `experiment`. Push to `main` only when the owner explicitly asks (e.g. "push to both").

## Practical notes

- API keys live only in `.env` or `.streamlit/secrets.toml` (both git-ignored). Never in code, logs, the database or Git history.
- Model names, temperatures, schedules and rate limits live in `config.yaml`, never in code.
- Business logic goes in `app/services/`, not `app/ui/`.
- The Streamlit entrypoint is `streamlit_app.py`; add new screens as files in `app/ui/` and register them in its `pages` list.
- Read keys only through `app/keys.get_key()` (supports `.env` and Streamlit secrets).
- Run tests with `python -m pytest`.
