"""
调试 MCP query_data 工具逻辑（跳过 claude 子进程）。

直接复现 mcp_server.py 中的 query_data 处理流程：
    sqlguard.sanitize -> dataapi.run_sql_rows -> dquery.write_csv_to -> store.log_query

用法：
    python debug/test_mcp_server.py "SELECT COUNT(*) FROM gamelog_raw.v_presto_log_rolelogin WHERE game_id = 312 AND ds = '20260630'"
"""
import argparse
import io
import sys
import time
from pathlib import Path

# Force UTF-8 output on Windows to avoid mojibake
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import dataapi
import dquery
import sqlguard
import store


def query_data(sql: str, chat_id: str, message_id: str, result_dir: Path):
    """Replicate the MCP query_data tool logic."""
    t0 = time.time()
    try:
        clean_sql = sqlguard.sanitize(sql)
        print(f"护栏通过，处理后 SQL:\n  {clean_sql}\n")

        rows = dataapi.run_sql_rows(clean_sql)
        print(f"数仓返回 {len(rows)} 行")

        csv_path = result_dir / "result.csv"
        dquery.write_csv_to(rows, csv_path)
        print(f"已写入 CSV: {csv_path}")

        latency_ms = int((time.time() - t0) * 1000)
        store.log_query(chat_id, message_id, clean_sql, len(rows), "ok", latency_ms)

        columns = list(rows[0].keys()) if rows else []
        return {
            "row_count": len(rows),
            "columns": columns,
            "preview": rows[:20],
        }
    except ValueError as e:
        latency_ms = int((time.time() - t0) * 1000)
        store.log_query(chat_id, message_id, sql, 0, "guard_error", latency_ms, str(e))
        raise
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        store.log_query(chat_id, message_id, sql, 0, "error", latency_ms, str(e))
        raise


def main():
    parser = argparse.ArgumentParser(description="Test query_data tool logic")
    parser.add_argument(
        "sql",
        nargs="?",
        default=f"SELECT COUNT(*) AS cnt FROM gamelog_raw.v_presto_log_rolelogin WHERE game_id = {config.GAME_ID} AND ds = '20260630' LIMIT 1",
        help="SQL to execute",
    )
    args = parser.parse_args()

    store.init()

    chat_id = "debug_chat_001"
    message_id = "debug_msg_001"
    result_dir = Path(config._ROOT) / "data" / "workspaces" / chat_id / "results"
    result_dir.mkdir(parents=True, exist_ok=True)

    print(f"当前 mock 模式: {config.DATA_API_MOCK}")
    print(f"SQL: {args.sql}\n")

    try:
        result = query_data(args.sql, chat_id, message_id, result_dir)
        print(f"\n[OK] 成功")
        print(f"row_count: {result['row_count']}")
        print(f"columns:   {result['columns']}")
        print(f"preview:   {result['preview'][:3]}")
        return 0
    except Exception as e:
        print(f"\n[FAIL] 失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
