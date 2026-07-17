import json
import sys
import types
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


def _gc(game_id=312, config_db=None):
    return types.SimpleNamespace(
        game_id=game_id,
        ds_start="20200101",
        schema="missing_schema.md",
        config_db=config_db or {},
    )


def _prepare_in_tmp(tmp_path, monkeypatch, gc):
    monkeypatch.setattr(workspace, "_ROOT", tmp_path)
    monkeypatch.setattr(workspace, "_WORKSPACES_DIR", tmp_path / "data" / "workspaces")
    return workspace.prepare("chat_cfg", "msg_1", game_config=gc)


def test_prepare_injects_config_db_rules_and_schema(tmp_path, monkeypatch):
    (tmp_path / "gm_schema_312.md").write_text(
        "# 配置库\nitem_config: 道具静态表", encoding="utf-8"
    )
    gc = _gc(config_db={"host": "h", "user": "u", "database": "d", "schema": "gm_schema_312.md"})
    _prepare_in_tmp(tmp_path, monkeypatch, gc)
    text = (tmp_path / "data" / "workspaces" / "chat_cfg" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "query_config" in text
    assert "SHOW TABLES" in text
    assert "item_config: 道具静态表" in text


def test_prepare_injects_config_db_static_database_rule(tmp_path, monkeypatch):
    (tmp_path / "gm_schema_312.md").write_text("# 配置库\n", encoding="utf-8")
    gc = _gc(config_db={
        "host": "h", "user": "u", "database": "gm_db", "static_database": "static_db",
        "schema": "gm_schema_312.md",
    })
    _prepare_in_tmp(tmp_path, monkeypatch, gc)
    text = (tmp_path / "data" / "workspaces" / "chat_cfg" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "GM 运营库名为 `gm_db`" in text
    assert "游戏静态库" in text
    assert "static_db" in text


def test_prepare_uses_database_when_static_database_missing(tmp_path, monkeypatch):
    (tmp_path / "gm_schema_312.md").write_text("# 配置库\n", encoding="utf-8")
    gc = _gc(config_db={
        "host": "h", "user": "u", "database": "only_db",
        "schema": "gm_schema_312.md",
    })
    _prepare_in_tmp(tmp_path, monkeypatch, gc)
    text = (tmp_path / "data" / "workspaces" / "chat_cfg" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "GM 运营库名为 `only_db`" in text
    assert "游戏静态库（道具/英雄等中文名）名为 `only_db`" in text
    _prepare_in_tmp(tmp_path, monkeypatch, _gc())
    text = (tmp_path / "data" / "workspaces" / "chat_cfg" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "query_config" not in text


def test_prepare_settings_allow_query_config(tmp_path, monkeypatch):
    _prepare_in_tmp(tmp_path, monkeypatch, _gc())
    settings = json.loads(
        (tmp_path / "data" / "workspaces" / "chat_cfg" / ".claude" / "settings.json")
        .read_text(encoding="utf-8")
    )
    assert "mcp__dquery__query_config" in settings["permissions"]["allow"]
    assert "mcp__dquery__query_data" in settings["permissions"]["allow"]
