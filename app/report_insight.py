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
