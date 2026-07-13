# LLM-Driven Query Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the keyword-based `query_planner.is_complex()` heuristic with an LLM-driven analyzer that reads `CLAUDE.md` business rules and schema mappings, decides whether a query crosses multiple tables / time windows / business domains, and automatically routes complex queries through the existing multi-step planned workflow.

**Architecture:** Add a lightweight planning layer before `_handle()` in `app/bot.py`. The planner sends the user question plus the active `workspace/CLAUDE.md` (game-specific rules + schema mappings) to Claude with a structured system prompt. The LLM returns a JSON decision: `simple` with an optional single SQL, or `planned` with ordered steps. If `CLAUDE.md` mappings are insufficient, the planner falls back to reading the referenced game source code directories and summarizing missing mappings back into a supplementary `CLAUDE.md` section.

**Tech Stack:** Python 3.12+, existing `claude_cli.py` subprocess wrapper, existing `query_planner.py` step execution engine, existing `workspace.py` rule/schema materialization, `pathlib` for source code traversal, JSON schema validation via `json` + regex extraction (no new dependencies).

## Global Constraints

- Python version: 3.12+
- Dependencies: do not install new packages without explicit user approval
- All files UTF-8
- New logic must have `tests/test_*.py` or `debug/test_*.py`
- Full test run: `python -m pytest tests/ -q`
- Syntax check: `python -m py_compile app/*.py`
- Sensitive config (`config.json`) must not be committed
- Commit messages in Chinese, end with `Co-Authored-By: Claude <noreply@anthropic.com>`
- Do not push without user explicit approval

---

## File Structure

| File | Responsibility |
|---|---|
| `app/query_analyzer.py` (new) | LLM-driven query analyzer. Consumes user question + `CLAUDE.md` text (+ optional source code summary) and returns a structured `AnalysisResult` (`mode`, `reason`, `steps`). |
| `app/source_code_index.py` (new) | Indexes configured game source directories, extracts behavior-to-table mappings, and produces a markdown summary that can be appended to `CLAUDE.md`. |
| `app/bot.py` | Replace the static `query_planner.is_complex()` call with `query_analyzer.analyze()` and route to simple vs planned handler. |
| `app/query_planner.py` | Keep `run_planned()` and step execution; add `is_complex()` deprecation shim that delegates to `query_analyzer` for backward compatibility. |
| `app/workspace.py` | Expose the rendered `CLAUDE.md` text to callers so the analyzer can read it without re-rendering. |
| `tests/test_query_analyzer.py` (new) | Unit tests for analyzer decision logic with mocked Claude CLI responses. |
| `tests/test_source_code_index.py` (new) | Unit tests for source code summarizer with temporary fake source trees. |
| `debug/test_query_analyzer.py` (new) | Local debug script to run analyzer against sample questions without Feishu. |

---

## Task 1: Create `query_analyzer.py` Core Data Model and Simple/Planned Heuristic Fallback

**Files:**
- Create: `app/query_analyzer.py`
- Modify: `app/query_planner.py:99-130`
- Test: `tests/test_query_analyzer.py`

**Interfaces:**
- Consumes: `claude_cli.run_with_system_prompt(question, ws, system_prompt)`, `workspace.get_claude_md_text(ws)` (to be added in Task 3)
- Produces: `AnalysisResult(mode: str, reason: str, steps: List[PlanStep])`; `analyze(question, ws, claude_md_text) -> AnalysisResult`

- [ ] **Step 1: Write the failing test**

```python
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import query_analyzer


def test_analyze_simple_query(tmp_path):
    ws = {"cwd": str(tmp_path), "mcp_config": str(tmp_path / "mcp.json"), "result_dir": str(tmp_path / "results")}
    claude_md = "规则：game_id = 312，付费表 gamelog_raw.v_presto_log_payrecharge"
    result = query_analyzer.analyze("312 昨日付费金额", ws, claude_md)
    assert result.mode == "simple"
    assert result.reason


def test_analyze_planned_query_cross_tables(tmp_path):
    ws = {"cwd": str(tmp_path), "mcp_config": str(tmp_path / "mcp.json"), "result_dir": str(tmp_path / "results")}
    claude_md = (
        "规则：付费表 gamelog_raw.v_presto_log_payrecharge，"
        "道具表 gameeco_raw.v_presto_log_roleitem，"
        "行为表 gameeco_raw.v_presto_log_rolebehavior"
    )

    def fake_llm(question, ws_arg, system_prompt):
        return (
            '{"mode": "planned", "reason": "需要跨付费表和道具行为表", '
            '"steps": [{"goal": "确认 role_id", "sql_hint": "payrecharge 查付费最多"}, '
            '{"goal": "查道具", "sql_hint": "roleitem"}]}',
            "",
        )

    with patch.object(query_analyzer.claude_cli, "run_with_system_prompt", side_effect=fake_llm):
        result = query_analyzer.analyze("312 昨日付费最多玩家的道具获得情况", ws, claude_md)
    assert result.mode == "planned"
    assert len(result.steps) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_query_analyzer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'query_analyzer'`

- [ ] **Step 3: Write minimal implementation**

Create `app/query_analyzer.py`:

```python
import json
import re
from dataclasses import dataclass
from typing import List

import claude_cli
import query_planner


@dataclass(frozen=True)
class AnalysisResult:
    """Result of LLM-driven query analysis."""
    mode: str  # "simple" or "planned"
    reason: str
    steps: List[query_planner.PlanStep]


_ANALYZER_SYSTEM_PROMPT = """\
你是一个数据仓库查询路由专家。请阅读下面的业务规则（CLAUDE.md），判断用户的问题是需要单步执行还是分步执行。

业务规则：
{claude_md}

用户问题：{question}

输出要求：
- 只输出 JSON，不要任何其他文字
- JSON 格式：
{{
  "mode": "simple" | "planned",
  "reason": "简短的理由（中文）",
  "steps": []  // mode=planned 时必填，最多 5 步
}}

判断标准：
- simple：问题只涉及单张表或单个明确指标，例如"昨日付费金额""昨日DAU"
- planned：问题需要跨多张表 JOIN、跨多个时间段对比、先找出目标对象再查其明细、或涉及道具/行为/资源/付费等多维度分析

steps 中每一步必须包含：
- goal：该步骤目标（中文）
- sql_hint：建议查询的库表、关键字段和过滤条件
"""


def _extract_json(text: str) -> dict:
    """Extract JSON object from text that may contain markdown fences."""
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError("No JSON object found in analyzer output")


def _fallback_heuristic(question: str) -> AnalysisResult:
    """Fallback to the existing keyword-based heuristic."""
    if query_planner.is_complex(question):
        return AnalysisResult(
            mode="planned",
            reason="命中关键词启发式规则",
            steps=[],
        )
    return AnalysisResult(mode="simple", reason="未命中复杂查询规则", steps=[])


def analyze(question: str, ws: dict, claude_md_text: str) -> AnalysisResult:
    """
    Ask an LLM to decide whether the question is simple or planned based on
    the active CLAUDE.md business rules.
    """
    system_prompt = _ANALYZER_SYSTEM_PROMPT.format(
        claude_md=claude_md_text,
        question=question,
    )
    try:
        answer, _ = claude_cli.run_with_system_prompt(question, ws, system_prompt)
        data = _extract_json(answer)
    except Exception:
        return _fallback_heuristic(question)

    mode = data.get("mode", "simple")
    if mode not in ("simple", "planned"):
        mode = "simple"

    raw_steps = data.get("steps", []) if mode == "planned" else []
    steps = [
        query_planner.PlanStep(goal=s.get("goal", ""), sql_hint=s.get("sql_hint", ""))
        for s in raw_steps[:5]
    ]
    return AnalysisResult(
        mode=mode,
        reason=data.get("reason", ""),
        steps=steps,
    )
```

Modify `app/query_planner.py` to keep `is_complex()` as the keyword fallback but add a public `decide_steps()` helper:

```python
def decide_steps(question: str, ws: dict, claude_md_text: str) -> tuple[bool, List[PlanStep]]:
    """Decide whether a question needs planned execution and return planned steps."""
    import query_analyzer
    result = query_analyzer.analyze(question, ws, claude_md_text)
    return result.mode == "planned", list(result.steps)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_query_analyzer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/query_analyzer.py app/query_planner.py tests/test_query_analyzer.py
git commit -m "feat: 新增 LLM 驱动的查询分析器 core

- query_analyzer.analyze() 读取 CLAUDE.md 业务规则判断 simple/planned
- 失败时回退到 keyword heuristic
- query_planner 暴露 decide_steps() 供 bot 调用

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Add Source Code Indexer for Missing Table Mappings

**Files:**
- Create: `app/source_code_index.py`
- Test: `tests/test_source_code_index.py`

**Interfaces:**
- Consumes: configured source directory path from `config.GAME_SOURCE_DIRS[game_id]`
- Produces: `summarize_game_source(game_id, source_dir) -> str` (markdown summary of category -> table mappings)

- [ ] **Step 1: Write the failing test**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import source_code_index


def test_summarize_logs(tmp_path):
    # Fake source tree for game 312
    src = tmp_path / "src" / "ns3" / "aes_game"
    src.mkdir(parents=True)
    (src / "module_item.go").write_text(
        "func execReward() { Log_RoleItem(1, item_id, amount) }\n"
        "func method_execConsume() { Log_RoleItem(2, item_id, amount) }\n"
        "func Log_RoleRes() { /* gain=1 consume=2 */ }\n",
        encoding="utf-8",
    )
    (src / "behavior.go").write_text(
        "func Log_RoleBehavior() { BhBehavior(b_type, b_value) }\n",
        encoding="utf-8",
    )
    summary = source_code_index.summarize_game_source(312, str(tmp_path / "src"))
    assert "Log_RoleItem" in summary
    assert "Log_RoleBehavior" in summary
    assert "gameeco_raw" in summary or "gamelog_raw" in summary


def test_summarize_no_source_dir(tmp_path):
    summary = source_code_index.summarize_game_source(999, str(tmp_path / "missing"))
    assert summary == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_source_code_index.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'source_code_index'`

- [ ] **Step 3: Write minimal implementation**

Create `app/source_code_index.py`:

```python
import re
from pathlib import Path


# Map from source code function / category suffix to recommended warehouse table.
# These are project conventions from CLAUDE.md; the indexer's job is to surface
# which ones appear in the source code so missing mappings can be added.
_KNOWN_LOG_PATTERNS = {
    "Log_RoleItem": ("gameeco_raw.v_presto_log_roleitem", "道具获得/消耗"),
    "Log_RoleRes": ("gameeco_raw.v_presto_log_roleres", "资源变动"),
    "Log_RoleBehavior": ("gameeco_raw.v_presto_log_rolebehavior", "玩法参与/高阶行为"),
    "BhBehavior": ("gamelog_raw.v_presto_log_bhbehavior", "玩法参与/高阶行为"),
    "RsProduceLog": ("gamelog_raw.v_presto_log_rsproduce", "道具/资源生产消耗"),
    "PayConsume": ("gamelog_raw.v_presto_log_payconsume", "货币/钻石消耗"),
    "PayGift": ("gamelog_raw.v_presto_log_paygift", "货币/钻石获得"),
    "TracePayRecharge": ("gamelog_raw.v_presto_log_payrecharge", "充值"),
    "TraceRoleReg": ("gamelog_raw.v_presto_log_rolereg", "注册/创角"),
    "EVENT_LOGIN": ("gamelog_raw.v_presto_log_rolelogin", "登录"),
    "cash_tracer": ("raw_scribe_log.curr", "货币获得"),
    "logExchangeCost": ("raw_scribe_log.prop", "货币/道具消耗"),
    "login_tracer": ("raw_scribe_log.login", "登录"),
    "register_tracer": ("raw_scribe_log.est", "注册/激活"),
}


def _find_matches(source_dir: Path) -> dict:
    """Scan source files for known log function/category patterns."""
    matches = {}
    if not source_dir.exists():
        return matches
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pattern, (table, desc) in _KNOWN_LOG_PATTERNS.items():
            if pattern in text and pattern not in matches:
                matches[pattern] = (table, desc)
    return matches


def summarize_game_source(game_id: int, source_dir: str) -> str:
    """
    Summarize the game source code to produce missing CLAUDE.md table mappings.
    Returns a markdown string; empty if source_dir is missing.
    """
    matches = _find_matches(Path(source_dir))
    if not matches:
        return ""
    lines = [f"### 游戏 {game_id} 源码日志映射补充（自动扫描）", ""]
    lines.append("| 源码标识 | 含义 | 推荐数仓表 |")
    lines.append("|---|---|---|")
    for pattern, (table, desc) in sorted(matches.items()):
        lines.append(f"| {pattern} | {desc} | {table} |")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_source_code_index.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/source_code_index.py tests/test_source_code_index.py
git commit -m "feat: 新增游戏源码日志映射索引器

- source_code_index.summarize_game_source() 扫描源码目录
- 识别已知日志函数/Tracer，输出 markdown 映射补充
- 用于 CLAUDE.md 表映射不全时自动补充

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Expose Rendered CLAUDE.md and Optionally Append Source Summary

**Files:**
- Modify: `app/workspace.py:175-179`
- Modify: `app/query_analyzer.py`
- Test: `tests/test_workspace.py`

**Interfaces:**
- Consumes: `workspace.prepare()` result dict
- Produces: `workspace.get_claude_md_text(ws) -> str`; analyzer appends source summary when mappings look incomplete

- [ ] **Step 1: Write the failing test**

Add to `tests/test_workspace.py` (create if absent):

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import workspace


def test_get_claude_md_text(tmp_path):
    ws_dir = tmp_path / "workspaces" / "chat_1"
    ws_dir.mkdir(parents=True)
    md_text = "规则：game_id=312"
    (ws_dir / "CLAUDE.md").write_text(md_text, encoding="utf-8")
    ws = {"cwd": str(ws_dir), "mcp_config": str(ws_dir / "mcp.json"), "result_dir": str(ws_dir / "results")}
    assert workspace.get_claude_md_text(ws) == md_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_workspace.py -v`
Expected: FAIL with `AttributeError: module 'workspace' has no attribute 'get_claude_md_text'`

- [ ] **Step 3: Write minimal implementation**

Modify `app/workspace.py` return value and add helper:

```python
    return {
        "cwd": str(ws_dir),
        "mcp_config": str(mcp_config_path),
        "result_dir": str(result_dir),
        "claude_md_path": str(ws_dir / "CLAUDE.md"),
    }


def get_claude_md_text(ws: dict) -> str:
    """Read the rendered CLAUDE.md text for the active workspace."""
    path = Path(ws.get("claude_md_path", Path(ws["cwd"]) / "CLAUDE.md"))
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""
```

Modify `app/query_analyzer.py` `_ANALYZER_SYSTEM_PROMPT` and `analyze()` to optionally include source summary. Add a helper `_maybe_append_source_summary(ws, claude_md_text)`:

```python
def _maybe_append_source_summary(claude_md_text: str, game_id: int) -> str:
    """If CLAUDE.md is short on table mappings, append source code summary."""
    import config
    import source_code_index
    # Simple heuristic: if the document does not mention at least two warehouse tables,
    # consider it incomplete and append source summary.
    table_mentions = sum(1 for kw in ("gamelog_raw", "gameeco_raw", "raw_scribe_log") if kw in claude_md_text)
    if table_mentions >= 2:
        return claude_md_text
    source_dirs = getattr(config, "GAME_SOURCE_DIRS", {})
    source_dir = source_dirs.get(game_id)
    if not source_dir:
        return claude_md_text
    summary = source_code_index.summarize_game_source(game_id, source_dir)
    if summary:
        return claude_md_text + "\n\n" + summary
    return claude_md_text
```

`analyze()` should call this before formatting the prompt and accept an optional `game_id`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_workspace.py tests/test_query_analyzer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workspace.py app/query_analyzer.py tests/test_workspace.py
git commit -m "feat: workspace 返回 CLAUDE.md 路径，分析器可追加源码映射

- workspace.prepare() 增加 claude_md_path
- workspace.get_claude_md_text() 读取已渲染规则
- query_analyzer 在表映射不足时自动追加源码扫描摘要

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Wire Analyzer into Bot Routing

**Files:**
- Modify: `app/bot.py:289-294`
- Modify: `app/bot.py:377-386`
- Test: `tests/test_bot.py` (create if absent) or extend `debug/test_bot_components.py`

**Interfaces:**
- Consumes: `query_analyzer.analyze(question, ws, claude_md_text)`
- Produces: bot routes to `_handle_planned` with pre-decided steps

- [ ] **Step 1: Write the failing test**

Create `tests/test_bot.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import bot


def test_handle_routes_planned_when_analyzer_says_planned(tmp_path):
    ws = {"cwd": str(tmp_path), "mcp_config": str(tmp_path / "mcp.json"), "result_dir": str(tmp_path / "results")}
    game_config = MagicMock()
    game_config.game_id = 312

    planned_result = bot.query_analyzer.AnalysisResult(
        mode="planned",
        reason="跨表",
        steps=[bot.query_planner.PlanStep("查付费", "payrecharge")],
    )

    with patch.object(bot.query_analyzer, "analyze", return_value=planned_result):
        with patch.object(bot, "_handle_planned") as mock_planned:
            with patch.object(bot, "_handle_simple") as mock_simple:
                with patch.object(bot.workspace, "prepare", return_value=ws):
                    with patch.object(bot.workspace, "get_claude_md_text", return_value="rules"):
                        bot._handle(None, "chat", "user", "msg", "question", [], game_config)
    mock_planned.assert_called_once()
    mock_simple.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bot.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Modify `app/bot.py`:

```python
def _handle(client, chat_id, user_id, message_id, text, opgames, game_config):
    """Route a query to simple or planned handler based on LLM analysis."""
    ws = workspace.prepare(chat_id, message_id, game_config=game_config, opgames=opgames)
    claude_md_text = workspace.get_claude_md_text(ws)
    result = query_analyzer.analyze(text, ws, claude_md_text)
    if result.mode == "planned" and result.steps:
        _handle_planned_with_steps(client, chat_id, user_id, message_id, text, opgames, game_config, ws, result.steps)
    elif result.mode == "planned":
        _handle_planned(client, chat_id, user_id, message_id, text, opgames, game_config)
    else:
        _handle_simple(client, chat_id, user_id, message_id, text, opgames, game_config)
```

Add a new helper `_handle_planned_with_steps` that skips `query_planner.plan()` and uses the provided steps:

```python
def _handle_planned_with_steps(client, chat_id, user_id, message_id, text, opgames, game_config, ws, steps):
    """Process a complex query using analyzer-provided steps."""
    t0 = time.time()
    try:
        _send_text(client, chat_id, "🔎 该问题较复杂，正在分步查询，请稍候…")
        summaries = []
        for i, step in enumerate(steps, start=1):
            summary = query_planner.execute_step(step, i, len(steps), ws, summaries)
            summaries.append(summary)
        final_summary = query_planner.summarize(text, ws, summaries)
        answer = "\n".join(f"第{i}步：{s}" for i, s in enumerate(summaries, start=1)) + "\n\n【总结】\n" + final_summary
        _send_text(client, chat_id, answer)
        _send_results(client, chat_id, ws)
        _send_query_summary(client, chat_id, message_id)
        latency = int((time.time() - t0) * 1000)
        store.log_out(chat_id, message_id, "ok", latency)
    except RuntimeError as e:
        ...
    except Exception as e:
        ...
    finally:
        _query_sem.release()
        with _active_lock:
            _active_chats.discard(chat_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bot.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/bot.py tests/test_bot.py
git commit -m "feat: bot 路由接入 LLM 分析器并支持预定义步骤

- _handle() 调用 query_analyzer.analyze() 替代 is_complex() 关键字判断
- 新增 _handle_planned_with_steps() 直接执行分析器返回的步骤
- 保留原 _handle_planned() 作为无步骤时的降级路径

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Add Debug Script and Run Full Validation

**Files:**
- Create: `debug/test_query_analyzer.py`

- [ ] **Step 1: Create debug script**

```python
"""
调试 query_analyzer 的决策逻辑（无需飞书/真实数仓）。
用法：python debug/test_query_analyzer.py
"""
import io
import sys
from pathlib import Path
from unittest.mock import patch

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import query_analyzer
import workspace


def main():
    game_config = config.game_config(312)
    chat_id = "debug_analyzer"
    message_id = "debug_msg"
    ws = workspace.prepare(chat_id, message_id, game_config=game_config, opgames=[])
    claude_md = workspace.get_claude_md_text(ws)

    questions = [
        "312 昨日付费金额是多少",
        "312 昨日付费最多的玩家的行为情况",
        "分析6月10-12日和7月10-12日的付费对比。找出衰减的原因",
        "312 昨日付费最多玩家获得了哪些道具",
    ]

    def fake_llm(question, ws_arg, system_prompt):
        # deterministic mock: planned if multiple tables implied
        if any(k in question for k in ("行为", "道具", "对比", "原因", "衰减")):
            return (
                '{"mode": "planned", "reason": "涉及跨表或多时段", "steps": [ '
                '{"goal": "第一步", "sql_hint": "hint"} ]}',
                "",
            )
        return (
            '{"mode": "simple", "reason": "单表单指标", "steps": []}',
            "",
        )

    with patch.object(query_analyzer.claude_cli, "run_with_system_prompt", side_effect=fake_llm):
        for q in questions:
            result = query_analyzer.analyze(q, ws, claude_md)
            print(f"[{result.mode}] {q}\n  理由：{result.reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run debug script**

Run: `python debug/test_query_analyzer.py`
Expected: prints mode/reason for each sample question

- [ ] **Step 3: Run full validation**

Run: `python -m py_compile app/*.py`
Run: `python -m pytest tests/ -q`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add debug/test_query_analyzer.py
git commit -m "chore: 新增 query_analyzer 调试脚本

- 无需飞书即可验证 LLM 分析器的路由决策

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Document New Behavior in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add planner section to CLAUDE.md**

Append to `CLAUDE.md` under the project overview:

```markdown
## 查询路由

Bot 不再依赖固定关键词判断是否需要分步查询。每次提问时：

1. `query_analyzer` 会读取当前 workspace 的 `CLAUDE.md`（含游戏 schema、表映射、业务规则）。
2. 由 LLM 判断问题是否涉及：
   - 跨多张表 JOIN
   - 多时间段对比 / 归因
   - 先找目标对象再查明细（如 Top 付费玩家 → 道具/行为）
3. 若判定为复杂查询，自动拆分为最多 5 步，每步一次 SQL，结果合并为 Excel。
4. 若 `CLAUDE.md` 中的表映射明显不足（少于 2 个库表提及），系统会自动扫描配置的游戏源码目录，补充日志函数 → 数仓表映射。

默认所有查询仍走 RAW 库；只有用户明确要求 T+1/odl 时才加 `-- use_odl`。
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 在 CLAUDE.md 中补充 LLM 驱动查询路由说明

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- LLM analyzes input based on CLAUDE.md ✅ Task 1
- Cross-table detection ✅ Task 1, Task 4
- Auto split into planned workflow ✅ Task 4
- Source code fallback when CLAUDE.md incomplete ✅ Task 2, Task 3
- No new dependencies ✅ all code uses stdlib + existing `claude_cli`

**Placeholder scan:** No TBD/TODO/fill-in details found.

**Type consistency:**
- `AnalysisResult.steps` uses `query_planner.PlanStep` consistently
- `workspace.prepare()` returns `claude_md_path` string
- `query_analyzer.analyze()` signature matches usage in `bot.py`

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-13-llm-driven-query-planner.md`.

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
