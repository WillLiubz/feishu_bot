"""验证 server_id 加引号后的查询耗时(单天)。"""
import io
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import dataapi

config.DATA_API_POLL_MAX_ATTEMPTS = 72

CASES = [
    ("raw rolereg 单天 加引号",
     "SELECT server_id, COUNT(*) AS cnt FROM gamelog_raw.v_presto_log_rolereg WHERE game_id = 160 AND server_id IN ('2251312168','2251312169') AND ds = '20260715' GROUP BY server_id"),
    ("raw rolereg 7天 加引号 GROUP BY ds",
     "SELECT server_id, ds, COUNT(*) AS cnt FROM gamelog_raw.v_presto_log_rolereg WHERE game_id = 160 AND server_id IN ('2251312168','2251312169') AND ds BETWEEN '20260713' AND '20260719' GROUP BY server_id, ds ORDER BY ds"),
]
for title, sql in CASES:
    print(f"=== {title} ===", flush=True)
    t0 = time.time()
    try:
        rows = dataapi.run_sql_rows(sql, max_rows=100)
        print(f"  {time.time()-t0:.0f}s -> {rows}", flush=True)
    except Exception as e:
        print(f"  {time.time()-t0:.0f}s ERR: {e}", flush=True)
