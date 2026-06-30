"""
调试 bot.py 中的纯逻辑组件（无需飞书连接）。

用法：
    python debug/test_bot_components.py
"""
import io
import json
import sys
from pathlib import Path

# Force UTF-8 output on Windows to avoid mojibake
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import bot
import config


def _make_text_event(text: str):
    """Build a minimal Feishu P2ImMessageReceiveV1-like object."""
    class Msg:
        message_type = "text"
        content = json.dumps({"text": text}, ensure_ascii=False)
        chat_id = "debug_chat_001"
        message_id = "debug_msg_001"

    class Sender:
        class SenderId:
            open_id = "debug_user_001"
        sender_id = SenderId()

    class Event:
        message = Msg()
        sender = Sender()

    class Data:
        event = Event()

    return Data()


def main():
    print(f"当前白名单开关: {config.WHITELIST}")
    print(f"HELP_TRIGGERS: {config.HELP_TRIGGERS}")
    print(f"REPORT_TRIGGERS: {config.REPORT_TRIGGERS}\n")

    # Test text extraction
    samples = [
        "hello bot",
        "@_user_1 查询今日充值",
        "kpi",
        "whoami",
        "帮助",
    ]
    print("--- 消息提取测试 ---")
    for text in samples:
        event = _make_text_event(text)
        extracted = bot._extract_text(event)
        print(f"  原始: {text!r:30} -> 提取: {extracted!r}")

    # Test policy
    print("\n--- 权限策略测试 ---")
    for uid, expected in [
        ("debug_user_001", True),
        ("unknown_user", True if not config.WHITELIST else False),
    ]:
        allowed, opgames = bot._policy(uid)
        status = "[OK]" if allowed == expected else "[MISMATCH]"
        print(f"  {status} user={uid} allowed={allowed} opgames={opgames}")

    # Test report trigger matching
    print("\n--- 报表触发词测试 ---")
    for text in ["今日数据", "kpi日报", "ltv报表", "查询装备强化"]:
        matched = bot.reports.match(text)
        print(f"  {text!r:20} -> {matched}")

    # Test _send_text / _send_file would need real Feishu client, skip
    print("\n--- 说明 ---")
    print("_send_text / _send_file 需要真实飞书连接，未在此测试。")
    print("如需测试完整消息链路，请运行: python app/run_bot.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
