import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import bot


def test_handle_routes_planned_when_analyzer_says_planned(tmp_path):
    ws = {"cwd": str(tmp_path), "mcp_config": str(tmp_path / "mcp.json"), "result_dir": str(tmp_path / "results")}
    game_config = MagicMock()
    game_config.game_id = 312

    planned_result = bot.query_analyzer.AnalysisResult(
        mode="planned",
        reason="跨表",
        steps=[bot.query_planner.PlanStep("查付费", "payrecharge")],
    )

    with patch.object(bot.query_analyzer, "analyze", return_value=planned_result):
        with patch.object(bot, "_handle_planned_with_steps") as mock_planned:
            with patch.object(bot, "_handle_simple") as mock_simple:
                with patch.object(bot.workspace, "prepare", return_value=ws):
                    with patch.object(bot.workspace, "get_claude_md_text", return_value="rules"):
                        bot._handle(None, "chat", "user", "msg", "question", [], game_config)
    mock_planned.assert_called_once()
    mock_simple.assert_not_called()


def _gc(gid, aliases=()):
    gc = MagicMock()
    gc.game_id = gid
    gc.aliases = list(aliases)
    return gc


def test_resolve_game_for_chat_unbound_uses_legacy():
    with patch.object(bot.config, "CHAT_GAMES", {}), \
         patch.object(bot, "_resolve_game", return_value="LEGACY") as m:
        assert bot._resolve_game_for_chat("oc_x", "昨日付费") == "LEGACY"
    m.assert_called_once_with("昨日付费", raise_on_missing=True)


def test_resolve_game_for_chat_bound_no_prefix():
    with patch.object(bot.config, "CHAT_GAMES", {"oc_a": 312}), \
         patch.object(bot.config, "game_config", return_value=_gc(312, ["女3"])) as mg:
        assert bot._resolve_game_for_chat("oc_a", "昨日付费").game_id == 312
    mg.assert_called_once_with(312)


def test_resolve_game_for_chat_bound_same_prefix():
    with patch.object(bot.config, "CHAT_GAMES", {"oc_a": 39}), \
         patch.object(bot.config, "game_config", return_value=_gc(39, ["女1"])):
        assert bot._resolve_game_for_chat("oc_a", "39 昨日充值").game_id == 39


def test_resolve_game_for_chat_bound_other_prefix_rejected():
    with patch.object(bot.config, "CHAT_GAMES", {"oc_a": 312}), \
         patch.object(bot.config, "game_config", return_value=_gc(312, ["女3"])):
        with pytest.raises(ValueError, match="本群仅支持查询游戏 312"):
            bot._resolve_game_for_chat("oc_a", "39 昨日充值")


def test_resolve_game_for_chat_bound_ignores_alias():
    with patch.object(bot.config, "CHAT_GAMES", {"oc_a": 312}), \
         patch.object(bot.config, "game_config", return_value=_gc(312, ["女3"])):
        assert bot._resolve_game_for_chat("oc_a", "女1玩法参与率").game_id == 312
