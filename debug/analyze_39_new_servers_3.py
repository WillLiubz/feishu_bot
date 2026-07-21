"""39 新服分析补充查询 第三轮:
1. 重试 G: prop 钻石消费系统分布(先近30天,再全窗口)
2. 各服系统账号(system@%)数量,修正真实注册数
3. 直购礼包名称: 不限 game_id / 探查 gift_bag id 范围
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


# 1. prop 消费系统分布(近30天, 避免之前全窗口异常)
run(
    "1. prop 钻石消费系统分布 (20260620-20260719)",
    f"""
SELECT serverid, custom_pra1 AS system_method,
       COUNT(*) AS times,
       COUNT(DISTINCT iuid) AS users,
       SUM(CAST(custom_pra3 AS BIGINT)) AS cost_diamonds
FROM raw_scribe_log.prop
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '20260620' AND '20260719'
GROUP BY serverid, custom_pra1
ORDER BY serverid, cost_diamonds DESC
""",
    max_rows=500, poll=60,
)

# 2. 各服系统账号数量(ouid 以 system@ 开头)
run(
    "2. 各服系统账号/真实注册拆分",
    f"""
SELECT serverid,
       COUNT(DISTINCT iuid) AS total_reg,
       COUNT(DISTINCT CASE WHEN ouid LIKE 'system@%' THEN iuid END) AS system_accounts,
       COUNT(DISTINCT CASE WHEN ouid NOT LIKE 'system@%' THEN iuid END) AS real_reg
FROM raw_scribe_log.est
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '20260510' AND '20260719'
GROUP BY serverid
ORDER BY serverid
""",
)

# 3. gift_bag 探查
gc = config.game_config(39)
cdb = gc.config_db
cfg = {
    "host": cdb["host"], "port": cdb["port"], "user": cdb["user"],
    "password": cdb["password"], "database": cdb["database"],
    "charset": cdb.get("charset", "utf8mb4"),
    "connect_timeout": cdb.get("connect_timeout", 5),
    "read_timeout": cdb.get("read_timeout", 30),
}

def q(sql, n=100):
    return configdb.query(cfg, configdb.sanitize(sql, max_rows=n), max_rows=n)

print(f"\n{'='*70}\n## 3a. gift_bag id 范围样例\n{'='*70}")
for r in q("SELECT game_id, MIN(id) AS min_id, MAX(id) AS max_id, COUNT(*) AS cnt FROM gift_bag GROUP BY game_id"):
    print(r)

gift_ids = "8000,5400100,5400101,5400103,5400104,5400106,5400107,5500001,62680,62700,62741,62743,62747,62748,62766,62783,62785,62793,62848,102,103,104,201,803,1402,19801"
print(f"\n{'='*70}\n## 3b. 直购礼包名称(不限 game_id)\n{'='*70}")
for r in q(f"SELECT id, game_id, name, quality, goods, desc_info FROM gift_bag WHERE id IN ({gift_ids})"):
    print(r)
