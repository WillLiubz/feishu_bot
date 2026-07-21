"""分析游戏 39 的 5月/6月新服表现。

5月新服: 39005900001598 Elysia(5/10), 39005900001599 Order(5/20)
6月新服: 39005900001600 Moon(6/10), 39005900001601 Crescent(6/20)

分析窗口: 2026-05-10 ~ 2026-07-19 (完整天)
"""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import dataapi

SERVERS = "('39005900001598','39005900001599','39005900001600','39005900001601')"
DS_START, DS_END = "20260510", "20260719"


def run(title, sql, max_rows=1000):
    print(f"\n{'='*70}\n## {title}\n{'='*70}")
    rows = dataapi.run_sql_rows(sql, max_rows=max_rows)
    if not rows:
        print("(无数据)")
        return rows
    cols = list(rows[0].keys())
    print(" | ".join(cols))
    print("-" * 60)
    for r in rows:
        print(" | ".join(str(r.get(c, "")) for c in cols))
    print(f"({len(rows)} 行)")
    return rows


# A. 每服每日新增注册
run(
    "A. 每服每日新增注册人数 (est)",
    f"""
SELECT serverid, ds, COUNT(DISTINCT iuid) AS new_users
FROM raw_scribe_log.est
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '{DS_START}' AND '{DS_END}'
GROUP BY serverid, ds
ORDER BY serverid, ds
""",
)

# B. 注册累计
run(
    "B. 每服累计注册人数",
    f"""
SELECT serverid, COUNT(DISTINCT iuid) AS total_reg
FROM raw_scribe_log.est
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '{DS_START}' AND '{DS_END}'
GROUP BY serverid
ORDER BY serverid
""",
)

# C. 付费汇总 (100 钻石 = 1 美元)
run(
    "C. 每服付费汇总 (pay)",
    f"""
SELECT serverid,
       COUNT(DISTINCT iuid) AS payers,
       COUNT(*) AS pay_times,
       SUM(CAST(custom_pra3 AS BIGINT)) AS total_diamonds,
       ROUND(SUM(CAST(custom_pra3 AS DOUBLE)) / 100, 2) AS total_usd,
       ROUND(SUM(CAST(custom_pra3 AS DOUBLE)) / 100 / COUNT(DISTINCT iuid), 2) AS arppu_usd
FROM raw_scribe_log.pay
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '{DS_START}' AND '{DS_END}'
GROUP BY serverid
ORDER BY serverid
""",
)

# D. 付费类型拆分: 1=兑换游戏币 2=直购道具
run(
    "D. 付费类型拆分 (1=兑换游戏币, 2=直购礼包)",
    f"""
SELECT serverid, custom_pra1 AS pay_type,
       COUNT(DISTINCT iuid) AS payers,
       COUNT(*) AS times,
       ROUND(SUM(CAST(custom_pra3 AS DOUBLE)) / 100, 2) AS usd
FROM raw_scribe_log.pay
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '{DS_START}' AND '{DS_END}'
GROUP BY serverid, custom_pra1
ORDER BY serverid, usd DESC
""",
)

# E. 直购礼包 TOP (custom_pra5 = gift_id)
run(
    "E. 直购礼包 TOP (按美元)",
    f"""
SELECT serverid, custom_pra5 AS gift_id,
       COUNT(DISTINCT iuid) AS payers,
       COUNT(*) AS times,
       ROUND(SUM(CAST(custom_pra3 AS DOUBLE)) / 100, 2) AS usd
FROM raw_scribe_log.pay
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '{DS_START}' AND '{DS_END}'
  AND custom_pra1 = '2'
GROUP BY serverid, custom_pra5
ORDER BY serverid, usd DESC
""",
    max_rows=200,
)

# F. 近7天活跃玩家等级分布
run(
    "F. 近7天活跃玩家等级分布 (login, 每玩家取最高等级)",
    f"""
WITH lv AS (
  SELECT serverid, iuid, MAX(CAST(user_level AS INTEGER)) AS lvl
  FROM raw_scribe_log.login
  WHERE gameid = '39' AND serverid IN {SERVERS}
    AND ds BETWEEN '20260713' AND '{DS_END}'
  GROUP BY serverid, iuid
)
SELECT serverid,
       CASE WHEN lvl < 20 THEN '01-19'
            WHEN lvl < 40 THEN '20-39'
            WHEN lvl < 60 THEN '40-59'
            WHEN lvl < 80 THEN '60-79'
            WHEN lvl < 100 THEN '80-99'
            ELSE '100+' END AS level_bucket,
       COUNT(*) AS users,
       MAX(lvl) AS max_lvl_in_bucket
FROM lv
GROUP BY serverid,
       CASE WHEN lvl < 20 THEN '01-19'
            WHEN lvl < 40 THEN '20-39'
            WHEN lvl < 60 THEN '40-59'
            WHEN lvl < 80 THEN '60-79'
            WHEN lvl < 100 THEN '80-99'
            ELSE '100+' END
ORDER BY serverid, level_bucket
""",
)

# F2. 近7天活跃数与最高等级
run(
    "F2. 近7天活跃玩家数与最高等级",
    f"""
SELECT serverid,
       COUNT(DISTINCT iuid) AS active_users_7d,
       MAX(CAST(user_level AS INTEGER)) AS max_level
FROM raw_scribe_log.login
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '20260713' AND '{DS_END}'
GROUP BY serverid
ORDER BY serverid
""",
)

# G. 消费系统分布 (prop, 玩家钻石消费去向 ≈ 参与的系统/玩法)
run(
    "G. 钻石消费系统分布 (prop.custom_pra1 = class.method)",
    f"""
SELECT serverid, custom_pra1 AS system_method,
       COUNT(*) AS times,
       COUNT(DISTINCT iuid) AS users,
       SUM(CAST(custom_pra3 AS BIGINT)) AS cost_diamonds
FROM raw_scribe_log.prop
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '{DS_START}' AND '{DS_END}'
GROUP BY serverid, custom_pra1
ORDER BY serverid, cost_diamonds DESC
""",
    max_rows=500,
)

# H. 每日付费趋势
run(
    "H. 每服每日付费金额 (美元)",
    f"""
SELECT serverid, ds,
       COUNT(DISTINCT iuid) AS payers,
       ROUND(SUM(CAST(custom_pra3 AS DOUBLE)) / 100, 2) AS usd
FROM raw_scribe_log.pay
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '{DS_START}' AND '{DS_END}'
GROUP BY serverid, ds
ORDER BY serverid, ds
""",
)
