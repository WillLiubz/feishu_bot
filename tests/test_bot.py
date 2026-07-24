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
            summaries, final, step_csvs, failed = bot._run_planned_with_steps_body(
                None, "chat", "msg", "text", ws,
                [bot.query_planner.PlanStep("g1", "h1"), bot.query_planner.PlanStep("g2", "h2")],
            )
    assert summaries == ["s1", "s2"]
    assert final == "final"
    assert step_csvs == [[], []]
    assert failed == set()


def test_send_charts_prefers_comparison_when_labels_given(tmp_path):
    client = MagicMock()
    with patch.object(bot.charts, "render_comparison_for_dir", return_value=["cmp.png"]) as mc, \
         patch.object(bot.charts, "render_pngs_for_dir") as ms, \
         patch.object(bot, "_send_image") as si:
        bot._send_charts(client, "chat1", str(tmp_path), step_labels=["5月", "6月"])
    mc.assert_called_once_with(str(tmp_path), ["5月", "6月"])
    ms.assert_not_called()
    si.assert_called_once_with(client, "chat1", "cmp.png")


def test_send_charts_falls_back_to_per_query_pngs(tmp_path):
    client = MagicMock()
    with patch.object(bot.charts, "render_comparison_for_dir", return_value=[]), \
         patch.object(bot.charts, "render_pngs_for_dir", return_value=["q1.png"]) as ms, \
         patch.object(bot, "_send_image") as si:
        bot._send_charts(client, "chat1", str(tmp_path), step_labels=["5月", "6月"])
    ms.assert_called_once_with(str(tmp_path))
    si.assert_called_once_with(client, "chat1", "q1.png")


def test_send_charts_without_labels_uses_per_query_pngs(tmp_path):
    client = MagicMock()
    with patch.object(bot.charts, "render_comparison_for_dir") as mc, \
         patch.object(bot.charts, "render_pngs_for_dir", return_value=[]) as ms:
        bot._send_charts(client, "chat1", str(tmp_path))
    mc.assert_not_called()
    ms.assert_called_once_with(str(tmp_path))


def test_run_planned_body_returns_steps(tmp_path):
    ws = {"result_dir": str(tmp_path)}
    plan = bot.query_planner.Plan(steps=[bot.query_planner.PlanStep("g1", "h1")])
    with patch.object(bot.query_planner, "plan", return_value=plan), \
         patch.object(bot.query_planner, "execute_step", return_value="s1"), \
         patch.object(bot.query_planner, "summarize", return_value="final"):
        summaries, final, steps, step_csvs, failed = bot._run_planned_body(None, "chat", "msg", "text", ws)
    assert summaries == ["s1"] and final == "final"
    assert [s.goal for s in steps] == ["g1"]
    assert failed == set()


def test_planned_handler_translates_and_passes_labels(tmp_path):
    ws = {"result_dir": str(tmp_path)}
    game_config = MagicMock()
    game_config.game_id = 39
    steps = [bot.query_planner.PlanStep("查5月充值", "h1"),
             bot.query_planner.PlanStep("查6月充值", "h2")]

    def fake_step(step, n, total, ws, prev):
        # 每步产生一个 query_N.csv，标签才能与文件一一对齐
        Path(ws["result_dir"], f"query_{n}.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        return f"s{n}"

    client = MagicMock()
    # _planned_handler 的 finally 会 release 信号量，先 acquire 模拟真实流程
    assert bot._query_sem.acquire(blocking=False)
    with patch.object(bot, "_send_text"), \
         patch.object(bot, "_send_query_summary"), \
         patch.object(bot, "_send_result_file"), \
         patch.object(bot.query_planner, "execute_step", side_effect=fake_step), \
         patch.object(bot.query_planner, "summarize", return_value="final"), \
         patch.object(bot.name_enrich, "translate_dir", return_value=2) as mt, \
         patch.object(bot, "_send_charts") as msc, \
         patch.object(bot.store, "log_out"):
        bot._planned_handler(client, "chat", "user", "msg", "对比", [], game_config, ws, steps=steps)
    mt.assert_called_once_with(str(tmp_path), game_config)
    assert msc.call_args.kwargs.get("step_labels") == ["查5月充值", "查6月充值"]


def _make_steps(*goals):
    return [bot.query_planner.PlanStep(g, f"h{i}") for i, g in enumerate(goals, 1)]


def test_execute_steps_continues_after_failure(tmp_path):
    """某步抛异常：标记失败、继续后续步骤、CSV 归属不错位。"""
    ws = {"result_dir": str(tmp_path)}
    steps = _make_steps("g1", "g2", "g3")

    def fake_step(step, n, total, ws, prev):
        if n == 2:
            raise RuntimeError("处理超时")
        # 失败步不产生 CSV，后续 CSV 编号前移（与 mcp_server 计数器行为一致）
        name = "query_1.csv" if n == 1 else "query_2.csv"
        Path(ws["result_dir"], name).write_text("a,b\n1,2\n", encoding="utf-8")
        return f"s{n}"

    with patch.object(bot.query_planner, "execute_step", side_effect=fake_step):
        summaries, step_csvs, failed = bot._execute_steps(None, "chat", "text", ws, steps)
    assert failed == {1}
    assert summaries[0] == "s1" and summaries[2] == "s3"
    assert "本步查询失败" in summaries[1] and "处理超时" in summaries[1]
    assert step_csvs == [["query_1.csv"], [], ["query_2.csv"]]


def test_execute_steps_failure_notice_best_effort(tmp_path):
    """失败进度提示：client 异常也不影响步骤继续。"""
    ws = {"result_dir": str(tmp_path)}
    steps = _make_steps("g1", "g2")
    client = MagicMock()
    client.im.v1.message.create.side_effect = RuntimeError("network down")
    with patch.object(bot.query_planner, "execute_step", side_effect=[RuntimeError("处理超时"), "s2"]):
        summaries, step_csvs, failed = bot._execute_steps(client, "chat", "text", ws, steps)
    assert failed == {0} and summaries[1] == "s2"


def test_planned_handler_partial_results_on_step_failure(tmp_path):
    """中间步骤超时：已完成步骤的翻译/图表/xlsx/总结照常返回。"""
    ws = {"result_dir": str(tmp_path)}
    game_config = MagicMock()
    game_config.game_id = 312
    steps = _make_steps("查7月充值", "查玩家行为")

    def fake_step(step, n, total, ws, prev):
        if n == 2:
            raise RuntimeError("处理超时")
        Path(ws["result_dir"], "query_1.csv").write_text("ds,充值\n20260701,100\n", encoding="utf-8")
        return "s1"

    client = MagicMock()
    assert bot._query_sem.acquire(blocking=False)
    with patch.object(bot, "_send_text") as mst, \
         patch.object(bot, "_send_query_summary"), \
         patch.object(bot, "_send_result_file") as msf, \
         patch.object(bot.query_planner, "execute_step", side_effect=fake_step), \
         patch.object(bot.query_planner, "summarize", return_value="final") as msm, \
         patch.object(bot.name_enrich, "translate_dir", return_value=1) as mt, \
         patch.object(bot, "_send_charts") as msc, \
         patch.object(bot.store, "log_out") as mlo:
        bot._planned_handler(client, "chat", "user", "msg", "分析", [], game_config, ws, steps=steps)
    # 下半程完整执行：翻译、图表、xlsx、总结
    mt.assert_called_once_with(str(tmp_path), game_config)
    assert msc.call_args.kwargs.get("step_labels") == ["查7月充值"]
    assert msf.call_args.kwargs.get("conclusions") == ["s1"]
    assert msf.call_args.kwargs.get("final_summary") == "final"
    # summarize 收到对齐后的 step_csvs（第2步无 CSV）
    assert msm.call_args.kwargs.get("step_csvs") == [["query_1.csv"], []]
    # 答案标注失败步骤与"部分结果"提示
    sent = "\n".join(c.args[2] for c in mst.call_args_list)
    assert "本步查询失败" in sent
    assert "部分结果" in sent
    # 有部分结果返回，状态记为 ok
    assert mlo.call_args.args[2] == "ok"


def test_planned_handler_all_steps_failed_sends_no_files(tmp_path):
    """所有步骤失败：只回报失败原因，不调用 summarize、不发图表/附件。"""
    ws = {"result_dir": str(tmp_path)}
    game_config = MagicMock()
    game_config.game_id = 312
    steps = _make_steps("g1", "g2")
    client = MagicMock()
    assert bot._query_sem.acquire(blocking=False)
    with patch.object(bot, "_send_text") as mst, \
         patch.object(bot, "_send_result_file") as msf, \
         patch.object(bot, "_send_charts") as msc, \
         patch.object(bot.query_planner, "execute_step", side_effect=RuntimeError("处理超时")), \
         patch.object(bot.query_planner, "summarize") as msm, \
         patch.object(bot.store, "log_out") as mlo:
        bot._planned_handler(client, "chat", "user", "msg", "分析", [], game_config, ws, steps=steps)
    msm.assert_not_called()
    msc.assert_not_called()
    msf.assert_not_called()
    sent = "\n".join(c.args[2] for c in mst.call_args_list)
    assert "所有步骤均未成功" in sent
    assert mlo.call_args.args[2] == "error"


def test_safe_summarize_falls_back_on_failure(tmp_path):
    ws = {"result_dir": str(tmp_path)}
    with patch.object(bot.query_planner, "summarize", side_effect=RuntimeError("处理超时")):
        result = bot._safe_summarize("q", ws, ["s1"], [["query_1.csv"]])
    assert "最终总结生成失败" in result


def test_handle_simple_timeout_returns_partial_results(tmp_path):
    """simple 模式子进程超时但已有 CSV：走部分结果保底。"""
    ws = {"result_dir": str(tmp_path)}
    Path(ws["result_dir"], "query_1.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    game_config = MagicMock()
    game_config.game_id = 312
    client = MagicMock()
    assert bot._query_sem.acquire(blocking=False)
    with patch.object(bot.store, "get_session", return_value=None), \
         patch.object(bot, "_send_text"), \
         patch.object(bot.claude_cli, "run", side_effect=RuntimeError("处理超时")), \
         patch.object(bot, "_send_partial_results") as msp, \
         patch.object(bot.store, "log_out"):
        bot._handle_simple(client, "chat", "user", "msg", "text", [], game_config, ws)
    msp.assert_called_once()


def test_handle_simple_timeout_without_results_keeps_old_message(tmp_path):
    """simple 模式超时且无任何 CSV：维持原提示，不走部分结果。"""
    ws = {"result_dir": str(tmp_path)}
    game_config = MagicMock()
    game_config.game_id = 312
    client = MagicMock()
    assert bot._query_sem.acquire(blocking=False)
    with patch.object(bot.store, "get_session", return_value=None), \
         patch.object(bot, "_send_text") as mst, \
         patch.object(bot.claude_cli, "run", side_effect=RuntimeError("处理超时")), \
         patch.object(bot, "_send_partial_results") as msp, \
         patch.object(bot.store, "log_out"):
        bot._handle_simple(client, "chat", "user", "msg", "text", [], game_config, ws)
    msp.assert_not_called()
    sent = "\n".join(c.args[2] for c in mst.call_args_list)
    assert "查询超时，请简化问题后重试" in sent


def test_handle_report_pay_activity_enriches_and_interprets(monkeypatch, tmp_path):
    import threading
    from unittest.mock import MagicMock

    import bot

    sent_texts = []
    translated = []
    monkeypatch.setattr(bot.reports, "run",
                        lambda rt, text, game_config=None: ("数据概览", str(tmp_path)))
    monkeypatch.setattr(bot.name_enrich, "translate_dir",
                        lambda d, gc: translated.append(d) or 1)
    monkeypatch.setattr(bot, "_send_charts", lambda *a, **k: None)
    monkeypatch.setattr(bot, "_send_text", lambda c, cid, t: sent_texts.append(t))
    monkeypatch.setattr(bot, "_send_result_file", lambda *a, **k: None)
    monkeypatch.setattr(bot.store, "log_out", lambda *a, **k: None)
    monkeypatch.setattr(bot.workspace, "prepare",
                        lambda *a, **k: {"cwd": str(tmp_path), "mcp_config": "m",
                                         "result_dir": str(tmp_path)})
    monkeypatch.setattr(bot.report_insight, "interpret", lambda q, d, ws: "解读文本")
    monkeypatch.setattr(bot, "_query_sem", threading.Semaphore(1))
    bot._query_sem.acquire()  # _handle_report 的 finally 会 release

    bot._handle_report(None, "oc_chat", "om_msg", "pay_activity", "付费构成",
                       MagicMock(game_id=312))

    assert translated == [str(tmp_path)]
    full = "\n".join(sent_texts)
    assert "数据概览" in full
    assert "【经营解读】" in full and "解读文本" in full


def test_handle_report_pay_activity_insight_failure_still_sends(monkeypatch, tmp_path):
    import threading
    from unittest.mock import MagicMock

    import bot

    sent_texts = []
    monkeypatch.setattr(bot.reports, "run",
                        lambda rt, text, game_config=None: ("数据概览", str(tmp_path)))
    monkeypatch.setattr(bot.name_enrich, "translate_dir", lambda d, gc: 0)
    monkeypatch.setattr(bot, "_send_charts", lambda *a, **k: None)
    monkeypatch.setattr(bot, "_send_text", lambda c, cid, t: sent_texts.append(t))
    monkeypatch.setattr(bot, "_send_result_file", lambda *a, **k: None)
    monkeypatch.setattr(bot.store, "log_out", lambda *a, **k: None)
    monkeypatch.setattr(bot.workspace, "prepare",
                        lambda *a, **k: {"cwd": str(tmp_path), "mcp_config": "m",
                                         "result_dir": str(tmp_path)})

    def boom(q, d, ws):
        raise RuntimeError("处理超时")

    monkeypatch.setattr(bot.report_insight, "interpret", boom)
    monkeypatch.setattr(bot, "_query_sem", threading.Semaphore(1))
    bot._query_sem.acquire()

    bot._handle_report(None, "oc_chat", "om_msg", "pay_activity", "付费构成",
                       MagicMock(game_id=312))

    full = "\n".join(sent_texts)
    assert "数据概览" in full
    assert "【经营解读】" not in full
