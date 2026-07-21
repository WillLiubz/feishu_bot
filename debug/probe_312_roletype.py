"""定位 312 rolelogin 超时原因: role_type 过滤写法对比(单天)。"""
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
BASE = f"""SELECT server_id, role_id, MAX(TRY_CAST(role_level AS BIGINT)) AS lvl
FROM gamelog_raw.v_presto_log_rolelogin
WHERE game_id = 312 AND server_id IN {S8} AND ds = '20260715'
{{extra}}
GROUP BY server_id, role_id"""

CASES = [
    ("无 role_type 过滤", BASE.format(extra="")),
    ("role_type = 1 不加引号", BASE.format(extra="AND role_type = 1")),
    ("role_type = '1' 加引号", BASE.format(extra="AND role_type = '1'")),
]
for title, sql in CASES:
    print(f"=== {title} ===", flush=True)
    t0 = time.time()
    try:
        rows = dataapi.run_sql_rows(sql, max_rows=100000)
        print(f"  {time.time()-t0:.0f}s rows={len(rows)}", flush=True)
    except Exception as e:
        print(f"  {time.time()-t0:.0f}s ERR: {e}", flush=True)
