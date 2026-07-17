import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
import configdb
import dataapi
import db_rewrite
import dquery
import sqlguard
import store

from fastmcp import FastMCP


def _load_counter(result_dir: Path) -> int:
    """Load the highest existing query_N.csv number to keep numbering across restarts."""
    if not result_dir.exists():
        return 0
    max_n = 0
    for p in result_dir.iterdir():
        if p.is_file() and p.suffix == ".csv":
            m = re.search(r'query_(\d+)\.csv$', p.name)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return max_n


def _prepare_sql(sql: str) -> tuple[str, bool]:
    """
    Prepare SQL for execution:
    1. Extract an optional leading `-- use_odl` hint.
    2. Run sqlguard validation on the cleaned SQL.
    3. Rewrite gamelog_odl / gameeco_odl to _raw unless the hint is present.

    Returns (final_sql, use_odl).
    """
    cleaned, use_odl = db_rewrite.extract_odl_hint(sql)
    sanitized = sqlguard.sanitize(cleaned)
    if not use_odl:
        sanitized = db_rewrite.rewrite_odl_to_raw(sanitized)
    return sanitized, use_odl


def run_config_query(sql: str, chat_id: str, message_id: str) -> dict:
    """
    query_config 工具的核心逻辑（独立于 MCP 注册，便于单测）。

    护栏校验 → 直连当前游戏的 MySQL 配置库 → 全量返回行（不写 CSV，
    配置查找是中间步骤，不混入最终合并的 Excel）。
    """
    t0 = time.time()
    cfg = config.game_config(config.GAME_ID).config_db or {}
    if not cfg:
        latency_ms = int((time.time() - t0) * 1000)
        store.log_query(chat_id, message_id, f"[config] {sql}", 0, "error",
                        latency_ms, "当前游戏未配置静态配置库")
        raise RuntimeError("当前游戏未配置静态配置库（config_db），无法查询道具/活动等静态配置")
    try:
        clean_sql = configdb.sanitize(sql, int(cfg.get("max_rows", 500)))
    except configdb.ConfigGuardError as e:
        latency_ms = int((time.time() - t0) * 1000)
        store.log_query(chat_id, message_id, f"[config] {sql}", 0, "guard_error",
                        latency_ms, str(e))
        raise
    try:
        rows = configdb.query(cfg, clean_sql, max_rows=int(cfg.get("max_rows", 500)))
        latency_ms = int((time.time() - t0) * 1000)
        store.log_query(chat_id, message_id, f"[config] {clean_sql}", len(rows), "ok", latency_ms)
        print(f"[mcp_server] query_config ok rows={len(rows)} latency={latency_ms}ms", flush=True)
        return {
            "row_count": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows,
        }
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        store.log_query(chat_id, message_id, f"[config] {clean_sql}", 0, "error",
                        latency_ms, str(e))
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", required=True)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--opgame-ids", default="[]")
    parser.add_argument("--mock", default="false")
    parser.add_argument("--game-id", type=int, default=None)
    args = parser.parse_args()

    result_dir = Path(args.result_dir)
    chat_id = args.chat_id
    message_id = args.message_id
    query_counter = [_load_counter(result_dir)]

    if args.game_id is not None:
        config.GAME_ID = args.game_id

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
        Result rows are capped to config.data_api.max_rows (default 10000).
        Each query has a maximum execution time of config.data_api.query_timeout
        seconds (default 120); exceeding it raises a timeout error.
        """
        t0 = time.time()
        try:
            clean_sql, use_odl = _prepare_sql(sql)
            rows = dataapi.run_sql_rows(
                clean_sql,
                max_rows=config.DATA_API_MAX_ROWS,
                timeout=config.DATA_API_QUERY_TIMEOUT,
            )
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
            print(f"[mcp_server] query_data ok rows={len(rows)} latency={latency_ms}ms", flush=True)
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

    @mcp.tool()
    def query_config(sql: str) -> dict:
        """
        查询当前游戏的静态配置 MySQL 库（只读）。
        用途：道具ID→道具名称、活动ID→活动信息等静态配置查找。
        仅允许 SELECT / SHOW / DESCRIBE / EXPLAIN；禁止任何写操作。
        结果上限 config_db.max_rows 行（默认 500），单次查询超时 read_timeout 秒（默认 30）。
        不知道有哪些表时先 SHOW TABLES 探索。SQL 使用 MySQL 语法，不需要 game_id 条件。
        """
        return run_config_query(sql, chat_id, message_id)

    mcp.run()


if __name__ == "__main__":
    main()
