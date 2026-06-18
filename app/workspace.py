import json
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import config

_ROOT = Path(config._ROOT)
_APP_DIR = Path(__file__).parent
_SCHEMA_PATH = _ROOT / "schema.md"
_WORKSPACES_DIR = _ROOT / "data" / "workspaces"

_RULES_TEMPLATE = """\
你是一个数据分析助手，帮助用户查询数仓数据。

今天日期（实时表 ds 分区）：{today}
昨天日期（T+1 延时表 ds 分区）：{yesterday}

规则：
1. 只能使用 query_data 工具查询数据，不允许使用任何其他工具
2. 只读查询，不允许修改数据
3. 用中文回答用户问题
4. 回答格式：先给一段中文总结（基于实际查到的数据），不需要返回表格
5. 所有 SQL 必须带 game_id = {game_id} 分区条件
6. ds 分区日期格式：yyyyMMdd（如 {today}）
7. 查累计类数据时加 ds >= {ds_start} 条件
8. 如果 SQL 报错，仔细检查原因后重写，最多重试 3 次
"""

_DENY_TOOLS = [
    "Bash", "Edit", "Write", "Read", "WebFetch", "WebSearch",
    "TodoWrite", "TodoRead", "computer_use", "str_replace_editor",
]


def _safe(s):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', s)


def prepare(chat_id, message_id, opgames=None):
    """
    Prepare per-chat workspace. Called before every query.
    Returns dict: {cwd, mcp_config, result_dir}
    """
    ws_dir = _WORKSPACES_DIR / _safe(chat_id)
    ws_dir.mkdir(parents=True, exist_ok=True)

    result_dir = ws_dir / "results"
    if result_dir.exists():
        shutil.rmtree(result_dir)
    result_dir.mkdir()

    today = date.today().strftime("%Y%m%d")
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")

    # CLAUDE.md: rules + channel aliases + schema content
    schema_text = ""
    if _SCHEMA_PATH.exists():
        schema_text = _SCHEMA_PATH.read_text(encoding="utf-8")
        schema_text = schema_text.replace("<今天ds>", today).replace("<昨天ds>", yesterday)

    channel_block = ""
    if config.CHANNEL_ALIASES:
        lines = "\n".join(f"  {name}：{ids}" for name, ids in config.CHANNEL_ALIASES.items())
        channel_block = f"\n渠道别名（中文名对应的 opgame_id）：\n{lines}\n"

    user_scope = ""
    if opgames:
        user_scope = f"\n当前用户仅可查询以下渠道：{', '.join(str(o) for o in opgames)}\n"

    rules = _RULES_TEMPLATE.format(
        today=today, yesterday=yesterday,
        game_id=config.GAME_ID, ds_start=config.DS_START,
    )
    claude_md = rules + channel_block + user_scope + "\n" + schema_text
    (ws_dir / "CLAUDE.md").write_text(claude_md, encoding="utf-8")

    # .claude/settings.json: deny all built-in tools
    claude_dir = ws_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings = {
        "permissions": {
            "allow": ["mcp__dquery__query_data"],
            "deny": _DENY_TOOLS,
        }
    }
    (claude_dir / "settings.json").write_text(
        json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # mcp.json: dquery MCP server config
    opgames_json = json.dumps([str(o) for o in (opgames or [])])
    mcp_cfg = {
        "mcpServers": {
            "dquery": {
                "command": sys.executable,
                "args": [
                    str(_APP_DIR / "mcp_server.py"),
                    "--result-dir", str(result_dir),
                    "--chat-id", chat_id,
                    "--message-id", message_id,
                    "--opgame-ids", opgames_json,
                    "--mock", str(config.DATA_API_MOCK).lower(),
                ],
                "env": {},
            }
        }
    }
    mcp_config_path = ws_dir / "mcp.json"
    mcp_config_path.write_text(
        json.dumps(mcp_cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "cwd": str(ws_dir),
        "mcp_config": str(mcp_config_path),
        "result_dir": str(result_dir),
    }
