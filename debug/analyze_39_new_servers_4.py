"""39 新服分析补充查询 第四轮:
1. prop 消费分布改用 TRY_CAST (怀疑 CAST 遇非法值导致空结果)
2. 找出 prop.custom_pra3 中的非数值
3. 静态库 angel_static.static_item 查直购礼包名称
"""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import configdb
import dataapi

SERVERS = "('39005900001598','39005900001599','39005900001600','39005900001601')"


def run(title, sql, max_rows=500, poll=None):
    print(f"\n{'='*70}\n## {title}\n{'='*70}")
    try:
        rows = dataapi.run_sql_rows(sql, max_rows=max_rows, poll_max_attempts=poll)
    except TypeError:
        rows = dataapi.run_sql_rows(sql, max_rows=max_rows)
    if not rows:
        print("(无数据)")
        return rows
    cols = list(rows[0].keys())
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join(str(r.get(c, "")) for c in cols))
    print(f"({len(rows)} 行)")
    return rows


run(
    "1. prop 钻石消费系统分布 TRY_CAST (开服~20260719)",
    f"""
SELECT serverid, custom_pra1 AS system_method,
       COUNT(*) AS times,
       COUNT(DISTINCT iuid) AS users,
       SUM(TRY_CAST(custom_pra3 AS BIGINT)) AS cost_diamonds
FROM raw_scribe_log.prop
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '20260510' AND '20260719'
GROUP BY serverid, custom_pra1
ORDER BY serverid, cost_diamonds DESC
""",
    max_rows=500, poll=60,
)

run(
    "2. prop.custom_pra3 非数值样例 (近7天)",
    f"""
SELECT custom_pra3, COUNT(*) AS cnt
FROM raw_scribe_log.prop
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds >= '20260713'
  AND TRY_CAST(custom_pra3 AS BIGINT) IS NULL
GROUP BY custom_pra3
ORDER BY cnt DESC
LIMIT 20
""",
    max_rows=20,
)

# 3. 静态库查礼包名
gc = config.game_config(39)
cdb = gc.config_db
static_db = cdb.get("static_database") or cdb["database"]
cfg = {
    "host": cdb["host"], "port": cdb["port"], "user": cdb["user"],
    "password": cdb["password"], "database": static_db,
    "charset": cdb.get("charset", "utf8mb4"),
    "connect_timeout": cdb.get("connect_timeout", 5),
    "read_timeout": cdb.get("read_timeout", 30),
}

def q(sql, n=100):
    return configdb.query(cfg, configdb.sanitize(sql, max_rows=n), max_rows=n)

gift_ids = "8000,5400100,5400101,5400103,5400104,5400106,5400107,5500001,62680,62700,62741,62743,62747,62748,62766,62783,62785,62793,62848,102,103,104,201,803,1402,19801"
print(f"\n{'='*70}\n## 3. static_item 直购礼包名称 (库 {static_db})\n{'='*70}")
rows = q(f"SELECT id, name, type, quality, `describe` FROM static_item WHERE id IN ({gift_ids})")
for r in rows:
    print(r)
print(f"({len(rows)} 行)")
