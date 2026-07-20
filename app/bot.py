import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest, CreateMessageRequestBody,
    CreateFileRequest, CreateFileRequestBody,
)

import account_cache
import charts
import claude_cli
import name_enrich
import config
import dquery
import names
import query_analyzer
import query_planner
import reports
import store
import workspace

_active_chats = set()
_active_lock = threading.Lock()
_query_sem = threading.Semaphore(config.MAX_CONCURRENT_QUERIES)

_game_id_pattern = re.compile(r'^(\d+)\s+')


def _lark_client():
    return lark.Client.builder() \
        .app_id(config.FEISHU_APP_ID) \
        .app_secret(config.FEISHU_APP_SECRET) \
        .build()


def _send_text(client, chat_id, text):
    req = CreateMessageRequest.builder() \
        .receive_id_type("chat_id") \
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        ).build()
    client.im.v1.message.create(req)


def _send_file(client, chat_id, file_path, file_name="result.csv"):
    with open(file_path, "rb") as f:
        up_req = CreateFileRequest.builder() \
            .request_body(
                CreateFileRequestBody.builder()
                .file_type("stream")
                .file_name(file_name)
                .file(f)
                .build()
            ).build()
        up_resp = client.im.v1.file.create(up_req)
    if not up_resp.success():
        return
    file_key = up_resp.data.file_key
    req = CreateMessageRequest.builder() \
        .receive_id_type("chat_id") \
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("file")
            .content(json.dumps({"file_key": file_key}))
            .build()
        ).build()
    client.im.v1.message.create(req)


def _extract_text(event):
    """Extract plain text from a message event (text or post type)."""
    msg = event.event.message
    try:
        content = json.loads(msg.content)
    except Exception:
        return None
    if msg.message_type == "text":
        text = content.get("text", "")
    elif msg.message_type == "post":
        parts = []
        for para in content.get("content", []):
            for item in para:
                if item.get("tag") == "text":
                    parts.append(item.get("text", ""))
        text = " ".join(parts)
    else:
        return None
    # Remove @mention placeholders added by Feishu in group chats
    text = re.sub(r'@_user_\d+', '', text).strip()
    return text if text else None


def _policy(user_id):
    """
    Return (allowed: bool, opgames: list).
    If WHITELIST is False, everyone is allowed with no opgame restriction.
    """
    if not config.WHITELIST:
        return True, []
    if user_id not in config.USER_OPGAMES:
        return False, []
    val = config.USER_OPGAMES[user_id]
    if val == "*":
        return True, []
    return True, list(val)


def _resolve_game(text, raise_on_missing=False):
    """Resolve game_id from text prefix or alias. Defaults to config.GAME_ID.

    If the user explicitly writes a game_id prefix and that game is not
    configured, raise ValueError when raise_on_missing=True; otherwise fall
    back to the default game for backwards compatibility.
    """
    if not text:
        return config.game_config()

    # Leading number like "312 查询..."
    m = _game_id_pattern.match(text)
    if m:
        gid = int(m.group(1))
        try:
            return config.game_config(gid)
        except ValueError:
            if raise_on_missing:
                raise ValueError(
                    f"未配置游戏 {gid}，请联系管理员在 config.json 的 games 中添加对应配置。"
                )
            # Fall back to default game when not in strict mode.
            pass

    # Aliases
    lowered = text.lower()
    if config.MULTI_GAME_MODE:
        for gid, gc in config.GAMES.items():
            for alias in gc.aliases:
                if alias.lower() in lowered:
                    return gc

    return config.game_config()

def _resolve_game_for_chat(chat_id, text):
    """Resolve game for a chat: bound chats are pinned to their game.

    Unbound chats keep the legacy resolution (prefix -> alias -> default).
    Bound chats skip prefix/alias matching entirely; an explicit numeric
    prefix for a DIFFERENT game is rejected with ValueError.
    """
    bound_gid = config.CHAT_GAMES.get(chat_id)
    if bound_gid is None:
        return _resolve_game(text, raise_on_missing=True)
    gc = config.game_config(bound_gid)
    m = _game_id_pattern.match(text or "")
    if m and int(m.group(1)) != bound_gid:
        aliases = "/".join(gc.aliases) if gc.aliases else str(bound_gid)
        raise ValueError(
            f"本群仅支持查询游戏 {bound_gid}（{aliases}），"
            f"如需查询游戏 {int(m.group(1))} 请到对应群。"
        )
    return gc

def _send_query_summary(client, chat_id, message_id):
    """Send SQL execution details to Feishu after a query."""
    import sqlite3
    from pathlib import Path
    db_path = Path(config._ROOT) / "data" / "bot.db"
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT sql, row_count, status, latency_ms, error FROM query_log"
            " WHERE message_id=? ORDER BY id",
            (message_id,)
        ).fetchall()
        conn.close()
    except Exception:
        return
    if not rows:
        return
    lines = ["📊 执行详情："]
    for i, (sql, row_count, status, latency_ms, error) in enumerate(rows, 1):
        short_sql = (sql or "")[:150].replace('\n', ' ')
        if status == "ok":
            lines.append(f"第{i}次查询（{latency_ms}ms）：{short_sql}\n→ 返回 {row_count} 行")
        else:
            lines.append(f"第{i}次查询（{status}）：{short_sql}\n→ {str(error or '')[:120]}")
    _send_text(client, chat_id, "\n".join(lines))


def _send_image(client, chat_id, image_path):
    """Upload an image file and send it as an image message. Never raises."""
    from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody
    try:
        with open(image_path, "rb") as f:
            up_req = CreateImageRequest.builder() \
                .request_body(
                    CreateImageRequestBody.builder()
                    .image_type("message")
                    .image(f)
                    .build()
                ).build()
            up_resp = client.im.v1.image.create(up_req)
        if not up_resp.success():
            print(f"[bot] image upload failed: {up_resp.code} {up_resp.msg}", flush=True)
            return
        image_key = up_resp.data.image_key
        req = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("image")
                .content(json.dumps({"image_key": image_key}))
                .build()
            ).build()
        client.im.v1.message.create(req)
    except Exception as e:
        print(f"[bot] send image failed: {e}", flush=True)


def _send_charts(client, chat_id, result_dir, step_labels=None):
    """Render PNG charts and send as image messages. Never raises.

    带 step_labels（分步查询）时先尝试合成跨期对比图；
    结构不兼容时退回每期单图。
    """
    try:
        pngs = []
        if step_labels and len(step_labels) >= 2:
            pngs = charts.render_comparison_for_dir(result_dir, step_labels)
        if not pngs:
            pngs = charts.render_pngs_for_dir(result_dir)
        for png in pngs:
            _send_image(client, chat_id, png)
    except Exception as e:
        print(f"[bot] send charts failed: {e}", flush=True)


def _send_result_file(client, chat_id, result_dir, conclusions=None, final_summary=None):
    """Combine query CSVs into result.xlsx (with charts and conclusions) and send it."""
    import os
    xlsx_path = dquery.combine_to_excel(
        result_dir, conclusions=conclusions, final_summary=final_summary
    )
    if xlsx_path and os.path.exists(xlsx_path):
        _send_file(client, chat_id, xlsx_path, file_name="result.xlsx")
    elif os.path.exists(result_dir + "/result.csv"):
        _send_file(client, chat_id, result_dir + "/result.csv")


def _read_csv_rows(csv_path):
    """Read a CSV file into list[dict]; returns [] on failure."""
    import csv as _csv
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            return list(_csv.DictReader(f))
    except Exception:
        return []


def _query_csv_snapshot(result_dir):
    """Return the set of query_*.csv file names currently in result_dir."""
    try:
        return {p.name for p in Path(result_dir).glob("query_*.csv")}
    except Exception:
        return set()


def _csv_sort_key(name):
    m = re.search(r"query_(\d+)", name)
    return int(m.group(1)) if m else 0


def _send_partial_results(client, chat_id, result_dir, game_config, note, step_labels=None):
    """Best-effort delivery of whatever query_*.csv already exist.

    Used when a query times out mid-way: never raises, never blocks the
    error-handling path.
    """
    try:
        if game_config is not None:
            name_enrich.translate_dir(result_dir, game_config)
        _send_charts(client, chat_id, result_dir, step_labels=step_labels)
        _send_text(client, chat_id, note)
        _send_result_file(client, chat_id, result_dir, conclusions=[note])
    except Exception as e:
        print(f"[bot] send partial results failed: {e}", flush=True)


def _handle_simple(client, chat_id, user_id, message_id, text, opgames, game_config, ws):
    """Process a simple query through a single Claude CLI call."""
    t0 = time.time()
    new_sid = None
    try:
        sid = store.get_session(chat_id, game_config.game_id)
        _send_text(client, chat_id, "🔎 正在查询数仓，请稍候…")
        answer, new_sid = claude_cli.run(text, ws, sid)
        store.set_session(chat_id, new_sid, game_config.game_id)
        name_enrich.translate_dir(ws["result_dir"], game_config)
        _send_charts(client, chat_id, ws["result_dir"])
        _send_text(client, chat_id, answer)
        _send_result_file(client, chat_id, ws["result_dir"], conclusions=[answer])
        _send_query_summary(client, chat_id, message_id)
        latency = int((time.time() - t0) * 1000)
        store.log_out(chat_id, message_id, "ok", latency, session_id=new_sid)
    except RuntimeError as e:
        msg = str(e)
        latency = int((time.time() - t0) * 1000)
        if "超时" in msg:
            if _query_csv_snapshot(ws["result_dir"]):
                # 子进程超时但已查到部分数据：把已获得的结果返回，不让用户一无所获
                _send_partial_results(
                    client, chat_id, ws["result_dir"], game_config,
                    "查询超时，以下为已获取的部分结果（明细见附件）：",
                )
            else:
                _send_text(client, chat_id, "查询超时，请简化问题后重试")
        else:
            detail = msg[:300].replace('\n', ' ')
            reply = f"处理失败：{detail}"
            _send_text(client, chat_id, reply)
        store.log_out(chat_id, message_id, "error", latency, error=msg)
    except ValueError as e:
        latency = int((time.time() - t0) * 1000)
        _send_text(client, chat_id, "该查询不符合权限限制")
        store.log_out(chat_id, message_id, "guard_error", latency, error=str(e))
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        _send_text(client, chat_id, "处理失败，请稍后重试")
        store.log_out(chat_id, message_id, "error", latency, error=str(e))
    finally:
        _query_sem.release()
        with _active_lock:
            _active_chats.discard(chat_id)


def _execute_steps(client, chat_id, text, ws, steps):
    """Execute planned steps one by one, tolerating per-step failures.

    A step that raises (e.g. claude 子进程超时) is marked failed and the
    remaining steps continue — 已完成的步骤结果不再被整体丢弃。

    Returns (summaries, step_csvs, failed):
      summaries[i] — 第 i 步中文总结；失败时为带标记的说明
      step_csvs[i] — 第 i 步实际产生的 query_*.csv 文件名列表（按编号排序）
      failed       — 失败步骤的下标集合（0-based）
    """
    summaries, step_csvs, failed = [], [], set()
    total = len(steps)
    for i, step in enumerate(steps, start=1):
        before = _query_csv_snapshot(ws["result_dir"])
        try:
            summary = query_planner.execute_step(step, i, total, ws, summaries)
        except Exception as e:
            failed.add(i - 1)
            summary = f"（本步查询失败：{str(e)[:120]}）"
            try:
                if client is not None:
                    _send_text(client, chat_id,
                               f"⚠️ 第{i}/{total}步（{step.goal}）执行失败：{str(e)[:80]}，继续执行剩余步骤…")
            except Exception:
                pass
        after = _query_csv_snapshot(ws["result_dir"])
        step_csvs.append(sorted(after - before, key=_csv_sort_key))
        summaries.append(summary)
    return summaries, step_csvs, failed


def _safe_summarize(text, ws, summaries, step_csvs):
    """LLM 最终总结；失败时兜底，绝不让已获得的各步结果丢失。"""
    try:
        return query_planner.summarize(text, ws, summaries, step_csvs=step_csvs)
    except Exception as e:
        print(f"[bot] summarize failed: {e}", flush=True)
        return "（最终总结生成失败，以上为各步实际查询结果，明细见附件）"


def _run_planned_body(client, chat_id, message_id, text, ws):
    """Plan first, then execute. Returns (summaries, final_summary, steps, step_csvs, failed)."""
    plan_obj = query_planner.plan(text, ws)
    summaries, step_csvs, failed = _execute_steps(client, chat_id, text, ws, plan_obj.steps)
    final_summary = "" if len(failed) == len(plan_obj.steps) else _safe_summarize(text, ws, summaries, step_csvs)
    return summaries, final_summary, plan_obj.steps, step_csvs, failed


def _run_planned_with_steps_body(client, chat_id, message_id, text, ws, steps):
    """Execute analyzer-provided steps. Returns (summaries, final_summary, step_csvs, failed)."""
    summaries, step_csvs, failed = _execute_steps(client, chat_id, text, ws, steps)
    final_summary = "" if len(failed) == len(steps) else _safe_summarize(text, ws, summaries, step_csvs)
    return summaries, final_summary, step_csvs, failed


def _planned_handler(client, chat_id, user_id, message_id, text, opgames, game_config, ws, steps=None):
    """Process a complex query. If steps is provided, execute them directly; otherwise plan first."""
    t0 = time.time()
    try:
        _send_text(client, chat_id, "🔎 该问题较复杂，正在分步查询，请稍候…")
        if steps is not None:
            summaries, final_summary, step_csvs, failed = _run_planned_with_steps_body(client, chat_id, message_id, text, ws, steps)
        else:
            summaries, final_summary, steps, step_csvs, failed = _run_planned_body(client, chat_id, message_id, text, ws)
        answer = "\n".join(f"第{i}步：{s}" for i, s in enumerate(summaries, start=1))
        if final_summary:
            answer += "\n\n【总结】\n" + final_summary
        if len(failed) == len(steps):
            # 所有步骤都失败：只回报失败原因，不发送空附件
            _send_text(client, chat_id, answer + "\n\n所有步骤均未成功，请简化问题后重试")
            latency = int((time.time() - t0) * 1000)
            store.log_out(chat_id, message_id, "error", latency, error="all steps failed")
            return
        if failed:
            answer += f"\n\n⚠️ 其中 {len(failed)} 步未成功，以上为已完成步骤的部分结果"
        # 失败步骤不产生 CSV，后续 CSV 编号前移：标签/结论必须按"每步实际产出的
        # CSV"对齐，而不是按步骤下标对齐
        csv_labels = [steps[i].goal for i, csvs in enumerate(step_csvs) for _ in csvs]
        csv_conclusions = [summaries[i] for i, csvs in enumerate(step_csvs) for _ in csvs]
        name_enrich.translate_dir(ws["result_dir"], game_config)
        _send_charts(client, chat_id, ws["result_dir"], step_labels=csv_labels)
        _send_text(client, chat_id, answer)
        _send_result_file(client, chat_id, ws["result_dir"],
                          conclusions=csv_conclusions, final_summary=final_summary or None)
        _send_query_summary(client, chat_id, message_id)
        latency = int((time.time() - t0) * 1000)
        store.log_out(chat_id, message_id, "ok", latency)
    except RuntimeError as e:
        msg = str(e)
        latency = int((time.time() - t0) * 1000)
        if "超时" in msg:
            reply = "查询超时，请简化问题后重试"
        else:
            detail = msg[:300].replace('\n', ' ')
            reply = f"处理失败：{detail}"
        _send_text(client, chat_id, reply)
        store.log_out(chat_id, message_id, "error", latency, error=msg)
    except ValueError as e:
        latency = int((time.time() - t0) * 1000)
        _send_text(client, chat_id, "该查询不符合权限限制")
        store.log_out(chat_id, message_id, "guard_error", latency, error=str(e))
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        _send_text(client, chat_id, "处理失败，请稍后重试")
        store.log_out(chat_id, message_id, "error", latency, error=str(e))
    finally:
        _query_sem.release()
        with _active_lock:
            _active_chats.discard(chat_id)


def _handle_planned(client, chat_id, user_id, message_id, text, opgames, game_config, ws):
    """Process a complex query by splitting it into multiple planned steps."""
    _planned_handler(client, chat_id, user_id, message_id, text, opgames, game_config, ws, steps=None)


def _handle_planned_with_steps(client, chat_id, user_id, message_id, text, opgames, game_config, ws, steps):
    """Process a complex query using analyzer-provided steps."""
    _planned_handler(client, chat_id, user_id, message_id, text, opgames, game_config, ws, steps=steps)


def _handle(client, chat_id, user_id, message_id, text, opgames, game_config):
    """Route a query to simple or planned handler based on LLM analysis."""
    ws = workspace.prepare(chat_id, message_id, game_config=game_config, opgames=opgames)
    claude_md_text = workspace.get_claude_md_text(ws)
    result = query_analyzer.analyze(text, ws, claude_md_text, game_id=game_config.game_id)
    if result.mode == "planned" and result.steps:
        _handle_planned_with_steps(client, chat_id, user_id, message_id, text, opgames, game_config, ws, result.steps)
    elif result.mode == "planned":
        _handle_planned(client, chat_id, user_id, message_id, text, opgames, game_config, ws)
    else:
        _handle_simple(client, chat_id, user_id, message_id, text, opgames, game_config, ws)


def _handle_report(client, chat_id, message_id, report_type, text, game_config):
    """Process a fixed report."""
    t0 = time.time()
    try:
        _send_text(client, chat_id, "📊 正在生成固定报表，请稍候…")
        summary, file_or_dir = reports.run(report_type, text, game_config=game_config)
        if file_or_dir and os.path.isdir(file_or_dir):
            # 多步报表（如玩家分层）：与 LLM 查询一致，图 → 文字 → 文件
            _send_charts(client, chat_id, file_or_dir)
            _send_text(client, chat_id, summary)
            _send_result_file(client, chat_id, file_or_dir, conclusions=[summary])
        elif file_or_dir:
            # 单 CSV 报表（KPI/LTV/月榜）：构造带图表+结论的 xlsx
            rows = _read_csv_rows(file_or_dir)
            if rows:
                try:
                    ctype = charts.detect_chart_type(rows)
                    if ctype:
                        fd, png_path = tempfile.mkstemp(suffix=".png")
                        os.close(fd)
                        try:
                            png = charts.render_png(rows, ctype, report_type, png_path)
                            if png:
                                _send_image(client, chat_id, png)
                        finally:
                            try:
                                os.remove(png_path)
                            except OSError:
                                pass
                except Exception as e:
                    print(f"[bot] report chart failed: {e}", flush=True)
            _send_text(client, chat_id, summary)
            if rows:
                try:
                    xlsx = dquery.rows_to_xlsx(rows, summary, title=report_type)
                    _send_file(client, chat_id, xlsx, file_name="result.xlsx")
                except Exception as e:
                    print(f"[bot] rows_to_xlsx failed: {e}", flush=True)
                    _send_file(client, chat_id, file_or_dir)
            else:
                _send_file(client, chat_id, file_or_dir)
        else:
            _send_text(client, chat_id, summary)
        store.log_out(chat_id, message_id, "ok", int((time.time() - t0) * 1000))
    except Exception as e:
        _send_text(client, chat_id, "报表生成失败，请稍后重试")
        store.log_out(chat_id, message_id, "error", int((time.time() - t0) * 1000), error=str(e))
    finally:
        _query_sem.release()
        with _active_lock:
            _active_chats.discard(chat_id)


def _on_message(data):
    """Main event handler for im.message.receive_v1."""
    import sys as _sys
    _sys.stderr.write(f"[bot] _on_message called type={type(data)}\n")
    _sys.stderr.flush()
    try:
        client = _lark_client()
        event = data
        msg = event.event.message
        chat_id = msg.chat_id
        user_id = event.event.sender.sender_id.open_id
        message_id = msg.message_id

        text = _extract_text(event)
        print(f"[bot] recv chat={chat_id[-8:]} user={user_id[-8:]} text={repr(text)}", flush=True)
        if not text:
            return

        store.log_in(chat_id, user_id, message_id, text)

        # Instant commands (no whitelist check)
        if text.strip().lower() == "whoami":
            uname = names.user_name(user_id)
            allowed, opgames = _policy(user_id)
            scope = "全部渠道" if not opgames else str(opgames)
            _send_text(client, chat_id,
                       f"你好 {uname}\nopen_id: {user_id}\n可查范围: {scope}")
            return

        if text.strip().lower() == "chatid":
            _send_text(client, chat_id, f"chat_id: {chat_id}")
            return

        if any(t in text.lower() for t in config.HELP_TRIGGERS if t not in ("?", "？")) or text.strip() in ("?", "？"):
            _send_text(client, chat_id, config.HELP_TEXT)
            return

        # Whitelist check
        allowed, opgames = _policy(user_id)
        if not allowed:
            _send_text(client, chat_id, "抱歉，你没有使用权限。如需开通请联系管理员。")
            return

        # Resolve game BEFORE acquiring locks: a failed resolution must not
        # leak the semaphore / active-chat slot (that wedged the chat).
        try:
            game_config = _resolve_game_for_chat(chat_id, text)
        except ValueError as e:
            _send_text(client, chat_id, str(e))
            return

        # Concurrency: per-chat serialization
        with _active_lock:
            if chat_id in _active_chats:
                _send_text(client, chat_id, "上一条查询还未完成，请等待结果后再提问。")
                return
            _active_chats.add(chat_id)

        # Concurrency: global semaphore
        if not _query_sem.acquire(blocking=False):
            with _active_lock:
                _active_chats.discard(chat_id)
            _send_text(client, chat_id, "当前查询较多，请稍后再试。")
            return

        # Route: fixed report or LLM
        report_type = reports.match(text)
        if report_type:
            t = threading.Thread(
                target=_handle_report,
                args=(client, chat_id, message_id, report_type, text, game_config),
                daemon=True,
            )
        else:
            t = threading.Thread(
                target=_handle,
                args=(client, chat_id, user_id, message_id, text, opgames, game_config),
                daemon=True,
            )

        try:
            t.start()
        except Exception:
            _query_sem.release()
            with _active_lock:
                _active_chats.discard(chat_id)

    except Exception as e:
        print(f"[bot] _on_message error: {e}", flush=True)
        import traceback
        traceback.print_exc()


def build_ws_client():
    """Build and return the Feishu WebSocket client."""
    handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(_on_message) \
        .build()

    ws = lark.ws.Client(
        config.FEISHU_APP_ID,
        config.FEISHU_APP_SECRET,
        event_handler=handler,
        log_level=lark.LogLevel.DEBUG,
    )
    return ws
