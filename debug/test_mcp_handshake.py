# -*- coding: utf-8 -*-
"""
诊断：直接用 MCP stdio 协议握手 mcp_server.py，打印 initialize / tools/list 原始响应，
验证服务端工具 schema 是否合法。

用法： python debug/test_mcp_handshake.py
"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
import config
import workspace


def main():
    ws = workspace.prepare("diag-mcp-handshake", "diag-msg-hs", game_config=config.game_config(39))
    mcp_cfg = json.loads(Path(ws["mcp_config"]).read_text(encoding="utf-8"))
    srv = mcp_cfg["mcpServers"]["dquery"]
    cmd = [srv["command"]] + srv["args"]
    print("spawn:", cmd[0], Path(cmd[1]).name, "...")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=ws["cwd"],
    )

    responses = []

    def reader():
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                responses.append(json.loads(line))
            except Exception:
                print("[non-json stdout]", line[:200])

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    def send(obj):
        proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
        proc.stdin.flush()

    send({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "diag", "version": "0.1"},
        },
    })
    time.sleep(3)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    time.sleep(1)
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    time.sleep(3)

    for r in responses:
        print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])
        print("----")

    proc.kill()
    err = proc.stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        print("==== server stderr ====")
        print(err[:3000])


if __name__ == "__main__":
    main()
