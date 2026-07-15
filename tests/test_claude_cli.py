import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import claude_cli


class _FakeProc:
    """Minimal subprocess stand-in: communicate() returns preset stdout/stderr."""

    def __init__(self, stdout_text, stderr_text="", returncode=0):
        self._stdout = stdout_text.encode("utf-8")
        self._stderr = stderr_text.encode("utf-8")
        self.returncode = returncode
        self.pid = 12345

    def communicate(self, input=None, timeout=None):
        return self._stdout, self._stderr


def _json_stdout(answer, session_id="sid-1"):
    return json.dumps({"result": answer, "session_id": session_id, "is_error": False})


_WS = {"cwd": ".", "mcp_config": "mcp.json", "result_dir": "results"}


# ---------- _child_env ----------

def test_child_env_strips_all_claude_vars():
    env = {
        "PATH": "C:\\Windows",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "abc",
        "CLAUDE_CODE_CHILD_SESSION": "1",
        "CLAUDE_CODE_EXECPATH": "/x",
        "AI_AGENT": "claude",
    }
    with patch.dict("os.environ", env, clear=True):
        child = claude_cli._child_env()
    assert "CLAUDECODE" not in child
    assert "CLAUDE_CODE_SESSION_ID" not in child
    assert "CLAUDE_CODE_CHILD_SESSION" not in child
    assert "CLAUDE_CODE_EXECPATH" not in child
    assert "AI_AGENT" not in child
    assert child["PATH"] == "C:\\Windows"
    assert child["PYTHONIOENCODING"] == "utf-8"


# ---------- _is_tool_missing ----------

def test_is_tool_missing_positive_phrasings():
    assert claude_cli._is_tool_missing("query_data 工具在我当前会话中不可用")
    assert claude_cli._is_tool_missing("mcp__dquery__query_data 没有挂载到我的工具列表里")
    assert claude_cli._is_tool_missing("`query_data` 不在我可调用的工具列表中")
    assert claude_cli._is_tool_missing("query_data is not available")


def test_is_tool_missing_negative_on_normal_answers():
    # 正常查询结论里即使提到 query_data / "没有"，也不应误判为工具缺失
    assert not claude_cli._is_tool_missing("query_data 查询没有返回数据，昨日无参与玩家")
    assert not claude_cli._is_tool_missing("共查到 100 行数据")
    assert not claude_cli._is_tool_missing("")


# ---------- tool-missing retry ----------

def test_run_retries_tool_missing_without_session():
    """分步流程（session_id=None）遇到工具缺失答案时也应重试一次。"""
    procs = [
        _FakeProc(_json_stdout("query_data 工具在我当前会话中不可用")),
        _FakeProc(_json_stdout("查到 3028 名玩家")),
    ]
    with patch.object(claude_cli.subprocess, "Popen", side_effect=procs) as popen:
        answer, _ = claude_cli.run("问题", dict(_WS), session_id=None)
    assert answer == "查到 3028 名玩家"
    assert popen.call_count == 2


def test_run_tool_missing_retries_only_once():
    procs = [
        _FakeProc(_json_stdout("query_data 工具在我当前会话中不可用")),
        _FakeProc(_json_stdout("query_data 工具在我当前会话中不可用")),
    ]
    with patch.object(claude_cli.subprocess, "Popen", side_effect=procs) as popen:
        answer, _ = claude_cli.run("问题", dict(_WS), session_id=None)
    assert "不可用" in answer
    assert popen.call_count == 2


def test_run_no_retry_on_normal_answer():
    procs = [_FakeProc(_json_stdout("共 100 行"))]
    with patch.object(claude_cli.subprocess, "Popen", side_effect=procs) as popen:
        answer, _ = claude_cli.run("问题", dict(_WS), session_id=None)
    assert answer == "共 100 行"
    assert popen.call_count == 1


# ---------- stderr logging ----------

def test_run_logs_child_stderr_on_success(capsys):
    procs = [_FakeProc(_json_stdout("ok"), stderr_text="MCP warning: slow server")]
    with patch.object(claude_cli.subprocess, "Popen", side_effect=procs):
        claude_cli.run("问题", dict(_WS), session_id=None)
    out = capsys.readouterr().out
    assert "MCP warning: slow server" in out
