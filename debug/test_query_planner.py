"""
调试 query_planner 的完整工作流（无需真实 Claude CLI / 数仓）。

用法：
    python debug/test_query_planner.py
"""
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import query_planner
import workspace


def _make_game_config():
    return config.GAMES.get("312") or config.DEFAULT_GAME


def main():
    if not config.GAMES:
        print("未配置游戏，跳过测试")
        return 1

    game_config = _make_game_config()
    chat_id = "debug_chat_planner"
    message_id = "debug_msg_planner"

    ws = workspace.prepare(chat_id, message_id, game_config, opgames=[])
    print(f"workspace: cwd={ws['cwd']}")
    print(f"result_dir: {ws['result_dir']}\n")

    # Prepare some fake CSVs to simulate previous query results
    result_dir = Path(ws["result_dir"])
    result_dir.mkdir(parents=True, exist_ok=True)

    fake_csvs = [
        ("query_1.csv", "role_id,total_pay\n3166123422787829761,999.00\n"),
        ("query_2.csv", "item_name,amount\n钻石,100\n金币,5000\n装备,1\n"),
        ("query_3.csv", "b_type,count\n竞技场,5\n副本,10\n"),
    ]
    for name, content in fake_csvs:
        (result_dir / name).write_text(content, encoding="utf-8-sig")
        (result_dir / name.replace(".csv", ".sql")).write_text(
            f"-- {name} mock SQL", encoding="utf-8"
        )

    planner_output = json.dumps({
        "steps": [
            {"goal": "确认 role_id 昨日付费最多", "sql_hint": "查 gamelog_raw.v_presto_log_payrecharge"},
            {"goal": "查该 role_id 昨日道具获得", "sql_hint": "查 gameeco_raw.v_presto_log_roleitem"},
            {"goal": "查该 role_id 昨日玩法参与", "sql_hint": "查 gameeco_raw.v_presto_log_rolebehavior"},
        ]
    })

    step_outputs = [
        "确认昨日付费最多的 role_id 是 3166123422787829761，付费 999 元，共 1 行",
        "昨日该角色获得道具 3 件（钻石 x100, 金币 x5000, 装备 x1），共 3 行",
        "昨日该角色参与了竞技场 5 次、副本 10 次，共 2 行",
    ]
    summary_output = (
        "玩家 3166123422787829761 昨日付费 999 元，获得钻石 100、金币 5000、装备 1 件，"
        "参与竞技场 5 次、副本 10 次。"
    )

    def fake_run(prompt, ws, system_prompt):
        print(f"[mock claude] prompt={prompt!r}")
        if "查询规划器" in system_prompt:
            return planner_output
        if "当前步骤" in system_prompt:
            return step_outputs.pop(0)
        return summary_output

    question = (
        "312 昨日付费最多的玩家（role_id: 3166123422787829761）"
        "昨日的道具获得情况是怎样的？玩法参与情况是怎样的？"
    )

    with patch.object(query_planner.claude_cli, "run_with_system_prompt", side_effect=fake_run):
        answer = query_planner.run_planned(question, ws)

    print("\n=== 最终回复 ===")
    print(answer)

    # Verify CSVs would be combined
    from dquery import combine_to_excel
    xlsx_path = combine_to_excel(ws["result_dir"])
    print(f"\n生成的 Excel: {xlsx_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
