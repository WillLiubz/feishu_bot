import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import query_analyzer
import source_code_index


def test_analyze_simple_query(tmp_path):
    ws = {"cwd": str(tmp_path), "mcp_config": str(tmp_path / "mcp.json"), "result_dir": str(tmp_path / "results")}
    claude_md = "规则：game_id = 312，付费表 gamelog_raw.v_presto_log_payrecharge"

    def fake_llm(question, ws_arg, system_prompt):
        return '{"mode": "simple", "reason": "单表查询", "steps": []}', ""

    with patch.object(query_analyzer.claude_cli, "run_with_system_prompt", side_effect=fake_llm):
        result = query_analyzer.analyze("312 昨日付费金额", ws, claude_md)
    assert result.mode == "simple"
    assert result.reason == "单表查询"


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


def test_analyze_handles_steps_none(tmp_path):
    ws = {"cwd": str(tmp_path), "mcp_config": str(tmp_path / "mcp.json"), "result_dir": str(tmp_path / "results")}
    claude_md = "规则：付费表 gamelog_raw.v_presto_log_payrecharge"

    def fake_llm(question, ws_arg, system_prompt):
        return '{"mode": "planned", "reason": "测试", "steps": null}', ""

    with patch.object(query_analyzer.claude_cli, "run_with_system_prompt", side_effect=fake_llm):
        result = query_analyzer.analyze("312 测试", ws, claude_md)
    assert result.mode == "planned"
    assert result.steps == []


def test_analyze_braces_in_question(tmp_path):
    ws = {"cwd": str(tmp_path), "mcp_config": str(tmp_path / "mcp.json"), "result_dir": str(tmp_path / "results")}
    claude_md = "规则：付费表 gamelog_raw.v_presto_log_payrecharge"

    def fake_llm(question, ws_arg, system_prompt):
        return '{"mode": "simple", "reason": "含大括号", "steps": []}', ""

    with patch.object(query_analyzer.claude_cli, "run_with_system_prompt", side_effect=fake_llm):
        result = query_analyzer.analyze("312 {foo} 昨日付费金额", ws, claude_md)
    assert result.mode == "simple"
    assert result.reason == "含大括号"


def test_analyze_fallback_on_llm_error(tmp_path):
    ws = {"cwd": str(tmp_path), "mcp_config": str(tmp_path / "mcp.json"), "result_dir": str(tmp_path / "results")}
    claude_md = "规则：付费表 gamelog_raw.v_presto_log_payrecharge"

    with patch.object(query_analyzer.claude_cli, "run_with_system_prompt", side_effect=RuntimeError("cli failed")):
        result = query_analyzer.analyze("312 昨日付费金额", ws, claude_md)
    assert result.mode == "simple"
    assert "启发式" in result.reason or "未命中" in result.reason


def test_analyze_appends_source_summary_when_mappings_incomplete(tmp_path):
    ws = {"cwd": str(tmp_path), "mcp_config": str(tmp_path / "mcp.json"), "result_dir": str(tmp_path / "results")}
    claude_md = "规则：付费表 gamelog_raw.v_presto_log_payrecharge"  # only one warehouse table

    def fake_llm(question, ws_arg, system_prompt):
        # Verify the source summary was appended to the prompt.
        assert "自动扫描" in system_prompt
        return '{"mode": "simple", "reason": "已补充", "steps": []}', ""

    with patch.object(query_analyzer.claude_cli, "run_with_system_prompt", side_effect=fake_llm):
        with patch.object(config, "GAME_SOURCE_DIRS", {"312": str(tmp_path)}):
            with patch.object(
                source_code_index,
                "summarize_game_source",
                return_value="### 游戏 312 源码日志映射补充（自动扫描）\n| a | b | c |",
            ):
                result = query_analyzer.analyze("312 昨日付费金额", ws, claude_md, game_id=312)
    assert result.mode == "simple"
    assert result.reason == "已补充"
