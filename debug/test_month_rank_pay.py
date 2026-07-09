"""
调试月度排行榜玩家充值查询（快速路径）。

用法：
    python debug/test_month_rank_pay.py --year-month 202606 --top-n 100
    python debug/test_month_rank_pay.py --mock
    python debug/test_month_rank_pay.py --game-id 160 --year-month 202506
"""
import argparse
import io
import sys
import time
from datetime import date
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import dataapi
import dquery
import role_ranking_cache


def _fmt_num(n):
    try:
        return f"{int(float(n)):,}"
    except (ValueError, TypeError):
        return str(n)


def _print_table(rows, title):
    if not rows:
        print(f"[{title}] 无数据\n")
        return

    headers = list(rows[0].keys())
    widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            widths[h] = max(widths[h], len(str(row.get(h, ""))))

    sep = "+" + "+".join("-" * (widths[h] + 2) for h in headers) + "+"
    print(f"\n[{title}] 共 {len(rows)} 行")
    print(sep)
    print("| " + " | ".join(h.ljust(widths[h]) for h in headers) + " |")
    print(sep)
    for row in rows:
        print("| " + " | ".join(str(row.get(h, "")).ljust(widths[h]) for h in headers) + " |")
    print(sep)


def _build_pay_sql(role_ids, pay_start_ds, pay_end_ds, game_id):
    if not role_ids:
        return None
    in_list = ", ".join(f"'{rid}'" for rid in role_ids)
    return (
        f"SELECT role_id,"
        f" COUNT(*) AS pay_times,"
        f" CAST(SUM(CAST(pay_money AS DOUBLE)) AS DECIMAL(18,2)) AS total_pay"
        f" FROM gamelog_raw.v_presto_log_payrecharge"
        f" WHERE game_id = {game_id}"
        f" AND ds >= '{pay_start_ds}' AND ds <= '{pay_end_ds}'"
        f" AND role_id IN ({in_list})"
        f" AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'"
        f" GROUP BY role_id"
        f" ORDER BY total_pay DESC"
    )


def main():
    parser = argparse.ArgumentParser(description="Test month-ranking player recharge fast path")
    parser.add_argument("--year-month", type=str, default=None, help="YYYYMM (default: last month)")
    parser.add_argument("--top-n", type=int, default=100, help="Number of ranking players (default 100)")
    parser.add_argument("--game-id", type=int, default=None, help="Game ID (default from config)")
    parser.add_argument("--pay-start-ds", type=str, default=None, help="Recharge start ds YYYYMMDD")
    parser.add_argument("--pay-end-ds", type=str, default=None, help="Recharge end ds YYYYMMDD")
    parser.add_argument("--mock", action="store_true", help="Force mock mode")
    parser.add_argument("--use-rolebehavior", action="store_true", help="Use MonthRank from rolebehavior (slower)")
    parser.add_argument("--csv", action="store_true", help="Save results to CSV")
    args = parser.parse_args()

    if args.mock:
        config.DATA_API_MOCK = True

    year_month = args.year_month
    if year_month is None:
        today = date.today()
        y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        year_month = f"{y}{m:02d}"

    pay_start_ds = args.pay_start_ds or f"{year_month}01"
    pay_end_ds = args.pay_end_ds or f"{year_month}{calendar.monthrange(int(year_month[:4]), int(year_month[4:6]))[1]:02d}"

    game_id = args.game_id if args.game_id is not None else config.GAME_ID
    gcfg = config.GAMES.get(game_id)
    if gcfg is None:
        print(f"未找到游戏 {game_id}")
        return 1

    print(f"游戏: {game_id}")
    print(f"月份: {year_month}")
    print(f"排行榜 TOP-N: {args.top_n}")
    print(f"充值区间: {pay_start_ds} ~ {pay_end_ds}")
    print(f"mock 模式: {config.DATA_API_MOCK}")
    print(f"rolebehavior 模式: {args.use_rolebehavior}\n")

    if args.use_rolebehavior:
        role_ranking_cache.init(gcfg)

        # Step 1: get ranking players
        t0 = time.time()
        rank_map = role_ranking_cache.get_rank_map(
            year_month=year_month, rank_type="MonthRank", top_n=args.top_n, game_config=gcfg
        )
        t1 = time.time()
        print(f"[Step 1] 获取排行榜玩家 {len(rank_map)} 人，耗时 {int((t1 - t0) * 1000)}ms")

        if not rank_map:
            print("未找到月度排行榜玩家")
            return 0

        role_ids = list(rank_map.keys())
        print(f"前5名 role_id: {role_ids[:5]}")

        # Step 2: query payrecharge for those players
        pay_sql = _build_pay_sql(role_ids, pay_start_ds, pay_end_ds, game_id)
        print(f"\n[Step 2] 充值查询 SQL:\n{pay_sql}\n")

        t0 = time.time()
        rows = dataapi.run_sql_rows(pay_sql, max_rows=args.top_n)
        t1 = time.time()
        print(f"[Step 2] 充值查询返回 {len(rows)} 行，耗时 {int((t1 - t0) * 1000)}ms")

        # Enrich with rank
        for r in rows:
            rid = r.get("role_id")
            r["rank"] = rank_map.get(rid)

        # Sort by rank for display
        rows.sort(key=lambda r: (r.get("rank") or 999999))

        _print_table(rows[:20], "月度排行榜玩家充值情况（TOP 20）")

        total_payers = len(rows)
        total_revenue = sum(float(r.get("total_pay", 0) or 0) for r in rows)
        print(f"\n汇总：上榜玩家 {len(rank_map)} 人，其中充值人数 {total_payers}，充值总额 {total_revenue:,.2f} 元")

        if args.csv and rows:
            csv_path = Path(config._ROOT) / "data" / f"month_rank_pay_{game_id}_{year_month}.csv"
            dquery.write_csv_to(rows, csv_path)
            print(f"\n已保存 CSV: {csv_path}")

        return 0

    # Default fast path: top monthly rechargers
    pay_sql = (
        f"SELECT role_id,"
        f" COUNT(*) AS pay_times,"
        f" CAST(SUM(CAST(pay_money AS DOUBLE)) AS DECIMAL(18,2)) AS total_pay"
        f" FROM gamelog_raw.v_presto_log_payrecharge"
        f" WHERE game_id = {game_id}"
        f" AND ds >= '{pay_start_ds}' AND ds <= '{pay_end_ds}'"
        f" AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'"
        f" GROUP BY role_id"
        f" ORDER BY total_pay DESC"
        f" LIMIT {args.top_n}"
    )
    print(f"[Fast path] 月度充值排行榜 SQL:\n{pay_sql}\n")

    t0 = time.time()
    rows = dataapi.run_sql_rows(pay_sql, max_rows=args.top_n)
    t1 = time.time()
    print(f"[Fast path] 查询返回 {len(rows)} 行，耗时 {int((t1 - t0) * 1000)}ms")

    for i, r in enumerate(rows, start=1):
        r["rank"] = i

    _print_table(rows[:20], f"月度充值排行榜 TOP{args.top_n}（前20）")

    total_revenue = sum(float(r.get("total_pay", 0) or 0) for r in rows)
    print(f"\n汇总：上榜玩家 {len(rows)} 人，充值总额 {total_revenue:,.2f} 元")

    if args.csv and rows:
        csv_path = Path(config._ROOT) / "data" / f"month_top_payers_{game_id}_{year_month}.csv"
        dquery.write_csv_to(rows, csv_path)
        print(f"\n已保存 CSV: {csv_path}")

    return 0


if __name__ == "__main__":
    import calendar
    sys.exit(main())
