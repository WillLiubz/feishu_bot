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

MAX_PIE_CATEGORIES = 8       # 含"其他"：Top-7 + 其他
MAX_BAR_ROWS_PNG = 16        # 含"其他"：Top-15 + 其他
MAX_LINE_POINTS_PNG = 60     # 超出时均匀抽稀（保留首末点）
MAX_SERIES = 3

_DATE_COL_RE = re.compile(r"(^|_)(日期|date|ds|月份|月$)(_|$)", re.IGNORECASE)
_DATE_VAL_RE = re.compile(r"^(\d{8}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{4}[-/]\d{1,2})$")
_ID_COL_RE = re.compile(r"(^|_)(id|uid|ouid|iuid|openid|account)(_|$)", re.IGNORECASE)


def to_float(v):
    """Parse a cell value as float, tolerating thousands separators. None if not numeric."""
    import math
    try:
        f = float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
    if math.isfinite(f):
        return f
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
    - 单行结果（只有一个数据）→ None（不画图，文字罗列数字即可）
    - 首列是日期 → 折线图
    - 行数 ≤ 8 且单数值列 → 饼图
    - 其余 → 柱状图
    """
    if not rows:
        return None
    if len(rows) < 2:
        return None
    series = series_columns(rows)
    if not series:
        return None
    if _first_col_is_date(rows):
        return "line"
    if len(rows) <= MAX_PIE_CATEGORIES and len(series) == 1:
        return "pie"
    return "bar"


def _merge_other(rows, series, total_rows):
    """按首系列值降序保留前 (total_rows-1) 类，其余合并为"其他"（各系列列求和）。

    行数不超过 total_rows 时原样返回（不排序，保持原始顺序）。
    """
    if len(rows) <= total_rows or not series:
        return rows[:total_rows] if not series else rows
    cat = list(rows[0].keys())[0]
    ordered = sorted(rows, key=lambda r: to_float(r.get(series[0])) or 0.0, reverse=True)
    top, rest = ordered[:total_rows - 1], ordered[total_rows - 1:]
    other = {cat: "其他"}
    for h in series:
        other[h] = str(sum(to_float(r.get(h)) or 0.0 for r in rest))
    return top + [other]


def _downsample(rows, max_points):
    """均匀抽稀到不超过 max_points 行，保留首末点。"""
    if max_points <= 1:
        return rows[:1] if max_points == 1 and rows else []
    if len(rows) <= max_points:
        return rows
    step = (len(rows) - 1) / (max_points - 1)
    idxs = sorted({round(i * step) for i in range(max_points)})
    return [rows[i] for i in idxs]


def _slice_for_png(rows, chart_type):
    """为 PNG 渲染裁剪行：pie/bar 超限时 Top-N+其他归并，line 超限时均匀抽稀。"""
    series = series_columns(rows)
    if chart_type == "pie":
        return _merge_other(rows, series, MAX_PIE_CATEGORIES)
    if chart_type == "line":
        return _downsample(rows, MAX_LINE_POINTS_PNG)
    return _merge_other(rows, series, MAX_BAR_ROWS_PNG)


def render_png(rows, chart_type, title, out_path):
    """Render rows to a PNG chart file. Returns str(out_path) or None on failure."""
    if not CHARTS_AVAILABLE or not rows or chart_type not in ("line", "pie", "bar"):
        return None
    headers = list(rows[0].keys())
    cat_col = headers[0]
    series = series_columns(rows)
    if not series:
        return None
    try:
        data = _slice_for_png(rows, chart_type)
        fig, ax = plt.subplots(figsize=(8, 5))
        try:
            if chart_type == "pie":
                labels = [str(r.get(cat_col, "")) for r in data]
                vals = [to_float(r.get(series[0])) or 0.0 for r in data]
                ax.pie(vals, labels=labels, autopct="%1.1f%%")
            elif chart_type == "line":
                xs = [str(r.get(cat_col, "")) for r in data]
                for h in series[:MAX_SERIES]:
                    ys = [to_float(r.get(h)) or 0.0 for r in data]
                    ax.plot(xs, ys, marker="o", label=h)
                ax.legend()
                ax.tick_params(axis="x", rotation=45)
            else:  # bar
                xs = [str(r.get(cat_col, "")) for r in data]
                chosen = series[:MAX_SERIES]
                if len(chosen) == 1:
                    ys = [to_float(r.get(chosen[0])) or 0.0 for r in data]
                    ax.bar(xs, ys)
                else:
                    width = 0.8 / len(chosen)
                    for i, h in enumerate(chosen):
                        ys = [to_float(r.get(h)) or 0.0 for r in data]
                        offset = [x + i * width for x in range(len(xs))]
                        ax.bar(offset, ys, width=width, label=h)
                    center = (len(chosen) - 1) * width / 2
                    ax.set_xticks([x + center for x in range(len(xs))])
                    ax.set_xticklabels(xs)
                    ax.legend()
                ax.tick_params(axis="x", rotation=45)
            ax.set_title(title)
            fig.tight_layout()
            fig.savefig(str(out_path), dpi=110, bbox_inches="tight")
        finally:
            plt.close(fig)
        return str(out_path)
    except Exception as e:
        print(f"[charts] render_png failed: {e}", flush=True)
        return None


def _title_for(result_dir: Path, index: int) -> str:
    """Derive chart title like '查询1_payrecharge' from the adjacent .sql file.

    Note: mirrors dquery._sheet_name logic; duplicated here to avoid a
    circular import (dquery imports charts).
    """
    sql_file = result_dir / f"query_{index}.sql"
    sql_text = sql_file.read_text(encoding="utf-8") if sql_file.exists() else ""
    m = re.search(r"\bFROM\s+(\S+)", sql_text, re.IGNORECASE)
    if m:
        tbl = m.group(1).split(".")[-1].strip('`"\' ')[:20]
        return f"查询{index}_{tbl}"
    return f"查询{index}"


def render_pngs_for_dir(result_dir):
    """Generate query_N.png next to each chartable query_N.csv. Returns list of paths."""
    result_dir = Path(result_dir)
    paths = []

    def _csv_index(p):
        m = re.search(r"query_(\d+)", p.stem)
        return int(m.group(1)) if m else -1

    query_files = sorted(result_dir.glob("query_*.csv"), key=_csv_index)
    for csv_path in query_files:
        try:
            idx = int(re.search(r"query_(\d+)", csv_path.stem).group(1))
        except (AttributeError, ValueError):
            continue
        try:
            with open(csv_path, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        except Exception:
            continue
        ctype = detect_chart_type(rows)
        if not ctype:
            continue
        out = result_dir / f"query_{idx}.png"
        if render_png(rows, ctype, _title_for(result_dir, idx), out):
            paths.append(str(out))
    return paths


def add_native_chart(ws, rows, chart_type, anchor):
    """Embed a native openpyxl chart into worksheet at anchor (e.g. 'J2').

    Data must already be written starting at A1 (header in row 1), and value
    cells referenced by the chart must be real numbers. Chart title uses the
    worksheet title. Returns True if a chart was embedded.
    """
    from openpyxl.chart import PieChart, BarChart, LineChart, Reference
    if not rows or chart_type not in ("line", "pie", "bar"):
        return False
    headers = list(rows[0].keys())
    series = series_columns(rows)
    if not series:
        return False
    n_rows = len(rows) + 1
    cats = Reference(ws, min_col=1, min_row=2, max_row=n_rows)
    if chart_type == "pie":
        chart = PieChart()
        chosen = series[:1]
    elif chart_type == "line":
        chart = LineChart()
        chosen = series[:MAX_SERIES]
    else:
        chart = BarChart()
        chart.type = "col"
        chosen = series[:MAX_SERIES]
    for h in chosen:
        col = headers.index(h) + 1
        vals = Reference(ws, min_col=col, min_row=1, max_row=n_rows)
        chart.add_data(vals, titles_from_data=True)
    chart.set_categories(cats)
    chart.title = ws.title
    chart.width = 14
    chart.height = 8
    ws.add_chart(chart, anchor)
    return True


def comparison_type(datasets):
    """判断多个数据集能否合成一张对比图：'line' | 'bar' | None。

    要求：≥2 个数据集、列名完全一致、系列列一致；
    首列全是日期 → line，全不是日期 → bar，混杂 → None。
    """
    if len(datasets) < 2 or any(not d for d in datasets):
        return None
    headers0 = list(datasets[0][0].keys())
    series0 = series_columns(datasets[0])
    if not series0:
        return None
    for d in datasets[1:]:
        if list(d[0].keys()) != headers0 or series_columns(d) != series0:
            return None
    date_flags = [_first_col_is_date(d) for d in datasets]
    if all(date_flags):
        return "line"
    if any(date_flags):
        return None
    return "bar"


def render_comparison_png(datasets, labels, title, out_path):
    """把多个同构数据集渲染成一张多系列对比图。Returns str(out_path) or None.

    只比较第一个系列列；labels 与 datasets 一一对应（不足补"查询N"，超出截断）。
    """
    if not CHARTS_AVAILABLE:
        return None
    ctype = comparison_type(datasets)
    if not ctype:
        return None
    labels = [str(l)[:12] for l in list(labels)]
    labels = (labels + [f"查询{i + 1}" for i in range(len(datasets))])[:len(datasets)]
    labels = [l or f"查询{i + 1}" for i, l in enumerate(labels)]
    cat = list(datasets[0][0].keys())[0]
    val = series_columns(datasets[0])[0]
    try:
        fig, ax = plt.subplots(figsize=(9, 5))
        try:
            if ctype == "line":
                xs = sorted({str(r.get(cat, "")) for d in datasets for r in d})
                for d, lab in zip(datasets, labels):
                    ymap = {str(r.get(cat, "")): to_float(r.get(val)) or 0.0 for r in d}
                    ax.plot(xs, [ymap.get(x, 0.0) for x in xs], marker="o", label=lab)
                ax.legend()
                ax.tick_params(axis="x", rotation=45)
            else:  # bar：类目并集分组柱状，超限时按总值取 Top-N + 其他
                cats = list(dict.fromkeys(str(r.get(cat, "")) for d in datasets for r in d))
                if len(cats) > MAX_BAR_ROWS_PNG:
                    totals = {}
                    for d in datasets:
                        for r in d:
                            k = str(r.get(cat, ""))
                            totals[k] = totals.get(k, 0.0) + (to_float(r.get(val)) or 0.0)
                    keep = set(sorted(totals, key=totals.get, reverse=True)[:MAX_BAR_ROWS_PNG - 1])
                    cats = [c for c in cats if c in keep] + ["其他"]
                width = 0.8 / len(datasets)
                for i, (d, lab) in enumerate(zip(datasets, labels)):
                    ymap = {str(r.get(cat, "")): to_float(r.get(val)) or 0.0 for r in d}
                    ys = [
                        sum(v for k, v in ymap.items() if k not in cats) if c == "其他"
                        else ymap.get(c, 0.0)
                        for c in cats
                    ]
                    ax.bar([x + i * width for x in range(len(cats))], ys, width=width, label=lab)
                center = (len(datasets) - 1) * width / 2
                ax.set_xticks([x + center for x in range(len(cats))])
                ax.set_xticklabels(cats)
                ax.legend()
                ax.tick_params(axis="x", rotation=45)
            ax.set_title(title)
            fig.tight_layout()
            fig.savefig(str(out_path), dpi=110, bbox_inches="tight")
        finally:
            plt.close(fig)
        return str(out_path)
    except Exception as e:
        print(f"[charts] render_comparison_png failed: {e}", flush=True)
        return None


def render_comparison_for_dir(result_dir, labels, title="多期对比"):
    """尝试把 result_dir 下的 query_*.csv 合成一张对比图。Returns [path] or []."""
    result_dir = Path(result_dir)

    def _csv_index(p):
        m = re.search(r"query_(\d+)", p.stem)
        return int(m.group(1)) if m else -1

    csv_files = sorted(result_dir.glob("query_*.csv"), key=_csv_index)
    if len(csv_files) < 2:
        return []
    datasets = []
    for p in csv_files:
        try:
            with open(p, encoding="utf-8-sig", newline="") as f:
                datasets.append(list(csv.DictReader(f)))
        except Exception:
            return []
    out = result_dir / "comparison.png"
    path = render_comparison_png(datasets, labels, title, out)
    return [path] if path else []
