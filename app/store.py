import sqlite3
import time
from pathlib import Path
import config

_ROOT = Path(config._ROOT)
_DB_PATH = _ROOT / "data" / "bot.db"


def _get_conn():
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            user_id TEXT,
            direction TEXT,
            msg_type TEXT,
            text TEXT,
            status TEXT,
            latency_ms INTEGER,
            error TEXT,
            session_id TEXT,
            message_id TEXT,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS conversations (
            chat_id TEXT PRIMARY KEY,
            claude_session_id TEXT,
            updated_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            message_id TEXT,
            sql TEXT,
            row_count INTEGER,
            status TEXT,
            latency_ms INTEGER,
            error TEXT,
            created_at INTEGER
        );
    """)
    conn.commit()
    conn.close()


def log_in(chat_id, user_id, message_id, text):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO messages (chat_id,user_id,direction,msg_type,text,status,message_id,created_at)"
        " VALUES (?,?,'in','text',?,'received',?,?)",
        (chat_id, user_id, text, message_id, int(time.time()))
    )
    conn.commit()
    conn.close()


def log_out(chat_id, message_id, status, latency_ms, error=None, session_id=None):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO messages (chat_id,direction,msg_type,status,latency_ms,error,session_id,message_id,created_at)"
        " VALUES (?,'out','text',?,?,?,?,?,?)",
        (chat_id, status, latency_ms, error, session_id, message_id, int(time.time()))
    )
    conn.commit()
    conn.close()


def get_session(chat_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT claude_session_id FROM conversations WHERE chat_id=?", (chat_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def set_session(chat_id, session_id):
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO conversations (chat_id,claude_session_id,updated_at) VALUES (?,?,?)",
        (chat_id, session_id, int(time.time()))
    )
    conn.commit()
    conn.close()


def log_query(chat_id, message_id, sql, row_count, status, latency_ms, error=None):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO query_log (chat_id,message_id,sql,row_count,status,latency_ms,error,created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (chat_id, message_id, sql, row_count, status, latency_ms, error, int(time.time()))
    )
    conn.commit()
    conn.close()
