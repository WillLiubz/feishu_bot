"""探查 160 GM 库 (xgame_gm) server 表结构与新服列表。"""
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


cfg = get_cfg(160)

def q(sql, n=500):
    return configdb.query(cfg, configdb.sanitize(sql, max_rows=n), max_rows=n)

print("=== DESC server ===")
for r in q("DESC server"):
    print(r["Field"], r["Type"])

print("\n=== 2026-04 之后开服 (game_id=160) ===")
rows = q("""
SELECT *
FROM server
WHERE game_id = 160 AND open_time >= 1775001600
ORDER BY open_time
""")
print(f"共 {len(rows)} 个")
for r in rows:
    print(r)
