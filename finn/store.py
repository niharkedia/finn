"""SQLite persistence: filings, alerts, and a JSON key-value store for caches, settings and ledgers."""
import json
import shutil
import sqlite3
import time
from contextlib import closing

from .config import DB_PATH, ROOT

SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS kv (ns TEXT, key TEXT, value TEXT, ts REAL, PRIMARY KEY (ns, key));
CREATE TABLE IF NOT EXISTS filings (id TEXT PRIMARY KEY, symbol TEXT, ts TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS filings_ts ON filings (ts);
CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, symbol TEXT, ts TEXT, kind TEXT, title TEXT, body TEXT,
                                   severity REAL, sent INTEGER DEFAULT 0);
"""


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def run(sql: str, args=()) -> int:
    """Execute one write statement; returns the number of rows changed."""
    with closing(_connect()) as con, con:
        return con.execute(sql, args).rowcount


def rows(sql: str, args=()) -> list[dict]:
    with closing(_connect()) as con:
        return [dict(r) for r in con.execute(sql, args)]


def get(ns: str, key: str, max_age: float | None = None):
    hit = rows("SELECT value, ts FROM kv WHERE ns = ? AND key = ?", (ns, key))
    if hit and (max_age is None or time.time() - hit[0]["ts"] < max_age):
        return json.loads(hit[0]["value"])


def put(ns: str, key: str, value):
    run("INSERT OR REPLACE INTO kv VALUES (?, ?, ?, ?)", (ns, key, json.dumps(value), time.time()))
    return value


def memo(ns: str, key: str, compute, max_age: float | None = None):
    """Cached `compute()`; on failure, fall back to a stale copy so a flaky source never blanks the app."""
    if (hit := get(ns, key, max_age)) is not None:
        return hit
    try:
        return put(ns, key, compute())
    except Exception:
        if (stale := get(ns, key)) is not None:
            return stale
        raise


DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if not DB_PATH.exists() and (ROOT / "seed" / "finn.db").exists():  # free hosts wipe the disk on sleep: start warm
    shutil.copyfile(ROOT / "seed" / "finn.db", DB_PATH)
with closing(_connect()) as _con:
    _con.executescript(SCHEMA)
