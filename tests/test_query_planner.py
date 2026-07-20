import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import pytest

import query_planner


def test_is_complex_positive():
    assert query_planner.is_complex(
        "312 昨日付费最多的玩家（role_id: 3166123422787829761）"
        "昨日的道具获得情况是怎样的？玩法参与情况是怎样的？"
    )


def test_is_complex_with_resource():
    assert query_planner.is_complex(
        "312 role_id 12345 昨日的资源获得和充值情况？"
    )


def test_is_complex_simple_pay_only():
    # Only mentions payment, no multi-dimension indicators
    assert not query_planner.is_complex("312 查询昨日的付费TOP100情况")


def test_is_complex_payment_plus_behavior():
    # Finding top payer then analyzing their behavior crosses tables and needs splitting.
    assert query_planner.is_complex("312 昨日付费最多的玩家的行为情况")


def test_is_complex_multi_period_comparison():
    # Comparing payment across two date windows needs per-period steps.
    assert query_planner.is_complex("分析6月10-12日和7月10-12日的付费对比。找出衰减的原因")


def test_is_complex_simple_single_date():
    # Single-period pay query should stay simple.
    assert not query_planner.is_complex("312 昨日付费金额是多少")

def test_is_complex_simple_dau():
    assert not query_planner.is_complex("312 昨日DAU是多少")


def test_extract_json_fenced():
    text = '```json\n{"steps": [{"goal": "a", "sql_hint": "b"}]}\n```'
    data = query_planner._extract_json(text)
    assert data == {"steps": [{"goal": "a", "sql_hint": "b"}]}


def test_extract_json_bare():
    text = 'some text\n{"steps": [{"goal": "a", "sql_hint": "b"}]}\nmore text'
    data = query_planner._extract_json(text)
    assert data == {"steps": [{"goal": "a", "sql_hint": "b"}]}


def test_extract_json_invalid():
    with pytest.raises(ValueError):
        query_planner._extract_json("no json here")


def test_planner_prompt_contains_new_rules():
    prompt = query_planner._PLANNER_SYSTEM_PROMPT
    assert "同一步只能查询一张主表" in prompt
    assert "每个时间段必须独立成步" in prompt
    assert "不得超过 10 天" in prompt
    assert "禁止在单条 SQL 里用" in prompt


def test_plan_invalid_json_raises_runtime_error(tmp_path):
    ws = {"cwd": str(tmp_path), "mcp_config": str(tmp_path / "mcp.json"), "result_dir": str(tmp_path / "results")}
    with patch.object(query_planner.claude_cli, "run_with_system_prompt", return_value=("not json", "")):
        with pytest.raises(RuntimeError):
            query_planner.plan("question", ws)


def test_plan_caps_at_five_steps(tmp_path):
    ws = {"cwd": str(tmp_path), "mcp_config": str(tmp_path / "mcp.json"), "result_dir": str(tmp_path / "results")}
    planner_output = json.dumps({
        "steps": [
            {"goal": f"step {i}", "sql_hint": f"hint {i}"}
            for i in range(10)
        ]
    })
    with patch.object(query_planner.claude_cli, "run_with_system_prompt", return_value=(planner_output, "")):
        plan = query_planner.plan("question", ws)
    assert len(plan.steps) == 5


def test_run_planned(tmp_path):
    ws = {"cwd": str(tmp_path), "mcp_config": str(tmp_path / "mcp.json"), "result_dir": str(tmp_path / "results")}
    Path(ws["result_dir"]).mkdir(parents=True)

    planner_output = json.dumps({
        "steps": [
            {"goal": "确认 role_id", "sql_hint": "查 payrecharge"},
            {"goal": "查道具", "sql_hint": "查 roleitem"},
        ]
    })
    step_outputs = [
        "确认 role_id 是 123，昨日付费 100 元，共 1 行",
        "查到道具 5 件，共 5 行",
    ]
    summary_output = "该玩家昨日付费 100 元，获得 5 件道具。"

    def fake_run(prompt, ws, system_prompt):
        if "查询规划器" in system_prompt or "plan" in system_prompt.lower():
            return (planner_output, "")
        if "前面步骤" in system_prompt or "当前步骤" in system_prompt:
            return (step_outputs.pop(0), "")
        return (summary_output, "")

    with patch.object(query_planner.claude_cli, "run_with_system_prompt", side_effect=fake_run):
        result = query_planner.run_planned("question", ws)

    assert "第1步" in result
    assert "第2步" in result
    assert "【总结】" in result
    assert "100 元" in result


def test_step_prompt_contains_new_rules():
    prompt = query_planner._STEP_SYSTEM_PROMPT_TEMPLATE
    assert "当前步骤只能调用一次 query_data" in prompt
    assert "查询只能涉及一张主表" in prompt
    assert "不得超过 10 天" in prompt
    assert "禁止在当前 SQL 里用" in prompt
    # MCP 异步加载时引导模型等待，而不是宣布工具不可用或绕行
    assert "WaitForMcpServers" in prompt


def test_read_csv_preview(tmp_path):
    csv_path = tmp_path / "query_1.csv"
    csv_path.write_text("col1,col2\n1,2\n3,4\n", encoding="utf-8-sig")
    preview = query_planner._read_csv_preview(csv_path)
    assert "共 2 行" in preview
    assert "1" in preview
    assert "col1" in preview


def test_build_step_summaries(tmp_path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    (result_dir / "query_1.csv").write_text("a,b\n1,2\n", encoding="utf-8-sig")
    summaries = ["第一步总结"]
    text = query_planner._build_step_summaries(str(result_dir), summaries)
    assert "第1步" in text
    assert "第一步总结" in text
    assert "共 1 行" in text


def test_build_step_summaries_with_step_csvs_mapping(tmp_path):
    """中间步骤失败后 CSV 编号前移：按 step_csvs 归属对齐，不按步骤下标猜。"""
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    (result_dir / "query_1.csv").write_text("a,b\n1,2\n", encoding="utf-8-sig")
    summaries = ["第一步总结", "（本步查询失败：处理超时）", "第三步总结"]
    # 第2步失败无 CSV；query_1.csv 实际属于第3步
    step_csvs = [[], [], ["query_1.csv"]]
    text = query_planner._build_step_summaries(str(result_dir), summaries, step_csvs=step_csvs)
    sections = text.split("## 第")
    assert "(本步未产生数据文件)" in sections[1]  # 第1步
    assert "(本步未产生数据文件)" in sections[2]  # 第2步（失败）
    assert "共 1 行" in sections[3]               # 第3步拿到 query_1.csv


def test_step_prompt_forbids_blind_retry_on_timeout():
    """步骤提示词必须包含"数仓超时禁止原样重试"规则。"""
    prompt = query_planner._STEP_SYSTEM_PROMPT_TEMPLATE
    assert "数仓任务超时" in prompt
    assert "禁止原样重试" in prompt
    assert "最多重试 1 次" in prompt
