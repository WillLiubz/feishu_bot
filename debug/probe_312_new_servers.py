"""探查 312 GM 库: 2026-04 之后开服的区服。"""
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


cfg = get_cfg(312)

rows = configdb.query(
    cfg,
    configdb.sanitize(
        """
SELECT server_id, dc_server_id, other_name, server_title, operator_id, opgame_id,
       is_main_server, status, FROM_UNIXTIME(open_time) AS open_dt
FROM server
WHERE game_id = 312 AND open_time >= 1775001600
ORDER BY open_time
""",
        max_rows=500,
    ),
    max_rows=500,
)
print(f"共 {len(rows)} 个区服(2026-04-01 之后)\n")
for r in rows:
    print(
        f"sid={r['server_id']:<6} dc={r['dc_server_id']:<14} op={r['operator_id']:<4} "
        f"opgame={r['opgame_id']:<6} main={r['is_main_server']} status={r['status']} "
        f"{r['open_dt']}  {r['other_name'] or r['server_title']}"
    )
