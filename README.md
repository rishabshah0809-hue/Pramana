# Pramana

*Called Mosaic India until 26 Sep 2026. Internal names (the `mosaic.db` database, `MOSAIC_*`
settings, the web user agent) are unchanged so existing data keeps working.*

A personal research app for Indian listed companies (NSE/BSE). It gathers free,
official public data, uses AI only to read and summarise that data, and links every
fact back to exactly where it came from.

> **Personal research tool. Not investment advice.**

**Current stage: Milestone 2 (Filings).** You can import NSE's and BSE's company lists,
build a watchlist, see delayed prices, and read your companies' filings (results, board
meetings, presentations, transcripts, orders, ratings, shareholding, insider and SAST
disclosures, bulk and block deals) exactly as the exchanges published them. No AI yet.

---

## One-time setup (about 15 minutes)

You only do this once. You don't need to write any code.

### Step 1 — Install Python

**Windows**
1. Go to https://www.python.org/downloads/ and click the big yellow **Download Python** button.
2. Open the downloaded file.
3. **Important:** on the first screen, tick the box **"Add python.exe to PATH"** at the bottom.
4. Click **Install Now** and wait for it to finish.

**Mac**
1. Go to https://www.python.org/downloads/ and click the big yellow **Download Python** button.
2. Open the downloaded file and click **Continue** / **Install** until it finishes.
3. A Finder window opens showing a "Python 3.x" folder. Double-click
   **Install Certificates.command** inside it (this lets the app download data securely later).

You need Python **3.11 or newer**. The app checks this for you and tells you if it's too old.

### Step 2 — Get the project onto your computer

The easiest way is **GitHub Desktop** (free), because it also makes updating easy later.

1. Download GitHub Desktop from https://desktop.github.com and sign in with your GitHub account.
2. Click **File → Clone repository**, choose **rishabshah0809-hue/Pramana**, and click **Clone**.
3. At the top of GitHub Desktop, click **Current branch** and choose:
   - **experiment** to try the newest work, or
   - **main** for the version you've approved.

### Step 3 — Open a terminal in the project folder

In GitHub Desktop, click **Repository → Show in Explorer** (Windows) or **Show in Finder** (Mac). Then:

- **Windows:** click the address bar at the top of the Explorer window, type `cmd`, and press **Enter**.
  A black window opens, already in the right folder.
- **Mac:** open the **Terminal** app, type `cd ` (with a space after it), drag the project folder
  from Finder into the Terminal window, and press **Enter**.

### Step 4 — Start the app

Type this and press **Enter**:

| Windows | Mac |
|---|---|
| `python start.py` | `python3 start.py` |

The **first time**, it spends a few minutes installing what it needs. Then your web browser
opens the Pramana dashboard at **http://localhost:8501**.

Keep the terminal window open while you use the app. To stop the app, click the terminal window
and press **Ctrl + C** (or just close the window).

### Your keys file (.env)

The first time you start the app, it creates a private file called `.env` in the project folder.
Later, you'll paste your free API keys into it (Angel One, Groq, Gemini, Telegram). **No keys
are needed yet.** You'll be told exactly when each one is needed and how to get it.

`.env` stays on your computer only. It is never uploaded to GitHub.

---

## First use: company list and watchlist

### 1. Import NSE's company list (about once a month)

NSE doesn't allow apps to download from its website automatically, so you download this one
file yourself:

1. In the app, open **Company list** in the left menu. It links to the NSE page.
2. On NSE's page, under *Equity segment*, click **Securities available for Equity segment
   (.csv)**. A file called **EQUITY_L.csv** downloads.
3. Back in the app, drag that file into the upload box and click **Import this file**.
   Don't open or edit the file first.

The Data Health page shows the list as **stale** after 35 days, as a reminder to download
a fresh copy.

### 2. Build your watchlist

Open **Watchlist**, type a name or NSE symbol (e.g. `TCS`), and click **Add**. You can
track up to 50 companies. Every add and remove is recorded in the audit log.

### 3. Prices

- Prices come from Yahoo Finance and are **delayed by about 15 minutes**. Each card is
  labelled **"Delayed · Yahoo"**.
- While the app is running, prices refresh **every 15 minutes during market hours**
  (09:15–15:30 IST, Monday to Friday) and once more at **15:45** for closing prices.
- You can also click **Refresh prices now** on the Command Center.
- Each card shows:
  - the price and change vs the previous close,
  - **the time of the price**,
  - **when the app fetched it**,
  - a **Current** or **Stale** badge.
- If a price isn't known, the card says **"Unknown"** and why. It never shows a blank or zero.

**Optional: market holidays.** Open `config.yaml`, find `market_holidays: []`, and list
NSE's holidays from its yearly holiday circular, like this:

```yaml
market_holidays:
  - 2026-10-02
```

Without this list, prices may show "stale" on a market holiday until the next trading day.

> **Note on Yahoo:** Yahoo's terms don't allow automated access. You chose to use it until
> your Angel One API is ready; see `DATA_SOURCES.md`. Live Angel One prices will replace it
> as the main source.

### 4. BSE's company list (about once a month)

BSE's announcements carry only a BSE code, so the app needs BSE's list to know which
company each one is about. On **Company list**, scroll to **BSE list of scrips** and follow the
steps there: on BSE's page choose **Segment: Equity** and **Status: Active**, press **Submit**,
click the download icon, and upload the file unedited.

### 5. Filings

- The app reads the official **RSS feeds** that NSE and BSE publish for feed readers:
  - **NSE:** every 5 minutes on weekdays from 08:00 to 22:00, and every 30 minutes otherwise.
  - **BSE:** every 15 minutes in market hours, and hourly otherwise.
- For **watchlist companies**, the filing's own file (PDF, XML or ZIP) is downloaded and stored
  unchanged in `data/raw/`.
- Bulk and block deals come from NSE's two daily files, fetched at **18:30** on weekdays.
- Open a company from the **Command Center** or **Watchlist** to see its **Filings**,
  **Shareholding** and **Large deals** tabs.
- **Open the original filing** shows it in the **Document Viewer**, with:
  - its source, published time, fetch time, version and hash,
  - a **Download original** button,
  - a **Re-fetch from source** button. If the file has changed, the new copy is saved as a new
    version beside the old one. Nothing is ever overwritten.
- **Older filings:** the feeds only list recent items, so the app starts collecting from the
  day it first runs. For anything older, download the file from NSE or BSE in your browser and
  add it under **Document Viewer → Add a filing**.
- **Past shareholding quarters:** upload the shareholding pattern's **XBRL (.xml)** file with
  type "Shareholding pattern", and the trend chart will include it.
- **Data Health** shows each feed's last success and error count. Its **Check now** button
  runs a feed immediately.

> **Note on bulk/block deals:** these come from NSE's daily report files, which NSE's terms
> don't allow apps to download automatically. You chose to use them anyway (26 Sep 2026); see
> `DATA_SOURCES.md`.

---

## Daily use

1. Open a terminal in the project folder (Step 3).
2. Run `python start.py` (Windows) or `python3 start.py` (Mac).
3. Use the dashboard in your browser. Press **Ctrl + C** in the terminal when you're done.

**To get new updates:** in GitHub Desktop, click **Fetch origin**, then **Pull origin**. Your
`.env` keys and your `data` folder are not touched by updates.

---

## Other ways to run it (optional)

`start.py` is the easiest way. The dashboard is a standard Streamlit app, so these work too:

**Directly with Streamlit** (after `start.py` has run once, so the packages are installed):

| Windows | Mac |
|---|---|
| `.venv\Scripts\streamlit run streamlit_app.py` | `.venv/bin/streamlit run streamlit_app.py` |

**On Streamlit Community Cloud** (free, runs in the browser without your computer):

1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **Create app**, then choose to deploy from GitHub.
3. Repository: **rishabshah0809-hue/Pramana**. Branch: **main** or **experiment**. Main file path: **streamlit_app.py**.
4. Open **Advanced settings** and pick Python **3.11** or newer.
5. Click **Deploy**.
6. **Keys:** don't upload `.env`. In the app's **Settings → Secrets**, paste the lines from
   `.streamlit/secrets.toml.example` with your keys filled in. None are needed yet.

> **Read before using the cloud version for real research.** The brief plans v1 as an app on
> your own computer. On Streamlit Cloud:
> - The database is **wiped whenever the app restarts or updates**, so history can't be replayed.
> - An app may be **visible to anyone with the link**, which isn't allowed for broker price
>   data (Angel One data is for your personal use only).
>
> It's fine for previewing the design now. Before real data arrives (Milestone 1 onwards),
> keep using `start.py` on your computer unless we agree a plan for these two issues.

---

## If something goes wrong

The app never shows you programmer error messages. It shows **PROBLEM** and **WHAT TO DO**.
Follow the "what to do" line first.

| You see | What to do |
|---|---|
| `'python' is not recognized` (Windows) | Python isn't installed or "Add to PATH" wasn't ticked. Re-run the Python installer, choose **Modify**, and tick **Add Python to environment variables**. Then close and reopen the terminal. |
| `command not found: python3` (Mac) | Install Python (Step 1), then close and reopen Terminal. |
| "needs Python 3.11 or newer" | Install the latest Python (Step 1), then close and reopen the terminal. |
| "Could not install the packages" | Check your internet connection and run the start command again. |
| "settings file has a typing mistake" | Undo your last edit to `config.yaml`. In GitHub Desktop you can right-click the file and choose **Discard changes**. |
| "database is busy" | Another copy of the app is running. Close other terminal windows running it and try again. |
| The browser didn't open | Copy **http://localhost:8501** into your browser yourself. |
| "This doesn't look like NSE's equity list" | Upload the file exactly as downloaded: **EQUITY_L.csv**, not opened or saved in Excel. |
| "Yahoo returned no prices" / "Could not reach Yahoo" | Check your internet. The app retries automatically; the Data Health page shows when it last worked. |
| "Yahoo is limiting requests" | Nothing to do: wait 15 minutes and it retries on its own. |
| A price shows **Stale** on a market holiday | Add the holiday to `market_holidays` in `config.yaml` (see above). |
| "The NSE … feed has changed its format" | Nothing to do right away: earlier filings are kept. If it lasts more than a day, tell Claude. |
| "NSE refused the request" / "BSE asked the app to slow down" | Nothing to do: the app waits and tries again at the next check. |
| A filing says "Not downloaded yet" | It downloads at the next check. If it keeps failing, open the link on the exchange website and add it under **Document Viewer → Add a filing**. |
| "This doesn't look like BSE's List of Scrips" | Download it again from BSE (Segment: Equity, Status: Active) and upload it unedited. If it still fails, send Claude the first line of the file. |
| Fetch status says **stale** for the feeds | The background checker isn't running. Close the app and start it again with `start.py`. |

**Still stuck?** Send Claude:
1. The exact PROBLEM / WHAT TO DO text from the screen, and
2. The last 20 lines of `logs/mosaic.log`, plus `logs/scheduler.log` if the problem is about prices.

---

## Project documents

- [PRODUCT_BRIEF.md](PRODUCT_BRIEF.md): what the app is and the rules it follows.
- [ARCHITECTURE.md](ARCHITECTURE.md): how the parts fit together.
- [DATA_SOURCES.md](DATA_SOURCES.md): every data source, its terms and limits.
- [CLAUDE.md](CLAUDE.md): the working rules for Claude Code.

## Running the tests (optional)

After `start.py` has run once, you can run the automated checks:

| Windows | Mac |
|---|---|
| `.venv\Scripts\python -m pytest` | `.venv/bin/python -m pytest` |

All tests should say **passed**.
