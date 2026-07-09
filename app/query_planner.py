import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import claude_cli
import config


@dataclass(frozen=True)
class PlanStep:
    """One step in a planned query workflow."""
    goal: str
    sql_hint: str


@dataclass(frozen=True)
class Plan:
    """A multi-step plan produced by the planner LLM."""
    steps: List[PlanStep]


_PLANNER_SYSTEM_PROMPT = """\
你是一个查询规划器。用户会提出一个复杂的数据分析问题。你的任务是把这个问题拆成最多5个简单的SQL查询步骤。

输出要求：
- 只输出 JSON，不要输出任何其他文字
- JSON 格式如下：
{
  "steps": [
    {"goal": "步骤目标（中文）", "sql_hint": "建议查询的表和关键过滤条件"},
    ...
  ]
}

拆分原则：
1. 每一步应该只查一张主表，或者一个明确的子问题
2. 如果用户已经给了 role_id，第一步先确认/验证该 role_id 的付费或基础信息
3. 道具获得情况查 gameeco_raw.v_presto_log_roleitem
4. 玩法参与情况查 gameeco_raw.v_presto_log_rolebehavior
5. 付费情况查 gamelog_raw.v_presto_log_payrecharge
6. 每一步的 sql_hint 必须包含数据库、表、game_id、ds、role_id 等关键信息
7. 如果问题只涉及一个简单查询，只输出一步
"""


_STEP_SYSTEM_PROMPT_TEMPLATE = """\
你是一个数据分析助手。请只执行当前这一步查询，不要回答其他问题。

{context}
当前步骤：{step_n}/{total_n}
目标：{goal}
提示：{sql_hint}

要求：
1. 用 query_data 工具执行一个 SQL 查询
2. 查询必须带 game_id 分区条件
3. ds 格式为 yyyyMMdd
4. ECO 表（roleitem / rolebehavior）使用 gameeco_raw，不是 gameeco_odl
5. 结果会自动保存到 results/query_N.csv
6. 最后只返回一句中文总结：查到了什么，共多少行，关键 role_id / 数值是多少
7. 不要输出 SQL 代码块，不要输出表格
"""


_SUMMARY_SYSTEM_PROMPT_TEMPLATE = """\
你是一个数据分析助手。之前已经执行了多步查询，每一步的结果都保存在 results/query_N.csv 文件中。

{step_summaries}

请读取这些 CSV 文件，给出一段完整的中文总结，回答用户最初的问题。

要求：
1. 基于实际数据，不要编造
2. 如果某一步没有数据，也要说明
3. 最后说明数据来源（哪些表）
4. 不要输出代码
"""


def _extract_json(text: str) -> dict:
    """Extract JSON object from text that may contain markdown fences."""
    # Try fenced code block
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Try bare JSON object
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError("No JSON object found in planner output")


def is_complex(text: str) -> bool:
    """Heuristic: does this question likely need multi-step planning?"""
    lowered = text.lower()
    indicators = [
        "role_id",
        "道具",
        "玩法",
        "获得",
        "参与",
        "资源",
        "充值",
        "付费",
        "并且",
        "以及",
        "和",
        "？",
        "?",
    ]
    score = sum(1 for ind in indicators if ind in lowered)
    # Need at least a concrete entity + multiple dimensions
    return score >= 3 and ("道具" in lowered or "玩法" in lowered or "资源" in lowered)


def plan(question: str, ws: dict) -> Plan:
    """Ask planner LLM to break question into steps."""
    system_prompt = _PLANNER_SYSTEM_PROMPT
    try:
        answer, _ = claude_cli.run_with_system_prompt(question, ws, system_prompt)
        data = _extract_json(answer)
    except (json.JSONDecodeError, ValueError) as e:
        raise RuntimeError(f"查询规划失败: {e}") from e
    steps = [PlanStep(goal=s["goal"], sql_hint=s["sql_hint"]) for s in data.get("steps", [])]
    if not steps:
        raise RuntimeError("查询规划失败: 未返回任何步骤")
    if len(steps) > 5:
        steps = steps[:5]
    return Plan(steps=steps)


def _format_context(summaries: List[str]) -> str:
    """Format previous step summaries for the next step prompt."""
    if not summaries:
        return ""
    lines = ["前面步骤的结果："]
    for i, s in enumerate(summaries, start=1):
        lines.append(f"第{i}步：{s}")
    return "\n".join(lines) + "\n\n"


def execute_step(step: PlanStep, step_n: int, total_n: int, ws: dict, prev_summaries: List[str]) -> str:
    """Run one planned step via LLM and return its Chinese summary."""
    context = _format_context(prev_summaries)
    system_prompt = _STEP_SYSTEM_PROMPT_TEMPLATE.format(
        context=context,
        step_n=step_n,
        total_n=total_n,
        goal=step.goal,
        sql_hint=step.sql_hint,
    )
    answer, _ = claude_cli.run_with_system_prompt("请执行当前步骤", ws, system_prompt)
    return answer


def _read_csv_preview(path: Path, limit: int = 20) -> str:
    """Read a CSV file and return a short text preview."""
    if not path.exists():
        return "(文件不存在)"
    rows = []
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        return f"(读取失败: {e})"
    if not rows:
        return "(无数据)"
    lines = [f"共 {len(rows)} 行，前 {min(limit, len(rows))} 行预览："]
    headers = list(rows[0].keys())
    lines.append(" | ".join(headers))
    for row in rows[:limit]:
        lines.append(" | ".join(str(row.get(h, "")) for h in headers))
    return "\n".join(lines)


def _build_step_summaries(result_dir: str, summaries: List[str]) -> str:
    """Combine step summaries with CSV previews for the final summary prompt."""
    result_dir = Path(result_dir)
    parts = []
    for i, summary in enumerate(summaries, start=1):
        csv_path = result_dir / f"query_{i}.csv"
        preview = _read_csv_preview(csv_path)
        parts.append(f"## 第{i}步\n总结：{summary}\n数据：\n{preview}")
    return "\n\n".join(parts)


def summarize(question: str, ws: dict, summaries: List[str]) -> str:
    """Ask LLM to summarize all query_N.csv results."""
    step_summaries = _build_step_summaries(ws["result_dir"], summaries)
    system_prompt = _SUMMARY_SYSTEM_PROMPT_TEMPLATE.format(step_summaries=step_summaries)
    answer, _ = claude_cli.run_with_system_prompt(question, ws, system_prompt)
    return answer


def run_planned(question: str, ws: dict) -> str:
    """Run full planned workflow and return summary text."""
    plan_obj = plan(question, ws)
    summaries = []
    for i, step in enumerate(plan_obj.steps, start=1):
        summary = execute_step(step, i, len(plan_obj.steps), ws, summaries)
        summaries.append(summary)
    final_summary = summarize(question, ws, summaries)
    return "\n".join(f"第{i}步：{s}" for i, s in enumerate(summaries, start=1)) + "\n\n【总结】\n" + final_summary
