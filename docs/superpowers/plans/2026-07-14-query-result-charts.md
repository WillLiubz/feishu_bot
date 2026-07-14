# 查询结果图表化展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为飞书数仓机器人的查询结果自动生成饼图/柱状图/折线图，在飞书聊天发送 PNG 图表、在 result.xlsx 嵌入原生图表，并把文字结论写入 xlsx 每个数据 sheet 的表格下方。

**Architecture:** 新增 `app/charts.py` 集中所有图表逻辑（类型自动判断、matplotlib PNG 渲染、openpyxl 原生图表）；`dquery.combine_to_excel` 扩展结论参数并嵌入图表；`bot.py` 新增图片发送并把三个 handler（简单查询/分步查询/固定报表）统一改为"图→文字→文件"时序。图表生成是结果落盘后的后处理，不影响查询主链路。

**Tech Stack:** Python 3.12、matplotlib（PNG 渲染，新依赖已获用户批准）、openpyxl 3.1.5（原生图表）、lark_oapi（飞书图片上传）、pytest。

## Global Constraints

- Python 3.12+，所有文件 UTF-8 编码。
- 除 matplotlib（用户已明确批准）外不安装其他新依赖。
- 图表是增强功能：任何图表相关失败只记日志、跳过，绝不影响文字结论和文件发送主链路。
- 测试：`python -m pytest tests/ -q` 必须全绿；新增逻辑必须配 `tests/test_*.py`。
- 提交：中文提交信息 `<type>: <描述>`，结尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`；不直接提交到 master。
- 每次提交前 `git diff --cached --name-only | grep -i config` 应无输出（敏感配置不入库）。
- 设计文档：`docs/superpowers/specs/2026-07-14-query-result-charts-design.md`。

---

### Task 1: charts.py 图表类型判断逻辑

纯数据判断模块，无第三方依赖，先行 TDD。

**Files:**
- Create: `app/charts.py`
- Test: `tests/test_charts.py`

**Interfaces:**
- Produces:
  - `charts.to_float(v) -> float | None` — 容忍千分位逗号的数值解析
  - `charts.series_columns(rows: list[dict]) -> list[str]` — 可作图表数列的列：数值型、非首列、非 id 类列名
  - `charts.detect_chart_type(rows: list[dict]) -> 'line' | 'pie' | 'bar' | None`
  - `charts._slice_for_png(rows, chart_type) -> list[dict]` — PNG 渲染行数截断（本任务先建，Task 2 使用）

- [ ] **Step 1: 新建功能分支**

```bash
git checkout -b feat-query-result-charts
```

（从当前 HEAD 切出，设计文档 commit `a700f43` 会随之带入新分支。）

- [ ] **Step 2: 写失败测试**

Create `tests/test_charts.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import charts


def test_detect_none_for_empty_rows():
    assert charts.detect_chart_type([]) is None


def test_detect_none_without_numeric_column():
    rows = [{"a": "x", "b": "y"}, {"a": "z", "b": "w"}]
    assert charts.detect_chart_type(rows) is None


def test_detect_line_when_first_column_is_date():
    rows = [{"日期": "20260701", "收入": "100"}, {"日期": "20260702", "收入": "200"}]
    assert charts.detect_chart_type(rows) == "line"


def test_detect_line_when_first_column_values_look_like_dates():
    rows = [{"ds": "20260701", "dau": "10"}, {"ds": "20260702", "dau": "20"},
            {"ds": "20260703", "dau": "30"}, {"ds": "20260704", "dau": "40"},
            {"ds": "20260705", "dau": "50"}, {"ds": "20260706", "dau": "60"},
            {"ds": "20260707", "dau": "70"}, {"ds": "20260708", "dau": "80"},
            {"ds": "20260709", "dau": "90"}]
    assert charts.detect_chart_type(rows) == "line"


def test_detect_pie_for_few_categories_single_value_column():
    rows = [{"渠道": f"ch{i}", "收入": str(i * 10 + 10)} for i in range(5)]
    assert charts.detect_chart_type(rows) == "pie"


def test_detect_bar_for_many_categories():
    rows = [{"渠道": f"ch{i}", "收入": str(i)} for i in range(12)]
    assert charts.detect_chart_type(rows) == "bar"


def test_detect_bar_for_multiple_value_columns():
    rows = [{"渠道": "a", "收入": "10", "付费人数": "3"}]
    assert charts.detect_chart_type(rows) == "bar"


def test_id_columns_excluded_from_series():
    rows = [{"排名": "1", "role_id": "1001", "充值金额": "50"},
            {"排名": "2", "role_id": "1002", "充值金额": "60"}]
    assert charts.series_columns(rows) == ["充值金额"]


def test_varchar_numeric_with_thousands_separator():
    # 游戏 39 场景：数值列是 VARCHAR，可能带千分位
    rows = [{"item": "钻石", "cnt": "1,234"}, {"item": "金币", "cnt": "5,678"}]
    assert charts.series_columns(rows) == ["cnt"]
    assert charts.detect_chart_type(rows) == "pie"


def test_to_float():
    assert charts.to_float("1,234.5") == 1234.5
    assert charts.to_float("42") == 42.0
    assert charts.to_float("abc") is None
    assert charts.to_float(None) is None


def test_slice_for_png_limits():
    rows = [{"c": str(i), "v": str(i)} for i in range(100)]
    assert len(charts._slice_for_png(rows, "pie")) == charts.MAX_PIE_CATEGORIES
    assert len(charts._slice_for_png(rows, "line")) == charts.MAX_LINE_POINTS_PNG
    assert len(charts._slice_for_png(rows, "bar")) == charts.MAX_BAR_ROWS_PNG
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_charts.py -q`
Expected: FAIL（ModuleNotFoundError: No module named 'charts'）

- [ ] **Step 4: 实现 charts.py 判断逻辑**

Create `app/charts.py`:

```python
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
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_charts.py -q`
Expected: PASS（12 passed）

- [ ] **Step 6: 提交**

```bash
git add app/charts.py tests/test_charts.py
git commit -m "feat: 新增 charts 模块图表类型自动判断逻辑

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: matplotlib PNG 渲染 + requirements.txt

安装已获批准的 matplotlib，实现飞书侧 PNG 渲染。

**Files:**
- Modify: `app/charts.py`（追加 render_png / _title_for / render_pngs_for_dir）
- Modify: `tests/test_charts.py`
- Create: `requirements.txt`

**Interfaces:**
- Consumes: `charts.to_float`、`charts.series_columns`、`charts._slice_for_png`、`charts.CHARTS_AVAILABLE`（Task 1）
- Produces:
  - `charts.render_png(rows, chart_type, title, out_path) -> str | None`
  - `charts.render_pngs_for_dir(result_dir) -> list[str]` — bot.py 调用

- [ ] **Step 1: 安装 matplotlib 并新建 requirements.txt**

```bash
pip install matplotlib
```

Create `requirements.txt`:

```
lark-oapi
fastmcp
openpyxl
matplotlib
pytest
```

- [ ] **Step 2: 写失败测试**

Append to `tests/test_charts.py`:

```python
import pytest


_PIE_ROWS = [{"渠道": "甲", "收入": "30"}, {"渠道": "乙", "收入": "70"}]
_LINE_ROWS = [{"日期": f"2026070{i}", "收入": str(i * 100)} for i in range(1, 4)]
_BAR_ROWS = [{"道具": f"item{i}", "数量": str(i * 5)} for i in range(10)]


def test_render_png_pie(tmp_path):
    if not charts.CHARTS_AVAILABLE:
        pytest.skip("matplotlib not installed")
    out = charts.render_png(_PIE_ROWS, "pie", "充值占比", tmp_path / "pie.png")
    assert out and Path(out).exists() and Path(out).stat().st_size > 0


def test_render_png_line(tmp_path):
    if not charts.CHARTS_AVAILABLE:
        pytest.skip("matplotlib not installed")
    out = charts.render_png(_LINE_ROWS, "line", "收入趋势", tmp_path / "line.png")
    assert out and Path(out).exists() and Path(out).stat().st_size > 0


def test_render_png_bar_grouped(tmp_path):
    if not charts.CHARTS_AVAILABLE:
        pytest.skip("matplotlib not installed")
    rows = [{"渠道": "a", "收入": "10", "付费人数": "3"},
            {"渠道": "b", "收入": "20", "付费人数": "5"}]
    out = charts.render_png(rows, "bar", "分组柱状", tmp_path / "bar.png")
    assert out and Path(out).exists() and Path(out).stat().st_size > 0


def test_render_png_returns_none_when_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(charts, "CHARTS_AVAILABLE", False)
    assert charts.render_png(_PIE_ROWS, "pie", "t", tmp_path / "x.png") is None


def test_render_png_returns_none_for_invalid_type(tmp_path):
    assert charts.render_png(_PIE_ROWS, "unknown", "t", tmp_path / "x.png") is None


def test_render_pngs_for_dir(tmp_path):
    (tmp_path / "query_1.csv").write_text("类别,数值\n甲,10\n乙,20\n", encoding="utf-8-sig")
    (tmp_path / "query_1.sql").write_text("SELECT a FROM db.payrecharge", encoding="utf-8")
    (tmp_path / "query_2.csv").write_text("a,b\nx,y\n", encoding="utf-8-sig")  # 无数值列
    paths = charts.render_pngs_for_dir(str(tmp_path))
    if charts.CHARTS_AVAILABLE:
        assert len(paths) == 1
        assert paths[0].endswith("query_1.png")
    else:
        assert paths == []
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_charts.py -q -k "render"`
Expected: FAIL（AttributeError: module 'charts' has no attribute 'render_png'）

- [ ] **Step 4: 实现 PNG 渲染**

Append to `app/charts.py`:

```python
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
                center = 0.4 - width / 2
                ax.set_xticks([x + center for x in range(len(xs))])
                ax.set_xticklabels(xs)
                ax.legend()
            ax.tick_params(axis="x", rotation=45)
        ax.set_title(title)
        fig.tight_layout()
        fig.savefig(str(out_path), dpi=110, bbox_inches="tight")
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
    query_files = sorted(
        result_dir.glob("query_*.csv"),
        key=lambda p: int(re.search(r"query_(\d+)", p.stem).group(1)),
    )
    for i, csv_path in enumerate(query_files, 1):
        try:
            with open(csv_path, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        except Exception:
            continue
        ctype = detect_chart_type(rows)
        if not ctype:
            continue
        out = result_dir / f"query_{i}.png"
        if render_png(rows, ctype, _title_for(result_dir, i), out):
            paths.append(str(out))
    return paths
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_charts.py -q`
Expected: PASS（18 passed，若 matplotlib 未装好则 render 类被 skip —— 必须先完成 Step 1）

- [ ] **Step 6: 提交**

```bash
git add app/charts.py tests/test_charts.py requirements.txt
git commit -m "feat: charts 模块新增 matplotlib PNG 渲染

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: openpyxl 原生图表嵌入

**Files:**
- Modify: `app/charts.py`（追加 add_native_chart）
- Test: `tests/test_charts.py`

**Interfaces:**
- Consumes: `charts.series_columns`（Task 1）
- Produces: `charts.add_native_chart(ws, rows, chart_type, anchor) -> bool` — dquery 调用。要求数据已从 A1 写入（表头在第 1 行），被引用的数值单元格必须是真正的数字（Task 4 的 `_coerce_number` 保证）。

- [ ] **Step 1: 写失败测试**

Append to `tests/test_charts.py`:

```python
def test_add_native_chart_pie():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["类别", "数值"])
    ws.append(["甲", 10])
    ws.append(["乙", 20])
    rows = [{"类别": "甲", "数值": "10"}, {"类别": "乙", "数值": "20"}]
    ok = charts.add_native_chart(ws, rows, "pie", "D2")
    assert ok is True
    assert len(ws._charts) == 1


def test_add_native_chart_line_multi_series():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["日期", "收入", "付费人数"])
    ws.append(["20260701", 100, 5])
    ws.append(["20260702", 200, 8])
    rows = [{"日期": "20260701", "收入": "100", "付费人数": "5"},
            {"日期": "20260702", "收入": "200", "付费人数": "8"}]
    ok = charts.add_native_chart(ws, rows, "line", "E2")
    assert ok is True
    assert len(ws._charts) == 1


def test_add_native_chart_returns_false_without_series():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["a", "b"])
    ws.append(["x", "y"])
    rows = [{"a": "x", "b": "y"}]
    assert charts.add_native_chart(ws, rows, "bar", "D2") is False
    assert len(ws._charts) == 0


def test_add_native_chart_returns_false_for_invalid_type():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    rows = [{"类别": "甲", "数值": "10"}]
    assert charts.add_native_chart(ws, rows, "unknown", "D2") is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_charts.py -q -k "native"`
Expected: FAIL（AttributeError: module 'charts' has no attribute 'add_native_chart'）

- [ ] **Step 3: 实现 add_native_chart**

Append to `app/charts.py`:

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_charts.py -q`
Expected: PASS（22 passed）

- [ ] **Step 5: 提交**

```bash
git add app/charts.py tests/test_charts.py
git commit -m "feat: charts 模块新增 openpyxl 原生图表嵌入

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: dquery 支持结论块、总结 sheet、图表嵌入与 rows_to_xlsx

**Files:**
- Modify: `app/dquery.py`
- Test: `tests/test_dquery.py`

**Interfaces:**
- Consumes: `charts.detect_chart_type`、`charts.series_columns`、`charts.to_float`、`charts.add_native_chart`
- Produces:
  - `dquery.combine_to_excel(result_dir, conclusions=None, final_summary=None) -> str | None`（新参数可选，旧调用方行为不变）
  - `dquery.rows_to_xlsx(rows, summary, title="报表", out_path=None) -> str` — bot 固定报表分支调用

布局（每个数据 sheet）：A1 表头 → 数据行（数值列写成真数字）→ 右侧锚点嵌入原生图表 → 表格下方【结论】文字块 → 最底部【SQL】块（现状逻辑下移）。

- [ ] **Step 1: 写失败测试**

Append to `tests/test_dquery.py`:

```python
def _write_query_files(tmp_path, n=1):
    for i in range(1, n + 1):
        (tmp_path / f"query_{i}.csv").write_text(
            "类别,数值\n甲,10\n乙,20\n", encoding="utf-8-sig"
        )
        (tmp_path / f"query_{i}.sql").write_text(
            f"SELECT x FROM db.table{i}", encoding="utf-8"
        )


def test_combine_to_excel_without_new_params_unchanged(tmp_path):
    import dquery
    _write_query_files(tmp_path)
    out = dquery.combine_to_excel(str(tmp_path))
    assert out and Path(out).exists()
    from openpyxl import load_workbook
    wb = load_workbook(out)
    ws = wb[wb.sheetnames[0]]
    labels = [ws.cell(r, 1).value for r in range(1, 10)]
    assert "【结论】" not in labels
    # 无结论时 SQL 块位置保持现状：数据 2 行 → 标签在第 5 行
    assert ws.cell(5, 1).value == "【SQL】"


def test_combine_to_excel_writes_conclusion_below_table(tmp_path):
    import dquery
    _write_query_files(tmp_path)
    out = dquery.combine_to_excel(str(tmp_path), conclusions=["甲占三分之一"])
    from openpyxl import load_workbook
    wb = load_workbook(out)
    ws = wb[wb.sheetnames[0]]
    assert ws.cell(4, 1).value == "【结论】"
    assert ws.cell(5, 1).value == "甲占三分之一"
    # SQL 块随结论下移
    assert ws.cell(7, 1).value == "【SQL】"


def test_combine_to_excel_embeds_native_chart(tmp_path):
    import dquery
    _write_query_files(tmp_path)
    out = dquery.combine_to_excel(str(tmp_path))
    from openpyxl import load_workbook
    wb = load_workbook(out)
    ws = wb[wb.sheetnames[0]]
    assert len(ws._charts) == 1


def test_combine_to_excel_coerces_numeric_cells(tmp_path):
    import dquery
    (tmp_path / "query_1.csv").write_text(
        "渠道,收入,role_id\nA,1234.5,10001\n", encoding="utf-8-sig"
    )
    out = dquery.combine_to_excel(str(tmp_path))
    from openpyxl import load_workbook
    wb = load_workbook(out)
    ws = wb[wb.sheetnames[0]]
    assert ws.cell(2, 2).value == 1234.5  # 数值列 → 真数字
    assert ws.cell(2, 3).value == "10001"  # id 列 → 保持字符串


def test_combine_to_excel_prepends_summary_sheet(tmp_path):
    import dquery
    _write_query_files(tmp_path, n=2)
    out = dquery.combine_to_excel(
        str(tmp_path), conclusions=["c1", "c2"], final_summary="总体结论"
    )
    from openpyxl import load_workbook
    wb = load_workbook(out)
    assert wb.sheetnames[0] == "总结"
    assert wb["总结"].cell(2, 1).value == "总体结论"
    assert len(wb.sheetnames) == 3


def test_rows_to_xlsx(tmp_path):
    import dquery
    rows = [{"类别": "甲", "数值": "10"}, {"类别": "乙", "数值": "20"}]
    out = dquery.rows_to_xlsx(rows, "结论文字", title="KPI", out_path=str(tmp_path / "r.xlsx"))
    assert Path(out).exists()
    from openpyxl import load_workbook
    wb = load_workbook(out)
    ws = wb.active
    assert ws.title == "KPI"
    assert len(ws._charts) == 1
    assert ws.cell(4, 1).value == "【结论】"
    assert ws.cell(5, 1).value == "结论文字"


def test_rows_to_xlsx_empty_rows(tmp_path):
    import dquery
    out = dquery.rows_to_xlsx([], "无数据", out_path=str(tmp_path / "r.xlsx"))
    assert Path(out).exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_dquery.py -q`
Expected: FAIL（combine_to_excel 不接受 conclusions 参数 / 无 rows_to_xlsx）

- [ ] **Step 3: 重构 dquery.py**

Replace the entire content of `app/dquery.py` with:

```python
import csv
import re
import tempfile
from pathlib import Path

import charts


def write_csv_to(rows, path):
    """Write list[dict] to path as UTF-8 BOM CSV. Overwrites if exists."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("(no data)\n", encoding="utf-8-sig")
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_csv(rows):
    """Write to a temp file, return file path string. Used by reports."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8-sig", newline=""
    ) as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return f.name


def _sheet_name(sql, index):
    """Derive a short sheet name from SQL and query index."""
    # Extract first table name after FROM/JOIN
    m = re.search(r'\bFROM\s+(\S+)', sql, re.IGNORECASE)
    if not m:
        m = re.search(r'\bJOIN\s+(\S+)', sql, re.IGNORECASE)
    if m:
        # Keep only the last part (after dot) and trim to 20 chars
        tbl = m.group(1).split('.')[-1].strip('`"\' ')[:20]
        name = f"查询{index}_{tbl}"
    else:
        name = f"查询{index}"
    # Excel sheet names max 31 chars, no special chars
    name = re.sub(r'[\\/*?\[\]:]', '_', name)
    return name[:31]


def _coerce_number(value):
    """Convert numeric strings to int/float so Excel charts can reference them."""
    if value is None:
        return ""
    s = str(value).strip()
    if s == "":
        return ""
    num = charts.to_float(s)
    if num is None:
        return value
    if num.is_integer() and "." not in s and "e" not in s.lower():
        return int(num)
    return num


def _estimate_height(text, chars_per_line, max_height):
    """Estimate row height for wrapped text."""
    lines = text.count("\n") + max(1, len(text) // chars_per_line)
    return min(15 * lines, max_height)


def _write_data_sheet(wb, title, rows, sql_text="", conclusion=None):
    """Create one sheet: styled table + native chart + conclusion + SQL block."""
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    ws = wb.create_sheet(title=title)
    header_fill = PatternFill("solid", fgColor="4472C4")
    header_font = Font(bold=True, color="FFFFFF")

    if not rows or (len(rows) == 1 and list(rows[0].values()) == ["(no data)"]):
        ws.cell(1, 1, "(no data)")
        return ws

    headers = list(rows[0].keys())

    # Header row with styling
    for ci, h in enumerate(headers, 1):
        cell = ws.cell(1, ci, h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    # Data rows; numeric series columns are written as real numbers so
    # native charts can reference them. id-like columns stay strings.
    coerce_cols = set(charts.series_columns(rows))
    for ri, row in enumerate(rows, 2):
        for ci, h in enumerate(headers, 1):
            v = row.get(h, "")
            ws.cell(ri, ci, _coerce_number(v) if h in coerce_cols else v)

    # Auto column width (max 40)
    for ci, h in enumerate(headers, 1):
        max_len = max(len(str(h)), max((len(str(r.get(h, ""))) for r in rows), default=0))
        ws.column_dimensions[get_column_letter(ci)].width = min(max_len + 2, 40)

    # Native chart anchored to the right of the table (never fatal)
    try:
        ctype = charts.detect_chart_type(rows)
        if ctype:
            anchor = f"{get_column_letter(len(headers) + 2)}2"
            charts.add_native_chart(ws, rows, ctype, anchor)
    except Exception as e:
        print(f"[dquery] chart embed failed: {e}", flush=True)

    # Conclusion and SQL blocks below the table
    cursor = len(rows) + 2  # first blank row after data
    if conclusion:
        label_cell = ws.cell(cursor, 1, "【结论】")
        label_cell.font = Font(bold=True, color="595959")
        body = ws.cell(cursor + 1, 1, conclusion)
        body.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[cursor + 1].height = _estimate_height(conclusion, 50, 200)
        cursor += 2
    if sql_text:
        label_cell = ws.cell(cursor + 1, 1, "【SQL】")
        label_cell.font = Font(bold=True, color="595959")
        sql_cell = ws.cell(cursor + 2, 1, sql_text.strip())
        sql_cell.font = Font(name="Courier New", size=9, color="595959")
        sql_cell.alignment = Alignment(wrap_text=True)
        ws.row_dimensions[cursor + 2].height = min(15 * (sql_text.count('\n') + 1), 200)
    return ws


def combine_to_excel(result_dir, conclusions=None, final_summary=None):
    """
    Combine all query_N.csv files in result_dir into a multi-sheet Excel.
    conclusions: optional list where item i-1 is the text conclusion for query_i.
    final_summary: optional overall summary; when given, a '总结' sheet is prepended.
    Returns the path to the generated xlsx file, or None if no query files found.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment

    result_dir = Path(result_dir)
    # Collect query_N.csv files in order
    query_files = sorted(
        result_dir.glob("query_*.csv"),
        key=lambda p: int(re.search(r'query_(\d+)', p.stem).group(1))
    )
    if not query_files:
        return None

    wb = Workbook()
    wb.remove(wb.active)  # remove default empty sheet

    if final_summary:
        sum_ws = wb.create_sheet(title="总结")
        title_cell = sum_ws.cell(1, 1, "最终结论")
        title_cell.font = Font(bold=True, size=12)
        body = sum_ws.cell(2, 1, final_summary)
        body.alignment = Alignment(wrap_text=True, vertical="top")
        sum_ws.column_dimensions["A"].width = 100
        sum_ws.row_dimensions[2].height = _estimate_height(final_summary, 60, 400)

    for i, csv_path in enumerate(query_files, 1):
        # Read CSV
        rows = []
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Read SQL label from adjacent .sql file if exists
        sql_file = csv_path.with_suffix('.sql')
        sql_text = sql_file.read_text(encoding="utf-8") if sql_file.exists() else ""
        sheet_name = _sheet_name(sql_text, i)
        conclusion = conclusions[i - 1] if conclusions and i - 1 < len(conclusions) else None
        _write_data_sheet(wb, sheet_name, rows, sql_text=sql_text, conclusion=conclusion)

    if not wb.sheetnames:
        return None

    out_path = result_dir / "result.xlsx"
    wb.save(out_path)
    return str(out_path)


def rows_to_xlsx(rows, summary, title="报表", out_path=None):
    """Build a single-sheet xlsx (table + native chart + conclusion) for fixed reports."""
    import os
    from openpyxl import Workbook

    if out_path is None:
        fd, out_path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
    wb = Workbook()
    wb.remove(wb.active)
    safe_title = re.sub(r'[\\/*?\[\]:]', '_', str(title))[:31] or "报表"
    _write_data_sheet(wb, safe_title, rows, conclusion=summary)
    wb.save(out_path)
    return out_path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_dquery.py tests/test_charts.py -q`
Expected: PASS（全部通过，包括 Task 1-3 的回归）

- [ ] **Step 5: 提交**

```bash
git add app/dquery.py tests/test_dquery.py
git commit -m "feat: result.xlsx 支持图表嵌入与结论块

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: bot.py 图片发送与三个 handler 接线

**Files:**
- Modify: `app/bot.py`
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: `charts.render_pngs_for_dir`、`charts.render_png`、`charts.detect_chart_type`、`dquery.combine_to_excel`（新签名）、`dquery.rows_to_xlsx`
- Produces（bot 内部）:
  - `_send_image(client, chat_id, image_path)` — 上传 PNG 并发 image 消息，失败只记日志
  - `_send_charts(client, chat_id, result_dir)` — 渲染并发送全部图表 PNG
  - `_send_result_file(client, chat_id, result_dir, conclusions=None, final_summary=None)` — 生成并发送 result.xlsx
  - 删除 `_send_results`（仅 `_handle_simple` / `_planned_handler` 两个调用方，本任务一并改掉）
  - `_run_planned_body` / `_run_planned_with_steps_body` 返回值由 `str` 改为 `(summaries: list[str], final_summary: str)`

消息时序（三个 handler 统一）：图表图片 → 文字结论 → result.xlsx 文件 → 执行详情。

- [ ] **Step 1: 写失败测试**

Append to `tests/test_bot.py`:

```python
import json


def test_send_image_uploads_then_sends_image_message(tmp_path):
    client = MagicMock()
    up_resp = MagicMock()
    up_resp.success.return_value = True
    up_resp.data.image_key = "img_key_1"
    client.im.v1.image.create.return_value = up_resp
    img = tmp_path / "q.png"
    img.write_bytes(b"\x89PNG fake")
    bot._send_image(client, "chat1", str(img))
    client.im.v1.image.create.assert_called_once()
    client.im.v1.message.create.assert_called_once()
    req = client.im.v1.message.create.call_args[0][0]
    assert req.request_body.msg_type == "image"
    assert json.loads(req.request_body.content) == {"image_key": "img_key_1"}


def test_send_image_skips_message_when_upload_fails(tmp_path):
    client = MagicMock()
    up_resp = MagicMock()
    up_resp.success.return_value = False
    client.im.v1.image.create.return_value = up_resp
    img = tmp_path / "q.png"
    img.write_bytes(b"\x89PNG fake")
    bot._send_image(client, "chat1", str(img))
    client.im.v1.message.create.assert_not_called()


def test_send_charts_never_raises(tmp_path):
    client = MagicMock()
    with patch.object(bot.charts, "render_pngs_for_dir", side_effect=RuntimeError("boom")):
        bot._send_charts(client, "chat1", str(tmp_path))  # 不应抛异常
    client.im.v1.message.create.assert_not_called()


def test_send_charts_sends_each_png(tmp_path):
    client = MagicMock()
    up_resp = MagicMock()
    up_resp.success.return_value = True
    up_resp.data.image_key = "k"
    client.im.v1.image.create.return_value = up_resp
    p1 = tmp_path / "query_1.png"
    p2 = tmp_path / "query_2.png"
    p1.write_bytes(b"\x89PNG fake")
    p2.write_bytes(b"\x89PNG fake")
    with patch.object(bot.charts, "render_pngs_for_dir", return_value=[str(p1), str(p2)]):
        bot._send_charts(client, "chat1", str(tmp_path))
    assert client.im.v1.image.create.call_count == 2
    assert client.im.v1.message.create.call_count == 2


def test_send_result_file_passes_conclusions_through(tmp_path):
    client = MagicMock()
    xlsx = tmp_path / "result.xlsx"
    xlsx.write_bytes(b"x")
    with patch.object(bot.dquery, "combine_to_excel", return_value=str(xlsx)) as m:
        with patch.object(bot, "_send_file") as sf:
            bot._send_result_file(client, "chat1", str(tmp_path),
                                  conclusions=["c1"], final_summary="fs")
    m.assert_called_once_with(str(tmp_path), conclusions=["c1"], final_summary="fs")
    sf.assert_called_once()


def test_planned_body_returns_structured_summaries(tmp_path):
    ws = {"result_dir": str(tmp_path)}
    with patch.object(bot.query_planner, "execute_step", side_effect=["s1", "s2"]):
        with patch.object(bot.query_planner, "summarize", return_value="final"):
            summaries, final = bot._run_planned_with_steps_body(
                None, "chat", "msg", "text", ws,
                [bot.query_planner.PlanStep("g1", "h1"), bot.query_planner.PlanStep("g2", "h2")],
            )
    assert summaries == ["s1", "s2"]
    assert final == "final"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_bot.py -q`
Expected: FAIL（_send_image / _send_charts / _send_result_file 不存在）

- [ ] **Step 3: 改造 bot.py**

Edit `app/bot.py` —— 在顶部 import 区追加 `import charts`（接在 `import claude_cli` 之后）：

```python
import account_cache
import charts
import claude_cli
```

在 `_send_file` 函数之后新增 `_send_image` / `_send_charts`，并把 `_send_results` 替换为 `_send_result_file`：

```python
def _send_image(client, chat_id, image_path):
    """Upload an image file and send it as an image message. Never raises."""
    from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody
    try:
        with open(image_path, "rb") as f:
            up_req = CreateImageRequest.builder() \
                .request_body(
                    CreateImageRequestBody.builder()
                    .image_type("message")
                    .image(f)
                    .build()
                ).build()
            up_resp = client.im.v1.image.create(up_req)
        if not up_resp.success():
            print(f"[bot] image upload failed: {up_resp.code} {up_resp.msg}", flush=True)
            return
        image_key = up_resp.data.image_key
        req = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("image")
                .content(json.dumps({"image_key": image_key}))
                .build()
            ).build()
        client.im.v1.message.create(req)
    except Exception as e:
        print(f"[bot] send image failed: {e}", flush=True)


def _send_charts(client, chat_id, result_dir):
    """Render PNG charts for query_N.csv files and send as image messages. Never raises."""
    try:
        for png in charts.render_pngs_for_dir(result_dir):
            _send_image(client, chat_id, png)
    except Exception as e:
        print(f"[bot] send charts failed: {e}", flush=True)


def _send_result_file(client, chat_id, result_dir, conclusions=None, final_summary=None):
    """Combine query CSVs into result.xlsx (with charts and conclusions) and send it."""
    import os
    xlsx_path = dquery.combine_to_excel(
        result_dir, conclusions=conclusions, final_summary=final_summary
    )
    if xlsx_path and os.path.exists(xlsx_path):
        _send_file(client, chat_id, xlsx_path, file_name="result.xlsx")
    elif os.path.exists(result_dir + "/result.csv"):
        _send_file(client, chat_id, result_dir + "/result.csv")
```

（删除原 `_send_results` 函数。）

新增 CSV 读取小工具（放在 `_send_result_file` 之后）：

```python
def _read_csv_rows(csv_path):
    """Read a CSV file into list[dict]; returns [] on failure."""
    import csv as _csv
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            return list(_csv.DictReader(f))
    except Exception:
        return []
```

改 `_handle_simple` 的发送段（原为 `_send_text(answer); _send_results(...)`）：

```python
        answer, new_sid = claude_cli.run(text, ws, sid)
        store.set_session(chat_id, new_sid, game_config.game_id)
        _send_charts(client, chat_id, ws["result_dir"])
        _send_text(client, chat_id, answer)
        _send_result_file(client, chat_id, ws["result_dir"], conclusions=[answer])
        _send_query_summary(client, chat_id, message_id)
```

改 `_run_planned_body` / `_run_planned_with_steps_body` 为返回结构化数据：

```python
def _run_planned_body(client, chat_id, message_id, text, ws):
    """Plan first, then execute. Returns (summaries, final_summary)."""
    plan_obj = query_planner.plan(text, ws)
    summaries = []
    for i, step in enumerate(plan_obj.steps, start=1):
        summary = query_planner.execute_step(step, i, len(plan_obj.steps), ws, summaries)
        summaries.append(summary)
    final_summary = query_planner.summarize(text, ws, summaries)
    return summaries, final_summary


def _run_planned_with_steps_body(client, chat_id, message_id, text, ws, steps):
    """Execute analyzer-provided steps. Returns (summaries, final_summary)."""
    summaries = []
    for i, step in enumerate(steps, start=1):
        summary = query_planner.execute_step(step, i, len(steps), ws, summaries)
        summaries.append(summary)
    final_summary = query_planner.summarize(text, ws, summaries)
    return summaries, final_summary
```

改 `_planned_handler` 的发送段：

```python
        _send_text(client, chat_id, "🔎 该问题较复杂，正在分步查询，请稍候…")
        if steps is not None:
            summaries, final_summary = _run_planned_with_steps_body(client, chat_id, message_id, text, ws, steps)
        else:
            summaries, final_summary = _run_planned_body(client, chat_id, message_id, text, ws)
        answer = "\n".join(f"第{i}步：{s}" for i, s in enumerate(summaries, start=1)) + "\n\n【总结】\n" + final_summary
        _send_charts(client, chat_id, ws["result_dir"])
        _send_text(client, chat_id, answer)
        _send_result_file(client, chat_id, ws["result_dir"],
                          conclusions=summaries, final_summary=final_summary)
        _send_query_summary(client, chat_id, message_id)
```

改 `_handle_report` 的发送段（替换 `summary, file_or_dir = ...` 之后到 `store.log_out` 之前的逻辑）：

```python
        summary, file_or_dir = reports.run(report_type, text, game_config=game_config)
        if file_or_dir and os.path.isdir(file_or_dir):
            # 多步报表（如玩家分层）：与 LLM 查询一致，图 → 文字 → 文件
            _send_charts(client, chat_id, file_or_dir)
            _send_text(client, chat_id, summary)
            _send_result_file(client, chat_id, file_or_dir, conclusions=[summary])
        elif file_or_dir:
            # 单 CSV 报表（KPI/LTV/月榜）：构造带图表+结论的 xlsx
            rows = _read_csv_rows(file_or_dir)
            if rows:
                try:
                    ctype = charts.detect_chart_type(rows)
                    if ctype:
                        png_path = file_or_dir.rsplit(".", 1)[0] + ".png"
                        png = charts.render_png(rows, ctype, report_type, png_path)
                        if png:
                            _send_image(client, chat_id, png)
                except Exception as e:
                    print(f"[bot] report chart failed: {e}", flush=True)
            _send_text(client, chat_id, summary)
            if rows:
                try:
                    xlsx = dquery.rows_to_xlsx(rows, summary, title=report_type)
                    _send_file(client, chat_id, xlsx, file_name="result.xlsx")
                except Exception as e:
                    print(f"[bot] rows_to_xlsx failed: {e}", flush=True)
                    _send_file(client, chat_id, file_or_dir)
            else:
                _send_file(client, chat_id, file_or_dir)
        else:
            _send_text(client, chat_id, summary)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_bot.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
python -m py_compile app/bot.py
git add app/bot.py tests/test_bot.py
git commit -m "feat: 飞书消息支持图表图片发送并统一图-文-文件时序

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 调试脚本 + 全量验证

**Files:**
- Create: `debug/test_charts_render.py`

**Interfaces:**
- Consumes: `charts.render_pngs_for_dir`、`dquery.combine_to_excel`（最终形态）

- [ ] **Step 1: 写调试脚本**

Create `debug/test_charts_render.py`:

```python
"""手工验证：用构造数据生成 PNG + xlsx，人工打开检查中文与图表效果。

运行：python debug/test_charts_render.py
产物：debug/output_charts/ 下的 query_N.png 与 result.xlsx
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import charts
import dquery

OUT = Path(__file__).parent / "output_charts"


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    datasets = {
        1: (  # 折线：日期 + 数值
            [{"日期": f"202607{d:02d}", "收入(美元)": str(d * 120.5), "付费人数": str(d * 3)}
             for d in range(1, 11)],
            "SELECT ds, money FROM raw_scribe_log.pay",
            "7 月上旬收入总体平稳，7 月 10 日达到峰值 1205 美元。",
        ),
        2: (  # 饼图：少类别 + 单数值
            [{"渠道": n, "充值金额": v} for n, v in
             [("AppStore", "5200"), ("GooglePlay", "3100"), ("官网", "1800"), ("其他", "600")]],
            "SELECT channel, money FROM gamelog_raw.v_presto_log_payrecharge",
            "AppStore 渠道贡献最大，占比约 48.6%。",
        ),
        3: (  # 柱状：多类别
            [{"道具": f"道具{i}", "获得数量": str(100 - i * 7)} for i in range(1, 13)],
            "SELECT item_name, cnt FROM gameeco_raw.v_presto_log_roleitem",
            "道具1 获得数量最高，长尾道具获取量较低。",
        ),
    }

    conclusions = []
    for i, (rows, sql, conclusion) in datasets.items():
        dquery.write_csv_to(rows, OUT / f"query_{i}.csv")
        (OUT / f"query_{i}.sql").write_text(sql, encoding="utf-8")
        conclusions.append(conclusion)

    pngs = charts.render_pngs_for_dir(str(OUT))
    print(f"生成 PNG: {pngs}")

    xlsx = dquery.combine_to_excel(
        str(OUT), conclusions=conclusions,
        final_summary="三个维度的分析显示：收入平稳、AppStore 为主要渠道、道具获取呈长尾分布。"
    )
    print(f"生成 xlsx: {xlsx}")
    print("请人工打开检查：中文显示、图表类型、结论位置。")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行调试脚本并人工检查**

Run: `python debug/test_charts_render.py`
Expected: 打印 3 个 PNG 路径和 1 个 xlsx 路径。人工打开 `debug/output_charts/result.xlsx` 确认：首个 sheet 是"总结"；每个数据 sheet 右侧有原生图表（折线/饼图/柱状）、表格下方有【结论】；PNG 中文不乱码。

- [ ] **Step 3: 全量测试与语法检查**

Run:
```bash
python -m py_compile app/*.py
python -m pytest tests/ -q
```
Expected: 编译无错误；全部测试通过。

- [ ] **Step 4: 检查暂存区无敏感配置**

Run: `git diff --cached --name-only | grep -i config`
Expected: 无输出。

- [ ] **Step 5: 提交**

```bash
git add debug/test_charts_render.py
git commit -m "test: 新增图表渲染手工验证脚本

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 6: 真实环境端到端验证（手动）**

向机器人发送一次真实查询（如 `39 昨天充值情况` 和一次分步复杂查询），确认：
1. 飞书聊天先收到图表图片，再收到文字结论，最后收到 result.xlsx；
2. xlsx 内图表原生可编辑、【结论】在表格下方、多步查询有"总结"sheet；
3. 固定报表（如 `kpi 近7天`）同样收到图+文字+xlsx。

---

## Self-Review 记录

- **Spec 覆盖**：图表双位置展示（Task 2/3/5）、自动判断（Task 1）、所有查询适用（Task 5 三个 handler + 报表两个分支）、xlsx 布局（Task 4）、错误降级（各任务 try/except + 测试）、依赖与 requirements（Task 2）、测试计划（各任务测试 + Task 6 手动验证）均已覆盖。
- **类型一致性**：`combine_to_excel(result_dir, conclusions, final_summary)` 在 Task 4 定义、Task 5 调用签名一致；`_run_planned*_body` 返回 `(summaries, final_summary)` 在 Task 5 定义与使用一致；`rows_to_xlsx(rows, summary, title, out_path)` 定义与调用一致。
- **已知取舍**：`charts._title_for` 与 `dquery._sheet_name` 有 6 行正则重复，为避免 dquery↔charts 循环导入而保留（charts.py 注释已说明）。
