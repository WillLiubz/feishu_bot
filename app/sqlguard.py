import re
import config


class SqlGuardError(ValueError):
    """Raised when SQL fails the safety guard."""

# Set per-user allowed opgame IDs from mcp_server startup args
REQUIRED_OPGAMES = []

_BANNED_KEYWORDS = re.compile(
    r'\b(insert|update|delete|drop|alter|create|truncate|merge|grant|revoke|exec|call)\b',
    re.IGNORECASE
)
_BANNED_PHRASES = re.compile(
    r'(--|/\*|\*/|#\s|into\s+outfile|load_file)',
    re.IGNORECASE
)


def _mask_literals(sql):
    """Replace all string literals with __MASKED__ to avoid false-positive keyword detection."""
    result = []
    i = 0
    while i < len(sql):
        c = sql[i]
        if c in ("'", '"'):
            quote = c
            i += 1
            while i < len(sql):
                if sql[i] == '\\':
                    i += 2
                    continue
                if sql[i] == quote:
                    if i + 1 < len(sql) and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            result.append('__MASKED__')
        else:
            result.append(c)
            i += 1
    return ''.join(result)


def _strip_parens(sql):
    """Return only top-level characters (outside any parentheses)."""
    depth = 0
    result = []
    for c in sql:
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif depth == 0:
            result.append(c)
    return ''.join(result)


def _extract_parens(sql, start):
    """Return the parenthesized substring beginning at start, or empty string if unmatched."""
    if start >= len(sql) or sql[start] != '(':
        return ""
    depth = 0
    for i in range(start, len(sql)):
        if sql[i] == '(':
            depth += 1
        elif sql[i] == ')':
            depth -= 1
            if depth == 0:
                return sql[start:i + 1]
    return ""


def _check_heavy_subquery(masked):
    """Reject unbounded role_id/iuid IN (SELECT ...) subqueries that lack LIMIT."""
    for match in re.finditer(r'\b(role_id|iuid)\s+IN\s*\(', masked, re.IGNORECASE):
        paren_pos = match.end() - 1
        subquery = _extract_parens(masked, paren_pos)
        if subquery and re.search(r'\bselect\b', subquery, re.IGNORECASE):
            if not re.search(r'\blimit\b', subquery, re.IGNORECASE):
                raise SqlGuardError(
                    "检测到未加 LIMIT 的 role_id/iuid IN (SELECT ...) 子查询，"
                    "请改写为带 LIMIT 的 CTE 或前一步预计算的用户列表，避免全表扫描"
                )


def sanitize(sql):
    """
    Validate and sanitize SQL.
    Returns cleaned SQL string on success. Raises ValueError on any violation.
    """
    sql = sql.strip()

    # Remove trailing semicolon
    if sql.endswith(';'):
        sql = sql[:-1].rstrip()

    masked = _mask_literals(sql)

    # No multiple statements
    if ';' in masked:
        raise SqlGuardError("不支持多条 SQL 语句")

    # Banned keywords (checked on masked SQL) — checked before SELECT/WITH so error message is consistent
    m = _BANNED_KEYWORDS.search(masked)
    if m:
        raise SqlGuardError(f"包含禁止操作: {m.group()}")

    # Must start with SELECT or WITH
    if not re.match(r'^\s*(select|with)\b', masked, re.IGNORECASE):
        raise SqlGuardError("只支持 SELECT / WITH 查询")

    # Banned phrases
    m = _BANNED_PHRASES.search(masked)
    if m:
        raise SqlGuardError(f"包含禁止内容: {m.group()}")

    # game_id / gameid must be present (check on original SQL)
    game_id = str(config.GAME_ID)
    if not re.search(rf"(game_id|gameid)\s*=\s*'?{re.escape(game_id)}'?", sql, re.IGNORECASE):
        raise SqlGuardError(f"SQL 必须包含 game_id = {game_id} 或 gameid = '{game_id}'")

    # Channel lock
    lock_ids = [str(x) for x in config.LOCK_OPGAME_IDS]
    if lock_ids:
        for oid in re.findall(r"opgame_id\s*=\s*'?(\d+)'?", sql, re.IGNORECASE):
            if oid not in lock_ids:
                raise SqlGuardError(f"无权限查询渠道 {oid}")

    # Per-user whitelist
    if REQUIRED_OPGAMES:
        allowed = [str(x) for x in REQUIRED_OPGAMES]
        for oid in re.findall(r"opgame_id\s*=\s*'?(\d+)'?", sql, re.IGNORECASE):
            if oid not in allowed:
                raise SqlGuardError(f"无权限查询渠道 {oid}")

    # Heavy subquery guard
    _check_heavy_subquery(masked)

    # Auto-add LIMIT if not present at top level
    top = _strip_parens(masked)
    if not re.search(r'\blimit\b', top, re.IGNORECASE):
        sql = f"{sql} LIMIT {config.DEFAULT_SQL_LIMIT}"

    return sql
