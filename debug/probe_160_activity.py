"""探查 160 GM 库: 5-6月活动排期 + game_mall 表结构。"""
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

print("=== DESC activity ===")
try:
    for r in q("DESC activity"):
        print(r["Field"], r["Type"])
except Exception as e:
    print("ERR:", e)

print("\n=== 2026-05/06 活动(按类型+名称聚合, 前80组) ===")
try:
    rows = q("""
SELECT SUBSTR(start_time, 1, 7) AS month, activity_type, name, COUNT(*) AS cnt,
       MIN(start_time) AS first_start, MAX(end_time) AS last_end
FROM activity
WHERE game_id = 160 AND start_time >= '2026-05-01' AND start_time < '2026-07-01'
GROUP BY SUBSTR(start_time, 1, 7), activity_type, name
ORDER BY month, first_start
""")
    print(f"共 {len(rows)} 组")
    for r in rows[:80]:
        print(f"{r['month']}  [{r['activity_type']}]  {r['name']}  x{r['cnt']}  {r['first_start']} ~ {r['last_end']}")
except Exception as e:
    print("ERR:", e)

print("\n=== DESC game_mall ===")
try:
    for r in q("DESC game_mall"):
        print(r["Field"], r["Type"])
except Exception as e:
    print("ERR:", e)

print("\n=== game_mall 样例 ===")
try:
    for r in q("SELECT * FROM game_mall WHERE game_id = 160 LIMIT 5", n=5):
        print(r)
except Exception as e:
    print("ERR:", e)
