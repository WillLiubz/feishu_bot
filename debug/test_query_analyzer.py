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
    try:
        game_config = config.game_config(312)
    except ValueError:
        game_config = config.game_config()
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
            print(f"[{result.mode}] {q}\n  理由：{result.reason}")
            if result.steps:
                print("  步骤：")
                for i, step in enumerate(result.steps, start=1):
                    print(f"    {i}. {step.goal} | hint: {step.sql_hint}")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
