import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import workspace


def test_get_claude_md_text(tmp_path):
    ws_dir = tmp_path / "workspaces" / "chat_1"
    ws_dir.mkdir(parents=True)
    md_text = "规则：game_id=312"
    (ws_dir / "CLAUDE.md").write_text(md_text, encoding="utf-8")
    ws = {"cwd": str(ws_dir), "mcp_config": str(ws_dir / "mcp.json"), "result_dir": str(ws_dir / "results")}
    assert workspace.get_claude_md_text(ws) == md_text


def test_rules_template_contains_mcp_wait_guidance():
    # MCP server 在新版 CLI 中异步连接，规则里必须引导模型等待而不是直接放弃
    assert "WaitForMcpServers" in workspace._RULES_TEMPLATE
    assert "异步" in workspace._RULES_TEMPLATE


def test_rules_template_requires_player_nickname_and_server():
    # 查询具体玩家信息时，规则要求用户额外提供昵称和服务器，缺失时先确认
    assert "昵称" in workspace._RULES_TEMPLATE
    assert "服务器" in workspace._RULES_TEMPLATE
