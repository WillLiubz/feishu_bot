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
