"""SQL template engine for fixed analytics reports.

Templates are stored as JSON files under app/templates/.
Each template defines a set of parameterized SQL sheets per game.
The engine renders placeholders and executes the sheets sequentially,
writing query_N.csv and query_N.sql so that dquery.combine_to_excel()
can merge them into a multi-sheet Excel file.
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path

import config
import dataapi
import dquery

_TEMPLATES_DIR = Path(__file__).parent

# Match relative date expressions in user questions.
_RELATIVE_PATTERNS = [
    (re.compile(r'近\s*3\s*[天日]'), 3),
    (re.compile(r'近\s*7\s*[天日]'), 7),
    (re.compile(r'近\s*14\s*[天日]'), 14),
    (re.compile(r'近\s*30\s*[天日]'), 30),
]


def _today():
    return date.today()


def _ds(d: date) -> str:
    return d.strftime("%Y%m%d")


def _parse_window_days(text: str, default: int = 7) -> int:
    """Extract analysis window length from text; fallback to default."""
    for pattern, days in _RELATIVE_PATTERNS:
        if pattern.search(text):
            return days
    if re.search(r'本\s*周', text):
        return _today().weekday() + 1
    if re.search(r'上\s*周', text):
        return 7
    if re.search(r'本\s*月', text):
        return _today().day
    return default


def _parse_absolute_range(text: str) -> tuple[date, date] | None:
    """Parse an absolute date range like 2026-07-01~2026-07-07 or 20260701 20260707."""
    # YYYY-MM-DD ~ YYYY-MM-DD
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s*[~到至-]\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})', text)
    if m:
        return (
            date(int(m.group(1)), int(m.group(2)), int(m.group(3))),
            date(int(m.group(4)), int(m.group(5)), int(m.group(6))),
        )
    # YYYYMMDD ~ YYYYMMDD
    m = re.search(r'(\d{8})\s*[~到至-]\s*(\d{8})', text)
    if m:
        s1, s2 = m.group(1), m.group(2)
        return (
            date(int(s1[:4]), int(s1[4:6]), int(s1[6:8])),
            date(int(s2[:4]), int(s2[4:6]), int(s2[6:8])),
        )
    # Single absolute date
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', text)
    if m:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d, d
    m = re.search(r'(\d{8})', text)
    if m:
        s = m.group(1)
        d = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return d, d
    return None


def compute_params(text: str, game_config, template_defaults: dict) -> dict:
    """Compute template parameters from user text and game config."""
    analysis_days = template_defaults.get("analysis_window_days", 7)
    silent_days = template_defaults.get("silent_window_days", 30)
    top_n = template_defaults.get("top_n", 100)

    # Window length can be overridden by the question.
    analysis_days = _parse_window_days(text, default=analysis_days)

    today = _today()
    abs_range = _parse_absolute_range(text)
    if abs_range:
        analysis_start, analysis_end = abs_range
    elif re.search(r'今日|今天', text):
        analysis_start = analysis_end = today
    elif re.search(r'昨日|昨天', text):
        analysis_start = analysis_end = today - timedelta(days=1)
    elif re.search(r'本\s*周', text):
        analysis_start = today - timedelta(days=today.weekday())
        analysis_end = today
    elif re.search(r'上\s*周', text):
        analysis_start = today - timedelta(days=today.weekday() + 7)
        analysis_end = analysis_start + timedelta(days=6)
    elif re.search(r'本\s*月', text):
        analysis_start = today.replace(day=1)
        analysis_end = today
    else:
        # Default: last N days ending yesterday (today's data may be incomplete).
        analysis_end = today - timedelta(days=1)
        analysis_start = analysis_end - timedelta(days=analysis_days - 1)

    # Silent window immediately precedes the analysis window.
    silent_end = analysis_start - timedelta(days=1)
    silent_start = analysis_end - timedelta(days=analysis_days + silent_days - 1)

    game_id = game_config.game_id
    # String game_id is required by some tables (ECO / game 39).
    game_id_str = str(game_id)

    # Per-game test-server filter.
    if game_id == 39:
        server_filter = ""
    else:
        server_filter = "AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'"

    return {
        "analysis_start": _ds(analysis_start),
        "analysis_end": _ds(analysis_end),
        "analysis_start_quoted": f"'{_ds(analysis_start)}'",
        "analysis_end_quoted": f"'{_ds(analysis_end)}'",
        "silent_start": _ds(silent_start),
        "silent_end": _ds(silent_end),
        "silent_start_quoted": f"'{_ds(silent_start)}'",
        "silent_end_quoted": f"'{_ds(silent_end)}'",
        "game_id": game_id,
        "game_id_str": game_id_str,
        "top_n": top_n,
        "server_filter": server_filter,
    }


def load_template(template_name: str) -> dict:
    """Load a template JSON file."""
    path = _TEMPLATES_DIR / f"{template_name}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def render_sql(sql: str, params: dict) -> str:
    """Render SQL with {placeholder} style placeholders."""
    # Replace each known placeholder explicitly to avoid conflicts with
    # any braces that may appear elsewhere in the SQL.
    for key, value in params.items():
        sql = sql.replace(f"{{{key}}}", str(value))
    return sql


def run_report(template_name: str, question: str, game_config) -> tuple[str, str]:
    """
    Run a templated report.

    Returns (summary_text, result_dir_path).
    The caller can pass result_dir_path to dquery.combine_to_excel().
    """
    template = load_template(template_name)
    defaults = template.get("default_params", {})
    params = compute_params(question, game_config, defaults)

    game_id_str = str(game_config.game_id)
    game_sheets = template["games"].get(game_id_str)
    if not game_sheets:
        raise ValueError(f"模板 {template_name} 不支持游戏 {game_id_str}")

    # Prepare result directory.
    import tempfile
    result_dir = Path(tempfile.mkdtemp(prefix=f"{template_name}_"))

    sheet_names = []
    for idx, (sheet_key, sheet_def) in enumerate(game_sheets.items(), start=1):
        sql = render_sql(sheet_def["sql"], params)
        max_rows = sheet_def.get("max_rows", config.DATA_API_MAX_ROWS)
        rows = dataapi.run_sql_rows(sql, max_rows=max_rows)

        # Apply Chinese display-name mapping if configured.
        column_map = sheet_def.get("columns")
        if column_map and rows:
            rows = [
                {column_map.get(k, k): v for k, v in row.items()}
                for row in rows
            ]

        # Apply per-cell value mapping if configured (e.g. pay_type code -> name).
        value_map = sheet_def.get("value_map")
        if value_map and rows:
            for row in rows:
                for col, mapping in value_map.items():
                    if col in row:
                        row[col] = mapping.get(str(row[col]), row[col])

        csv_path = result_dir / f"query_{idx}.csv"
        sql_path = result_dir / f"query_{idx}.sql"
        dquery.write_csv_to(rows, csv_path)
        sql_path.write_text(sql, encoding="utf-8")
        sheet_names.append(sheet_def.get("name", sheet_key))

    fmt = {**params, "template_name": template_name, "game_id": game_config.game_id}
    summary_template = template.get(
        "summary_template",
        "【{template_name}】游戏 {game_id}，分析窗口 {analysis_start}~{analysis_end}",
    )
    summary = summary_template.format(**fmt) + (
        f"\n共 {len(sheet_names)} 个 Sheet：{', '.join(sheet_names)}"
    )
    return summary, str(result_dir)
