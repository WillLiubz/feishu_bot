import json
import os
import re
import threading
import time

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest, CreateMessageRequestBody,
    CreateFileRequest, CreateFileRequestBody,
)

import account_cache
import claude_cli
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


def _send_results(client, chat_id, ws):
    """Send generated result files (Excel or CSV) to Feishu."""
    import os
    xlsx_path = dquery.combine_to_excel(ws["result_dir"])
    if xlsx_path and os.path.exists(xlsx_path):
        _send_file(client, chat_id, xlsx_path, file_name="result.xlsx")
    elif os.path.exists(ws["result_dir"] + "/result.csv"):
        _send_file(client, chat_id, ws["result_dir"] + "/result.csv")


def _handle_simple(client, chat_id, user_id, message_id, text, opgames, game_config, ws):
    """Process a simple query through a single Claude CLI call."""
    t0 = time.time()
    new_sid = None
    try:
        sid = store.get_session(chat_id, game_config.game_id)
        _send_text(client, chat_id, "🔎 正在查询数仓，请稍候…")
        answer, new_sid = claude_cli.run(text, ws, sid)
        store.set_session(chat_id, new_sid, game_config.game_id)
        _send_text(client, chat_id, answer)
        _send_results(client, chat_id, ws)
        _send_query_summary(client, chat_id, message_id)
        latency = int((time.time() - t0) * 1000)
        store.log_out(chat_id, message_id, "ok", latency, session_id=new_sid)
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


def _run_planned_body(client, chat_id, message_id, text, ws):
    """Shared body for planned query handlers. Returns answer text."""
    answer = query_planner.run_planned(text, ws)
    return answer


def _run_planned_with_steps_body(client, chat_id, message_id, text, ws, steps):
    """Shared body for planned query handlers with analyzer-provided steps."""
    summaries = []
    for i, step in enumerate(steps, start=1):
        summary = query_planner.execute_step(step, i, len(steps), ws, summaries)
        summaries.append(summary)
    final_summary = query_planner.summarize(text, ws, summaries)
    answer = "\n".join(f"第{i}步：{s}" for i, s in enumerate(summaries, start=1)) + "\n\n【总结】\n" + final_summary
    return answer


def _planned_handler(client, chat_id, user_id, message_id, text, opgames, game_config, ws, steps=None):
    """Process a complex query. If steps is provided, execute them directly; otherwise plan first."""
    t0 = time.time()
    try:
        _send_text(client, chat_id, "🔎 该问题较复杂，正在分步查询，请稍候…")
        if steps is not None:
            answer = _run_planned_with_steps_body(client, chat_id, message_id, text, ws, steps)
        else:
            answer = _run_planned_body(client, chat_id, message_id, text, ws)
        _send_text(client, chat_id, answer)
        _send_results(client, chat_id, ws)
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
        _send_text(client, chat_id, summary)
        # Some reports return a result directory containing query_N.csv files
        # that should be merged into a multi-sheet Excel.
        if file_or_dir and os.path.isdir(file_or_dir):
            xlsx_path = dquery.combine_to_excel(file_or_dir)
            if xlsx_path and os.path.exists(xlsx_path):
                _send_file(client, chat_id, xlsx_path, file_name="result.xlsx")
            elif os.path.exists(file_or_dir + "/result.csv"):
                _send_file(client, chat_id, file_or_dir + "/result.csv")
        elif file_or_dir:
            _send_file(client, chat_id, file_or_dir)
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

        if any(t in text.lower() for t in config.HELP_TRIGGERS if t not in ("?", "？")) or text.strip() in ("?", "？"):
            _send_text(client, chat_id, config.HELP_TEXT)
            return

        # Whitelist check
        allowed, opgames = _policy(user_id)
        if not allowed:
            _send_text(client, chat_id, "抱歉，你没有使用权限。如需开通请联系管理员。")
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

        try:
            game_config = _resolve_game(text, raise_on_missing=True)
        except ValueError as e:
            _send_text(client, chat_id, str(e))
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
