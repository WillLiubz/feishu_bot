import json
import os
import subprocess
import sys
import time
from pathlib import Path

import config


def _child_env():
    """Return environment for claude subprocess: remove CLAUDECODE to allow nesting."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _kill_tree(proc):
    """Kill entire process tree rooted at proc."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True
        )
    else:
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


def _is_session_invalid(text):
    t = text.lower()
    return "session" in t and ("invalid" in t or "not found" in t or "expired" in t)


def _is_tool_missing(text):
    return "query_data" in text and any(
        kw in text for kw in ("没有", "不可用", "不存在", "无法使用", "not available")
    )


def _parse(stdout_text):
    """
    Parse claude --output-format json stdout.
    Returns (answer_text, session_id).
    Only raises RuntimeError when is_error=True (subtype check removed entirely).
    """
    t_parse = time.time()
    data = json.loads(stdout_text)
    result = str(data.get("result", ""))
    session_id = str(data.get("session_id", ""))
    if data.get("is_error"):
        raise RuntimeError(f"Claude 返回错误: {result[:300]}")
    print(f"[claude_cli] parse done in {int((time.time() - t_parse) * 1000)}ms", flush=True)
    return result, session_id


def run(question, ws, session_id=None, _retry=0, system_prompt=None, timeout=None):
    """
    Spawn claude subprocess. Feed question via stdin.
    Returns (answer_text, new_session_id).
    ws: dict from workspace.prepare() with keys: cwd, mcp_config, result_dir
    Raises RuntimeError on timeout or process error.
    """
    t0 = time.time()
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
        "--max-turns", str(config.CLAUDE_CLI_MAX_TURNS),
        "--permission-mode", "bypassPermissions",
        "--model", config.CLAUDE_MODEL,
        "--mcp-config", ws["mcp_config"],
        "--allowedTools", "mcp__dquery__query_data",
    ]
    if session_id:
        cmd += ["--resume", session_id]

    full_prompt = question
    if system_prompt:
        full_prompt = f"<system>\n{system_prompt}\n</system>\n\n{question}"

    print(f"[claude_cli] spawn: {cli} cwd={ws['cwd']} session={session_id} retry={_retry}", flush=True)
    proc = subprocess.Popen(
        cmd,
        cwd=ws["cwd"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_child_env(),
        **popen_kwargs,
    )

    try:
        t_comm = time.time()
        stdout, stderr = proc.communicate(
            input=full_prompt.encode("utf-8"),
            timeout=timeout if timeout is not None else config.CLAUDE_CLI_TIMEOUT,
        )
        print(f"[claude_cli] communicate wait {int((time.time() - t_comm) * 1000)}ms", flush=True)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        raise RuntimeError("处理超时")

    stderr_text = stderr.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        if session_id and _is_session_invalid(stderr_text) and _retry == 0:
            return run(question, ws, session_id=None, _retry=1, system_prompt=system_prompt, timeout=timeout)
        raise RuntimeError(f"Claude 异常退出 (rc={proc.returncode}): {stderr_text[:400]}")

    stdout_text = stdout.decode("utf-8", errors="replace")
    try:
        answer, new_sid = _parse(stdout_text)
    except RuntimeError as e:
        msg = str(e)
        # Legacy _parse raises on subtype=success but the result is the actual answer
        if "subtype=success:" in msg:
            answer = msg.split("subtype=success:", 1)[1].strip()
            new_sid = ""
        else:
            raise
    if session_id and _retry == 0 and _is_tool_missing(answer):
        return run(question, ws, session_id=None, _retry=1, system_prompt=system_prompt, timeout=timeout)
    print(f"[claude_cli] total {int((time.time() - t0) * 1000)}ms", flush=True)
    return answer, new_sid


def run_with_system_prompt(question, ws, system_prompt, session_id=None, _retry=0, timeout=None):
    """Convenience wrapper that injects a system prompt before the user question."""
    return run(question, ws, session_id, _retry, system_prompt=system_prompt, timeout=timeout)
