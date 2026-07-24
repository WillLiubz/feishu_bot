"""Tests for the player_segment SQL template engine."""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

# Ensure app/ is importable
sys.path.insert(0, "app")

import templates


class _GameConfig:
    """Minimal stand-in for config.GameConfig."""

    def __init__(self, game_id):
        self.game_id = game_id


@pytest.fixture
def template():
    return templates.load_template("player_segment")


@pytest.mark.parametrize(
    "text,expected_days",
    [
        ("近7天玩家分群", 7),
        ("近14天", 14),
        ("近30天", 30),
        ("昨天", 1),
        ("本周", date.today().weekday() + 1),
    ],
)
def test_parse_window_days(template, text, expected_days):
    gc = _GameConfig(312)
    params = templates.compute_params(text, gc, template["default_params"])
    analysis_start = datetime.strptime(params["analysis_start"], "%Y%m%d").date()
    analysis_end = datetime.strptime(params["analysis_end"], "%Y%m%d").date()
    assert (analysis_end - analysis_start).days + 1 == expected_days


def test_default_window_ends_yesterday(template):
    gc = _GameConfig(312)
    params = templates.compute_params("玩家分群", gc, template["default_params"])
    assert params["analysis_end"] == (date.today() - timedelta(days=1)).strftime("%Y%m%d")


def test_silent_window_precedes_analysis_window(template):
    gc = _GameConfig(312)
    params = templates.compute_params("玩家分群", gc, template["default_params"])
    analysis_start = datetime.strptime(params["analysis_start"], "%Y%m%d").date()
    silent_end = datetime.strptime(params["silent_end"], "%Y%m%d").date()
    assert silent_end == analysis_start - timedelta(days=1)


@pytest.mark.parametrize("game_id", [312, 160, 39])
def test_all_placeholders_replaced(template, game_id):
    gc = _GameConfig(game_id)
    params = templates.compute_params("近7天玩家分群", gc, template["default_params"])
    sheets = template["games"][str(game_id)]
    for key, sheet in sheets.items():
        sql = templates.render_sql(sheet["sql"], params)
        assert "{" not in sql, f"game={game_id} sheet={key} has unreplaced placeholders"


@pytest.mark.parametrize("game_id", [312, 160, 39])
def test_rendered_sql_contains_game_filter(template, game_id):
    gc = _GameConfig(game_id)
    params = templates.compute_params("近7天玩家分群", gc, template["default_params"])
    sheets = template["games"][str(game_id)]
    for key, sheet in sheets.items():
        sql = templates.render_sql(sheet["sql"], params)
        assert "game_id" in sql.lower() or "gameid" in sql.lower(), (
            f"game={game_id} sheet={key} missing game_id/gameid filter"
        )


def test_game_39_uses_gameid_string(template):
    gc = _GameConfig(39)
    params = templates.compute_params("近7天玩家分群", gc, template["default_params"])
    sheets = template["games"]["39"]
    for key, sheet in sheets.items():
        sql = templates.render_sql(sheet["sql"], params)
        assert "gameid = '39'" in sql, f"game=39 sheet={key} should filter by gameid = '39'"


def test_server_filter_for_312_and_160(template):
    for game_id in (312, 160):
        gc = _GameConfig(game_id)
        params = templates.compute_params("近7天", gc, template["default_params"])
        assert "SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'" in params["server_filter"]


def test_server_filter_empty_for_39(template):
    gc = _GameConfig(39)
    params = templates.compute_params("近7天", gc, template["default_params"])
    assert params["server_filter"] == ""


@pytest.mark.parametrize("game_id", [312, 160, 39])
def test_all_column_aliases_are_ascii(template, game_id):
    """Data API rejects Chinese column aliases, so SQL aliases must be ASCII."""
    gc = _GameConfig(game_id)
    params = templates.compute_params("近7天玩家分群", gc, template["default_params"])
    sheets = template["games"][str(game_id)]
    for key, sheet in sheets.items():
        sql = templates.render_sql(sheet["sql"], params)
        # Extract aliases after AS and ensure they are ASCII.
        import re
        aliases = re.findall(r"\bAS\s+(\w+)", sql, re.IGNORECASE)
        for alias in aliases:
            assert alias.isascii(), (
                f"game={game_id} sheet={key} has non-ASCII alias: {alias}"
            )


@pytest.mark.parametrize("game_id", [312, 160, 39])
def test_every_sheet_has_column_mapping(template, game_id):
    sheets = template["games"][str(game_id)]
    for key, sheet in sheets.items():
        assert "columns" in sheet, f"game={game_id} sheet={key} missing columns mapping"
        assert sheet["columns"], f"game={game_id} sheet={key} has empty columns mapping"


def test_column_mapping_renames_output(template):
    """run_report should rename dict keys according to the sheet's columns mapping."""
    gc = _GameConfig(312)

    # Patch dataapi to return predictable rows without hitting the network.
    import dataapi
    original_run_sql_rows = dataapi.run_sql_rows
    def _mock_run_sql_rows(sql, max_rows=None):
        return [{"segment": "paid", "user_count": "100", "pay_amount": "1234.56"}]
    dataapi.run_sql_rows = _mock_run_sql_rows
    try:
        summary, result_dir = templates.run_report("player_segment", "近7天", gc)
        csv_text = Path(result_dir).joinpath("query_1.csv").read_text(encoding="utf-8-sig")
        # First data row should contain Chinese headers, not English aliases.
        assert "分群" in csv_text
        assert "人数" in csv_text
        assert "充值金额" in csv_text
    finally:
        dataapi.run_sql_rows = original_run_sql_rows


def test_run_report_summary_and_dir_prefix(monkeypatch, tmp_path):
    """run_report 的 summary 由模板 summary_template 驱动，目录前缀=模板名。"""
    monkeypatch.setattr(templates.dataapi, "run_sql_rows", lambda sql, max_rows=None: [])
    summary, result_dir = templates.run_report(
        "player_segment", "近7天玩家分群", _GameConfig(312)
    )
    assert "【玩家分群分析】游戏 312" in summary
    assert "分析窗口" in summary and "沉默窗口" in summary
    assert "共 6 个 Sheet" in summary
    assert result_dir.split("/")[-1].split("\\")[-1].startswith("player_segment_")
