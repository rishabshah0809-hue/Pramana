"""Keep the golden-set run going until every passage has been read, on its own.

    python -m tests.golden.run_until_done

Runs `tests.golden.score` (which continues where it stopped), waits 20 minutes, and repeats
until the AI queue is empty, then writes the final report. It runs independently of Claude
Code, so it keeps going between sessions. Output: tests/golden/results/run_until_done.log.
To stop it: end the process whose id is in tests/golden/results/run_until_done.pid.
"""

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RESULTS = HERE / "results"
WAIT_SECONDS = 20 * 60


def left() -> int:
    env = dict(os.environ, MOSAIC_DATA_DIR=str(HERE / ".run" / "data"),
               MOSAIC_LOG_DIR=str(HERE / ".run" / "logs"))
    out = subprocess.run([sys.executable, "-c", "from app.services import signals; "
                          "q = signals.queue_state(); print(q.passages + q.summaries)"],
                         cwd=ROOT, env=env, capture_output=True, text=True)
    try:
        return int(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return -1  # could not tell; keep going


def main() -> int:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "run_until_done.pid").write_text(str(os.getpid()))
    log = open(RESULTS / "run_until_done.log", "a", encoding="utf-8")
    while True:
        log.write(f"=== {datetime.now():%Y-%m-%d %H:%M} pass\n")
        log.flush()
        subprocess.run([sys.executable, "-X", "utf8", "-m", "tests.golden.score"], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT)
        n = left()
        log.write(f"left: {n}\n")
        log.flush()
        if n == 0:
            log.write("GOLDEN RUN COMPLETE\n")
            return 0
        time.sleep(WAIT_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
