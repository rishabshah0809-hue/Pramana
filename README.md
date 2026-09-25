# Mosaic India

A personal research app for Indian listed companies (NSE/BSE). It gathers free,
official public data, uses AI only to read and summarise that data, and links every
fact back to exactly where it came from.

> **Personal research tool. Not investment advice.**

**Current stage: Milestone 0 (Foundation).** The app opens an empty dashboard. Companies
and prices arrive in Milestone 1.

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
opens the Mosaic India dashboard at **http://localhost:8501**.

Keep the terminal window open while you use the app. To stop the app, click the terminal window
and press **Ctrl + C** (or just close the window).

### Your keys file (.env)

The first time you start the app, it creates a private file called `.env` in the project folder.
Later, you'll paste your free API keys into it (Angel One, Groq, Gemini, Telegram). **No keys
are needed yet.** You'll be told exactly when each one is needed and how to get it.

`.env` stays on your computer only. It is never uploaded to GitHub.

---

## Daily use

1. Open a terminal in the project folder (Step 3).
2. Run `python start.py` (Windows) or `python3 start.py` (Mac).
3. Use the dashboard in your browser. Press **Ctrl + C** in the terminal when you're done.

**To get new updates:** in GitHub Desktop, click **Fetch origin**, then **Pull origin**. Your
`.env` keys and your `data` folder are not touched by updates.

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

**Still stuck?** Send Claude:
1. The exact PROBLEM / WHAT TO DO text from the screen, and
2. The last 20 lines of the newest file in the project's `logs` folder.

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
