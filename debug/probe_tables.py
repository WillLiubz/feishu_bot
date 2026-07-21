import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import configdb


def list_tables(game_id):
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
        clean = configdb.sanitize("SHOW TABLES", max_rows=500)
        rows = configdb.query(cfg, clean, max_rows=500)
        print(f"\n=== game {game_id} tables in {cdb['database']} ===")
        key = list(rows[0].keys())[0] if rows else None
        for r in rows:
            print(r[key])
    except Exception as e:
        print(f"[{game_id}] ERROR: {e}")


for gid in (160, 312):
    list_tables(gid)
