import re

_ODL_HINT_RE = re.compile(r"^\s*--\s*use_odl\b", re.IGNORECASE)
_ODL_DB_RE = re.compile(r"\bgamelog_odl\b", re.IGNORECASE)


def _split_by_literals(sql: str):
    """Split sql into (is_literal, text) segments."""
    segments = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c in ("'", '"'):
            start = i
            quote = c
            i += 1
            while i < n:
                if sql[i] == "\\":
                    i += 2
                    continue
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            segments.append((True, sql[start:i]))
        else:
            start = i
            while i < n and sql[i] not in ("'", '"'):
                i += 1
            segments.append((False, sql[start:i]))
    return segments


def extract_odl_hint(sql: str) -> tuple[str, bool]:
    """
    Strip a leading `-- use_odl` hint and return (cleaned_sql, use_odl).

    The hint must be the first non-whitespace content in the SQL. It is
    removed before sqlguard validation so that comments do not trigger
    the banned-phrases guard.
    """
    m = _ODL_HINT_RE.match(sql)
    if not m:
        return sql, False
    cleaned = sql[m.end() :]
    # Drop the newline that followed the hint so the SQL remains valid.
    cleaned = cleaned.lstrip(" \t\r\n")
    return cleaned, True


def rewrite_odl_to_raw(sql: str) -> str:
    """
    Replace gamelog_odl with gamelog_raw, leaving string literals untouched.

    Only the `gamelog_odl` database token is rewritten; `gameeco_odl` and
    other databases are left unchanged.
    """
    parts = []
    for is_literal, seg in _split_by_literals(sql):
        if is_literal:
            parts.append(seg)
        else:
            parts.append(_ODL_DB_RE.sub("gamelog_raw", seg))
    return "".join(parts)
