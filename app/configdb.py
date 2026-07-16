"""静态配置 MySQL 库访问：只读护栏 + 查询执行。

游戏静态配置库（道具表、活动表等）与 Presto 数仓是两个独立数据库。
本模块提供：
- sanitize(): 只允许 SELECT / SHOW / DESCRIBE / EXPLAIN 的只读护栏
- query():    用 pymysql 直连配置库执行，连接即用即关（不做连接池）
"""
import re

import pymysql
import pymysql.cursors

import sqlguard


class ConfigGuardError(ValueError):
    """Raised when config SQL fails the safety guard."""


_BANNED_KEYWORDS = re.compile(
    r'\b(insert|update|delete|drop|alter|create|truncate|merge|grant|revoke'
    r'|replace|exec|call|use|set|load|handler|lock|unlock|kill|shutdown)\b',
    re.IGNORECASE,
)
_BANNED_PHRASES = re.compile(
    r'(--|/\*|\*/|#\s|into\s+outfile|into\s+dumpfile|load_file|sleep\s*\(|benchmark\s*\()',
    re.IGNORECASE,
)
_ALLOWED_START = re.compile(r'^\s*(select|show|describe|desc|explain)\b', re.IGNORECASE)
_LIMIT_EXEMPT = re.compile(r'^\s*(show|describe|desc|explain)\b', re.IGNORECASE)


def sanitize(sql: str, max_rows: int = 500) -> str:
    """
    Validate config SQL. Returns cleaned SQL on success
    (auto-LIMIT appended for SELECT lacking one; SHOW/DESCRIBE/EXPLAIN exempt).
    Raises ConfigGuardError on any violation.
    """
    sql = sql.strip()
    if sql.endswith(';'):
        sql = sql[:-1].rstrip()

    masked = sqlguard._mask_literals(sql)

    # No multiple statements
    if ';' in masked:
        raise ConfigGuardError("不支持多条 SQL 语句")

    # Banned keywords (checked on masked SQL so string literals don't false-positive)
    m = _BANNED_KEYWORDS.search(masked)
    if m:
        raise ConfigGuardError(f"包含禁止操作: {m.group()}")

    # Must start with SELECT / SHOW / DESCRIBE / EXPLAIN
    if not _ALLOWED_START.match(masked):
        raise ConfigGuardError("只支持 SELECT / SHOW / DESCRIBE / EXPLAIN 查询")

    # Banned phrases
    m = _BANNED_PHRASES.search(masked)
    if m:
        raise ConfigGuardError(f"包含禁止内容: {m.group()}")

    # Auto-add LIMIT for SELECT without one
    if not _LIMIT_EXEMPT.match(masked):
        top = sqlguard._strip_parens(masked)
        if not re.search(r'\blimit\b', top, re.IGNORECASE):
            sql = f"{sql} LIMIT {max_rows}"

    return sql


def query(cfg: dict, sql: str, max_rows: int = 500) -> list:
    """
    Execute read-only SQL against the game's config MySQL DB.

    cfg: the game's config_db dict (host/port/user/password/database/charset/
    connect_timeout/read_timeout). Connection is opened per call and always
    closed. Result rows are clamped to max_rows.
    Returns list[dict].
    """
    conn = pymysql.connect(
        host=cfg["host"],
        port=int(cfg.get("port", 3306)),
        user=cfg["user"],
        password=cfg.get("password", ""),
        database=cfg["database"],
        charset=cfg.get("charset", "utf8mb4"),
        connect_timeout=int(cfg.get("connect_timeout", 5)),
        read_timeout=int(cfg.get("read_timeout", 30)),
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    finally:
        conn.close()
    return list(rows[:max_rows])
