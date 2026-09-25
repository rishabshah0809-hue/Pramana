# Data sources

Every data source, its terms, refresh schedule and known limits. Updated at the end of
every milestone.

**Status after M0: no source is connected yet.** Before each adapter is written, its
current endpoint, terms of use and free-tier limits will be checked. Anything paid,
blocked or forbidden will be flagged to the owner, with a free alternative proposed,
before any work continues.

| Source | Provides | Trust tier | Planned refresh | Milestone | Terms verified? | Status |
|---|---|---|---|---|---|---|
| NSE / BSE equity lists | Symbol ↔ BSE code ↔ ISIN master | 1 | Daily | M1 | Not yet | Not built |
| Angel One SmartAPI | Live prices, historical candles (needs account + key + TOTP) | 1 | Live, 09:15–15:30 IST | M1 | Not yet | Not built |
| yfinance (`.NS` / `.BO`) | Delayed and end-of-day prices (unofficial library) | 2 | 15 min + daily close | M1 | Not yet | Not built |
| BSE / NSE corporate announcements | Results, board meetings, presentations, transcripts, orders, ratings | 1 | 15 min in market hours, hourly otherwise | M2 | Not yet | Not built |
| Shareholding patterns | Promoter / FII / DII / public holdings, pledges | 1 | Quarterly, checked daily | M2 | Not yet | Not built |
| Insider trading (SEBI PIT) and SAST | Insider buying and selling | 1 | Daily | M2 | Not yet | Not built |
| Bulk and block deals | Large institutional trades | 1 | Daily after close | M2 | Not yet | Not built |
| FII / DII daily activity | Net institutional flows | 1 | Daily after close | M2 | Not yet | Not built |
| XBRL financial results | Structured quarterly P&L and balance sheet | 1 | Quarterly | M2 | Not yet | Not built |
| AMFI mutual fund portfolios | Which funds hold which stocks | 1 | Monthly | M2 | Not yet | Not built |
| Company monthly business updates | Auto sales, cement volumes, bank deposit and loan growth | 1 | Monthly | M2 | Not yet | Not built |
| Credit rating releases (CRISIL, ICRA, CARE) | Rating actions and rationale | 1 | Daily | M2 | Not yet | Not built |
| Macro: RBI DBIE, MOSPI, PIB | Repo rate, CPI, IIP, GDP, GST | 1 | Monthly | M6 | Not yet | Not built |
| News RSS (ET Markets, Business Standard, Livemint, Google News) | Headline, link, date and snippet only | 3 | Every 30 min | M6 | Not yet | Not built |

The brief places filings-type sources in M2 and macro and news in M6. The final
milestone for each source will be confirmed when its milestone is planned.

## Rules every adapter will follow (brief Section 4)

- Save the raw document (URL, publish time, fetch time, content hash) **before** any processing.
- Each source gets its own adapter module with a health check shown on the Data Health page.
- Scrape politely: send a clear user agent, cache responses, make at most a few requests per
  second, and back off on errors.
- Never scrape sites whose terms forbid it (for example Screener.in, Naukri, LinkedIn).
- For news, store only the headline, link, date and snippet. Never store full articles.

## Known gaps

- **Analyst consensus estimates:** there is no reliable free source. v1 uses a manual
  "Street view" field plus a management-guidance tracker.
