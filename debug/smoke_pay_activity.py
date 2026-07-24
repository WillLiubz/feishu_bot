"""一次性真实库冒烟:pay_activity 报表 7 个 Sheet 整跑(Task 9)。

用法:
    set PYTHONIOENCODING=utf-8
    set DATA_API_POLL_MAX_ATTEMPTS=60
    python debug/smoke_pay_activity.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import config
import dataapi
import templates
import name_enrich

_orig_run = dataapi.run_sql_rows
_timings = []
_sheet_idx = [0]


def timed_run(sql, max_rows=None):
    _sheet_idx[0] += 1
    idx = _sheet_idx[0]
    t0 = time.time()
    try:
        rows = _orig_run(sql, max_rows=max_rows)
        dt = time.time() - t0
        _timings.append((idx, dt, len(rows), None))
        return rows
    except Exception as e:
        dt = time.time() - t0
        _timings.append((idx, dt, -1, repr(e)[:300]))
        raise


dataapi.run_sql_rows = timed_run

gc = config.game_config(312)
summary, result_dir = templates.run_report("pay_activity", "昨天付费构成", gc)
print(summary)
print("result_dir:", result_dir)

translated = name_enrich.translate_dir(result_dir, gc)
print("translated:", translated)

for idx, dt, nrows, err in _timings:
    print(f"sheet{idx}: {dt:.1f}s rows={nrows} err={err}")

for p in sorted(Path(result_dir).glob("query_*.csv")):
    lines = p.read_text(encoding="utf-8-sig").splitlines()
    print(p.name, len(lines), "lines; header:", lines[0] if lines else "<empty>")
    # Sheet 7 道具名称非空检查
    if p.name == "query_7.csv" and len(lines) > 1:
        header = lines[0].split(",")
        if "道具名称" in header:
            i = header.index("道具名称")
            nonempty = sum(
                1 for ln in lines[1:]
                if len(ln.split(",")) > i and ln.split(",")[i].strip()
            )
            print(f"  sheet7 道具名称非空行: {nonempty}/{len(lines)-1}")
