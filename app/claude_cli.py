import json
import os
import subprocess
import sys
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


def _parse(stdout_text):
    """
    Parse claude --output-format json stdout.
    Returns (answer_text, session_id).
    Raises RuntimeError on error responses.
    """
    data = json.loads(stdout_text)
    if data.get("is_error"):
        raise RuntimeError(f"Claude 返回错误: {str(data.get('result', ''))[:300]}")
    subtype = data.get("subtype", "")
    if subtype not in ("", "final_answer", None):
        raise RuntimeError(f"Claude 非正常退出 subtype={subtype}: {str(data.get('result', ''))[:200]}")
    return str(data.get("result", "")), str(data.get("session_id", ""))


def run(question, ws, session_id=None, _retry=0):
    """
    Spawn claude subprocess. Feed question via stdin.
    Returns (answer_text, new_session_id).
    ws: dict from workspace.prepare() with keys: cwd, mcp_config, result_dir
    Raises RuntimeError on timeout or process error.
    """
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
        stdout, stderr = proc.communicate(
            input=question.encode("utf-8"),
            timeout=config.CLAUDE_CLI_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        raise RuntimeError("处理超时")

    stderr_text = stderr.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        # If session is invalid, retry once without --resume
        if session_id and _is_session_invalid(stderr_text) and _retry == 0:
            return run(question, ws, session_id=None, _retry=1)
        raise RuntimeError(f"Claude 异常退出 (rc={proc.returncode}): {stderr_text[:400]}")

    stdout_text = stdout.decode("utf-8", errors="replace")
    return _parse(stdout_text)
