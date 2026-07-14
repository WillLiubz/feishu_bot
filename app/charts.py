"""查询结果图表：类型自动判断 + matplotlib PNG + openpyxl 原生图表。

- to_float / series_columns / detect_chart_type：纯数据判断，无第三方依赖
- render_png / render_pngs_for_dir：matplotlib PNG，供飞书图片消息（Task 2）
- add_native_chart：openpyxl 原生图表，供 result.xlsx（Task 3）
"""
import csv
import re
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import rcParams
    rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    rcParams["axes.unicode_minus"] = False
    CHARTS_AVAILABLE = True
except Exception:
    CHARTS_AVAILABLE = False

MAX_PIE_CATEGORIES = 8
MAX_BAR_ROWS_PNG = 20
MAX_LINE_POINTS_PNG = 60
MAX_SERIES = 3

_DATE_COL_RE = re.compile(r"日期|date|^ds$|月份|月$", re.IGNORECASE)
_DATE_VAL_RE = re.compile(r"^(\d{8}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{4}[-/]\d{1,2})$")
_ID_COL_RE = re.compile(r"(^|_)(id|uid|ouid|iuid|openid|account|role)(_|$)", re.IGNORECASE)


def to_float(v):
    """Parse a cell value as float, tolerating thousands separators. None if not numeric."""
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _is_numeric_column(rows, header):
    """True if >50% of non-empty values in the column parse as float."""
    values = [str(r.get(header, "")).strip() for r in rows]
    non_empty = [v for v in values if v not in ("", "None", "null")]
    if not non_empty:
        return False
    ok = sum(1 for v in non_empty if to_float(v) is not None)
    return ok / len(non_empty) > 0.5


def series_columns(rows):
    """Columns usable as chart series: numeric, not the first column, not id-like."""
    if not rows:
        return []
    headers = list(rows[0].keys())
    return [
        h for h in headers[1:]
        if not _ID_COL_RE.search(h) and _is_numeric_column(rows, h)
    ]


def _first_col_is_date(rows):
    first = list(rows[0].keys())[0]
    if _DATE_COL_RE.search(first):
        return True
    sample = [str(r.get(first, "")).strip() for r in rows[:5]]
    non_empty = [v for v in sample if v]
    if not non_empty:
        return False
    hits = sum(1 for v in non_empty if _DATE_VAL_RE.match(v))
    return hits / len(non_empty) >= 0.5


def detect_chart_type(rows):
    """Return 'line' | 'pie' | 'bar' | None based on data shape.

    - 无数值列 → None（不画图）
    - 首列是日期 → 折线图
    - 行数 ≤ 8 且单数值列 → 饼图
    - 其余 → 柱状图
    """
    if not rows:
        return None
    series = series_columns(rows)
    if not series:
        return None
    if _first_col_is_date(rows):
        return "line"
    if len(rows) <= MAX_PIE_CATEGORIES and len(series) == 1:
        return "pie"
    return "bar"


def _slice_for_png(rows, chart_type):
    """Truncate rows for PNG rendering to keep charts readable."""
    if chart_type == "pie":
        return rows[:MAX_PIE_CATEGORIES]
    if chart_type == "line":
        return rows[:MAX_LINE_POINTS_PNG]
    return rows[:MAX_BAR_ROWS_PNG]
