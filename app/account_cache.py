import sqlite3
import threading
import time
from pathlib import Path
import config
import dataapi

_ROOT = Path(config._ROOT)
_DB_PATH = _ROOT / "data" / "account_dim.db"
_TTL = 60
_last_refresh = 0
_refreshing = False
_lock = threading.Lock()


def _get_conn():
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS account_dim (
                account TEXT PRIMARY KEY,
                reg_date TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def refresh():
    """Incrementally fetch new accounts from data warehouse. Thread-safe, TTL-gated."""
    global _last_refresh, _refreshing
    now = time.time()
    with _lock:
        if now - _last_refresh < _TTL:
            return
        if _refreshing:
            return
        _refreshing = True
    try:
        conn = _get_conn()
        try:
            row = conn.execute("SELECT MAX(reg_date) FROM account_dim").fetchone()
            max_date = (row[0] if row and row[0] else config.DS_START)
        finally:
            conn.close()

        sql = (
            f"SELECT account, MIN(ds) as reg_date"
            f" FROM {config.REPORT_LOGIN_TABLE}"
            f" WHERE game_id = {config.GAME_ID}"
            f" AND ds >= '{max_date}'"
            f" GROUP BY account"
        )
        rows = dataapi.run_sql_rows(sql, max_rows=500000)
        if rows:
            conn = _get_conn()
            try:
                conn.executemany(
                    "INSERT OR IGNORE INTO account_dim (account, reg_date) VALUES (?,?)",
                    [(r.get("account", ""), r.get("reg_date", "")) for r in rows]
                )
                conn.commit()
            finally:
                conn.close()
        _last_refresh = time.time()
    except Exception as e:
        print(f"[account_cache] refresh failed (using cached data): {e}")
    finally:
        _refreshing = False


def reg_date_map(accounts):
    """Return {account: reg_date} for the given list of accounts."""
    if not accounts:
        return {}
    conn = _get_conn()
    try:
        placeholders = ",".join("?" * len(accounts))
        rows = conn.execute(
            f"SELECT account, reg_date FROM account_dim WHERE account IN ({placeholders})",
            list(accounts)
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        conn.close()


def cohort_sizes():
    """Return {reg_date: account_count} for all registration dates."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT reg_date, COUNT(*) FROM account_dim GROUP BY reg_date"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        conn.close()


def new_accounts_on(ds):
    """Return count of accounts first seen on ds."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM account_dim WHERE reg_date=?", (ds,)
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def stats():
    """Return summary stats: total accounts, min/max reg_date."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*), MIN(reg_date), MAX(reg_date) FROM account_dim"
        ).fetchone()
        return {"total": row[0], "min_date": row[1], "max_date": row[2]}
    finally:
        conn.close()
