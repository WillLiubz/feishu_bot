import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import configdb


def probe(game_id, sql):
    gc = config.game_config(game_id)
    cdb = gc.config_db
    cfg = {
        "host": cdb["host"],
        "port": cdb["port"],
        "user": cdb["user"],
        "password": cdb["password"],
        "database": cdb["static_database"],
        "charset": cdb.get("charset", "utf8mb4"),
        "connect_timeout": cdb.get("connect_timeout", 5),
        "read_timeout": cdb.get("read_timeout", 30),
    }
    try:
        clean = configdb.sanitize(sql, max_rows=cdb.get("max_rows", 500))
        rows = configdb.query(cfg, clean, max_rows=cdb.get("max_rows", 500))
        print(f"[{game_id}] OK rows={len(rows)}")
        if rows:
            print(json.dumps(rows[:3], ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        print(f"[{game_id}] ERROR: {e}")


for gid in (39, 160, 312):
    print(f"\n=== game {gid} ===")
    probe(gid, "SHOW TABLES")
    probe(gid, "SELECT * FROM static_item LIMIT 3")
