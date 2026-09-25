"""Mosaic India — the one command to start everything.

    Windows:  python start.py
    Mac:      python3 start.py

What it does, in order:
  1. Checks your Python version.
  2. Creates a private package folder (.venv) and installs what the app needs.
  3. Creates your private keys file (.env) if it doesn't exist yet.
  4. Checks the settings file (config.yaml) and sets up the database.
  5. Opens the dashboard in your web browser.

If anything goes wrong you get a plain-English message and what to do next.
"""

import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
STAMP_FILE = VENV_DIR / "mosaic-requirements.sha256"
MIN_PYTHON = (3, 11)


class StartupProblem(Exception):
    def __init__(self, message, fix):
        super().__init__(message)
        self.message = message
        self.fix = fix


def say(text=""):
    print(text, flush=True)


def show_problem(message, fix):
    say()
    say("  PROBLEM:    " + message)
    say("  WHAT TO DO: " + fix)
    say()


# ---------------------------------------------------------------------------
# Stage 1: runs with your normal Python (standard library only)
# ---------------------------------------------------------------------------

def check_python_version(version=None):
    version = version or sys.version_info[:2]
    if tuple(version) < MIN_PYTHON:
        raise StartupProblem(
            "Mosaic India needs Python %d.%d or newer, but this computer is using Python %d.%d."
            % (MIN_PYTHON + tuple(version)),
            "Install the latest Python from https://www.python.org/downloads/ "
            "(see README.md, step 1), close this window, and run start.py again.",
        )


def venv_python():
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def running_inside_venv():
    try:
        return Path(sys.prefix).resolve() == VENV_DIR.resolve()
    except OSError:
        return False


def requirements_hash():
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def ensure_venv():
    if not venv_python().exists():
        say("First-time setup: creating a private package folder (.venv)...")
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(VENV_DIR)], capture_output=True, text=True
        )
        if result.returncode != 0 or not venv_python().exists():
            shutil.rmtree(VENV_DIR, ignore_errors=True)
            raise StartupProblem(
                "Could not create the private package folder (.venv).",
                "Reinstall Python from https://www.python.org/downloads/ (on Windows, tick "
                "'Add python.exe to PATH'), then run start.py again.",
            )

    if STAMP_FILE.exists() and STAMP_FILE.read_text().strip() == requirements_hash():
        return
    say("Installing the packages Mosaic India needs. The first time this takes a few minutes...")
    result = subprocess.run(
        [str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check",
         "-q", "-r", str(REQUIREMENTS)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        (log_dir / "install.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        raise StartupProblem(
            "Could not install the packages Mosaic India needs.",
            "Check that you are connected to the internet and run start.py again. If it "
            "still fails, send Claude the file logs/install.log.",
        )
    STAMP_FILE.write_text(requirements_hash())
    say("Packages installed.")


def relaunch_inside_venv():
    """Run this same script again using the private .venv Python."""
    try:
        return subprocess.call([str(venv_python()), str(Path(__file__).resolve())])
    except KeyboardInterrupt:
        return 0


# ---------------------------------------------------------------------------
# Stage 2: runs inside .venv (app packages available)
# ---------------------------------------------------------------------------

def ensure_env_file():
    """Create .env from .env.example the first time, so the owner never has to."""
    env = PROJECT_ROOT / ".env"
    if env.exists():
        return False
    example = PROJECT_ROOT / ".env.example"
    if not example.exists():
        raise StartupProblem(
            "The file .env.example is missing from the project folder.",
            "Download the project again from GitHub.",
        )
    shutil.copyfile(example, env)
    say("Created your private keys file (.env). No keys are needed yet.")
    return True


def port_is_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_port(preferred):
    for port in range(preferred, preferred + 20):
        if port_is_free(port):
            return port
    raise StartupProblem(
        "Could not find a free port to open the dashboard on.",
        "Close other copies of Mosaic India (or restart your computer), then run start.py again.",
    )


def wait_until_up(proc, port, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def run_app():
    sys.path.insert(0, str(PROJECT_ROOT))
    from app import paths
    from app.config import load_config
    from app.errors import FriendlyError, report, setup_logging
    from app.store.db import init_db

    try:
        logger = setup_logging()
        logger.info("Starting Mosaic India")
        ensure_env_file()
        config = load_config()
        logger.setLevel(config.get("app", {}).get("log_level", "INFO"))
        init_db()
        say("Database ready.")
        port = pick_port(int(config.get("app", {}).get("dashboard_port", 8501)))
    except StartupProblem:
        raise
    except FriendlyError as exc:
        raise StartupProblem(exc.message, exc.fix)
    except Exception as exc:
        err = report(exc)
        raise StartupProblem(err.message, err.fix)

    paths.log_dir().mkdir(parents=True, exist_ok=True)
    ui_log = open(paths.log_dir() / "dashboard.log", "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(PROJECT_ROOT / "app" / "ui" / "Home.py"),
         "--server.port", str(port), "--server.address", "localhost",
         "--server.headless", "true"],
        cwd=str(PROJECT_ROOT), stdout=ui_log, stderr=subprocess.STDOUT,
    )
    try:
        if not wait_until_up(proc, port):
            proc.terminate()
            raise StartupProblem(
                "The dashboard did not start.",
                "Run start.py again. If it still fails, send Claude the last lines of "
                "logs/dashboard.log.",
            )
        url = "http://localhost:%d" % port
        say()
        say("Mosaic India is running at " + url)
        say("Your browser should open by itself. If not, copy that address into your browser.")
        say("Keep this window open while you use the app. Press Ctrl+C here to stop it.")
        webbrowser.open(url)
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        say()
        say("Mosaic India stopped.")
    finally:
        ui_log.close()
    return 0


def main():
    try:
        check_python_version()
        if not running_inside_venv():
            ensure_venv()
            return relaunch_inside_venv()
        return run_app()
    except StartupProblem as exc:
        show_problem(exc.message, exc.fix)
        return 1
    except KeyboardInterrupt:
        say("\nStopped.")
        return 0
    except Exception as exc:  # last resort: never show a traceback
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        import traceback
        with open(log_dir / "startup-error.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)) + "\n")
        show_problem(
            "Something unexpected went wrong while starting.",
            "Run start.py again. If it still fails, send Claude the file "
            "logs/startup-error.log.",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
