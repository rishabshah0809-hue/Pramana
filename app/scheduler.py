"""Background scheduler: refreshes delayed prices during NSE market hours.

Started by start.py as a separate process (logs in logs/scheduler.log). Not used on
Streamlit Cloud, where the 'Refresh prices now' button is the way to update.

    python -m app.scheduler
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

from app.config import load_config  # noqa: E402
from app.errors import report, setup_logging  # noqa: E402
from app.keys import load_env_file  # noqa: E402
from app.services import prices  # noqa: E402
from app.store.db import init_db  # noqa: E402
from app.timeutil import IST, market_is_open, now_utc, parse_holidays  # noqa: E402

log = logging.getLogger("mosaic.scheduler")


def price_job(force: bool = False) -> None:
    try:
        cfg = load_config()
        holidays = parse_holidays(cfg.get("market_holidays"))
        if not force and not market_is_open(now_utc(), cfg["market_hours"]["open"],
                                            cfg["market_hours"]["close"], holidays):
            return
        summary = prices.refresh()
        log.info("Price refresh: %s — %s", summary.status, summary.message)
    except Exception as exc:  # keep the scheduler alive; details go to the log
        report(exc, log)


def build(scheduler) -> None:
    cfg = load_config()
    every = int(cfg["schedules"]["prices_delayed"]["every_minutes"])
    close_h, close_m = cfg["schedules"]["prices_delayed"]["after_close"].split(":")
    scheduler.add_job(price_job, CronTrigger(day_of_week="mon-fri", hour="9-15",
                                             minute=f"*/{every}", timezone=IST),
                      id="prices_intraday", max_instances=1, coalesce=True)
    scheduler.add_job(price_job, CronTrigger(day_of_week="mon-fri", hour=int(close_h),
                                             minute=int(close_m), timezone=IST),
                      kwargs={"force": True}, id="prices_close", max_instances=1, coalesce=True)


def main() -> int:
    setup_logging()
    load_env_file()
    init_db()
    scheduler = BlockingScheduler(timezone=IST)
    build(scheduler)
    log.info("Scheduler started")
    price_job()  # catch up immediately if the market is open
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
