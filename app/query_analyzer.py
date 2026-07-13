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
__CLAUDE_MD__

用户问题：__QUESTION__

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
    """Extract the first JSON object from text, handling nested braces."""
    # Fenced code block
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))

    # Find the first balanced { ... } object to avoid stopping at nested braces
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in analyzer output")

    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])

    raise ValueError("No complete JSON object found in analyzer output")


def _fallback_heuristic(question: str) -> AnalysisResult:
    """Fallback to the existing keyword-based heuristic."""
    if query_planner.is_complex(question):
        return AnalysisResult(
            mode="planned",
            reason="命中关键词启发式规则",
            steps=[],
        )
    return AnalysisResult(mode="simple", reason="未命中复杂查询规则", steps=[])


def _maybe_append_source_summary(claude_md_text: str, game_id: int | None) -> str:
    """If CLAUDE.md is short on table mappings, append source code summary."""
    import config
    import source_code_index

    try:
        # Simple heuristic: if the document does not mention at least two warehouse tables,
        # consider it incomplete and append source summary.
        table_mentions = sum(1 for kw in ("gamelog_raw", "gameeco_raw", "raw_scribe_log") if kw in claude_md_text)
        if table_mentions >= 2:
            return claude_md_text
        source_dirs = config.GAME_SOURCE_DIRS
        source_dir = source_dirs.get(str(game_id))
        if not source_dir:
            return claude_md_text
        summary = source_code_index.summarize_game_source(game_id, source_dir)
        if summary:
            return claude_md_text + "\n\n" + summary
    except Exception:
        # Source scanning is an optional augmentation; never let it break routing.
        pass
    return claude_md_text


def analyze(question: str, ws: dict, claude_md_text: str, game_id: int | None = None) -> AnalysisResult:
    """
    Ask an LLM to decide whether the question is simple or planned based on
    the active CLAUDE.md business rules.
    """
    augmented_md = _maybe_append_source_summary(claude_md_text, game_id)
    system_prompt = _ANALYZER_SYSTEM_PROMPT.replace(
        "__CLAUDE_MD__", augmented_md
    ).replace("__QUESTION__", question)
    try:
        answer, _ = claude_cli.run_with_system_prompt(question, ws, system_prompt)
        data = _extract_json(answer)
    except Exception:
        return _fallback_heuristic(question)

    mode = data.get("mode", "simple")
    if mode not in ("simple", "planned"):
        mode = "simple"

    raw_steps = (data.get("steps") or []) if mode == "planned" else []
    if not isinstance(raw_steps, list):
        raw_steps = []
    steps = [
        query_planner.PlanStep(goal=s.get("goal", ""), sql_hint=s.get("sql_hint", ""))
        for s in raw_steps[:5]
    ]
    return AnalysisResult(
        mode=mode,
        reason=data.get("reason", ""),
        steps=steps,
    )
