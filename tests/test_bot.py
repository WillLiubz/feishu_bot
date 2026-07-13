import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

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
