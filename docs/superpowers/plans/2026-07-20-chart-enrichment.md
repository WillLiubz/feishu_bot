# 数仓分析后处理管线实现计划：中文名翻译 + 跨期对比图 + 图表增强

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在查询结果落盘（query_N.csv）与图表/文件发送之间插入后处理管线：代码层批量翻译 ID→中文名、多期对比合成图、Top-N+"其他"归并。

**Architecture:** 新增 `app/name_enrich.py`（复用 `configdb.query` 只读通道批量翻译并回写 CSV）；扩展 `app/charts.py`（`_slice_for_png` 改为 Top-N 归并 + 折线抽稀，新增 `render_comparison_png` / `render_comparison_for_dir`）；`app/bot.py` 三条查询路径接入（`_handle_simple` / `_planned_handler` 调翻译，`_send_charts` 优先合成对比图）。

**Tech Stack:** Python 3.12、matplotlib（Agg）、openpyxl、pymysql（经 configdb）、pytest。

**Spec:** `docs/superpowers/specs/2026-07-20-chart-enrichment-design.md`

## Global Constraints

- 所有文件 UTF-8 编码；测试文件首部 `sys.path.insert(0, str(Path(__file__).parent.parent / "app"))`。
- 不安装新依赖（用户全局规则）。
- 后处理任何失败**绝不向上抛**（与 `_send_charts` 现有 "Never raises" 风格一致），仅 `print(..., flush=True)` 日志。
- `configdb.query(cfg, sql, max_rows=500, *, database=None)` 自带只读护栏；`database=None` 时用 `cfg["database"]`（GM 运营库），翻译静态库表时传 `cfg.get("static_database")`。
- 提交信息中文，格式 `<type>: <描述>`，结尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`；不 push。
- 当前分支 `fix-game39-raw-scribe-tables`，直接在此分支提交。
- 每个 Task 完成后运行 `python -m pytest tests/ -q` 全量回归。

---

### Task 1: `app/name_enrich.py` — 中文名代码层翻译

**Files:**
- Create: `app/name_enrich.py`
- Test: `tests/test_name_enrich.py`

**Interfaces:**
- Consumes: `configdb.query(cfg, sql, database=...) -> list[dict]`；`game_config.game_id: int`、`game_config.config_db: dict`。
- Produces: `translate_dir(result_dir, game_config) -> int`（Task 4 的 bot.py 调用）；`translate_csv(csv_path, game_config) -> bool`；`_COLUMN_RULES: dict[int, list[dict]]`；`_cache: dict`（测试需清空）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_name_enrich.py`：

```python
import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import name_enrich


@pytest.fixture(autouse=True)
def _clear_cache():
    name_enrich._cache.clear()
    yield
    name_enrich._cache.clear()


def _gc(game_id=39, with_db=True):
    gc = MagicMock()
    gc.game_id = game_id
    gc.config_db = {"host": "h", "user": "u", "database": "gm_db",
                    "static_database": "static_db"} if with_db else {}
    return gc


def _write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_translate_39_item_id(monkeypatch, tmp_path):
    calls = []

    def fake_query(cfg, sql, max_rows=500, *, database=None):
        calls.append((sql, database))
        return [{"id": 10010, "name": "钻石礼包"}, {"id": 10011, "name": "金币箱"}]

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_1.csv"
    _write_csv(p, ["item_id", "数量"], [["10010", "5"], ["10011", "3"], ["10010", "2"]])
    assert name_enrich.translate_csv(str(p), _gc(39)) is True
    rows = _read_csv(p)
    assert list(rows[0].keys()) == ["item_id", "道具名称", "数量"]
    assert rows[0]["道具名称"] == "钻石礼包"
    assert rows[2]["道具名称"] == "钻石礼包"
    # 去重后一次 IN 查询，且走静态库
    assert len(calls) == 1
    assert "static_item" in calls[0][0] and "IN (10010, 10011)" in calls[0][0]
    assert calls[0][1] == "static_db"


def test_translate_39_activity_id_uses_gm_db(monkeypatch, tmp_path):
    calls = []

    def fake_query(cfg, sql, max_rows=500, *, database=None):
        calls.append((sql, database))
        return [{"id": 7, "name": "每日登陆"}]

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_1.csv"
    _write_csv(p, ["activity_id", "参与人数"], [["7", "100"]])
    assert name_enrich.translate_csv(str(p), _gc(39)) is True
    rows = _read_csv(p)
    assert rows[0]["活动名称"] == "每日登陆"
    assert "activity" in calls[0][0]
    assert calls[0][1] is None  # GM 运营库用默认 database


def test_translate_160_item_id_filters_game_id(monkeypatch, tmp_path):
    calls = []

    def fake_query(cfg, sql, max_rows=500, *, database=None):
        calls.append(sql)
        return [{"ident": "601229", "name": "屠龙刀"}]

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_1.csv"
    _write_csv(p, ["item_id", "数量"], [["601229", "1"]])
    assert name_enrich.translate_csv(str(p), _gc(160)) is True
    assert _read_csv(p)[0]["道具名称"] == "屠龙刀"
    assert "game_item" in calls[0] and "game_id = 160" in calls[0]
    assert "'601229'" in calls[0]  # 非纯数字 ID 加引号


def test_skip_when_name_column_exists(monkeypatch, tmp_path):
    def fake_query(cfg, sql, max_rows=500, *, database=None):
        raise AssertionError("不应查询配置库")

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_1.csv"
    _write_csv(p, ["item_id", "item_name", "数量"], [["1", "已有名", "5"]])
    assert name_enrich.translate_csv(str(p), _gc(312)) is False


def test_no_config_db_returns_false(tmp_path):
    p = tmp_path / "query_1.csv"
    _write_csv(p, ["item_id", "数量"], [["10010", "5"]])
    assert name_enrich.translate_csv(str(p), _gc(39, with_db=False)) is False


def test_query_failure_keeps_csv_unchanged(monkeypatch, tmp_path):
    def fake_query(cfg, sql, max_rows=500, *, database=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_1.csv"
    _write_csv(p, ["item_id", "数量"], [["10010", "5"]])
    assert name_enrich.translate_csv(str(p), _gc(39)) is False
    assert list(_read_csv(p)[0].keys()) == ["item_id", "数量"]


def test_translate_dir_only_touches_query_csvs(monkeypatch, tmp_path):
    def fake_query(cfg, sql, max_rows=500, *, database=None):
        return [{"id": 1, "name": "X"}]

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    _write_csv(tmp_path / "query_1.csv", ["item_id", "数量"], [["1", "5"]])
    _write_csv(tmp_path / "other.csv", ["item_id", "数量"], [["1", "5"]])
    n = name_enrich.translate_dir(str(tmp_path), _gc(39))
    assert n == 1
    assert "道具名称" in _read_csv(tmp_path / "query_1.csv")[0]
    assert "道具名称" not in _read_csv(tmp_path / "other.csv")[0]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_name_enrich.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'name_enrich'`）

- [ ] **Step 3: 实现 `app/name_enrich.py`**

```python
"""查询结果后处理：把 ID 列批量翻译成中文名。

在 query_N.csv 生成后、画图/合并 Excel 前调用：
- 按 game_id 的内置规则识别 ID 列（item_id / activity_id / id_name 等）
- 复用 configdb.query 批量 IN 查询静态配置库 / GM 运营库
- 中文名列插在 ID 列右侧；已存在同义名列时跳过
- 任何失败静默跳过（打印日志），绝不阻塞主流程
"""
import csv
from pathlib import Path

import configdb

_NAME_CANDIDATES = ("name", "title", "activity_name")

# 每个游戏的翻译规则：
#   cols:     CSV 中可能出现的 ID 列名（取第一个命中的）
#   db:       "static"=静态库(config_db.static_database) / "gm"=GM 运营库(config_db.database)
#   table:    配置表名
#   key:      表内主键列
#   where:    额外过滤条件（如 game_id = 160），无则 None
#   new_col:  插入的中文名列名
#   existing: 已存在这些列时跳过翻译（避免覆盖 roleitem 自带的 item_name 等）
_COLUMN_RULES = {
    39: [
        {"cols": ["item_id"], "db": "static", "table": "static_item", "key": "id",
         "where": None, "new_col": "道具名称", "existing": ("item_name", "道具名称")},
        {"cols": ["activity_id"], "db": "gm", "table": "activity", "key": "id",
         "where": None, "new_col": "活动名称", "existing": ("activity_name", "活动名称")},
    ],
    160: [
        {"cols": ["item_id", "ident"], "db": "gm", "table": "game_item", "key": "ident",
         "where": "game_id = 160", "new_col": "道具名称", "existing": ("item_name", "道具名称")},
        {"cols": ["id_name"], "db": "gm", "table": "game_resource", "key": "id_name",
         "where": "game_id = 160", "new_col": "资源名称", "existing": ("资源名称",)},
    ],
    312: [
        {"cols": ["item_id", "ident"], "db": "gm", "table": "game_item", "key": "ident",
         "where": "game_id = 312", "new_col": "道具名称", "existing": ("item_name", "道具名称")},
        {"cols": ["id_name"], "db": "gm", "table": "game_resource", "key": "id_name",
         "where": "game_id = 312", "new_col": "资源名称", "existing": ("资源名称",)},
    ],
}

# (game_id, table, id) -> 中文名；进程级缓存，避免同次会话重复查配置库
_cache = {}


def _quote(v):
    """纯数字不加引号，其余按字符串字面值转义。"""
    s = str(v).strip()
    if s.isdigit():
        return s
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _fetch_names(game_id, cfg, rule, ids):
    """批量查 id -> 中文名映射。Never raises."""
    table, key = rule["table"], rule["key"]
    ids = [str(i).strip() for i in ids if str(i).strip()]
    unique = list(dict.fromkeys(ids))
    missing = [i for i in unique if (game_id, table, i) not in _cache]
    if missing:
        where = f"{key} IN ({', '.join(_quote(i) for i in missing)})"
        if rule["where"]:
            where += f" AND {rule['where']}"
        sql = f"SELECT * FROM {table} WHERE {where}"
        database = cfg.get("static_database") if rule["db"] == "static" else None
        try:
            rows = configdb.query(cfg, sql, database=database)
        except Exception as e:
            print(f"[name_enrich] query {table} failed: {e}", flush=True)
            rows = []
        name_key = None
        if rows:
            cols = set(rows[0].keys())
            name_key = next((c for c in _NAME_CANDIDATES if c in cols), None)
        for row in rows:
            if name_key and key in row:
                _cache[(game_id, table, str(row[key]))] = str(row.get(name_key) or "")
        for i in missing:  # 未命中的 ID 缓存为空串，避免反复查
            _cache.setdefault((game_id, table, i), "")
    return {i: _cache.get((game_id, table, i), "") for i in unique}


def translate_csv(csv_path, game_config) -> bool:
    """翻译单个 CSV 的 ID 列（原地回写）。返回是否有改动。Never raises."""
    rules = _COLUMN_RULES.get(getattr(game_config, "game_id", None), [])
    cfg = getattr(game_config, "config_db", None) or {}
    if not rules or not cfg:
        return False
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
    except Exception as e:
        print(f"[name_enrich] read {csv_path} failed: {e}", flush=True)
        return False
    if not rows or not fieldnames:
        return False
    changed = False
    for rule in rules:
        col = next((c for c in rule["cols"] if c in fieldnames), None)
        if not col:
            continue
        if any(a in fieldnames for a in rule["existing"]):
            continue
        mapping = _fetch_names(game_config.game_id, cfg, rule, [r.get(col, "") for r in rows])
        if not any(mapping.values()):
            continue
        fieldnames.insert(fieldnames.index(col) + 1, rule["new_col"])
        for r in rows:
            r[rule["new_col"]] = mapping.get(str(r.get(col, "")).strip(), "")
        changed = True
    if not changed:
        return False
    try:
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    except Exception as e:
        print(f"[name_enrich] write {csv_path} failed: {e}", flush=True)
        return False
    return True


def translate_dir(result_dir, game_config) -> int:
    """翻译 result_dir 下所有 query_*.csv，返回改动文件数。Never raises."""
    n = 0
    try:
        for p in sorted(Path(result_dir).glob("query_*.csv")):
            try:
                if translate_csv(str(p), game_config):
                    n += 1
            except Exception as e:
                print(f"[name_enrich] translate {p} failed: {e}", flush=True)
    except Exception as e:
        print(f"[name_enrich] translate_dir failed: {e}", flush=True)
    return n
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_name_enrich.py -v`
Expected: 7 passed

- [ ] **Step 5: 全量回归 + 提交**

Run: `python -m pytest tests/ -q`
Expected: 全部通过

```bash
git add app/name_enrich.py tests/test_name_enrich.py
git commit -m "feat: 新增 name_enrich 查询结果 ID 列批量翻译中文名

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `charts.py` — Top-N+"其他"归并与折线抽稀

**Files:**
- Modify: `app/charts.py:22-25`（常量）、`app/charts.py:100-106`（`_slice_for_png`）
- Test: `tests/test_charts.py`（修改 `test_slice_for_png_limits`，新增归并/抽稀用例）

**Interfaces:**
- Consumes: 现有 `series_columns`、`to_float`。
- Produces: `_merge_other(rows, series, total_rows) -> list[dict]`、`_downsample(rows, max_points) -> list[dict]`；常量语义变化：`MAX_PIE_CATEGORIES=8`（含"其他"）、`MAX_BAR_ROWS_PNG=16`（Top-15+"其他"）。`render_png` / `render_pngs_for_dir` 签名不变（Task 3、bot.py 不受影响）。

- [ ] **Step 1: 改/写失败测试**

修改 `tests/test_charts.py` 中 `test_slice_for_png_limits` 并新增用例：

```python
def test_slice_for_png_limits():
    rows = [{"c": str(i), "v": str(i)} for i in range(100)]
    assert len(charts._slice_for_png(rows, "pie")) == charts.MAX_PIE_CATEGORIES
    assert len(charts._slice_for_png(rows, "line")) == charts.MAX_LINE_POINTS_PNG
    assert len(charts._slice_for_png(rows, "bar")) == charts.MAX_BAR_ROWS_PNG


def test_merge_other_pie_sums_remainder():
    rows = [{"渠道": f"ch{i}", "收入": str(100 - i)} for i in range(10)]
    out = charts._slice_for_png(rows, "pie")
    assert len(out) == charts.MAX_PIE_CATEGORIES  # Top-7 + 其他
    assert out[-1]["渠道"] == "其他"
    top_sum = sum(float(r["收入"]) for r in out[:-1])
    other = float(out[-1]["收入"])
    assert top_sum + other == sum(100 - i for i in range(10))
    # Top-N 按值降序
    assert float(out[0]["收入"]) >= float(out[1]["收入"])


def test_merge_other_bar_multi_series():
    rows = [{"渠道": f"ch{i}", "收入": str(i), "付费人数": "1"} for i in range(20)]
    out = charts._slice_for_png(rows, "bar")
    assert len(out) == charts.MAX_BAR_ROWS_PNG  # Top-15 + 其他
    assert out[-1]["渠道"] == "其他"
    # "其他"行对所有系列列求和
    assert float(out[-1]["收入"]) == sum(i for i in range(5))
    assert float(out[-1]["付费人数"]) == 5


def test_merge_other_keeps_order_when_under_limit():
    rows = [{"渠道": f"ch{i}", "收入": str(i)} for i in range(5)]
    out = charts._slice_for_png(rows, "bar")
    assert [r["渠道"] for r in out] == [f"ch{i}" for i in range(5)]  # 不排序


def test_downsample_keeps_first_and_last():
    rows = [{"ds": f"202607{i:02d}", "v": str(i)} for i in range(100)]
    out = charts._downsample(rows, 60)
    assert len(out) <= 60
    assert out[0]["ds"] == rows[0]["ds"]
    assert out[-1]["ds"] == rows[-1]["ds"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_charts.py -v`
Expected: 新增 4 个用例 FAIL（`_downsample` 不存在、归并逻辑未实现）；`test_slice_for_png_limits` 中 bar 断言 FAIL（当前上限 20，新常量 16）

- [ ] **Step 3: 实现**

修改 `app/charts.py`：

常量区（替换第 22-25 行）：

```python
MAX_PIE_CATEGORIES = 8       # 含"其他"：Top-7 + 其他
MAX_BAR_ROWS_PNG = 16        # 含"其他"：Top-15 + 其他
MAX_LINE_POINTS_PNG = 60     # 超出时均匀抽稀（保留首末点）
MAX_SERIES = 3
```

替换 `_slice_for_png`（第 100-106 行）为：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_charts.py -v`
Expected: 全部通过（含既有用例）

- [ ] **Step 5: 全量回归 + 提交**

Run: `python -m pytest tests/ -q`
Expected: 全部通过

```bash
git add app/charts.py tests/test_charts.py
git commit -m "feat: 图表 PNG 改为 Top-N+其他归并，折线超限均匀抽稀

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: `charts.py` — 跨期对比合成图

**Files:**
- Modify: `app/charts.py`（文件尾部追加）
- Test: `tests/test_charts.py`（追加用例）

**Interfaces:**
- Consumes: 现有 `series_columns` / `_first_col_is_date` / `to_float` / `MAX_BAR_ROWS_PNG` / `CHARTS_AVAILABLE` / `plt`。
- Produces:
  - `comparison_type(datasets: list[list[dict]]) -> "line" | "bar" | None`
  - `render_comparison_png(datasets, labels, title, out_path) -> str | None`
  - `render_comparison_for_dir(result_dir, labels, title="多期对比") -> list[str]`（Task 4 的 bot.py 调用）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_charts.py`：

```python
def _ds_rows(prefix, days, base=0):
    return [{"ds": f"2026{prefix}{d:02d}", "收入": str(base + d)} for d in days]


def test_comparison_type_none_for_single_dataset():
    assert charts.comparison_type([_ds_rows("05", [1, 2])]) is None


def test_comparison_type_none_for_mismatched_headers():
    a = [{"ds": "20260501", "收入": "1"}]
    b = [{"ds": "20260601", "付费人数": "2"}]
    assert charts.comparison_type([a, b]) is None


def test_comparison_type_line_when_all_first_cols_are_dates():
    datasets = [_ds_rows("05", [1, 2]), _ds_rows("06", [1, 2])]
    assert charts.comparison_type(datasets) == "line"


def test_comparison_type_bar_when_first_col_is_dimension():
    a = [{"渠道": "甲", "收入": "10"}, {"渠道": "乙", "收入": "20"}]
    b = [{"渠道": "甲", "收入": "30"}, {"渠道": "乙", "收入": "40"}]
    assert charts.comparison_type([a, b]) == "bar"


def test_render_comparison_png_line(tmp_path):
    if not charts.CHARTS_AVAILABLE:
        pytest.skip("matplotlib not installed")
    datasets = [_ds_rows("05", range(1, 6), base=100), _ds_rows("06", range(1, 6), base=200)]
    out = charts.render_comparison_png(datasets, ["5月", "6月"], "充值对比", tmp_path / "cmp.png")
    assert out and Path(out).exists() and Path(out).stat().st_size > 0


def test_render_comparison_png_bar(tmp_path):
    if not charts.CHARTS_AVAILABLE:
        pytest.skip("matplotlib not installed")
    a = [{"渠道": "甲", "收入": "10"}, {"渠道": "乙", "收入": "20"}]
    b = [{"渠道": "甲", "收入": "30"}, {"渠道": "丙", "收入": "40"}]  # 类目并集
    out = charts.render_comparison_png([a, b], ["5月", "6月"], "渠道对比", tmp_path / "cmp.png")
    assert out and Path(out).exists()


def test_render_comparison_png_none_when_incompatible(tmp_path):
    a = [{"ds": "20260501", "收入": "1"}]
    out = charts.render_comparison_png([a], ["5月"], "t", tmp_path / "cmp.png")
    assert out is None


def test_render_comparison_for_dir(tmp_path):
    if not charts.CHARTS_AVAILABLE:
        pytest.skip("matplotlib not installed")
    (tmp_path / "query_1.csv").write_text("ds,收入\n20260501,10\n20260502,20\n", encoding="utf-8-sig")
    (tmp_path / "query_2.csv").write_text("ds,收入\n20260601,30\n20260602,40\n", encoding="utf-8-sig")
    paths = charts.render_comparison_for_dir(str(tmp_path), ["5月", "6月"])
    assert len(paths) == 1 and paths[0].endswith("comparison.png")


def test_render_comparison_for_dir_fallback_when_incompatible(tmp_path):
    (tmp_path / "query_1.csv").write_text("ds,收入\n20260501,10\n", encoding="utf-8-sig")
    (tmp_path / "query_2.csv").write_text("渠道,收入\n甲,20\n", encoding="utf-8-sig")
    assert charts.render_comparison_for_dir(str(tmp_path), ["a", "b"]) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_charts.py -v -k comparison`
Expected: FAIL（`AttributeError: module 'charts' has no attribute 'comparison_type'`）

- [ ] **Step 3: 实现**

在 `app/charts.py` 文件尾部追加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_charts.py -v`
Expected: 全部通过

- [ ] **Step 5: 全量回归 + 提交**

Run: `python -m pytest tests/ -q`
Expected: 全部通过

```bash
git add app/charts.py tests/test_charts.py
git commit -m "feat: 新增跨期对比合成图（多线折线/分组柱状）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: `bot.py` 集成 — 翻译接入 + 对比图优先

**Files:**
- Modify: `app/bot.py:15`（import）、`app/bot.py:229-235`（`_send_charts`）、`app/bot.py:260-274`（`_handle_simple`）、`app/bot.py:299-307`（`_run_planned_body` 返回值）、`app/bot.py:320-336`（`_planned_handler`）
- Test: `tests/test_bot.py`（追加用例）

**Interfaces:**
- Consumes: `name_enrich.translate_dir(result_dir, game_config) -> int`（Task 1）；`charts.render_comparison_for_dir(result_dir, labels) -> list[str]`（Task 3）。
- Produces: `_send_charts(client, chat_id, result_dir, step_labels=None)`；`_run_planned_body(...) -> (summaries, final_summary, steps)`（返回值从 2 元组改为 3 元组，调用方仅 `_planned_handler`）。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_bot.py`：

```python
def test_send_charts_prefers_comparison_when_labels_given(tmp_path):
    client = MagicMock()
    with patch.object(bot.charts, "render_comparison_for_dir", return_value=["cmp.png"]) as mc, \
         patch.object(bot.charts, "render_pngs_for_dir") as ms, \
         patch.object(bot, "_send_image") as si:
        bot._send_charts(client, "chat1", str(tmp_path), step_labels=["5月", "6月"])
    mc.assert_called_once_with(str(tmp_path), ["5月", "6月"])
    ms.assert_not_called()
    si.assert_called_once_with(client, "chat1", "cmp.png")


def test_send_charts_falls_back_to_per_query_pngs(tmp_path):
    client = MagicMock()
    with patch.object(bot.charts, "render_comparison_for_dir", return_value=[]), \
         patch.object(bot.charts, "render_pngs_for_dir", return_value=["q1.png"]) as ms, \
         patch.object(bot, "_send_image") as si:
        bot._send_charts(client, "chat1", str(tmp_path), step_labels=["5月", "6月"])
    ms.assert_called_once_with(str(tmp_path))
    si.assert_called_once_with(client, "chat1", "q1.png")


def test_send_charts_without_labels_uses_per_query_pngs(tmp_path):
    client = MagicMock()
    with patch.object(bot.charts, "render_comparison_for_dir") as mc, \
         patch.object(bot.charts, "render_pngs_for_dir", return_value=[]) as ms:
        bot._send_charts(client, "chat1", str(tmp_path))
    mc.assert_not_called()
    ms.assert_called_once_with(str(tmp_path))


def test_run_planned_body_returns_steps(tmp_path):
    ws = {"result_dir": str(tmp_path)}
    plan = bot.query_planner.Plan(steps=[bot.query_planner.PlanStep("g1", "h1")])
    with patch.object(bot.query_planner, "plan", return_value=plan), \
         patch.object(bot.query_planner, "execute_step", return_value="s1"), \
         patch.object(bot.query_planner, "summarize", return_value="final"):
        summaries, final, steps = bot._run_planned_body(None, "chat", "msg", "text", ws)
    assert summaries == ["s1"] and final == "final"
    assert [s.goal for s in steps] == ["g1"]


def test_planned_handler_translates_and_passes_labels(tmp_path):
    ws = {"result_dir": str(tmp_path)}
    game_config = MagicMock()
    game_config.game_id = 39
    steps = [bot.query_planner.PlanStep("查5月充值", "h1"),
             bot.query_planner.PlanStep("查6月充值", "h2")]
    client = MagicMock()
    # _planned_handler 的 finally 会 release 信号量，先 acquire 模拟真实流程
    assert bot._query_sem.acquire(blocking=False)
    with patch.object(bot, "_send_text"), \
         patch.object(bot, "_send_query_summary"), \
         patch.object(bot, "_send_result_file"), \
         patch.object(bot.query_planner, "execute_step", side_effect=["s1", "s2"]), \
         patch.object(bot.query_planner, "summarize", return_value="final"), \
         patch.object(bot.name_enrich, "translate_dir", return_value=2) as mt, \
         patch.object(bot, "_send_charts") as msc, \
         patch.object(bot.store, "log_out"):
        bot._planned_handler(client, "chat", "user", "msg", "对比", [], game_config, ws, steps=steps)
    mt.assert_called_once_with(str(tmp_path), game_config)
    assert msc.call_args.kwargs.get("step_labels") == ["查5月充值", "查6月充值"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_bot.py -v -k "send_charts or planned"`
Expected: 新用例 FAIL（`render_comparison_for_dir` 参数未传递 / `_run_planned_body` 解包 3 元组报错 / `name_enrich` 未导入）；既有 `test_send_charts_never_raises`、`test_send_charts_sends_each_png`、`test_planned_body_returns_structured_summaries` 仍应通过

- [ ] **Step 3: 实现 `app/bot.py` 改动**

第 15 行 `import charts` 下方加一行：

```python
import name_enrich
```

替换 `_send_charts`（第 229-235 行）：

```python
def _send_charts(client, chat_id, result_dir, step_labels=None):
    """Render PNG charts and send as image messages. Never raises.

    带 step_labels（分步查询）时先尝试合成跨期对比图；
    结构不兼容时退回每期单图。
    """
    try:
        pngs = []
        if step_labels and len(step_labels) >= 2:
            pngs = charts.render_comparison_for_dir(result_dir, step_labels)
        if not pngs:
            pngs = charts.render_pngs_for_dir(result_dir)
        for png in pngs:
            _send_image(client, chat_id, png)
    except Exception as e:
        print(f"[bot] send charts failed: {e}", flush=True)
```

`_handle_simple`（第 267-271 行区域），在 `_send_charts` 前插入翻译：

```python
        answer, new_sid = claude_cli.run(text, ws, sid)
        store.set_session(chat_id, new_sid, game_config.game_id)
        name_enrich.translate_dir(ws["result_dir"], game_config)
        _send_charts(client, chat_id, ws["result_dir"])
```

`_run_planned_body`（第 299-307 行）返回值改为 3 元组：

```python
def _run_planned_body(client, chat_id, message_id, text, ws):
    """Plan first, then execute. Returns (summaries, final_summary, steps)."""
    plan_obj = query_planner.plan(text, ws)
    summaries = []
    for i, step in enumerate(plan_obj.steps, start=1):
        summary = query_planner.execute_step(step, i, len(plan_obj.steps), ws, summaries)
        summaries.append(summary)
    final_summary = query_planner.summarize(text, ws, summaries)
    return summaries, final_summary, plan_obj.steps
```

`_planned_handler`（第 320-336 行区域）：

```python
def _planned_handler(client, chat_id, user_id, message_id, text, opgames, game_config, ws, steps=None):
    """Process a complex query. If steps is provided, execute them directly; otherwise plan first."""
    t0 = time.time()
    try:
        _send_text(client, chat_id, "🔎 该问题较复杂，正在分步查询，请稍候…")
        if steps is not None:
            summaries, final_summary = _run_planned_with_steps_body(client, chat_id, message_id, text, ws, steps)
        else:
            summaries, final_summary, steps = _run_planned_body(client, chat_id, message_id, text, ws)
        step_labels = [s.goal for s in steps]
        answer = "\n".join(f"第{i}步：{s}" for i, s in enumerate(summaries, start=1)) + "\n\n【总结】\n" + final_summary
        name_enrich.translate_dir(ws["result_dir"], game_config)
        _send_charts(client, chat_id, ws["result_dir"], step_labels=step_labels)
        _send_text(client, chat_id, answer)
        _send_result_file(client, chat_id, ws["result_dir"],
                          conclusions=summaries, final_summary=final_summary)
        _send_query_summary(client, chat_id, message_id)
        latency = int((time.time() - t0) * 1000)
        store.log_out(chat_id, message_id, "ok", latency)
```

（函数其余 except/finally 分支保持不变。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_bot.py -v`
Expected: 全部通过

- [ ] **Step 5: 语法检查 + 全量回归 + 提交**

Run: `python -m py_compile app/*.py`
Run: `python -m pytest tests/ -q`
Expected: 无语法错误；全部通过

确认无敏感文件：

Run: `git diff --cached --name-only`
Expected: 仅 `app/bot.py`、`tests/test_bot.py`

```bash
git add app/bot.py tests/test_bot.py
git commit -m "feat: bot 接入查询后翻译与跨期对比图优先发送

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review 记录

- **Spec 覆盖**：模块 A（Task 1）、模块 B（Task 3 + Task 4 的 `_send_charts`/`_planned_handler` 接入）、模块 C（Task 2）均有对应 Task；`_handle_simple` 翻译接入在 Task 4；固定报表路径按 spec 维持现状不改。
- **类型一致性**：`translate_dir(result_dir, game_config)`、`render_comparison_for_dir(result_dir, labels)`、`_send_charts(..., step_labels=None)`、`_run_planned_body -> 3 元组` 在 Task 1/3/4 间签名一致。
- **无占位符**：所有代码步骤均含完整实现。
