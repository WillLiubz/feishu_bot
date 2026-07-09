"""
调试数据库选库重写逻辑。

用法：
    python debug/test_db_rewrite.py
    python debug/test_db_rewrite.py "SELECT * FROM gamelog_odl.v_presto_log_rolelogin WHERE game_id = 160"
    python debug/test_db_rewrite.py "-- use_odl\nSELECT * FROM gamelog_odl.v_presto_log_rolelogin WHERE game_id = 160"
"""
import argparse
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import db_rewrite


SAMPLES = [
    ("单表 odl → raw", "SELECT COUNT(*) FROM gamelog_odl.v_presto_log_rolelogin WHERE game_id = 312"),
    ("多表 odl → raw", "SELECT * FROM gamelog_odl.v_presto_log_rolelogin a, gamelog_odl.v_presto_log_payrecharge b WHERE a.game_id = 312"),
    ("gameeco_odl 不改写", "SELECT * FROM gameeco_odl.v_presto_log_rolebehavior WHERE game_id = '312'"),
    ("字符串字面量保护", "SELECT 'gamelog_odl' AS note FROM gamelog_odl.v_presto_log_rolelogin WHERE game_id = 312"),
    ("使用 use_odl 保留 odl", "-- use_odl\nSELECT * FROM gamelog_odl.v_presto_log_rolelogin WHERE game_id = 312"),
]


def main():
    parser = argparse.ArgumentParser(description="Test db_rewrite logic")
    parser.add_argument("sql", nargs="?", help="Optional single SQL to test")
    args = parser.parse_args()

    if args.sql:
        samples = [("命令行", args.sql)]
    else:
        samples = SAMPLES

    for label, sql in samples:
        cleaned, use_odl = db_rewrite.extract_odl_hint(sql)
        final = cleaned if use_odl else db_rewrite.rewrite_odl_to_raw(cleaned)
        print(f"[{label}]")
        print(f"  use_odl hint: {use_odl}")
        print(f"  original:     {sql.replace(chr(10), ' ')}")
        print(f"  final:        {final.replace(chr(10), ' ')}")
        print()


if __name__ == "__main__":
    main()
