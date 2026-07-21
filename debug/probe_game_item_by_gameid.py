import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import configdb


def query(game_id, sql):
    gc = config.game_config(game_id)
    cdb = gc.config_db
    cfg = {
        "host": cdb["host"],
        "port": cdb["port"],
        "user": cdb["user"],
        "password": cdb["password"],
        "database": cdb["database"],
        "charset": cdb.get("charset", "utf8mb4"),
        "connect_timeout": cdb.get("connect_timeout", 5),
        "read_timeout": cdb.get("read_timeout", 30),
    }
    try:
        clean = configdb.sanitize(sql, max_rows=10)
        rows = configdb.query(cfg, clean, max_rows=10)
        print(f"\n=== game {game_id} ===")
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        print(f"[{game_id}] ERROR: {e}")


for gid in (160, 312):
    query(gid, f"SELECT * FROM game_item WHERE game_id = {gid} LIMIT 3")
    query(gid, f"SELECT * FROM game_resource WHERE game_id = {gid} LIMIT 3")
    query(gid, f"SELECT COUNT(*) AS cnt FROM game_item WHERE game_id = {gid}")
    query(gid, f"SELECT COUNT(*) AS cnt FROM game_resource WHERE game_id = {gid}")
    query(gid, f"SELECT DISTINCT game_id FROM game_item LIMIT 10")
    query(gid, f"SELECT DISTINCT game_id FROM game_resource LIMIT 10")
