"""Tests for the pay_activity SQL template."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import templates


class _GameConfig:
    def __init__(self, game_id):
        self.game_id = game_id


@pytest.fixture
def template():
    return templates.load_template("pay_activity")


def test_default_window_is_single_day(template):
    """付费构成默认分析单日（昨天）。"""
    params = templates.compute_params("付费构成", _GameConfig(312), template["default_params"])
    assert params["analysis_start"] == params["analysis_end"]


def test_all_placeholders_replaced(template):
    params = templates.compute_params("昨天付费构成", _GameConfig(312), template["default_params"])
    for key, sheet in template["games"]["312"].items():
        sql = templates.render_sql(sheet["sql"], params)
        assert "{" not in sql, f"sheet={key} has unreplaced placeholders"


def test_all_sheets_have_game_filter(template):
    for key, sheet in template["games"]["312"].items():
        assert "game_id" in sheet["sql"], f"sheet={key} missing game_id filter"


def test_segment_boundaries(template):
    """9 档美元分层边界与用户确认口径一致。"""
    sql = template["games"]["312"]["payer_segments"]["sql"]
    for frag in [
        "WHEN total < 10 THEN 1", "WHEN total < 20 THEN 2", "WHEN total < 40 THEN 3",
        "WHEN total < 80 THEN 4", "WHEN total < 100 THEN 5", "WHEN total < 150 THEN 6",
        "WHEN total < 200 THEN 7", "WHEN total < 300 THEN 8", "ELSE 9",
        "'<$10'", "'$10~20'", "'$20~40'", "'$40~80'", "'$80~100'",
        "'$100~150'", "'$150~200'", "'$200~300'", "'>=$300'",
    ]:
        assert frag in sql


def test_direct_purchase_split(template):
    """直购按 pay_itemid 的 actId:giftId 识别。"""
    sql = template["games"]["312"]["pay_composition"]["sql"]
    assert "strpos(pay_itemid, ':') > 0" in sql
    assert "split_part(pay_itemid, ':', 1)" in sql


def test_activity_sheets_use_rolepromo_cn_topic(template):
    """活动 Sheet 用 rolepromo 参与记录，主题取多语言 JSON 的 cn 字段。"""
    for key in ("segment_activity", "activity_overview"):
        sql = template["games"]["312"][key]["sql"]
        assert "rolepromo" in sql
        assert "json_extract_scalar" in sql and "'$.cn'" in sql


def test_item_flow_sheet_uses_explicit_cast(template):
    """道具产销 Sheet 走 roleitem，varchar 数值列必须显式 CAST。"""
    sql = template["games"]["312"]["segment_item_flow"]["sql"]
    assert "v_presto_log_roleitem" in sql
    assert "CAST(r.status_after AS BIGINT)" in sql
    assert "CAST(r.status_before AS BIGINT)" in sql
    assert "change_type" in sql


def test_run_report_pay_activity_summary(monkeypatch, template):
    monkeypatch.setattr(templates.dataapi, "run_sql_rows", lambda sql, max_rows=None: [])
    summary, result_dir = templates.run_report("pay_activity", "昨天付费构成", _GameConfig(312))
    assert "【付费构成与活动分析】游戏 312" in summary
    assert "共 7 个 Sheet" in summary
    assert result_dir.split("/")[-1].split("\\")[-1].startswith("pay_activity_")


def test_match_pay_activity_trigger(monkeypatch):
    import config
    import reports

    monkeypatch.setattr(config, "REPORT_TRIGGERS", {
        "player_segment": ["玩家分群", "付费点分析"],
        "pay_activity": ["付费构成", "活动付费分析", "付费活动分析", "付费分层"],
    })
    assert reports.match("312昨日付费构成") == "pay_activity"
    assert reports.match("看一下付费分层情况") == "pay_activity"
    assert reports.match("付费点分析") == "player_segment"


def test_run_dispatch_pay_activity(monkeypatch):
    import reports

    monkeypatch.setattr(
        reports.templates, "run_report",
        lambda name, q, game_config=None: (f"summary:{name}", "/tmp/x"),
    )
    summary, result_dir = reports.run("pay_activity", "付费构成", game_config=_GameConfig(312))
    assert summary == "summary:pay_activity"
    assert result_dir == "/tmp/x"
