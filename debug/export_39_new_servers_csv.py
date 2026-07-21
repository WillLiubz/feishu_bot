"""将 39 游戏 5月/6月新服分析结论导出为 CSV 文件。

输出目录: debug/output/39_new_servers/
"""
import csv
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import dataapi

OUT_DIR = Path(__file__).parent / "output" / "39_new_servers"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SERVERS = "('39005900001598','39005900001599','39005900001600','39005900001601')"
DS_START, DS_END = "20260510", "20260719"

SERVER_META = {
    "39005900001598": {"batch": "5月", "name": "Elysia(1598)", "open": "2026-05-10", "open_ds": "20260510"},
    "39005900001599": {"batch": "5月", "name": "Order(1599)", "open": "2026-05-20", "open_ds": "20260520"},
    "39005900001600": {"batch": "6月", "name": "Moon(1600)", "open": "2026-06-10", "open_ds": "20260610"},
    "39005900001601": {"batch": "6月", "name": "Crescent(1601)", "open": "2026-06-20", "open_ds": "20260620"},
}
ORDER = list(SERVER_META.keys())


def write_csv(filename, header, rows):
    path = OUT_DIR / filename
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"[OK] {path}  ({len(rows)} 行)")


def run(title, sql, max_rows=1000, poll=None):
    print(f"[query] {title} ...")
    try:
        return dataapi.run_sql_rows(sql, max_rows=max_rows, poll_max_attempts=poll)
    except TypeError:
        return dataapi.run_sql_rows(sql, max_rows=max_rows)


# ---------- 查询 ----------
daily_reg = run(
    "每日注册(含系统账号拆分)",
    f"""
SELECT serverid, ds,
       COUNT(DISTINCT iuid) AS new_users,
       COUNT(DISTINCT CASE WHEN ouid NOT LIKE 'system@%' THEN iuid END) AS real_new_users
FROM raw_scribe_log.est
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '{DS_START}' AND '{DS_END}'
GROUP BY serverid, ds
ORDER BY serverid, ds
""",
    poll=60,
)

reg_split = run(
    "注册总量拆分",
    f"""
SELECT serverid,
       COUNT(DISTINCT iuid) AS total_reg,
       COUNT(DISTINCT CASE WHEN ouid LIKE 'system@%' THEN iuid END) AS system_accounts,
       COUNT(DISTINCT CASE WHEN ouid NOT LIKE 'system@%' THEN iuid END) AS real_reg
FROM raw_scribe_log.est
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '{DS_START}' AND '{DS_END}'
GROUP BY serverid
""",
)

pay_sum = run(
    "付费汇总",
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
""",
)

pay_type = run(
    "付费类型拆分",
    f"""
SELECT serverid, custom_pra1 AS pay_type,
       COUNT(DISTINCT iuid) AS payers,
       COUNT(*) AS times,
       ROUND(SUM(CAST(custom_pra3 AS DOUBLE)) / 100, 2) AS usd
FROM raw_scribe_log.pay
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '{DS_START}' AND '{DS_END}'
GROUP BY serverid, custom_pra1
""",
)

daily_pay = run(
    "每日付费趋势",
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
    poll=60,
)

level_dist = run(
    "近7天活跃玩家等级分布",
    f"""
WITH lv AS (
  SELECT serverid, iuid, MAX(CAST(user_level AS INTEGER)) AS lvl
  FROM raw_scribe_log.login
  WHERE gameid = '39' AND serverid IN {SERVERS}
    AND ds BETWEEN '20260713' AND '{DS_END}'
  GROUP BY serverid, iuid
)
SELECT serverid,
       COUNT(*) AS active_users_7d,
       MAX(lvl) AS max_level,
       SUM(CASE WHEN lvl < 20 THEN 1 ELSE 0 END) AS lv_01_19,
       SUM(CASE WHEN lvl >= 20 AND lvl < 40 THEN 1 ELSE 0 END) AS lv_20_39,
       SUM(CASE WHEN lvl >= 40 AND lvl < 60 THEN 1 ELSE 0 END) AS lv_40_59,
       SUM(CASE WHEN lvl >= 60 AND lvl < 80 THEN 1 ELSE 0 END) AS lv_60_79,
       SUM(CASE WHEN lvl >= 80 THEN 1 ELSE 0 END) AS lv_80_plus
FROM lv
GROUP BY serverid
""",
)

prop_top = run(
    "钻石消费系统分布",
    f"""
SELECT serverid, custom_pra1 AS system_method,
       COUNT(*) AS times,
       COUNT(DISTINCT iuid) AS users,
       SUM(TRY_CAST(custom_pra3 AS BIGINT)) AS cost_diamonds
FROM raw_scribe_log.prop
WHERE gameid = '39' AND serverid IN {SERVERS}
  AND ds BETWEEN '{DS_START}' AND '{DS_END}'
GROUP BY serverid, custom_pra1
ORDER BY serverid, cost_diamonds DESC
""",
    max_rows=1000, poll=60,
)

gift_top = run(
    "直购礼包TOP",
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
    max_rows=300,
)

# ---------- 加工 ----------
idx = {r["serverid"]: r for r in reg_split}
ipay = {r["serverid"]: r for r in pay_sum}
ilvl = {r["serverid"]: r for r in level_dist}

def open_plus7(open_ds):
    y, m, d = int(open_ds[:4]), int(open_ds[4:6]), int(open_ds[6:])
    import datetime
    return (datetime.date(y, m, d) + datetime.timedelta(days=6)).strftime("%Y%m%d")

# 首7日注册/付费
first7_reg = {s: 0 for s in ORDER}
for r in daily_reg:
    s = r["serverid"]
    if SERVER_META[s]["open_ds"] <= r["ds"] <= open_plus7(SERVER_META[s]["open_ds"]):
        first7_reg[s] += int(r["real_new_users"])

first7_pay = {s: 0.0 for s in ORDER}
for r in daily_pay:
    s = r["serverid"]
    if SERVER_META[s]["open_ds"] <= r["ds"] <= open_plus7(SERVER_META[s]["open_ds"]):
        first7_pay[s] += float(r["usd"])

# ---------- 写 CSV ----------
# 01 新服概况
write_csv(
    "01_新服概况.csv",
    ["批次", "serverid", "服名", "开服时间", "运营商"],
    [[SERVER_META[s]["batch"], s, SERVER_META[s]["name"], SERVER_META[s]["open"], "590"] for s in ORDER],
)

# 02 注册汇总
write_csv(
    "02_注册汇总.csv",
    ["批次", "服名", "serverid", "累计注册(含系统账号)", "系统账号数", "真实注册", "首7日真实注册"],
    [[SERVER_META[s]["batch"], SERVER_META[s]["name"], s,
      idx[s]["total_reg"], idx[s]["system_accounts"], idx[s]["real_reg"], first7_reg[s]] for s in ORDER],
)

# 03 付费汇总
write_csv(
    "03_付费汇总.csv",
    ["批次", "服名", "serverid", "付费人数", "真实注册", "付费率%", "充值总额(美元)", "充值总额(钻石)", "充值笔数", "ARPPU(美元)"],
    [[SERVER_META[s]["batch"], SERVER_META[s]["name"], s,
      ipay[s]["payers"], idx[s]["real_reg"],
      round(int(ipay[s]["payers"]) / int(idx[s]["real_reg"]) * 100, 1),
      ipay[s]["total_usd"], ipay[s]["total_diamonds"], ipay[s]["pay_times"], ipay[s]["arppu_usd"]] for s in ORDER],
)

# 04 首7日对齐对比
write_csv(
    "04_首7日对齐对比.csv",
    ["批次", "服名", "serverid", "首7日注册", "首7日付费(美元)", "首7日ARPU(美元)"],
    [[SERVER_META[s]["batch"], SERVER_META[s]["name"], s,
      first7_reg[s], round(first7_pay[s], 2),
      round(first7_pay[s] / first7_reg[s], 2) if first7_reg[s] else 0] for s in ORDER],
)

# 05 付费类型拆分
type_name = {"1": "兑换游戏币", "2": "直购礼包"}
write_csv(
    "05_付费类型拆分.csv",
    ["批次", "服名", "serverid", "付费类型", "付费人数", "笔数", "金额(美元)"],
    [[SERVER_META[r["serverid"]]["batch"], SERVER_META[r["serverid"]]["name"], r["serverid"],
      type_name.get(r["pay_type"], r["pay_type"]), r["payers"], r["times"], r["usd"]]
     for r in sorted(pay_type, key=lambda x: (ORDER.index(x["serverid"]), x["pay_type"]))],
)

# 06 等级分布
write_csv(
    "06_等级分布_近7天活跃.csv",
    ["批次", "服名", "serverid", "近7天活跃人数", "最高等级", "1-19级", "20-39级", "40-59级", "60-79级", "80级以上", "活跃/真实注册%"],
    [[SERVER_META[s]["batch"], SERVER_META[s]["name"], s,
      ilvl[s]["active_users_7d"], ilvl[s]["max_level"],
      ilvl[s]["lv_01_19"], ilvl[s]["lv_20_39"], ilvl[s]["lv_40_59"], ilvl[s]["lv_60_79"], ilvl[s]["lv_80_plus"],
      round(int(ilvl[s]["active_users_7d"]) / int(idx[s]["real_reg"]) * 100, 1)] for s in ORDER],
)

# 07 消费系统TOP15 (每服)
rows = []
for s in ORDER:
    tops = [r for r in prop_top if r["serverid"] == s][:15]
    for i, r in enumerate(tops, 1):
        rows.append([SERVER_META[s]["batch"], SERVER_META[s]["name"], s, i,
                     r["system_method"], r["users"], r["times"], r["cost_diamonds"]])
write_csv("07_钻石消费系统TOP15.csv", ["批次", "服名", "serverid", "排名", "消费系统(class.method)", "消费人数", "消费次数", "消费钻石"], rows)

# 08 直购礼包TOP (全服合计 + 分服)
from collections import defaultdict
gift_agg = defaultdict(lambda: [0, 0, 0.0])
for r in gift_top:
    g = gift_agg[r["gift_id"]]
    g[0] += int(r["payers"]); g[1] += int(r["times"]); g[2] += float(r["usd"])
rows = [[gid, v[0], v[1], round(v[2], 2)] for gid, v in sorted(gift_agg.items(), key=lambda kv: -kv[1][2])]
write_csv("08_直购礼包TOP_全服合计.csv", ["礼包ID", "付费人数(分服累加)", "购买笔数", "金额(美元)"], rows)

rows = [[SERVER_META[r["serverid"]]["batch"], SERVER_META[r["serverid"]]["name"], r["serverid"],
         r["gift_id"], r["payers"], r["times"], r["usd"]]
        for r in sorted(gift_top, key=lambda x: (ORDER.index(x["serverid"]), -float(x["usd"])))]
write_csv("09_直购礼包TOP_分服.csv", ["批次", "服名", "serverid", "礼包ID", "付费人数", "购买笔数", "金额(美元)"], rows)

# 10 每日注册趋势
write_csv(
    "10_每日新增注册.csv",
    ["批次", "服名", "serverid", "日期(ds)", "新增注册", "真实新增(剔除系统账号)"],
    [[SERVER_META[r["serverid"]]["batch"], SERVER_META[r["serverid"]]["name"], r["serverid"],
      r["ds"], r["new_users"], r["real_new_users"]] for r in daily_reg],
)

# 11 每日付费趋势
write_csv(
    "11_每日付费趋势.csv",
    ["批次", "服名", "serverid", "日期(ds)", "付费人数", "付费金额(美元)"],
    [[SERVER_META[r["serverid"]]["batch"], SERVER_META[r["serverid"]]["name"], r["serverid"],
      r["ds"], r["payers"], r["usd"]] for r in daily_pay],
)

print(f"\n全部导出完成 -> {OUT_DIR}")
