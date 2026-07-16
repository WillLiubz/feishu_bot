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


def test_send_image_uploads_then_sends_image_message(tmp_path):
    client = MagicMock()
    up_resp = MagicMock()
    up_resp.success.return_value = True
    up_resp.data.image_key = "img_key_1"
    client.im.v1.image.create.return_value = up_resp
    img = tmp_path / "q.png"
    img.write_bytes(b"\x89PNG fake")
    bot._send_image(client, "chat1", str(img))
    client.im.v1.image.create.assert_called_once()
    client.im.v1.message.create.assert_called_once()
    req = client.im.v1.message.create.call_args[0][0]
    assert req.request_body.msg_type == "image"
    assert json.loads(req.request_body.content) == {"image_key": "img_key_1"}


def test_send_image_skips_message_when_upload_fails(tmp_path):
    client = MagicMock()
    up_resp = MagicMock()
    up_resp.success.return_value = False
    client.im.v1.image.create.return_value = up_resp
    img = tmp_path / "q.png"
    img.write_bytes(b"\x89PNG fake")
    bot._send_image(client, "chat1", str(img))
    client.im.v1.message.create.assert_not_called()


def test_send_charts_never_raises(tmp_path):
    client = MagicMock()
    with patch.object(bot.charts, "render_pngs_for_dir", side_effect=RuntimeError("boom")):
        bot._send_charts(client, "chat1", str(tmp_path))  # 不应抛异常
    client.im.v1.message.create.assert_not_called()


def test_send_charts_sends_each_png(tmp_path):
    client = MagicMock()
    up_resp = MagicMock()
    up_resp.success.return_value = True
    up_resp.data.image_key = "k"
    client.im.v1.image.create.return_value = up_resp
    p1 = tmp_path / "query_1.png"
    p2 = tmp_path / "query_2.png"
    p1.write_bytes(b"\x89PNG fake")
    p2.write_bytes(b"\x89PNG fake")
    with patch.object(bot.charts, "render_pngs_for_dir", return_value=[str(p1), str(p2)]):
        bot._send_charts(client, "chat1", str(tmp_path))
    assert client.im.v1.image.create.call_count == 2
    assert client.im.v1.message.create.call_count == 2


def test_send_result_file_passes_conclusions_through(tmp_path):
    client = MagicMock()
    xlsx = tmp_path / "result.xlsx"
    xlsx.write_bytes(b"x")
    with patch.object(bot.dquery, "combine_to_excel", return_value=str(xlsx)) as m:
        with patch.object(bot, "_send_file") as sf:
            bot._send_result_file(client, "chat1", str(tmp_path),
                                  conclusions=["c1"], final_summary="fs")
    m.assert_called_once_with(str(tmp_path), conclusions=["c1"], final_summary="fs")
    sf.assert_called_once()


def test_planned_body_returns_structured_summaries(tmp_path):
    ws = {"result_dir": str(tmp_path)}
    with patch.object(bot.query_planner, "execute_step", side_effect=["s1", "s2"]):
        with patch.object(bot.query_planner, "summarize", return_value="final"):
            summaries, final = bot._run_planned_with_steps_body(
                None, "chat", "msg", "text", ws,
                [bot.query_planner.PlanStep("g1", "h1"), bot.query_planner.PlanStep("g2", "h2")],
            )
    assert summaries == ["s1", "s2"]
    assert final == "final"
