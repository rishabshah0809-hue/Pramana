# Data sources

Every data source, its terms, refresh schedule and known limits. Updated at the end of
every milestone.

**Status after M0: no source is connected yet.** Before each adapter is written, its
current endpoint, terms of use and free-tier limits will be checked. Anything paid,
blocked or forbidden will be flagged to the owner, with a free alternative proposed,
before any work continues.

| Source | Provides | Trust tier | Planned refresh | Milestone | Terms verified? | Status |
|---|---|---|---|---|---|---|
| NSE / BSE equity lists | Symbol ↔ BSE code ↔ ISIN master | 1 | Daily | M1 | **Checked 25 Sep 2026: restricted, see below** | Waiting for owner decision |
| Angel One SmartAPI | Live prices, historical candles (needs account + key + TOTP) | 1 | Live, 09:15–15:30 IST | M1 | **Checked 25 Sep 2026: free, official, see below** | Not built |
| yfinance (`.NS` / `.BO`) | Delayed and end-of-day prices (unofficial library) | 2 | 15 min + daily close | M1 | **Checked 25 Sep 2026: restricted, see below** | Waiting for owner decision |
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
