import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import configdb


def desc_table(game_id, table):
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
        clean = configdb.sanitize(f"DESCRIBE {table}", max_rows=500)
        rows = configdb.query(cfg, clean, max_rows=500)
        print(f"\n=== game {game_id} {table} ===")
        for r in rows:
            print(r)
        clean2 = configdb.sanitize(f"SELECT * FROM {table} LIMIT 3", max_rows=500)
        rows2 = configdb.query(cfg, clean2, max_rows=500)
        print("--- sample ---")
        print(json.dumps(rows2, ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        print(f"[{game_id}] ERROR: {e}")


for gid in (160, 312):
    desc_table(gid, "game_item")
    desc_table(gid, "game_resource")
