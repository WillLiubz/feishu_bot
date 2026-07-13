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
