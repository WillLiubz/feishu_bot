import calendar
import sqlite3
import threading
import time
from pathlib import Path

import config
import dataapi

_ROOT = Path(config._ROOT)
_TTL = 3600  # 1 hour

# Per-game refresh state keyed by (game_id, year_month, rank_type)
_last_refresh: dict[tuple[int, str, str], float] = {}
_refreshing: dict[tuple[int, str, str], bool] = {}
_lock = threading.Lock()


def _default_game_config(game_config=None):
    if game_config is not None:
        return game_config
    if config.DEFAULT_GAME is None:
        raise ValueError("没有配置任何游戏")
    return config.DEFAULT_GAME


def _db_path(game_config):
    """Per-game SQLite database path."""
    return _ROOT / "data" / f"ranking_dim_{game_config.game_id}.db"


def _get_conn(game_config):
    db = _db_path(game_config)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init(game_config=None):
    gcfg = _default_game_config(game_config)
    db_path = _db_path(gcfg)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _get_conn(gcfg)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ranking_dim (
                year_month TEXT,
                rank_type TEXT,
                role_id TEXT,
                rank_value INTEGER,
                cached_at INTEGER,
                PRIMARY KEY (year_month, rank_type, role_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ranking_lookup
            ON ranking_dim(year_month, rank_type, rank_value)
        """)
        conn.commit()
    finally:
        conn.close()


def _last_day_of_month(year_month: str) -> str:
    y = int(year_month[:4])
    m = int(year_month[4:6])
    _, last_day = calendar.monthrange(y, m)
    return f"{year_month}{last_day:02d}"


def _key(game_config, year_month, rank_type):
    return (game_config.game_id, year_month, rank_type)


def refresh(year_month="202606", rank_type="MonthRank", top_n=200, game_config=None):
    """Fetch top ranking players from data warehouse and cache locally. Thread-safe, TTL-gated."""
    gcfg = _default_game_config(game_config)
    gid = gcfg.game_id
    key = _key(gcfg, year_month, rank_type)
    now = time.time()
    with _lock:
        if now - _last_refresh.get(key, 0) < _TTL:
            return
        if _refreshing.get(key, False):
            return
        _refreshing[key] = True

    try:
        start_ds = f"{year_month}01"
        end_ds = _last_day_of_month(year_month)
        game_id_str = str(gid)

        sql = (
            f"SELECT role_id, MIN(rank_after) AS rank_value"
            f" FROM gameeco_raw.v_presto_log_rolebehavior"
            f" WHERE game_id = '{game_id_str}'"
            f" AND b_type = '{rank_type}'"
            f" AND ds >= '{start_ds}' AND ds <= '{end_ds}'"
            f" AND rank_after > 0"
            f" AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'"
            f" GROUP BY role_id"
            f" ORDER BY rank_value"
            f" LIMIT {top_n}"
        )
        rows = dataapi.run_sql_rows(sql, max_rows=top_n)

        conn = _get_conn(gcfg)
        try:
            conn.execute(
                "DELETE FROM ranking_dim WHERE year_month=? AND rank_type=?",
                (year_month, rank_type)
            )
            cached_at = int(time.time())
            conn.executemany(
                "INSERT INTO ranking_dim (year_month, rank_type, role_id, rank_value, cached_at) VALUES (?,?,?,?,?)",
                [(year_month, rank_type, str(r.get("role_id", "")), int(r.get("rank_value", 0)), cached_at)
                 for r in rows]
            )
            conn.commit()
        finally:
            conn.close()

        _last_refresh[key] = time.time()
    except Exception as e:
        print(f"[role_ranking_cache] refresh failed (using cached data): {e}")
    finally:
        with _lock:
            _refreshing[key] = False


def get_roles(year_month="202606", rank_type="MonthRank", top_n=200, game_config=None) -> list[str]:
    """Return ordered list of role_id strings for the given month and rank type."""
    gcfg = _default_game_config(game_config)
    refresh(year_month=year_month, rank_type=rank_type, top_n=top_n, game_config=gcfg)
    conn = _get_conn(gcfg)
    try:
        rows = conn.execute(
            "SELECT role_id FROM ranking_dim"
            " WHERE year_month=? AND rank_type=?"
            " ORDER BY rank_value"
            " LIMIT ?",
            (year_month, rank_type, top_n)
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def get_rank_map(year_month="202606", rank_type="MonthRank", top_n=200, game_config=None) -> dict[str, int]:
    """Return {role_id: rank_value} for the given month and rank type."""
    gcfg = _default_game_config(game_config)
    refresh(year_month=year_month, rank_type=rank_type, top_n=top_n, game_config=gcfg)
    conn = _get_conn(gcfg)
    try:
        rows = conn.execute(
            "SELECT role_id, rank_value FROM ranking_dim"
            " WHERE year_month=? AND rank_type=?"
            " ORDER BY rank_value"
            " LIMIT ?",
            (year_month, rank_type, top_n)
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        conn.close()


def stats(game_config=None):
    """Return summary stats: total rows, distinct months, latest cache time."""
    gcfg = _default_game_config(game_config)
    conn = _get_conn(gcfg)
    try:
        row = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT year_month), MAX(cached_at) FROM ranking_dim"
        ).fetchone()
        return {"total": row[0], "months": row[1], "latest_cached_at": row[2]}
    finally:
        conn.close()
