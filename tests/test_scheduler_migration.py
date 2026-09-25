import sqlite3

from app import scheduler
from app.store import db


def test_old_m0_database_is_upgraded(temp_dirs):
    path = temp_dirs / "data" / "mosaic.db"
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE prices (id INTEGER PRIMARY KEY, company TEXT NOT NULL, "
                 "timestamp TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL, "
                 "volume REAL, source TEXT NOT NULL, fetched_at TEXT NOT NULL, "
                 "created_at TEXT NOT NULL DEFAULT 'x')")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    db.init_db()
    conn = db.connect()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(prices)")}
    assert {"interval", "is_delayed", "currency"} <= cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    conn.close()


def test_scheduler_jobs(db_ready):
    class Recorder:
        def __init__(self):
            self.ids = []

        def add_job(self, func, trigger, id, **kw):
            self.ids.append(id)

    r = Recorder()
    scheduler.build(r)
    assert r.ids == ["prices_intraday", "prices_close"]


def test_price_job_never_crashes(db_ready, monkeypatch):
    def boom():
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(scheduler.prices, "refresh", boom)
    scheduler.price_job(force=True)  # logs the error, does not raise
