"""160 新服直购查证: vip.go 直购 payItemid='actId:giftId', 普通='0', pay_type 恒为 1。"""
import io
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import dataapi

config.DATA_API_POLL_MAX_ATTEMPTS = 72

S2 = "('2251312168','2251312169')"
WIN = "ds BETWEEN '20260506' AND '20260719'"

CASES = [
    ("pay_itemid 形态分布",
     f"""SELECT CASE WHEN strpos(pay_itemid, ':') > 0 THEN '直购 a:g' ELSE '普通(' || pay_itemid || ')' END AS kind,
       COUNT(*) c, COUNT(DISTINCT role_id) roles,
       ROUND(SUM(COALESCE(TRY_CAST(pay_money AS DOUBLE),0)),2) money
FROM gamelog_raw.v_presto_log_payrecharge
WHERE game_id = 160 AND server_id IN {S2} AND {WIN}
GROUP BY 1 ORDER BY money DESC"""),
    ("直购按 activityId 分布",
     f"""SELECT server_id, split_part(pay_itemid, ':', 1) AS act_id,
       COUNT(*) c, COUNT(DISTINCT role_id) roles,
       ROUND(SUM(COALESCE(TRY_CAST(pay_money AS DOUBLE),0)),2) money
FROM gamelog_raw.v_presto_log_payrecharge
WHERE game_id = 160 AND server_id IN {S2} AND {WIN}
  AND strpos(pay_itemid, ':') > 0
GROUP BY 1, 2 ORDER BY server_id, money DESC"""),
    ("直购按服×商品 TOP",
     f"""SELECT server_id, split_part(pay_itemid, ':', 1) AS act_id, split_part(pay_itemid, ':', 2) AS gift_id,
       COUNT(*) c, COUNT(DISTINCT role_id) roles,
       ROUND(SUM(COALESCE(TRY_CAST(pay_money AS DOUBLE),0)),2) money
FROM gamelog_raw.v_presto_log_payrecharge
WHERE game_id = 160 AND server_id IN {S2} AND {WIN}
  AND strpos(pay_itemid, ':') > 0
GROUP BY 1, 2, 3 ORDER BY server_id, money DESC LIMIT 50"""),
]

for title, sql in CASES:
    print(f"=== {title} ===", flush=True)
    t0 = time.time()
    try:
        rows = dataapi.run_sql_rows(sql, max_rows=10000)
        print(f"  {time.time()-t0:.0f}s rows={len(rows)}", flush=True)
        for r in rows[:60]:
            print("   ", r, flush=True)
    except Exception as e:
        print(f"  {time.time()-t0:.0f}s ERR: {e}", flush=True)
