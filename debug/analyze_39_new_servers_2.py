"""39 新服分析补充查询:
1. 验证 prop 表是否真的没有这些服的数据
2. 重试 H: 每服每日付费趋势
3. 确认 1600/1601 开服前 5/29 的 81 个注册(疑似迁移)
4. 直购礼包名称对照 (GM gift_bag)
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


# 1. prop 验证: 近30天全游戏是否有数据 + 这些服是否有
run(
    "1a. prop 近7天全游戏数据量验证",
    """
SELECT ds, COUNT(*) AS cnt
FROM raw_scribe_log.prop
WHERE gameid = '39' AND ds >= '20260713'
GROUP BY ds ORDER BY ds
""",
)
run(
    "1b. prop 近7天新服数据量",
    f"""
SELECT serverid, COUNT(*) AS cnt
FROM raw_scribe_log.prop
WHERE gameid = '39' AND ds >= '20260713' AND serverid IN {SERVERS}
GROUP BY serverid
""",
)

# 2. H 重试: 每日付费趋势 (加大轮询次数)
run(
    "2. 每服每日付费金额趋势 (重试)",
    f"""
SELECT serverid, ds,
       COUNT(DISTINCT iuid) AS payers,
       ROUND(SUM(CAST(custom_pra3 AS DOUBLE)) / 100, 2) AS usd
FROM raw_scribe_log.pay
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '20260510' AND '20260719'
GROUP BY serverid, ds
ORDER BY serverid, ds
""",
    max_rows=500, poll=60,
)

# 3. 5/29 异常注册确认: 两服 iuid 是否同一批
run(
    "3. 1600/1601 在 20260529 的注册明细样例",
    """
SELECT serverid, iuid, ouid, custom_pra1, custom_pra2, custom_pra3, user_level
FROM raw_scribe_log.est
WHERE gameid = '39' AND ds = '20260529'
  AND serverid IN ('39005900001600','39005900001601')
ORDER BY serverid, iuid
LIMIT 20
""",
    max_rows=20,
)
run(
    "3b. 5/29 注册在两服的重合度",
    """
WITH a AS (
  SELECT DISTINCT iuid FROM raw_scribe_log.est
  WHERE gameid='39' AND ds='20260529' AND serverid='39005900001600'
),
b AS (
  SELECT DISTINCT iuid FROM raw_scribe_log.est
  WHERE gameid='39' AND ds='20260529' AND serverid='39005900001601'
)
SELECT (SELECT COUNT(*) FROM a) AS cnt_1600,
       (SELECT COUNT(*) FROM b) AS cnt_1601,
       (SELECT COUNT(*) FROM a JOIN b ON a.iuid = b.iuid) AS overlap
""",
)

# 4. 直购礼包名称
gc = config.game_config(39)
cdb = gc.config_db
cfg = {
    "host": cdb["host"], "port": cdb["port"], "user": cdb["user"],
    "password": cdb["password"], "database": cdb["database"],
    "charset": cdb.get("charset", "utf8mb4"),
    "connect_timeout": cdb.get("connect_timeout", 5),
    "read_timeout": cdb.get("read_timeout", 30),
}
gift_ids = "8000,5400100,5400101,5400103,5400104,5400106,5400107,5500001,62680,62700,62741,62743,62747,62748,62766,62783,62785,62793,62848,102,103,104,201,803,1402,19801"
rows = configdb.query(
    cfg,
    configdb.sanitize(
        f"SELECT id, name, quality, goods, use_level, desc_info FROM gift_bag WHERE game_id = 39 AND id IN ({gift_ids})",
        max_rows=100,
    ),
    max_rows=100,
)
print(f"\n{'='*70}\n## 4. 直购礼包名称 (GM gift_bag)\n{'='*70}")
for r in rows:
    print(r)
