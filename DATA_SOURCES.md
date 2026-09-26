# Data sources

Every data source, its terms, refresh schedule and known limits. Updated at the end of
every milestone.

**Status: Milestone 2 (filings) built on `experiment`.** Before each adapter is written,
its current endpoint, terms of use and free-tier limits are checked. Anything paid, blocked
or forbidden is flagged to the owner, with a free alternative proposed, before any work
continues.

| Source | Provides | Trust tier | Planned refresh | Milestone | Terms verified? | Status |
|---|---|---|---|---|---|---|
| NSE equity list (EQUITY_L.csv) | Symbol ↔ ISIN master | 1 | Monthly, uploaded by the owner | M1 | **Checked 25 Sep 2026: manual download only** | Built: Company list page. App never contacts NSE |
| Angel One SmartAPI | Live prices, historical candles (needs account + key + TOTP) | 1 | Live, 09:15–15:30 IST | M1 | **Checked 25 Sep 2026: free, official, see below** | Waiting for owner's API keys |
| yfinance (`.NS`) | Delayed and end-of-day prices (unofficial library) | 2 | 15 min in market hours + 15:45 close | M1 | **Checked 25 Sep 2026: conflicts with Yahoo terms; owner accepted the risk** | Built. Labelled "Delayed · Yahoo" |
| BSE list of scrips (List of Scrips CSV) | BSE code ↔ ISIN, BSE-only companies | 1 | Monthly, uploaded by the owner | M2 | **Checked 26 Sep 2026: manual download only** | Built: Company list page. App never contacts BSE for it |
| BSE / NSE corporate announcements | Results, board meetings, presentations, transcripts, orders, ratings | 1 | NSE feeds: 5 min (weekdays 08:00–22:00), 30 min otherwise. BSE feed: 15 min in market hours, hourly otherwise | M2 | **Checked 26 Sep 2026: official RSS feeds** | Built: `announcements` adapter |
| Shareholding patterns | Promoter / FII / DII / public holdings, pledges | 1 | Same feed checks as NSE announcements | M2 | **Checked 26 Sep 2026: official RSS feeds** | Built: `shareholding` adapter |
| Insider trading (SEBI PIT) and SAST | Insider buying and selling | 1 | Same feed checks as NSE announcements | M2 | **Checked 26 Sep 2026: official RSS feeds** | Built: `insider_sast` adapter |
| Bulk and block deals | Large institutional trades | 1 | Weekdays 18:30 IST | M2 | **Checked 26 Sep 2026: conflicts with NSE terms; owner accepted the risk** | Built: `bulk_block` adapter |
| FII / DII daily activity | Net institutional flows | 1 | Daily after close | M2 | Not yet | Not built |
| XBRL financial results | Structured quarterly P&L and balance sheet | 1 | Quarterly | M2 | Not yet | Not built |
| AMFI mutual fund portfolios | Which funds hold which stocks | 1 | Monthly | M2 | Not yet | Not built |
| Company monthly business updates | Auto sales, cement volumes, bank deposit and loan growth | 1 | Monthly | M2 | Not yet | Not built |
| Credit rating releases (CRISIL, ICRA, CARE) | Rating actions and rationale | 1 | Daily | M2 | Not yet | Not built |
| Macro: RBI DBIE, MOSPI, PIB | Repo rate, CPI, IIP, GDP, GST | 1 | Monthly | M6 | Not yet | Not built |
| News RSS (ET Markets, Business Standard, Livemint, Google News) | Headline, link, date and snippet only | 3 | Every 30 min | M6 | Not yet | Not built |

The brief places filings-type sources in M2 and macro and news in M6. The final
milestone for each source will be confirmed when its milestone is planned.

## M1 terms check (25 Sep 2026)

This cloud workspace's network blocks the exchange and broker websites, so these checks
used web search and published documentation. Each should be re-checked on the owner's
machine before its adapter goes live.

- **NSE website (nseindia.com), including the equity list file.** NSE's
  [terms of use](https://www.nseindia.com/static/nse-terms-of-use) prohibit "systematic or
  automated data collection activities, including scraping, data mining, data extraction and
  data harvesting", and limit the site to personal, non-commercial use. **Automated download
  is not allowed**, even for personal use. A person downloading a file in their own browser
  is ordinary personal use. NSE publishes [official RSS feeds](https://www.nseindia.com/static/rss-feed)
  for announcements; whether reading them automatically is allowed will be checked in M2.
- **BSE website (bseindia.com).** The [disclaimer](https://www.bseindia.com/static/about/disclaimer.htm)
  grants "personal use" only, prohibits reproduction and redistribution, and has strict
  "not to download or modify" wording. Treated as **restricted to manual personal use**
  until clarified.
- **yfinance / Yahoo Finance.** yfinance is [not affiliated with Yahoo](https://github.com/ranaroussi/yfinance)
  and says the API is "for personal use only". Yahoo's
  [Terms of Service](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html) prohibit
  robots, scrapers or "other automated means … not provided by us" to access the services
  or extract data. **Automated use conflicts with Yahoo's terms.**
- **Angel One SmartAPI.** An official broker API, [free of charge](https://www.angelone.in/knowledge-center/smartapi/detailed-introduction-to-smartapi)
  for Angel One account holders. Login needs client code + PIN + TOTP. Documented limits
  are LTP about 10 requests/second and historical candles 3/second (180/minute), with about
  9/second combined. The SmartAPI forum has 2026 reports of
  [rate-limit errors well below the documented limits](https://smartapi.angelone.in/smartapi/forum/topic/5639/getcandledata-rate-limit-false-positives-at-0-003-req-sec-six-independent-reports-zero-acknowledgment),
  so the adapter must queue and back off conservatively. Its public
  [instrument master](https://smartapi.angelone.in/smartapi/forum/topic/1300/instrument-master-fields-interpretation)
  (`OpenAPIScripMaster.json`) gives NSE/BSE symbols and tokens but **no ISIN**. Angel One's
  own API terms page could not be opened from this workspace and must be read before go-live.
- **Upstox instrument file** (possible alternative). A public
  [instruments file](https://upstox.com/developer/api-documentation/instruments/) that
  includes ISIN. Its terms have not been checked yet.

## Owner decisions (25 Sep 2026)

- **Company list:** option A. The owner downloads NSE's `EQUITY_L.csv` in their browser
  about once a month and uploads it on the Company list page. BSE-only companies are not
  covered yet.
- **Prices:** yfinance is used for now, by the owner's explicit choice, despite the
  Yahoo terms conflict above. It will be replaced as the main source by Angel One once
  the owner's API keys are ready. Yahoo prices are always labelled "Delayed · Yahoo
  (tier 2)".

## M2 terms check (26 Sep 2026)

This check was done from the owner's own computer, which can reach the exchange websites.

- **NSE terms (re-read).** The ban on "systematic or automated data collection activities
  (including scraping, data mining, data extraction and data harvesting)" is still there.
- **NSE RSS feeds.** NSE's [RSS page](https://www.nseindia.com/static/rss-feed) publishes 23
  feeds and says RSS readers help "by automatically retrieving updates". The feeds are served
  from `nsearchives.nseindia.com` and ask to be re-read every 5 minutes (`<ttl>5</ttl>`). The
  app treats reading these feeds as the permitted, intended use.
  - Each NSE feed holds only the latest **10–20 items**, and some items have no published time.
  - NSE supports "only if changed" requests (ETag / Last-Modified), so unchanged feeds cost
    almost nothing.
- **BSE RSS feeds.** BSE's RSS section offers Sensex, Notices and Corporate Announcements
  feeds for feed readers. The announcements feed (`www.bseindia.com/data/xml/announcements.xml`)
  holds about 1,700 items, but most are mutual-fund NAV notices, so on busy nights it covers
  only about 2 hours. Every item carries a BSE scrip code.
- **BSE's own API** (`api.bseindia.com`) refused the request (403). It is **not** used.
- **Filing files.** Each feed item links to its own file on `nsearchives.nseindia.com`,
  `archives.nseindia.com` or `www.bseindia.com`. The terms neither allow nor forbid opening
  these links automatically. They are downloaded for watchlist companies only (see decisions).
- **NSE bulk/block deal files** (`nsearchives.nseindia.com/content/equities/bulk.csv` and
  `block.csv`). These are daily reports, not feeds, so downloading them automatically falls
  under NSE's ban.
- **User agent.** Both exchanges accept an honest, identifying user agent
  (`MosaicIndia/0.2 (personal research tool …)`). The app does not pretend to be a browser.
- **BSE List of Scrips.** Downloaded by the owner in the browser. Its column names could not be
  confirmed from here, so the upload accepts the common spellings and names any missing
  column instead of guessing.

## Owner decisions (26 Sep 2026)

1. **Filing files:** downloaded automatically, **for watchlist companies only**. Everything
   else is indexed from the feed (company, subject, time, link) without downloading the file.
2. **Bulk and block deals:** the app downloads NSE's two daily files once each weekday at
   18:30 IST, **by the owner's explicit choice, despite the NSE terms conflict above**.
3. **Feed timing:** NSE feeds every 5 minutes on weekdays 08:00–22:00 and every 30 minutes
   otherwise, matching the feeds' own guidance. This is more often than the brief's
   "15 min / hourly", which would miss filings because the feeds hold so few items. BSE keeps
   the brief's timing.

## Known M2 limits

- **Only new filings.** Feeds list recent items only. Anything older is added by the owner
  under Document Viewer → Add a filing. Items that scroll off a feed between two checks are
  missed; the 5-minute NSE timing keeps this rare.
- **Company matching is exact** (14.4):
  - BSE items are matched by BSE code (this needs BSE's list uploaded).
  - NSE items are matched by exact company name (ignoring only letter case and spacing).
  - Unmatched items are counted on Data Health and never guessed.
- **Shareholding numbers** are read by code (no AI) from the XBRL file's category totals.
  They were checked against a real NSE filing on 26 Sep 2026: promoter 49.13% + public 50.87%
  = 100%.
  - Only whether promoter shares are pledged (yes/no) is read. The pledged percentage is left
    to the original filing until its exact place in the XBRL file is confirmed on a real
    pledged example.
- **Storage:** feed files are stored gzip-compressed. Expect roughly 1 GB a year, mostly BSE's
  large feed.

## Internet hosts the app may contact (brief 14.12)

The app refuses any host that isn't in this list (`app/adapters/registry.py`), and a test
keeps the list and this file in sync.

| Source | Hosts | Last terms check |
|---|---|---|
| NSE equity list | none: uploaded by the owner, never fetched | 2026-09-25 |
| BSE list of scrips | none: uploaded by the owner, never fetched | 2026-09-26 |
| Yahoo (yfinance) | `query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `fc.yahoo.com`, `guce.yahoo.com`, `consent.yahoo.com` | 2026-09-25 |
| Company announcements (tier 1) | `nsearchives.nseindia.com`, `archives.nseindia.com`, `www.bseindia.com` (official RSS feeds and the filing files they link to) | 2026-09-26 |
| Shareholding and pledges (tier 1) | `nsearchives.nseindia.com`, `archives.nseindia.com` | 2026-09-26 |
| Insider trading and SAST (tier 1) | `nsearchives.nseindia.com`, `archives.nseindia.com` | 2026-09-26 |
| Bulk and block deals (tier 1) | `nsearchives.nseindia.com` (conflicts with NSE terms; owner's choice) | 2026-09-26 |

Never contacted: `www.nseindia.com` (NSE's main website and its API) and `api.bseindia.com`.

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
