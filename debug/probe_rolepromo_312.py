"""探针：实测 312 rolepromo 表，为 pay_activity 模板提供口径依据。

用法：python debug/probe_rolepromo_312.py [yyyymmdd]  （默认昨天）
需要本机 config.json 已配置可用的 data_api。
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import dataapi

DS = sys.argv[1] if len(sys.argv) > 1 else (date.today() - timedelta(days=1)).strftime("%Y%m%d")


def probe(title, sql, max_rows=20):
    print(f"\n=== {title} ===")
    try:
        rows = dataapi.run_sql_rows(sql, max_rows=max_rows)
        if not rows:
            print("(no rows)")
        for r in rows:
            print(r)
    except Exception as e:
        print(f"ERROR: {e}")


probe(
    "1. game_id 列类型",
    "SELECT typeof(game_id) AS t FROM gameeco_raw.v_presto_log_rolepromo "
    f"WHERE ds = '{DS}' LIMIT 1",
)
probe(
    "2. role_type 列是否存在",
    "SELECT typeof(role_type) AS t FROM gameeco_raw.v_presto_log_rolepromo "
    f"WHERE ds = '{DS}' LIMIT 1",
)
probe(
    "3. item_spend / item_get 样例",
    "SELECT activity_topic, item_spend, item_get "
    "FROM gameeco_raw.v_presto_log_rolepromo "
    f"WHERE game_id = '312' AND ds = '{DS}' "
    "AND item_spend IS NOT NULL AND item_spend <> '' LIMIT 10",
)
probe(
    "4. 当日 activity_topic 分布（对照运营日历）",
    "SELECT activity_topic, activity_special, activity_pay, COUNT(*) AS cnt "
    "FROM gameeco_raw.v_presto_log_rolepromo "
    f"WHERE game_id = '312' AND ds = '{DS}' "
    "GROUP BY activity_topic, activity_special, activity_pay ORDER BY cnt DESC",
    max_rows=100,
)
probe(
    "5. role_id 列类型（JOIN 键确认）",
    "SELECT typeof(role_id) AS t FROM gameeco_raw.v_presto_log_rolepromo "
    f"WHERE ds = '{DS}' LIMIT 1",
)
