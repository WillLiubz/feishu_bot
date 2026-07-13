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
