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
