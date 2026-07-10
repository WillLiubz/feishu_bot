"""Debug script for player_segment template.

Sets up a temporary FEISHU_BOT_ROOT with mock data_api, then runs the
player_segment report for games 312, 160, and 39, producing an Excel file
per game under the system temp directory.
"""

import json
import os
import sys
import tempfile
from pathlib import Path


def _setup_config(game_id: int):
    """Create a temp config root and set FEISHU_BOT_ROOT."""
    root = Path(tempfile.mkdtemp(prefix="feishu_bot_debug_"))
    cfg = {
        "feishu": {"app_id": "debug", "app_secret": "debug"},
        "game": {"game_id": game_id, "ds_start": "20200101"},
        "channels": {"lock_opgame_ids": [], "aliases": {}},
        "data_api": {
            "client_id": "0",
            "key": "k",
            "search_url": "http://s/",
            "download_url": "http://d/",
            "max_rows": 100,
            "mock": True,
        },
        "claude": {"model": "m", "cli_path": "claude", "max_turns": 5, "timeout": 60},
        "bot": {
            "max_concurrent": 1,
            "default_sql_limit": 100,
            "whitelist": False,
            "user_opgames": {},
            "names": {},
        },
        "logview": {"host": "127.0.0.1", "port": 8900, "key": ""},
        "help_text": "h",
        "report_triggers": {"player_segment": ["玩家分群"]},
        "reports": {
            "login_table": "t.login",
            "pay_table": "t.pay",
            "account_login_table": "t.acc",
        },
    }
    (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    os.environ["FEISHU_BOT_ROOT"] = str(root)
    return root


def _import_templates():
    """Import templates after FEISHU_BOT_ROOT is set."""
    sys.path.insert(0, "app")
    import templates
    import dquery

    return templates, dquery


class _GameConfig:
    def __init__(self, game_id):
        self.game_id = game_id


def main():
    for game_id in (312, 160, 39):
        config_root = _setup_config(game_id)
        templates, dquery = _import_templates()
        game_config = _GameConfig(game_id)

        summary, result_dir = templates.run_report(
            "player_segment", "近7天玩家分群", game_config
        )
        xlsx_path = dquery.combine_to_excel(result_dir)

        print(f"\n[游戏 {game_id}] 完成")
        print(summary)
        print(f"结果目录: {result_dir}")
        if xlsx_path:
            print(f"Excel 文件: {xlsx_path}")
        else:
            print("未生成 Excel（无数据）")

        # Print rendered SQL of first sheet for a quick sanity check.
        first_sql = Path(result_dir) / "query_1.sql"
        if first_sql.exists():
            print("首 Sheet SQL 预览:")
            print(first_sql.read_text(encoding="utf-8")[:500] + "...")


if __name__ == "__main__":
    main()
