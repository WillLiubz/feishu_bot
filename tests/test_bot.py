import json
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


def _make_event(chat_id="oc_chat1", text="hello"):
    from types import SimpleNamespace
    msg = SimpleNamespace(
        chat_id=chat_id,
        message_id="om_m1",
        message_type="text",
        content=json.dumps({"text": text}, ensure_ascii=False),
    )
    sender = SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_u1"))
    return SimpleNamespace(event=SimpleNamespace(message=msg, sender=sender))


def test_on_message_game_resolve_failure_releases_locks():
    chat_id = "oc_leak_test"
    event = _make_event(chat_id=chat_id, text="999 昨日充值")
    with patch.object(bot, "_lark_client", return_value=MagicMock()), \
         patch.object(bot.store, "log_in"), \
         patch.object(bot, "_send_text") as mock_send, \
         patch.object(bot.reports, "match", return_value=None), \
         patch.object(bot, "_resolve_game_for_chat", side_effect=ValueError("未配置游戏 999")):
        bot._active_chats.discard(chat_id)
        bot._on_message(event)
    # 错误提示已发送
    assert any("未配置游戏 999" in str(c.args[2]) for c in mock_send.call_args_list)
    # 解析失败不得占用资源：群不在活跃集合，信号量可获取
    assert chat_id not in bot._active_chats
    assert bot._query_sem.acquire(blocking=False)
    bot._query_sem.release()


def test_chatid_command():
    chat_id = "oc_chatid_test"
    event = _make_event(chat_id=chat_id, text="chatid")
    with patch.object(bot, "_lark_client", return_value=MagicMock()), \
         patch.object(bot.store, "log_in"), \
         patch.object(bot, "_handle"), \
         patch.object(bot, "_send_text") as mock_send:
        bot._on_message(event)
    assert mock_send.call_count == 1
    assert mock_send.call_args.args[2] == f"chat_id: {chat_id}"
