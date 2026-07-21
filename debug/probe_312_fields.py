"""探查 312(修正版): 全部加引号 + 小窗口。"""
import io
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import dataapi

config.DATA_API_POLL_MAX_ATTEMPTS = 72

S8 = "('1448311606','1448311607','1448311608','1448311609','1448311610','1448311611','1448311612','1448311613')"

CASES = [
    ("payrecharge 币种分布(6月窗口)",
     f"SELECT pay_currency, COUNT(*) c, ROUND(SUM(COALESCE(TRY_CAST(pay_money AS DOUBLE),0)),2) money FROM gamelog_raw.v_presto_log_payrecharge WHERE game_id=312 AND server_id IN {S8} AND ds BETWEEN '20260601' AND '20260630' GROUP BY pay_currency"),
    ("payrecharge pay_type 分布(6月窗口)",
     f"SELECT pay_type, COUNT(*) c FROM gamelog_raw.v_presto_log_payrecharge WHERE game_id=312 AND server_id IN {S8} AND ds BETWEEN '20260601' AND '20260630' GROUP BY pay_type"),
    ("roleres 资源类型分布(gameeco 加引号, 1天1服)",
     "SELECT res_id, res_name, change_type, COUNT(*) c FROM gameeco_raw.v_presto_log_roleres WHERE game_id='312' AND server_id = '1448311610' AND ds='20260715' GROUP BY res_id, res_name, change_type ORDER BY c DESC LIMIT 20"),
    ("rolepromo 活动抽样(6月服, 6月窗口)",
     f"SELECT activity_topic, activity_pay, COUNT(*) c, COUNT(DISTINCT role_id) roles FROM gameeco_raw.v_presto_log_rolepromo WHERE game_id='312' AND server_id IN {S8} AND ds BETWEEN '20260601' AND '20260630' GROUP BY activity_topic, activity_pay ORDER BY c DESC LIMIT 25"),
    ("rolelogin role_level 抽样(查 level 字段)",
     f"SELECT role_id, role_level, role_type FROM gamelog_raw.v_presto_log_rolelogin WHERE game_id=312 AND server_id IN {S8} AND ds='20260715' LIMIT 5"),
]
for title, sql in CASES:
    print(f"=== {title} ===", flush=True)
    t0 = time.time()
    try:
        rows = dataapi.run_sql_rows(sql, max_rows=100)
        print(f"  {time.time()-t0:.0f}s rows={len(rows)}", flush=True)
        for r in rows[:25]:
            print("   ", r, flush=True)
    except Exception as e:
        print(f"  {time.time()-t0:.0f}s ERR: {e}", flush=True)
