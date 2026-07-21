"""列出游戏 39 在 2026-04 之后开服的区服（含 5月/6月新服）。"""
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

# 2026-04-01 UTC = 1775001600
sql = """
SELECT dc_server_id, server_name, operator_id, is_test, status,
       FROM_UNIXTIME(open_time) AS open_dt, open_time
FROM server
WHERE game_id = 39 AND open_time >= 1775001600
ORDER BY open_time
"""
rows = configdb.query(cfg, configdb.sanitize(sql, max_rows=500), max_rows=500)
print(f"共 {len(rows)} 个区服（2026-04-01 之后开服）\n")
for r in rows:
    print(f"{r['dc_server_id']:>10}  {r['open_dt']}  op={r['operator_id']:<4} test={r['is_test']} status={r['status']}  {r['server_name']}")
