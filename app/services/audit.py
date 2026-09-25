"""Audit log writer: every user and system change is recorded (brief Sections 5 and 14.11)."""

import json
import sqlite3


def log(conn: sqlite3.Connection, actor: str, action: str, obj: str,
        before=None, after=None) -> None:
    conn.execute(
        "INSERT INTO audit_log (actor, action, object, before, after) VALUES (?, ?, ?, ?, ?)",
        (actor, action, obj,
         None if before is None else json.dumps(before, default=str),
         None if after is None else json.dumps(after, default=str)),
    )
