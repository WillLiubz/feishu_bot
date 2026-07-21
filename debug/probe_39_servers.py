"""探查游戏 39 GM 库 server 表结构，并找出 5月/6月新服。"""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import configdb


def get_cfg(game_id):
    gc = config.game_config(game_id)
    cdb = gc.config_db
    if not cdb:
        raise SystemExit(f"game {game_id} 未配置 config_db")
    return {
        "host": cdb["host"],
        "port": cdb["port"],
        "user": cdb["user"],
        "password": cdb["password"],
        "database": cdb["database"],
        "charset": cdb.get("charset", "utf8mb4"),
        "connect_timeout": cdb.get("connect_timeout", 5),
        "read_timeout": cdb.get("read_timeout", 30),
    }, cdb


cfg, cdb = get_cfg(39)
print(f"GM database: {cdb['database']}  static: {cdb.get('static_database')}")

rows = configdb.query(cfg, configdb.sanitize("DESC server", max_rows=200), max_rows=200)
print("\n=== DESC server ===")
for r in rows:
    print(r)
