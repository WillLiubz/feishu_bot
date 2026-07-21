"""探查 39 GM 库 activity 相关表结构与 5-6 月活动。"""
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
    return {
        "host": cdb["host"], "port": cdb["port"], "user": cdb["user"],
        "password": cdb["password"], "database": cdb["database"],
        "charset": cdb.get("charset", "utf8mb4"),
        "connect_timeout": cdb.get("connect_timeout", 5),
        "read_timeout": cdb.get("read_timeout", 30),
    }


cfg = get_cfg(39)

def q(sql, max_rows=300):
    return configdb.query(cfg, configdb.sanitize(sql, max_rows=max_rows), max_rows=max_rows)

print("=== DESC activity ===")
for r in q("DESC activity"):
    print(r["Field"], r["Type"])
