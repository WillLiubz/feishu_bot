"""确认 raw_scribe_log 中 serverid 格式与 GM dc_server_id 的对应关系。"""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import dataapi

sql = """
SELECT serverid, COUNT(*) AS cnt
FROM raw_scribe_log.est
WHERE gameid = '39' AND ds >= '20260710'
GROUP BY serverid
ORDER BY cnt DESC
LIMIT 30
"""
rows = dataapi.run_sql_rows(sql, max_rows=30)
for r in rows:
    print(r)
