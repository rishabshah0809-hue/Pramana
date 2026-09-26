"""Background scheduler: delayed prices in market hours, exchange feeds every few minutes
(app/services/schedule.py decides which are due), and bulk/block deals after the close.

Started by start.py as a separate process (logs in logs/scheduler.log). Not used on
Streamlit Cloud, where the 'Refresh prices now' and 'Check now' buttons are the way to update.

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
from app.services import prices, schedule  # noqa: E402
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


def feeds_tick(force: bool = False, now=None) -> None:
    """Runs every 5 minutes; checks whichever exchange feeds are due."""
    from app.adapters import announcements, insider_sast, shareholding

    now = now or now_utc()
    try:
        cfg = load_config()
        nse, bse = schedule.nse_due(now, cfg), schedule.bse_due(now, cfg)
    except Exception as exc:  # keep the scheduler alive
        report(exc, log)
        return
    jobs = []
    if force or nse:
        jobs += [("Announcements (NSE)", lambda: announcements.run(exchange="NSE")),
                 ("Shareholding", shareholding.run), ("Insider / SAST", insider_sast.run)]
    if force or bse:
        jobs.append(("Announcements (BSE)", lambda: announcements.run(exchange="BSE")))
    for label, job in jobs:
        try:
            summary = job()
            log.info("%s: %s — %s", label, summary.status, summary.message)
        except Exception as exc:  # adapters never raise, but never let one stop the rest
            report(exc, log)


def deals_job() -> None:
    from app.adapters import bulk_block

    try:
        summary = bulk_block.run()
        log.info("Bulk/block deals: %s — %s", summary.status, summary.message)
    except Exception as exc:
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
    scheduler.add_job(feeds_tick, CronTrigger(minute="*/5", timezone=IST), id="exchange_feeds",
                      max_instances=1, coalesce=True)
    deals_h, deals_m = cfg["schedules"]["bulk_block_deals"]["after_close"].split(":")
    scheduler.add_job(deals_job, CronTrigger(day_of_week="mon-fri", hour=int(deals_h),
                                             minute=int(deals_m), timezone=IST),
                      id="bulk_block_deals", max_instances=1, coalesce=True)


def main() -> int:
    setup_logging()
    load_env_file()
    init_db()
    scheduler = BlockingScheduler(timezone=IST)
    build(scheduler)
    log.info("Scheduler started")
    price_job()  # catch up immediately if the market is open
    feeds_tick(force=True)  # read every feed once on start
    deals_job()  # yesterday's (or today's) deals, if not stored yet
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
