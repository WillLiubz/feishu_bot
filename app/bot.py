import json
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
import names
import reports
import store
import workspace

_active_chats = set()
_active_lock = threading.Lock()
_query_sem = threading.Semaphore(config.MAX_CONCURRENT_QUERIES)


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


def _handle(client, chat_id, user_id, message_id, text, opgames):
    """Process a query through the LLM path."""
    t0 = time.time()
    new_sid = None
    try:
        sid = store.get_session(chat_id)
        ws = workspace.prepare(chat_id, message_id, opgames)
        _send_text(client, chat_id, "🔎 正在查询数仓，请稍候…")
        answer, new_sid = claude_cli.run(text, ws, sid)
        store.set_session(chat_id, new_sid)
        _send_text(client, chat_id, answer)
        import os
        csv_path = ws["result_dir"] + "/result.csv"
        if os.path.exists(csv_path):
            _send_file(client, chat_id, csv_path)
        latency = int((time.time() - t0) * 1000)
        store.log_out(chat_id, message_id, "ok", latency, session_id=new_sid)
    except RuntimeError as e:
        msg = str(e)
        latency = int((time.time() - t0) * 1000)
        reply = "查询超时，请简化问题后重试" if "超时" in msg else "处理失败，请稍后重试"
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


def _handle_report(client, chat_id, message_id, report_type, text):
    """Process a fixed report."""
    t0 = time.time()
    try:
        summary, csv_path = reports.run(report_type, text)
        _send_text(client, chat_id, summary)
        _send_file(client, chat_id, csv_path)
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

        if any(t in text.lower() for t in config.HELP_TRIGGERS):
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

        # Route: fixed report or LLM
        report_type = reports.match(text)
        if report_type:
            t = threading.Thread(
                target=_handle_report,
                args=(client, chat_id, message_id, report_type, text),
                daemon=True,
            )
        else:
            t = threading.Thread(
                target=_handle,
                args=(client, chat_id, user_id, message_id, text, opgames),
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
        log_level=lark.LogLevel.ERROR,
    )
    return ws
