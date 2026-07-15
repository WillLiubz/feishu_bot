# -*- coding: utf-8 -*-
"""
诊断：分步查询中子 Claude CLI 偶发不挂载 mcp__dquery__query_data。

完全复刻 claude_cli.run 的 spawn 方式，区别是始终打印完整 stderr，
以便观察 MCP server 加载阶段的告警/错误。

用法：
    python debug/test_mcp_mount.py            # 跑 3 轮，每轮一次 SELECT 1
    python debug/test_mcp_mount.py --rounds 5
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import workspace


def run_once(round_n: int) -> dict:
    ws = workspace.prepare(
        f"diag-mcp-mount", f"diag-msg-{int(time.time())}-{round_n}",
        game_config=config.game_config(39),
    )
    cli = config.CLAUDE_CLI_PATH
    if sys.platform == "win32":
        base_cmd = ["cmd", "/c", cli]
        popen_kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        base_cmd = [cli]
        popen_kwargs = {"start_new_session": True}

    cmd = base_cmd + [
        "-p",
        "--output-format", "json",
        "--max-turns", "5",
        "--permission-mode", "bypassPermissions",
        "--model", config.CLAUDE_MODEL,
        "--mcp-config", ws["mcp_config"],
        "--allowedTools", "mcp__dquery__query_data",
    ]
    prompt = (
        "请使用 mcp__dquery__query_data 工具执行 SQL：SELECT 1 AS one。"
        "如果该工具不在你的工具列表里，请明确回答 TOOL_MISSING，不要编造结果。"
    )
    import os
    env = os.environ.copy()
    # 生产环境 _child_env 只移除 CLAUDECODE；诊断脚本默认剥离全部 CLAUDE*/AI_AGENT
    # 变量，避免在 Claude Code 会话内运行时子进程附着到父会话。
    if "--keep-parent-env" not in sys.argv:
        for k in list(env):
            if k.startswith("CLAUDE") or k == "AI_AGENT":
                env.pop(k, None)
    else:
        env.pop("CLAUDECODE", None)
    env["PYTHONIOENCODING"] = "utf-8"

    t0 = time.time()
    proc = subprocess.Popen(
        cmd, cwd=ws["cwd"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, **popen_kwargs,
    )
    stdout, stderr = proc.communicate(input=prompt.encode("utf-8"), timeout=180)
    elapsed = time.time() - t0

    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")

    import json
    answer = ""
    tool_missing = None
    try:
        data = json.loads(stdout_text)
        answer = str(data.get("result", ""))
        # 只把"以 TOOL_MISSING 开头"判为缺失，避免误伤"不是 TOOL_MISSING"的说明
        tool_missing = answer.strip().startswith("TOOL_MISSING")
    except Exception as e:
        answer = f"<stdout parse failed: {e}> {stdout_text[:300]}"

    return {
        "rc": proc.returncode,
        "elapsed": elapsed,
        "tool_missing": tool_missing,
        "answer": answer[:200],
        "stderr": stderr_text,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    for i in range(1, args.rounds + 1):
        print(f"\n===== round {i} =====", flush=True)
        r = run_once(i)
        print(f"rc={r['rc']} elapsed={r['elapsed']:.1f}s tool_missing={r['tool_missing']}")
        print(f"answer: {r['answer']}")
        if r["stderr"].strip():
            print("---- stderr ----")
            print(r["stderr"][:3000])
        else:
            print("(stderr empty)")


if __name__ == "__main__":
    main()
