"""定位 312 gameeco roleres 超时: res_id/change_type/role_type 引号矩阵(单天单服)。"""
import io
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import dataapi

config.DATA_API_POLL_MAX_ATTEMPTS = 30

BASE = """SELECT COUNT(*) c FROM gameeco_raw.v_presto_log_roleres
WHERE game_id = '312' AND server_id = '1448311610' AND ds = '20260715' {extra}"""

CASES = [
    ("无额外过滤", ""),
    ("res_id IN (2,3) 不加引号", "AND res_id IN (2,3)"),
    ("res_id IN ('2','3') 加引号", "AND res_id IN ('2','3')"),
    ("change_type = 2 不加引号", "AND change_type = 2"),
    ("role_type = 1 不加引号", "AND role_type = 1"),
]
for title, extra in CASES:
    print(f"=== {title} ===", flush=True)
    t0 = time.time()
    try:
        rows = dataapi.run_sql_rows(BASE.format(extra=extra), max_rows=10)
        print(f"  {time.time()-t0:.0f}s -> {rows}", flush=True)
    except Exception as e:
        print(f"  {time.time()-t0:.0f}s ERR: {e}", flush=True)
