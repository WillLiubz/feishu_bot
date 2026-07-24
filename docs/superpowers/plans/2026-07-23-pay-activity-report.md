# 312 付费构成与活动分析报表（pay_activity）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为游戏 312 新增固定报表 `pay_activity`：指定日期（默认昨日）的付费构成、付费用户美元分层、分层×活动参与的消耗/产出（道具名补全），并附 LLM 中文经营解读。

**Architecture:** 与 `player_segment` 同构的 SQL 模板（`app/templates/pay_activity.json`，7 个 Sheet）+ `templates.run_report` 执行 → `name_enrich` 道具名翻译（增强：中文表头兼容 + game_resource fallback）→ `report_insight` 调子 Claude 生成经营解读（失败只丢文字）→ `bot._handle_report` 发送 Excel。

**Tech Stack:** Python 3.12+ 标准库 + 现有 `dataapi` / `configdb` / `claude_cli` / pytest。无新依赖。

**Spec:** `docs/superpowers/specs/2026-07-23-pay-activity-report-design.md`

## Global Constraints

- 分支：`feat/pay-activity-report`（已创建，不要提交到 master）。
- 不安装新依赖；所有文件 UTF-8。
- 提交信息中文，格式 `<type>: <简短描述>`，结尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`。
- `config.json` 已 gitignore，**不得提交**；其修改为本地手工步骤。
- 每个任务完成后：`python -m py_compile app/*.py` + `python -m pytest tests/ -q` 全绿才提交。
- SQL 约束：列别名必须英文（数仓不支持中文别名）；数值字段 `COALESCE(TRY_CAST(... AS DOUBLE), 0)`；`role_id` 为 VARCHAR，字面值比较加引号；312 过滤 `game_id = 312`（gamelog_raw）/ `game_id = '{game_id_str}'`（gameeco_raw，兼容字符串/整数列，字面量可被隐式转换，列不被包装）。

---

### Task 1: rolepromo 实测探针脚本

模板 SQL 的 `item_spend`/`item_get` 炸开写法、`game_id` 类型、`role_type` 是否存在、`activity_topic` 实际取值，都依赖真实数据。先用探针脚本实测，结果决定 Task 4 的最终 SQL。

**Files:**
- Create: `debug/probe_rolepromo_312.py`

**Interfaces:**
- Consumes: `dataapi.run_sql_rows(sql, max_rows=N)`（现有）。
- Produces: 终端打印的实测结论（供 Task 4 人工核对；不产出代码接口）。

- [ ] **Step 1: 写探针脚本**

```python
"""探针：实测 312 rolepromo 表，为 pay_activity 模板提供口径依据。

用法：python debug/probe_rolepromo_312.py [yyyymmdd]  （默认昨天）
需要本机 config.json 已配置可用的 data_api。
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import dataapi

DS = sys.argv[1] if len(sys.argv) > 1 else (date.today() - timedelta(days=1)).strftime("%Y%m%d")


def probe(title, sql, max_rows=20):
    print(f"\n=== {title} ===")
    try:
        rows = dataapi.run_sql_rows(sql, max_rows=max_rows)
        if not rows:
            print("(no rows)")
        for r in rows:
            print(r)
    except Exception as e:
        print(f"ERROR: {e}")


probe(
    "1. game_id 列类型",
    "SELECT typeof(game_id) AS t FROM gameeco_raw.v_presto_log_rolepromo "
    f"WHERE ds = '{DS}' LIMIT 1",
)
probe(
    "2. role_type 列是否存在",
    "SELECT typeof(role_type) AS t FROM gameeco_raw.v_presto_log_rolepromo "
    f"WHERE ds = '{DS}' LIMIT 1",
)
probe(
    "3. item_spend / item_get 样例",
    "SELECT activity_topic, item_spend, item_get "
    "FROM gameeco_raw.v_presto_log_rolepromo "
    f"WHERE game_id = '312' AND ds = '{DS}' "
    "AND item_spend IS NOT NULL AND item_spend <> '' LIMIT 10",
)
probe(
    "4. 当日 activity_topic 分布（对照运营日历）",
    "SELECT activity_topic, activity_special, activity_pay, COUNT(*) AS cnt "
    "FROM gameeco_raw.v_presto_log_rolepromo "
    f"WHERE game_id = '312' AND ds = '{DS}' "
    "GROUP BY activity_topic, activity_special, activity_pay ORDER BY cnt DESC",
    max_rows=100,
)
probe(
    "5. role_id 列类型（JOIN 键确认）",
    "SELECT typeof(role_id) AS t FROM gameeco_raw.v_presto_log_rolepromo "
    f"WHERE ds = '{DS}' LIMIT 1",
)
```

- [ ] **Step 2: 运行探针并记录结论**

Run: `python debug/probe_rolepromo_312.py`
Expected: 5 段输出。记录：① `game_id` 是 varchar 还是 bigint；② `role_type` 是否存在（ERROR 即不存在）；③ `item_spend`/`item_get` 分隔符格式（本计划 Task 4 假设 `id:num;id:num`，若不同必须调整炸开 SQL）；④ 当日活动主题清单；⑤ `role_id` 类型（应为 varchar）。

- [ ] **Step 3: Commit**

```bash
git add debug/probe_rolepromo_312.py
git commit -m "test: 新增312 rolepromo实测探针脚本

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: templates.run_report summary 模板化

`run_report` 的 summary 当前硬编码"【玩家分群分析】…沉默窗口…"，pay_activity 需要自己的文案。把 summary 改为模板 JSON 驱动，同时把 `tempfile.mkdtemp` 前缀参数化。player_segment 输出保持不变。

**Files:**
- Modify: `app/templates/__init__.py:159-213`（`run_report`）
- Modify: `app/templates/player_segment.json`（顶部加 `summary_template`）
- Test: `tests/test_player_segment_templates.py`

**Interfaces:**
- Consumes: 模板 JSON 顶层新增可选键 `summary_template`（支持 `{game_id}` `{analysis_start}` `{analysis_end}` `{silent_start}` `{silent_end}` `{template_name}` 占位符）。
- Produces: `templates.run_report(template_name, question, game_config) -> (summary, result_dir)`（签名不变）；result_dir 前缀变为 `<template_name>_`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_player_segment_templates.py` 末尾追加：

```python
def test_run_report_summary_and_dir_prefix(monkeypatch, tmp_path):
    """run_report 的 summary 由模板 summary_template 驱动，目录前缀=模板名。"""
    monkeypatch.setattr(templates.dataapi, "run_sql_rows", lambda sql, max_rows=None: [])
    summary, result_dir = templates.run_report(
        "player_segment", "近7天玩家分群", _GameConfig(312)
    )
    assert "【玩家分群分析】游戏 312" in summary
    assert "分析窗口" in summary and "沉默窗口" in summary
    assert "共 6 个 Sheet" in summary
    assert result_dir.split("/")[-1].split("\\")[-1].startswith("player_segment_")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_player_segment_templates.py::test_run_report_summary_and_dir_prefix -v`
Expected: FAIL（当前 summary 不含"【玩家分群分析】游戏 312，分析窗口…沉默窗口…"由模板驱动 —— 实际失败点：目录前缀当前已是 `player_segment_` 但 summary 依赖硬编码；此测试在当前代码下 summary 断言会过、目录断言也会过，因此需把断言写严：确认 summary 来自模板字段。若意外全过，则改断言为 monkeypatch 一个**新模板**验证驱动能力，见 Step 3 后的补充测试。）

> 说明：该测试主要防止回归。真正驱动"先失败"的是 pay_activity 场景（Task 4 的 `test_run_report_pay_activity_summary`），此处先落 player_segment 的回归保护。

- [ ] **Step 3: 实现**

`app/templates/player_segment.json` 顶部（`"description"` 之后）加：

```json
  "summary_template": "【玩家分群分析】游戏 {game_id}，分析窗口 {analysis_start}~{analysis_end}，沉默窗口 {silent_start}~{silent_end}",
```

`app/templates/__init__.py` 中 `run_report` 的两处改动：

```python
    result_dir = Path(tempfile.mkdtemp(prefix=f"{template_name}_"))
```

以及文件末尾 summary 生成替换为：

```python
    fmt = {**params, "template_name": template_name, "game_id": game_config.game_id}
    summary_template = template.get(
        "summary_template",
        "【{template_name}】游戏 {game_id}，分析窗口 {analysis_start}~{analysis_end}",
    )
    summary = summary_template.format(**fmt) + (
        f"\n共 {len(sheet_names)} 个 Sheet：{', '.join(sheet_names)}"
    )
    return summary, str(result_dir)
```

（删除原 `import tempfile` 位置的硬编码 prefix 与末尾硬编码 summary；`import tempfile` 保留在函数内原处。）

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_player_segment_templates.py -v`
Expected: 全部 PASS（含新回归测试）。

- [ ] **Step 5: Commit**

```bash
git add app/templates/__init__.py app/templates/player_segment.json tests/test_player_segment_templates.py
git commit -m "refactor: run_report摘要改为模板summary_template驱动,目录前缀随模板名

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: name_enrich 中文表头兼容 + game_resource fallback

模板写 CSV 前列头已映射为中文，312 的 `item_id` 规则匹配不到"道具ID"；活动消耗还会混入资源 ID（钻石/体力），`game_item` 查不到需 fallback `game_resource`。

**Files:**
- Modify: `app/name_enrich.py`（`_COLUMN_RULES[312]` + `translate_csv`）
- Test: `tests/test_name_enrich.py`

**Interfaces:**
- Consumes: 规则字典新增可选键 `fallback`（结构与规则相同的子集：`db`/`table`/`key`/`where`/`quote`）。
- Produces: `translate_csv(csv_path, game_config) -> bool`（签名不变）；312 规则 `cols` 增加 `"道具ID"`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_name_enrich.py` 末尾追加：

```python
def test_translate_312_chinese_header(monkeypatch, tmp_path):
    calls = []

    def fake_query(cfg, sql, max_rows=500, *, database=None):
        calls.append(sql)
        return [{"ident": "2014003", "name": "屠龙刀"}]

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_5.csv"
    _write_csv(p, ["分层", "道具ID", "数量"], [["<$10", "2014003", "5"]])
    assert name_enrich.translate_csv(str(p), _gc(312)) is True
    rows = _read_csv(p)
    assert list(rows[0].keys()) == ["分层", "道具ID", "道具名称", "数量"]
    assert rows[0]["道具名称"] == "屠龙刀"
    assert "game_item" in calls[0] and "game_id = 312" in calls[0]


def test_translate_312_fallback_game_resource(monkeypatch, tmp_path):
    calls = []

    def fake_query(cfg, sql, max_rows=500, *, database=None):
        calls.append(sql)
        if "game_item" in sql:
            return []  # 道具表未命中
        return [{"id_name": "261", "name": "钻石"}]

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_6.csv"
    _write_csv(p, ["item_id", "amount"], [["261", "100"]])
    assert name_enrich.translate_csv(str(p), _gc(312)) is True
    rows = _read_csv(p)
    assert rows[0]["道具名称"] == "钻石"
    assert any("game_resource" in s and "id_name" in s for s in calls)


def test_translate_312_fallback_failure_silent(monkeypatch, tmp_path):
    def fake_query(cfg, sql, max_rows=500, *, database=None):
        if "game_resource" in sql:
            raise RuntimeError("db down")
        return []

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_6.csv"
    _write_csv(p, ["item_id", "amount"], [["999", "1"]])
    # 不抛异常；主表与 fallback 都未命中时无改动
    assert name_enrich.translate_csv(str(p), _gc(312)) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_name_enrich.py -v`
Expected: 3 个新测试 FAIL（中文表头未命中 / 无 fallback）。

- [ ] **Step 3: 实现**

`app/name_enrich.py` 的 `_COLUMN_RULES[312]` 第一条规则改为（注意 `cols` 加 `"道具ID"`、新增 `fallback` 键）：

```python
    312: [
        {"cols": ["item_id", "ident", "道具ID"], "db": "gm", "table": "game_item", "key": "ident",
         "where": "game_id = 312", "new_col": "道具名称", "existing": ("item_name", "道具名称"),
         "quote": True,
         "fallback": {"db": "gm", "table": "game_resource", "key": "id_name",
                      "where": "game_id = 312", "quote": True}},
        {"cols": ["id_name"], "db": "gm", "table": "game_resource", "key": "id_name",
         "where": "game_id = 312", "new_col": "资源名称", "existing": ("资源名称",),
         "quote": True},
    ],
```

`translate_csv` 中 `mapping = _fetch_names(...)` 之后插入 fallback 逻辑：

```python
        mapping = _fetch_names(game_config.game_id, cfg, rule, [r.get(col, "") for r in rows])
        fb = rule.get("fallback")
        if fb:
            missing_ids = [i for i, n in mapping.items() if not n]
            if missing_ids:
                fb_map = _fetch_names(game_config.game_id, cfg, fb, missing_ids)
                mapping.update({k: v for k, v in fb_map.items() if v})
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_name_enrich.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/name_enrich.py tests/test_name_enrich.py
git commit -m "feat: name_enrich支持中文表头道具ID与game_resource资源名fallback

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: pay_activity 模板 JSON + 模板测试

核心交付物。7 个 Sheet 的完整 SQL 如下。**口径已按 Task 1 探针 + 用户裁决修订**：rolepromo 的 `item_spend`/`item_get` 恒空（源码硬编码），活动 Sheet 只统计参与；消耗/产出走 `roleitem`（varchar 列必须显式 `CAST(... AS BIGINT)`）；`activity_topic` 用 `json_extract_scalar(..., '$.cn')` 取中文名。

**Files:**
- Create: `app/templates/pay_activity.json`
- Test: `tests/test_pay_activity_templates.py`

**Interfaces:**
- Consumes: `templates.compute_params` 占位符 `{game_id}` `{game_id_str}` `{analysis_start}` `{analysis_end}` `{server_filter}`；Task 2 的 `summary_template`。
- Produces: 模板 `games.312` 的 7 个 Sheet，键固定为 `overview` / `pay_composition` / `pay_tiers` / `payer_segments` / `segment_activity` / `activity_overview` / `segment_item_flow`（Task 5/6/7 依赖此顺序与命名）。

- [ ] **Step 1: 写失败测试**

Create `tests/test_pay_activity_templates.py`：

```python
"""Tests for the pay_activity SQL template."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import templates


class _GameConfig:
    def __init__(self, game_id):
        self.game_id = game_id


@pytest.fixture
def template():
    return templates.load_template("pay_activity")


def test_default_window_is_single_day(template):
    """付费构成默认分析单日（昨天）。"""
    params = templates.compute_params("付费构成", _GameConfig(312), template["default_params"])
    assert params["analysis_start"] == params["analysis_end"]


def test_all_placeholders_replaced(template):
    params = templates.compute_params("昨天付费构成", _GameConfig(312), template["default_params"])
    for key, sheet in template["games"]["312"].items():
        sql = templates.render_sql(sheet["sql"], params)
        assert "{" not in sql, f"sheet={key} has unreplaced placeholders"


def test_all_sheets_have_game_filter(template):
    for key, sheet in template["games"]["312"].items():
        assert "game_id" in sheet["sql"], f"sheet={key} missing game_id filter"


def test_segment_boundaries(template):
    """9 档美元分层边界与用户确认口径一致。"""
    sql = template["games"]["312"]["payer_segments"]["sql"]
    for frag in [
        "WHEN total < 10 THEN 1", "WHEN total < 20 THEN 2", "WHEN total < 40 THEN 3",
        "WHEN total < 80 THEN 4", "WHEN total < 100 THEN 5", "WHEN total < 150 THEN 6",
        "WHEN total < 200 THEN 7", "WHEN total < 300 THEN 8", "ELSE 9",
        "'<$10'", "'$10~20'", "'$20~40'", "'$40~80'", "'$80~100'",
        "'$100~150'", "'$150~200'", "'$200~300'", "'>=$300'",
    ]:
        assert frag in sql


def test_direct_purchase_split(template):
    """直购按 pay_itemid 的 actId:giftId 识别。"""
    sql = template["games"]["312"]["pay_composition"]["sql"]
    assert "strpos(pay_itemid, ':') > 0" in sql
    assert "split_part(pay_itemid, ':', 1)" in sql


def test_activity_sheets_use_rolepromo_cn_topic(template):
    """活动 Sheet 用 rolepromo 参与记录，主题取多语言 JSON 的 cn 字段。"""
    for key in ("segment_activity", "activity_overview"):
        sql = template["games"]["312"][key]["sql"]
        assert "rolepromo" in sql
        assert "json_extract_scalar" in sql and "'$.cn'" in sql


def test_item_flow_sheet_uses_explicit_cast(template):
    """道具产销 Sheet 走 roleitem，varchar 数值列必须显式 CAST。"""
    sql = template["games"]["312"]["segment_item_flow"]["sql"]
    assert "v_presto_log_roleitem" in sql
    assert "CAST(r.status_after AS BIGINT)" in sql
    assert "CAST(r.status_before AS BIGINT)" in sql
    assert "change_type" in sql


def test_run_report_pay_activity_summary(monkeypatch, template):
    monkeypatch.setattr(templates.dataapi, "run_sql_rows", lambda sql, max_rows=None: [])
    summary, result_dir = templates.run_report("pay_activity", "昨天付费构成", _GameConfig(312))
    assert "【付费构成与活动分析】游戏 312" in summary
    assert "共 7 个 Sheet" in summary
    assert result_dir.split("/")[-1].split("\\")[-1].startswith("pay_activity_")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_pay_activity_templates.py -v`
Expected: FAIL（`load_template` 找不到 pay_activity.json）。

- [ ] **Step 3: 写模板 JSON**

Create `app/templates/pay_activity.json`：

```json
{
  "name": "pay_activity",
  "description": "312付费构成与活动分析：付费概览、普通充值vs直购、充值档位、美元分层、分层×活动参与、活动总览、分层×道具产销",
  "summary_template": "【付费构成与活动分析】游戏 {game_id}，分析窗口 {analysis_start}~{analysis_end}",
  "default_params": {
    "analysis_window_days": 1
  },
  "games": {
    "312": {
      "overview": {
        "name": "付费概览",
        "max_rows": 10,
        "sql": "WITH pay AS (\n  SELECT COUNT(DISTINCT role_id) AS payer_count,\n         COUNT(*) AS pay_times,\n         SUM(COALESCE(TRY_CAST(pay_money AS DOUBLE), 0)) AS revenue\n  FROM gamelog_raw.v_presto_log_payrecharge\n  WHERE game_id = {game_id}\n    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'\n    {server_filter}\n),\ndau AS (\n  SELECT COUNT(DISTINCT role_id) AS dau\n  FROM gamelog_raw.v_presto_log_rolelogin\n  WHERE game_id = {game_id}\n    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'\n    {server_filter}\n)\nSELECT\n  d.dau,\n  p.payer_count,\n  ROUND(p.revenue, 2) AS revenue_usd,\n  p.pay_times,\n  ROUND(CAST(p.payer_count AS DOUBLE) / NULLIF(d.dau, 0) * 100, 2) AS pay_rate_pct,\n  ROUND(p.revenue / NULLIF(p.payer_count, 0), 2) AS arppu,\n  ROUND(CAST(p.pay_times AS DOUBLE) / NULLIF(p.payer_count, 0), 2) AS avg_pay_times\nFROM pay p CROSS JOIN dau d",
        "columns": {
          "dau": "DAU",
          "payer_count": "付费人数",
          "revenue_usd": "收入(USD)",
          "pay_times": "付费次数",
          "pay_rate_pct": "付费率(%)",
          "arppu": "ARPPU",
          "avg_pay_times": "人均付费次数"
        }
      },
      "pay_composition": {
        "name": "付费构成",
        "max_rows": 100,
        "sql": "SELECT\n  CASE WHEN strpos(pay_itemid, ':') > 0 THEN '直购' ELSE '普通充值' END AS pay_kind,\n  CASE WHEN strpos(pay_itemid, ':') > 0 THEN split_part(pay_itemid, ':', 1) ELSE '' END AS act_id,\n  COUNT(DISTINCT role_id) AS payer_count,\n  COUNT(*) AS pay_times,\n  ROUND(SUM(COALESCE(TRY_CAST(pay_money AS DOUBLE), 0)), 2) AS pay_amount,\n  ROUND(SUM(COALESCE(TRY_CAST(pay_money AS DOUBLE), 0)) * 100.0\n        / NULLIF(SUM(SUM(COALESCE(TRY_CAST(pay_money AS DOUBLE), 0))) OVER (), 0), 2) AS amount_pct\nFROM gamelog_raw.v_presto_log_payrecharge\nWHERE game_id = {game_id}\n  AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'\n  {server_filter}\nGROUP BY 1, 2\nORDER BY pay_amount DESC",
        "columns": {
          "pay_kind": "充值类型",
          "act_id": "直购活动",
          "payer_count": "付费人数",
          "pay_times": "付费次数",
          "pay_amount": "金额(USD)",
          "amount_pct": "金额占比(%)"
        },
        "value_map": {
          "act_id": {
            "14": "14-新手直购",
            "13": "13-新月卡",
            "9": "9-天使通行证",
            "7": "7-商店",
            "8": "8-商店"
          }
        }
      },
      "pay_tiers": {
        "name": "充值档位分布",
        "max_rows": 20,
        "sql": "WITH t AS (\n  SELECT role_id, COALESCE(TRY_CAST(pay_money AS DOUBLE), 0) AS amt\n  FROM gamelog_raw.v_presto_log_payrecharge\n  WHERE game_id = {game_id}\n    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'\n    {server_filter}\n)\nSELECT\n  CASE\n    WHEN amt < 1 THEN '<$1'\n    WHEN amt < 5 THEN '$1~5'\n    WHEN amt < 10 THEN '$5~10'\n    WHEN amt < 20 THEN '$10~20'\n    WHEN amt < 50 THEN '$20~50'\n    WHEN amt < 100 THEN '$50~100'\n    ELSE '>=$100'\n  END AS price_tier,\n  COUNT(*) AS pay_times,\n  COUNT(DISTINCT role_id) AS payer_count,\n  ROUND(SUM(amt), 2) AS pay_amount\nFROM t\nGROUP BY 1\nORDER BY MIN(amt)",
        "columns": {
          "price_tier": "单笔档位",
          "pay_times": "笔数",
          "payer_count": "付费人数",
          "pay_amount": "金额(USD)"
        }
      },
      "payer_segments": {
        "name": "付费用户分层",
        "max_rows": 20,
        "sql": "WITH per_role AS (\n  SELECT role_id, SUM(COALESCE(TRY_CAST(pay_money AS DOUBLE), 0)) AS total\n  FROM gamelog_raw.v_presto_log_payrecharge\n  WHERE game_id = {game_id}\n    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'\n    {server_filter}\n  GROUP BY role_id\n),\nseg AS (\n  SELECT\n    CASE\n      WHEN total < 10 THEN 1 WHEN total < 20 THEN 2 WHEN total < 40 THEN 3\n      WHEN total < 80 THEN 4 WHEN total < 100 THEN 5 WHEN total < 150 THEN 6\n      WHEN total < 200 THEN 7 WHEN total < 300 THEN 8 ELSE 9\n    END AS seg_no,\n    total\n  FROM per_role\n)\nSELECT\n  seg_no,\n  CASE seg_no\n    WHEN 1 THEN '<$10' WHEN 2 THEN '$10~20' WHEN 3 THEN '$20~40'\n    WHEN 4 THEN '$40~80' WHEN 5 THEN '$80~100' WHEN 6 THEN '$100~150'\n    WHEN 7 THEN '$150~200' WHEN 8 THEN '$200~300' ELSE '>=$300'\n  END AS segment,\n  COUNT(*) AS user_count,\n  ROUND(SUM(total), 2) AS pay_amount,\n  ROUND(SUM(total) * 100.0 / NULLIF(SUM(SUM(total)) OVER (), 0), 2) AS amount_pct,\n  ROUND(SUM(total) / COUNT(*), 2) AS arppu\nFROM seg\nGROUP BY seg_no\nORDER BY seg_no",
        "columns": {
          "seg_no": "分层编号",
          "segment": "分层",
          "user_count": "人数",
          "pay_amount": "金额(USD)",
          "amount_pct": "金额占比(%)",
          "arppu": "层内ARPPU"
        }
      },
      "segment_activity": {
        "name": "分层×活动参与",
        "max_rows": 1000,
        "sql": "WITH per_role AS (\n  SELECT role_id, SUM(COALESCE(TRY_CAST(pay_money AS DOUBLE), 0)) AS total\n  FROM gamelog_raw.v_presto_log_payrecharge\n  WHERE game_id = {game_id}\n    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'\n    {server_filter}\n  GROUP BY role_id\n),\nseg AS (\n  SELECT role_id,\n    CASE\n      WHEN total < 10 THEN 1 WHEN total < 20 THEN 2 WHEN total < 40 THEN 3\n      WHEN total < 80 THEN 4 WHEN total < 100 THEN 5 WHEN total < 150 THEN 6\n      WHEN total < 200 THEN 7 WHEN total < 300 THEN 8 ELSE 9\n    END AS seg_no\n  FROM per_role\n),\npromo AS (\n  SELECT COALESCE(json_extract_scalar(activity_topic, '$.cn'), activity_topic) AS topic_cn,\n         role_id\n  FROM gameeco_raw.v_presto_log_rolepromo\n  WHERE game_id = '{game_id_str}'\n    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'\n    AND role_type = 1\n    {server_filter}\n)\nSELECT\n  s.seg_no,\n  CASE s.seg_no\n    WHEN 1 THEN '<$10' WHEN 2 THEN '$10~20' WHEN 3 THEN '$20~40'\n    WHEN 4 THEN '$40~80' WHEN 5 THEN '$80~100' WHEN 6 THEN '$100~150'\n    WHEN 7 THEN '$150~200' WHEN 8 THEN '$200~300' ELSE '>=$300'\n  END AS segment,\n  p.topic_cn AS activity_topic,\n  COUNT(DISTINCT p.role_id) AS user_count,\n  COUNT(*) AS event_count\nFROM promo p\nJOIN seg s ON p.role_id = s.role_id\nGROUP BY s.seg_no, p.topic_cn\nORDER BY s.seg_no, user_count DESC",
        "columns": {
          "seg_no": "分层编号",
          "segment": "分层",
          "activity_topic": "活动主题",
          "user_count": "参与人数",
          "event_count": "参与次数"
        }
      },
      "activity_overview": {
        "name": "活动总览",
        "max_rows": 200,
        "sql": "SELECT\n  COALESCE(json_extract_scalar(activity_topic, '$.cn'), activity_topic) AS activity_topic,\n  COUNT(DISTINCT role_id) AS user_count,\n  COUNT(*) AS event_count\nFROM gameeco_raw.v_presto_log_rolepromo\nWHERE game_id = '{game_id_str}'\n  AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'\n  AND role_type = 1\n  {server_filter}\nGROUP BY COALESCE(json_extract_scalar(activity_topic, '$.cn'), activity_topic)\nORDER BY user_count DESC\nLIMIT 100",
        "columns": {
          "activity_topic": "活动主题",
          "user_count": "参与人数",
          "event_count": "参与次数"
        }
      },
      "segment_item_flow": {
        "name": "分层×道具产销",
        "max_rows": 5000,
        "sql": "WITH per_role AS (\n  SELECT role_id, SUM(COALESCE(TRY_CAST(pay_money AS DOUBLE), 0)) AS total\n  FROM gamelog_raw.v_presto_log_payrecharge\n  WHERE game_id = {game_id}\n    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'\n    {server_filter}\n  GROUP BY role_id\n),\nseg AS (\n  SELECT role_id,\n    CASE\n      WHEN total < 10 THEN 1 WHEN total < 20 THEN 2 WHEN total < 40 THEN 3\n      WHEN total < 80 THEN 4 WHEN total < 100 THEN 5 WHEN total < 150 THEN 6\n      WHEN total < 200 THEN 7 WHEN total < 300 THEN 8 ELSE 9\n    END AS seg_no\n  FROM per_role\n)\nSELECT\n  s.seg_no,\n  CASE s.seg_no\n    WHEN 1 THEN '<$10' WHEN 2 THEN '$10~20' WHEN 3 THEN '$20~40'\n    WHEN 4 THEN '$40~80' WHEN 5 THEN '$80~100' WHEN 6 THEN '$100~150'\n    WHEN 7 THEN '$150~200' WHEN 8 THEN '$200~300' ELSE '>=$300'\n  END AS segment,\n  CASE r.change_type WHEN '1' THEN '产出' WHEN '2' THEN '消耗' ELSE r.change_type END AS direction,\n  r.item_id,\n  r.item_name,\n  COUNT(DISTINCT r.role_id) AS user_count,\n  COUNT(*) AS event_count,\n  SUM(ABS(CAST(r.status_after AS BIGINT) - CAST(r.status_before AS BIGINT))) AS amount\nFROM gameeco_raw.v_presto_log_roleitem r\nJOIN seg s ON r.role_id = s.role_id\nWHERE r.game_id = '{game_id_str}'\n  AND r.ds BETWEEN '{analysis_start}' AND '{analysis_end}'\n  AND r.role_type = 1\n  AND SUBSTR(CAST(r.server_id AS VARCHAR), 5, 1) != '4'\nGROUP BY s.seg_no, r.change_type, r.item_id, r.item_name\nORDER BY s.seg_no, direction, amount DESC",
        "columns": {
          "seg_no": "分层编号",
          "segment": "分层",
          "direction": "方向",
          "item_id": "道具ID",
          "item_name": "道具名称",
          "user_count": "涉及人数",
          "event_count": "变动次数",
          "amount": "数量"
        }
      }
    }
  }
}
```

> 注意：
> - `segment_item_flow` 的 `{server_filter}` 只出现在 `per_role` CTE（payrecharge 侧）中；roleitem 侧测试服过滤必须写成带 `r.` 前缀的字面条件（JOIN 后不带前缀的 `server_id` 会歧义报错），这是有意为之，不要替换成占位符。
> - `roleitem` 单日约 1600 万行；`status_before`/`status_after`/`change_type` 均为 varchar，聚合必须显式 `CAST(... AS BIGINT)`（隐式算术实测 6 分钟跑不完，显式 CAST 约 5 秒），不要"简化"掉 CAST。
> - 冒烟时若 `role_type`/`server_id` 列在 roleitem 上报不存在，按探针实测修正（rolepromo 的 `role_type` 已确认为 integer 存在）。


---

### Task 5: reports 分支 + 触发词

**Files:**
- Modify: `app/reports.py`（`pay_activity_report` + `run` 分支）
- Modify: `config.json`（本地，不提交）
- Test: `tests/test_pay_activity_templates.py`（追加 match 测试）

**Interfaces:**
- Consumes: `templates.run_report("pay_activity", ...)`（Task 2/4）。
- Produces: `reports.pay_activity_report(question, game_config=None) -> (summary, result_dir)`；`reports.run("pay_activity", ...)`；`reports.match` 命中新触发词。

- [ ] **Step 1: 写失败测试**

在 `tests/test_pay_activity_templates.py` 末尾追加：

```python
def test_match_pay_activity_trigger(monkeypatch):
    import config
    import reports

    monkeypatch.setattr(config, "REPORT_TRIGGERS", {
        "player_segment": ["玩家分群", "付费点分析"],
        "pay_activity": ["付费构成", "活动付费分析", "付费活动分析", "付费分层"],
    })
    assert reports.match("312昨日付费构成") == "pay_activity"
    assert reports.match("看一下付费分层情况") == "pay_activity"
    assert reports.match("付费点分析") == "player_segment"


def test_run_dispatch_pay_activity(monkeypatch):
    import reports

    monkeypatch.setattr(
        reports.templates, "run_report",
        lambda name, q, game_config=None: (f"summary:{name}", "/tmp/x"),
    )
    summary, result_dir = reports.run("pay_activity", "付费构成", game_config=_GameConfig(312))
    assert summary == "summary:pay_activity"
    assert result_dir == "/tmp/x"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_pay_activity_templates.py::test_match_pay_activity_trigger tests/test_pay_activity_templates.py::test_run_dispatch_pay_activity -v`
Expected: FAIL（`run` 抛出"未知报表类型: pay_activity"）。

- [ ] **Step 3: 实现**

`app/reports.py` 在 `player_segment_report` 之后新增：

```python
def pay_activity_report(question, game_config=None):
    """Run pay composition & activity analysis report. Returns (summary, result_dir)."""
    if game_config is None:
        game_config = config.game_config()
    return templates.run_report("pay_activity", question, game_config=game_config)
```

`run()` 中 `player_segment` 分支后新增：

```python
    if report_type == "pay_activity":
        return pay_activity_report(question, game_config=game_config)
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_pay_activity_templates.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 修改本地 config.json（不提交）**

`config.json` 的 `report_triggers` 中追加一行：

```json
    "pay_activity": ["付费构成", "活动付费分析", "付费活动分析", "付费分层"]
```

验证：`git status --short` 中不应出现 `config.json`（已 gitignore）。

- [ ] **Step 6: Commit**

```bash
git add app/reports.py tests/test_pay_activity_templates.py
git commit -m "feat: reports新增pay_activity分支与触发词

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: report_insight LLM 经营解读

**Files:**
- Create: `app/report_insight.py`
- Test: `tests/test_report_insight.py`

**Interfaces:**
- Consumes: `claude_cli.run_with_system_prompt(question, ws, system_prompt) -> (answer, session_id)`（现有）。
- Produces:
  - `report_insight.build_prompt(result_dir: str) -> str` — 拼接 result_dir 下所有 `query_*.csv` 内容（含截断）。
  - `report_insight.interpret(question: str, result_dir: str, ws: dict) -> str` — 返回中文解读；**Never raises**，失败返回 `""`。

- [ ] **Step 1: 写失败测试**

Create `tests/test_report_insight.py`：

```python
"""Tests for report_insight (LLM 经营解读)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import report_insight


def _write(path, text):
    path.write_text(text, encoding="utf-8-sig")


def test_build_prompt_includes_all_sheets(tmp_path):
    _write(tmp_path / "query_1.csv", "a,b\n1,2\n")
    _write(tmp_path / "query_2.csv", "c,d\n3,4\n")
    prompt = report_insight.build_prompt(str(tmp_path))
    assert "query_1" in prompt and "query_2" in prompt
    assert "1,2" in prompt and "3,4" in prompt


def test_build_prompt_truncates_long_sheet(tmp_path, monkeypatch):
    monkeypatch.setattr(report_insight, "_MAX_ROWS_PER_SHEET", 5)
    rows = "\n".join(f"{i},{i}" for i in range(100))
    _write(tmp_path / "query_1.csv", "a,b\n" + rows + "\n")
    prompt = report_insight.build_prompt(str(tmp_path))
    assert "截断" in prompt


def test_build_prompt_empty_dir(tmp_path):
    assert report_insight.build_prompt(str(tmp_path)) == ""


def test_interpret_returns_stripped_answer(monkeypatch, tmp_path):
    _write(tmp_path / "query_1.csv", "a\n1\n")
    monkeypatch.setattr(
        report_insight.claude_cli, "run_with_system_prompt",
        lambda q, ws, sp: ("  解读文本  ", "sid"),
    )
    assert report_insight.interpret("付费构成", str(tmp_path), MagicMock()) == "解读文本"


def test_interpret_failure_returns_empty(monkeypatch, tmp_path):
    _write(tmp_path / "query_1.csv", "a\n1\n")

    def boom(q, ws, sp):
        raise RuntimeError("处理超时")

    monkeypatch.setattr(report_insight.claude_cli, "run_with_system_prompt", boom)
    assert report_insight.interpret("付费构成", str(tmp_path), MagicMock()) == ""


def test_interpret_no_data_returns_empty(tmp_path):
    assert report_insight.interpret("付费构成", str(tmp_path), MagicMock()) == ""
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_report_insight.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

Create `app/report_insight.py`：

```python
"""固定报表的 LLM 经营解读：读取 result_dir 下 query_N.csv，生成中文解读。

任何失败返回空串，绝不影响报表数据本身的交付。
"""
import csv
from pathlib import Path

import claude_cli

_MAX_ROWS_PER_SHEET = 200
_MAX_CHARS_PER_SHEET = 20000

_SYSTEM_PROMPT = """你是游戏运营数据分析师。用户给你一份游戏 312（女3，海外服）的单日付费报表，包含多个 Sheet 的 CSV 内容。
只做经营解读：禁止调用任何工具、禁止执行任何查询、禁止修改文件。
金额单位为美元（USD）；付费分层按当日累计充值划分。
输出固定结构（中文、简洁、每节 2-4 条要点）：
1.【当日付费大盘】收入、付费人数、ARPPU、付费率
2.【付费构成亮点】普通充值 vs 直购占比、主要直购活动
3.【分层观察】贡献最大的分层、高价值层（≥$200）人数与金额
4.【活动表现】参与人数 Top 活动、精彩活动/充值活动标记对照、产出/消耗异常
5.【建议关注点】1-3 条运营可执行建议"""


def _read_sheet(csv_path):
    """读取单个 CSV 为文本；超限截断。失败返回空串。"""
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
    except Exception:
        return ""
    if len(rows) > _MAX_ROWS_PER_SHEET:
        rows = rows[:_MAX_ROWS_PER_SHEET] + [[f"...(仅展示前{_MAX_ROWS_PER_SHEET}行,已截断)"]]
    text = "\n".join(",".join(str(c) for c in r) for r in rows)
    if len(text) > _MAX_CHARS_PER_SHEET:
        text = text[:_MAX_CHARS_PER_SHEET] + "\n...(已截断)"
    return text


def build_prompt(result_dir):
    """拼接 result_dir 下所有 query_*.csv 的内容。"""
    parts = []
    try:
        paths = sorted(Path(result_dir).glob("query_*.csv"))
    except Exception:
        return ""
    for p in paths:
        text = _read_sheet(p)
        if text:
            parts.append(f"### {p.stem}\n{text}")
    return "\n\n".join(parts)


def interpret(question, result_dir, ws):
    """生成中文经营解读。Never raises；失败返回空串。"""
    try:
        data = build_prompt(result_dir)
        if not data:
            return ""
        full_question = f"{question}\n\n报表数据如下：\n{data}"
        answer, _ = claude_cli.run_with_system_prompt(full_question, ws, _SYSTEM_PROMPT)
        return (answer or "").strip()
    except Exception as e:
        print(f"[report_insight] interpret failed: {e}", flush=True)
        return ""
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_report_insight.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/report_insight.py tests/test_report_insight.py
git commit -m "feat: 新增report_insight固定报表LLM经营解读(失败静默)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: bot._handle_report 接线

目录型报表分支补 `name_enrich.translate_dir`（player_segment 同时受益）；`pay_activity` 追加 LLM 解读。

**Files:**
- Modify: `app/bot.py:26` 附近（加 `import report_insight`）
- Modify: `app/bot.py:488-492`（`_handle_report` 目录分支）
- Test: `tests/test_bot.py`（追加）

**Interfaces:**
- Consumes: `name_enrich.translate_dir(result_dir, game_config) -> int`（Task 3）；`report_insight.interpret(question, result_dir, ws) -> str`（Task 6）；`workspace.prepare(chat_id, message_id, game_config=...) -> dict`（现有）。
- Produces: `_handle_report` 行为变化：目录分支先发图前翻译道具名；`pay_activity` 的 summary 后拼 `【经营解读】` 段（解读为空则不拼）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_bot.py` 末尾追加：

```python
def test_handle_report_pay_activity_enriches_and_interprets(monkeypatch, tmp_path):
    import threading
    from unittest.mock import MagicMock

    import bot

    sent_texts = []
    translated = []
    monkeypatch.setattr(bot.reports, "run",
                        lambda rt, text, game_config=None: ("数据概览", str(tmp_path)))
    monkeypatch.setattr(bot.name_enrich, "translate_dir",
                        lambda d, gc: translated.append(d) or 1)
    monkeypatch.setattr(bot, "_send_charts", lambda *a, **k: None)
    monkeypatch.setattr(bot, "_send_text", lambda c, cid, t: sent_texts.append(t))
    monkeypatch.setattr(bot, "_send_result_file", lambda *a, **k: None)
    monkeypatch.setattr(bot.workspace, "prepare",
                        lambda *a, **k: {"cwd": str(tmp_path), "mcp_config": "m",
                                         "result_dir": str(tmp_path)})
    monkeypatch.setattr(bot.report_insight, "interpret", lambda q, d, ws: "解读文本")
    monkeypatch.setattr(bot, "_query_sem", threading.Semaphore(1))
    bot._query_sem.acquire()  # _handle_report 的 finally 会 release

    bot._handle_report(None, "oc_chat", "om_msg", "pay_activity", "付费构成",
                       MagicMock(game_id=312))

    assert translated == [str(tmp_path)]
    full = "\n".join(sent_texts)
    assert "数据概览" in full
    assert "【经营解读】" in full and "解读文本" in full


def test_handle_report_pay_activity_insight_failure_still_sends(monkeypatch, tmp_path):
    import threading
    from unittest.mock import MagicMock

    import bot

    sent_texts = []
    monkeypatch.setattr(bot.reports, "run",
                        lambda rt, text, game_config=None: ("数据概览", str(tmp_path)))
    monkeypatch.setattr(bot.name_enrich, "translate_dir", lambda d, gc: 0)
    monkeypatch.setattr(bot, "_send_charts", lambda *a, **k: None)
    monkeypatch.setattr(bot, "_send_text", lambda c, cid, t: sent_texts.append(t))
    monkeypatch.setattr(bot, "_send_result_file", lambda *a, **k: None)
    monkeypatch.setattr(bot.workspace, "prepare",
                        lambda *a, **k: {"cwd": str(tmp_path), "mcp_config": "m",
                                         "result_dir": str(tmp_path)})

    def boom(q, d, ws):
        raise RuntimeError("处理超时")

    monkeypatch.setattr(bot.report_insight, "interpret", boom)
    monkeypatch.setattr(bot, "_query_sem", threading.Semaphore(1))
    bot._query_sem.acquire()

    bot._handle_report(None, "oc_chat", "om_msg", "pay_activity", "付费构成",
                       MagicMock(game_id=312))

    full = "\n".join(sent_texts)
    assert "数据概览" in full
    assert "【经营解读】" not in full
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_bot.py::test_handle_report_pay_activity_enriches_and_interprets -v`
Expected: FAIL（`bot.report_insight` 属性不存在 / 未调用 translate_dir）。

- [ ] **Step 3: 实现**

`app/bot.py` import 区（`import reports` 之后）加：

```python
import report_insight
```

`_handle_report` 目录分支（`app/bot.py:488-492`）替换为：

```python
        if file_or_dir and os.path.isdir(file_or_dir):
            # 多步报表（如玩家分层/付费构成）：与 LLM 查询一致，翻译 → 图 → 文字 → 文件
            if game_config is not None:
                name_enrich.translate_dir(file_or_dir, game_config)
            _send_charts(client, chat_id, file_or_dir)
            if report_type == "pay_activity":
                insight = ""
                try:
                    ws = workspace.prepare(chat_id, message_id, game_config=game_config)
                    insight = report_insight.interpret(text, file_or_dir, ws)
                except Exception as e:
                    print(f"[bot] report insight failed: {e}", flush=True)
                if insight:
                    summary = summary + "\n\n【经营解读】\n" + insight
            _send_text(client, chat_id, summary)
            _send_result_file(client, chat_id, file_or_dir, conclusions=[summary])
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_bot.py -v`
Expected: 全部 PASS（含 2 个新测试）。

- [ ] **Step 5: Commit**

```bash
git add app/bot.py tests/test_bot.py
git commit -m "feat: 目录型固定报表补道具名翻译,pay_activity追加LLM经营解读

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: 文档更新

**Files:**
- Modify: `app/templates/README.md`
- Modify: `CLAUDE.md`
- Modify: `schema_312.md`

- [ ] **Step 1: 更新 `app/templates/README.md`**

在"新增模板的方法"一节之前插入：

```markdown
## 付费构成与活动分析模板（pay_activity，仅 312）

模板文件：`app/templates/pay_activity.json`

对指定日期（默认昨日单日）输出 7 个 Sheet：

1. **付费概览**：DAU、付费人数、收入(USD)、付费率、ARPPU。
2. **付费构成**：普通充值 vs 直购（按 actId 细分：14 新手直购 / 13 新月卡 / 9 天使通行证 / 7、8 商店）。
3. **充值档位分布**：单笔金额档位（<$1 ~ ≥$100）的笔数/人数/金额。
4. **付费用户分层**：按当日累计充值 9 档（<$10 / 10~20 / 20~40 / 40~80 / 80~100 / 100~150 / 150~200 / 200~300 / ≥$300）。
5. **分层×活动参与**：分层 × 活动主题（`json_extract_scalar(activity_topic,'$.cn')`）的参与人数/次数（`rolepromo` 领奖记录）。
6. **活动总览**：全量玩家当日全部活动主题，按参与人数排序。
7. **分层×道具产销**：分层 × 产出/消耗 × 道具（`roleitem`，数量=变动前后差绝对值合计，表自带道具名称）。

口径：金额 USD；活动参与来自 `gameeco_raw.v_presto_log_rolepromo`（其 `item_spend`/`item_get` 源码硬编码恒空，不可用）；道具产销来自 `gameeco_raw.v_presto_log_roleitem`（`change_type` '1'=产出 / '2'=消耗，varchar 数值列必须显式 `CAST(... AS BIGINT)`）；全部活动纳入不过滤。
触发词：`付费构成`、`活动付费分析`、`付费活动分析`、`付费分层`。
```

- [ ] **Step 2: 更新 `CLAUDE.md`**

在"目录结构"的 `app/` 注释块中 `reports.py` 行后加：

```
  report_insight.py # 固定报表 LLM 经营解读
```

并在"复杂查询"一条之后补充一行：

```
- **pay_activity 报表**：312 专用付费构成+活动分析（触发词：付费构成/活动付费分析/付费活动分析/付费分层），模板 `app/templates/pay_activity.json`。
```

- [ ] **Step 3: 更新 `schema_312.md`**

在 `rolepromo` 表说明处（约 987 行表格之后）追加 Task 1 探针实测结论（以下内容逐字使用，已无占位符）：

```markdown
> **实测补充（2026-07-24，pay_activity 探针+源码确认）**：
> - `item_spend` / `item_get` 恒为空：唯一调用点 `module_activity.go:2293` 硬编码传 `""`；2026-07 全月 170 万+ 行无一非空。**不要用这两个字段统计消耗/产出**（道具产销走 `v_presto_log_roleitem`）。
> - `activity_special` / `activity_pay` 同处硬编码 `1` / `0`，不能作为精彩/付费活动标记。
> - `activity_topic` 为多语言 JSON 字符串，中文名用 `json_extract_scalar(activity_topic, '$.cn')` 提取（示例："女神通行证升级福利"、"买一送一送豪礼"、"大亨积分奖励"、"王的财宝限定礼包"、"女神新集市购买礼包"）。
> - `game_id` / `role_id` 为 varchar；`role_type` 为 integer（过滤真实玩家加 `role_type = 1`）。
> - 该表记录的是"领取活动奖励"事件（`handle_ActivityFinish`）。
```

并在 `roleitem` 表说明处（约 894 行表格之后）追加：

```markdown
> **实测补充（2026-07-24，pay_activity 探针确认）**：
> - `change_type` 为 **varchar**：`'1'`=产出 / `'2'`=消耗，过滤必须加引号。
> - `status_before` / `status_after` 为 **varchar**：聚合必须显式 `CAST(... AS BIGINT)`（隐式算术在 1600 万行/天上超 6 分钟跑不完，显式 CAST 约 5 秒）。单日变动量 = `SUM(ABS(CAST(status_after AS BIGINT) - CAST(status_before AS BIGINT)))`。
> - `game_id` / `role_id` 为 varchar。
```

- [ ] **Step 4: Commit**

```bash
git add app/templates/README.md CLAUDE.md schema_312.md
git commit -m "docs: 补充pay_activity模板说明与rolepromo实测口径

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: 全量验证 + 真实库冒烟

**Files:**
- Modify: `debug/probe_rolepromo_312.py`（可选：追加整跑模式）

- [ ] **Step 1: 语法与全量测试**

Run: `python -m py_compile app/*.py`
Expected: 无输出（全部编译通过）。

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS。

Run: `git diff --cached --name-only | grep -i config`
Expected: 无输出（config.json 未入暂存区）。

- [ ] **Step 2: 真实库整跑冒烟**

写一个一次性验证（直接在 python REPL 或临时脚本执行，不必留存）：

```python
import sys
sys.path.insert(0, "app")
import templates, config
gc = config.game_config(312)
summary, result_dir = templates.run_report("pay_activity", "昨天付费构成", gc)
print(summary)
import name_enrich
print("translated:", name_enrich.translate_dir(result_dir, gc))
from pathlib import Path
for p in sorted(Path(result_dir).glob("query_*.csv")):
    print(p.name, sum(1 for _ in open(p, encoding="utf-8-sig")), "rows")
```

Expected: 7 个 CSV 均生成；Sheet 7 的"道具名称"列有非空值（roleitem 自带）；各 Sheet 行数合理（Sheet 1 一行，Sheet 4 ≤9 行）。若某 Sheet SQL 报错，按报错信息修正模板（已知敏感点：roleitem/rolepromo 的 `role_type` 列、`activity_topic` 非 JSON 值导致 `json_extract_scalar` 报错——后者可改为 `TRY_CAST` 式兜底或 `COALESCE` 包装）。

- [ ] **Step 3: 触发词手工验证**

确认本地 `config.json` 已含 `"pay_activity": [...]`（Task 5 Step 5），启动 bot 后在 312 绑定群发送"昨日付费构成"，观察：文字回复含数据概览 + 【经营解读】，附件 Excel 含 7 个 Sheet。

- [ ] **Step 4: 最终提交（如有修正）**

```bash
git add -A
git commit -m "fix: pay_activity真实库冒烟修正

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review 记录

- **Spec 覆盖**：7 Sheet → Task 4；道具名补全（translate_dir 接线 + 中文表头 + fallback，本报表 Sheet 7 自带 item_name，主要惠及 player_segment 及通用查询路径）→ Task 3/7；LLM 解读 + 失败兜底 → Task 6/7；触发词/报表注册 → Task 5；文档 → Task 8；实测探针 → Task 1（已完成并触发口径修订：rolepromo 消耗/产出字段恒空 → 改走 roleitem）；验证 → Task 9。Spec 中"不改动 run_report 单 Sheet 容错"为非目标，无对应任务（符合）。
- **类型一致性**：`templates.run_report` 返回 `(summary, result_dir)` —— Task 2/4/5 一致；`report_insight.interpret(question, result_dir, ws)` —— Task 6 定义、Task 7 调用一致；`name_enrich.translate_dir(dir, game_config)` —— Task 3 不变签名、Task 7 调用一致。
- **已知风险**：Sheet 7（分层×道具产销）行数可能接近 max_rows=5000，超出时 dataapi 截断——冒烟时确认行数；`json_extract_scalar` 对非 JSON 的 `activity_topic` 可能报错——冒烟验证。
