"""
调试用户流失 / 沉默分析 SQL。

用法：
    python debug/test_churn_sql.py
    python debug/test_churn_sql.py --days 7
    python debug/test_churn_sql.py --mock
    python debug/test_churn_sql.py --sql-type churn_detail --days 14
    python debug/test_churn_sql.py --end-date 2026-06-29 --days 7

SQL 来源：schema_312.md 示例 SQL 章节。
"""
import argparse
import io
import sys
from datetime import date, timedelta
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import dataapi
import dquery


SQLS = {
    "overview": """
WITH params AS (
  SELECT
    '{end_ds}' AS end_ds,
    '{start_ds}' AS start_ds,
    '{end_date}' AS end_date,
    '{start_date}' AS start_date
),

role_pool AS (
  SELECT DISTINCT
    role_id,
    role_name,
    server_id,
    opgame_id,
    role_level,
    role_vip,
    total_pay_money,
    last_login
  FROM gameeco_raw.v_presto_snap_rolecache
  WHERE game_id = '312'
    AND SUBSTR(cache_day, 1, 10) = '{end_date}'
    AND role_type = 1
    AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
),

recent_login AS (
  SELECT
    role_id,
    MAX(ds) AS last_login_ds,
    COUNT(DISTINCT ds) AS login_days
  FROM gamelog_odl.v_presto_log_rolelogin
  WHERE game_id = 312
    AND ds >= '{start_ds}'
    AND ds <= '{end_ds}'
    AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
  GROUP BY role_id
),

recent_pay AS (
  SELECT
    role_id,
    SUM(CAST(pay_money AS DOUBLE)) AS recent_pay_money,
    COUNT(*) AS recent_pay_times
  FROM gamelog_odl.v_presto_log_payrecharge
  WHERE game_id = 312
    AND ds >= '{start_ds}'
    AND ds <= '{end_ds}'
    AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
  GROUP BY role_id
),

classified AS (
  SELECT
    r.role_id,
    r.role_name,
    r.opgame_id,
    r.role_level,
    r.role_vip,
    COALESCE(r.total_pay_money, 0) AS total_pay_money,
    CASE WHEN l.role_id IS NOT NULL THEN 1 ELSE 0 END AS has_login_n_days,
    l.last_login_ds,
    l.login_days,
    COALESCE(p.recent_pay_money, 0) AS recent_pay_money,
    CASE
      WHEN l.role_id IS NULL THEN '流失'
      WHEN r.total_pay_money > 0 AND COALESCE(p.recent_pay_money, 0) = 0 THEN '沉默'
      ELSE '活跃'
    END AS life_state,
    CASE WHEN COALESCE(r.total_pay_money, 0) > 0 THEN '付费用户' ELSE '免费用户' END AS pay_type
  FROM role_pool r
  LEFT JOIN recent_login l ON r.role_id = l.role_id
  LEFT JOIN recent_pay  p ON r.role_id = p.role_id
)

SELECT
  pay_type,
  life_state,
  COUNT(DISTINCT role_id) AS user_count,
  ROUND(AVG(role_level), 1) AS avg_level,
  ROUND(AVG(role_vip), 1) AS avg_vip,
  ROUND(SUM(total_pay_money), 2) AS total_pay
FROM classified
GROUP BY pay_type, life_state
ORDER BY pay_type, life_state
LIMIT 50
""",

    "churn_detail": """
SELECT
  r.role_id,
  r.role_name,
  r.server_id,
  r.opgame_id,
  r.role_level,
  r.role_vip,
  r.total_pay_money,
  r.last_login
FROM gameeco_raw.v_presto_snap_rolecache r
WHERE r.game_id = '312'
  AND SUBSTR(cache_day, 1, 10) = '{end_date}'
  AND r.role_type = 1
  AND SUBSTR(CAST(r.server_id AS VARCHAR), 5, 1) != '4'
  AND COALESCE(r.total_pay_money, 0) > 0
  AND NOT EXISTS (
    SELECT 1
    FROM gamelog_odl.v_presto_log_rolelogin l
    WHERE l.game_id = 312
      AND l.role_id = r.role_id
      AND l.ds >= '{start_ds}'
      AND l.ds <= '{end_ds}'
      AND SUBSTR(CAST(l.server_id AS VARCHAR), 5, 1) != '4'
  )
ORDER BY r.total_pay_money DESC
LIMIT 200
""",

    "silent_detail": """
SELECT
  r.role_id,
  r.role_name,
  r.server_id,
  r.opgame_id,
  r.role_level,
  r.role_vip,
  r.total_pay_money,
  r.last_login
FROM gameeco_raw.v_presto_snap_rolecache r
WHERE r.game_id = '312'
  AND SUBSTR(cache_day, 1, 10) = '{end_date}'
  AND r.role_type = 1
  AND SUBSTR(CAST(r.server_id AS VARCHAR), 5, 1) != '4'
  AND COALESCE(r.total_pay_money, 0) > 0
  AND EXISTS (
    SELECT 1
    FROM gamelog_odl.v_presto_log_rolelogin l
    WHERE l.game_id = 312
      AND l.role_id = r.role_id
      AND l.ds >= '{start_ds}'
      AND l.ds <= '{end_ds}'
      AND SUBSTR(CAST(l.server_id AS VARCHAR), 5, 1) != '4'
  )
  AND NOT EXISTS (
    SELECT 1
    FROM gamelog_odl.v_presto_log_payrecharge p
    WHERE p.game_id = 312
      AND p.role_id = r.role_id
      AND p.ds >= '{start_ds}'
      AND p.ds <= '{end_ds}'
      AND SUBSTR(CAST(p.server_id AS VARCHAR), 5, 1) != '4'
  )
ORDER BY r.total_pay_money DESC
LIMIT 200
""",
}


def _fmt_num(n):
    """Format number with thousand separators."""
    try:
        return f"{int(float(n)):,}"
    except (ValueError, TypeError):
        return str(n)


def _print_table(rows, title):
    if not rows:
        print(f"[{title}] 无数据\n")
        return

    headers = list(rows[0].keys())
    # Calculate column widths
    widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            widths[h] = max(widths[h], len(str(row.get(h, ""))))

    # Print header
    sep = "+" + "+".join("-" * (widths[h] + 2) for h in headers) + "+"
    print(f"\n[{title}] 共 {len(rows)} 行")
    print(sep)
    print("| " + " | ".join(h.ljust(widths[h]) for h in headers) + " |")
    print(sep)
    for row in rows:
        print("| " + " | ".join(str(row.get(h, "")).ljust(widths[h]) for h in headers) + " |")
    print(sep)


def _build_conclusion(overview_rows):
    """Build a Chinese conclusion from overview rows."""
    if not overview_rows:
        return "分类统计数据为空。"

    total = 0
    paid_total = 0
    paid_active = 0
    paid_silent = 0
    paid_churn = 0
    free_total = 0
    free_active = 0
    free_churn = 0

    for r in overview_rows:
        cnt = int(float(r.get("user_count", 0)))
        total += cnt
        pay_type = r.get("pay_type", "")
        state = r.get("life_state", "")
        if pay_type == "付费用户":
            paid_total += cnt
            if state == "活跃":
                paid_active = cnt
            elif state == "沉默":
                paid_silent = cnt
            elif state == "流失":
                paid_churn = cnt
        else:
            free_total += cnt
            if state == "活跃":
                free_active = cnt
            elif state == "流失":
                free_churn = cnt

    lines = [
        "结论：",
        f"  全量正常角色 {total:,} 个（以最新快照为分母，已排除测试服/机器人/GM）。",
        f"  付费用户 {paid_total:,} 个：活跃 {paid_active:,} 人，沉默 {paid_silent:,} 人，流失 {paid_churn:,} 人。",
        f"  免费用户 {free_total:,} 个：活跃 {free_active:,} 人，流失 {free_churn:,} 人。",
    ]
    if paid_total > 0:
        lines.append(
            f"  付费用户中：活跃占比 {paid_active/paid_total*100:.1f}%，沉默占比 {paid_silent/paid_total*100:.1f}%，流失占比 {paid_churn/paid_total*100:.1f}%。"
        )
    lines.append(
        "  口径说明：流失只看登录，不看充值；付费用户只要还在登录，即使近期无充值也计为沉默，不计为流失。"
    )
    return "\n".join(lines)


def _latest_cache_day():
    """Query the latest available cache_day for snap_rolecache (game_id=312)."""
    sql = """
    SELECT MAX(SUBSTR(cache_day, 1, 10)) AS latest_day
    FROM gameeco_raw.v_presto_snap_rolecache
    WHERE game_id = '312'
      AND cache_day LIKE '____-__-__%'
    """
    rows = dataapi.run_sql_rows(sql, max_rows=10)
    if rows and rows[0].get("latest_day"):
        return rows[0]["latest_day"]
    return None


def main():
    parser = argparse.ArgumentParser(description="Test churn / silent user analysis SQL")
    parser.add_argument("--days", type=int, default=7, help="Observation window days (default 7)")
    parser.add_argument("--sql-type", choices=["overview", "churn_detail", "silent_detail", "all"], default="all", help="Which SQL to run")
    parser.add_argument("--mock", action="store_true", help="Force mock mode")
    parser.add_argument("--csv", action="store_true", help="Save results to CSV")
    parser.add_argument("--limit", type=int, default=200, help="Row limit for detail SQLs")
    parser.add_argument("--end-date", type=str, default=None, help="End date yyyy-MM-dd (default: latest available cache_day)")
    args = parser.parse_args()

    if args.mock:
        config.DATA_API_MOCK = True

    # Determine end date: use provided value, otherwise query latest available cache_day
    if args.end_date:
        end_date = date.fromisoformat(args.end_date)
    else:
        latest = _latest_cache_day()
        if latest:
            end_date = date.fromisoformat(latest)
            print(f"未指定 --end-date，使用数仓最新快照日期: {latest}")
        else:
            end_date = date.today() - timedelta(days=1)
            print(f"无法查询最新快照日期，默认使用昨天: {end_date.strftime('%Y-%m-%d')}")

    start_date = end_date - timedelta(days=args.days - 1)
    end_ds = end_date.strftime("%Y%m%d")
    start_ds = start_date.strftime("%Y%m%d")
    end_date_str = end_date.strftime("%Y-%m-%d")
    start_date_str = start_date.strftime("%Y-%m-%d")

    print(f"观察窗口：{args.days} 天")
    print(f"结束日期：{end_ds} / {end_date_str}")
    print(f"开始日期：{start_ds} / {start_date_str}")
    print(f"mock 模式：{args.mock or config.DATA_API_MOCK}\n")

    types_to_run = list(SQLS.keys()) if args.sql_type == "all" else [args.sql_type]

    all_results = {}
    for sql_type in types_to_run:
        sql_template = SQLS[sql_type]
        sql = sql_template.format(
            end_ds=end_ds,
            start_ds=start_ds,
            end_date=end_date_str,
            start_date=start_date_str,
        )
        # Replace LIMIT in detail templates if user specified
        if args.limit != 200:
            sql = sql.replace("LIMIT 200", f"LIMIT {args.limit}")

        print(f"\n{'='*60}")
        print(f"执行 [{sql_type}]")
        print(f"{'='*60}")
        print(f"SQL:\n{sql}\n")

        try:
            rows = dataapi.run_sql_rows(sql, max_rows=300)
            print(f"返回 {len(rows)} 行")
            _print_table(rows, sql_type)
            all_results[sql_type] = rows

            if sql_type == "overview":
                print("\n" + _build_conclusion(rows))

            if args.csv and rows:
                csv_path = Path(config._ROOT) / "data" / f"churn_{sql_type}_{end_ds}.csv"
                dquery.write_csv_to(rows, csv_path)
                print(f"\n已保存 CSV: {csv_path}")
        except Exception as e:
            print(f"[FAIL] 执行失败: {e}")
            return 1

    print(f"\n{'='*60}")
    print("全部执行完成")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
