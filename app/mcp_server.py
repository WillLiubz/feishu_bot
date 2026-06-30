import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
import dataapi
import dquery
import sqlguard
import store

from fastmcp import FastMCP


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", required=True)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--opgame-ids", default="[]")
    parser.add_argument("--mock", default="false")
    args = parser.parse_args()

    result_dir = Path(args.result_dir)
    chat_id = args.chat_id
    message_id = args.message_id
    query_counter = [0]  # mutable counter shared across tool calls

    sqlguard.REQUIRED_OPGAMES = json.loads(args.opgame_ids)

    if args.mock.lower() == "true":
        config.DATA_API_MOCK = True

    store.init()

    mcp = FastMCP("dquery")

    @mcp.tool()
    def query_data(sql: str) -> dict:
        """
        Execute a Presto SQL query against the data warehouse.
        Returns row_count, columns, preview (first 20 rows).
        Full result is written to result.csv in the workspace.
        """
        t0 = time.time()
        try:
            clean_sql = sqlguard.sanitize(sql)
            rows = dataapi.run_sql_rows(clean_sql)
            # Save last result as result.csv (for backward compat)
            csv_path = result_dir / "result.csv"
            dquery.write_csv_to(rows, csv_path)
            # Save numbered copy for multi-sheet Excel
            query_counter[0] += 1
            n = query_counter[0]
            dquery.write_csv_to(rows, result_dir / f"query_{n}.csv")
            (result_dir / f"query_{n}.sql").write_text(clean_sql, encoding="utf-8")
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

    mcp.run()


if __name__ == "__main__":
    main()
