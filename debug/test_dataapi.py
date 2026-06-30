"""
调试数仓 API 客户端。

用法：
    python debug/test_dataapi.py              # 使用 config.json 中的 mock 设置
    python debug/test_dataapi.py --real       # 强制使用真实 API（会提交一条轻量 SQL）
    python debug/test_dataapi.py --mock       # 强制使用 mock 数据
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


def main():
    parser = argparse.ArgumentParser(description="Test dataapi connectivity")
    parser.add_argument("--real", action="store_true", help="Force real API call")
    parser.add_argument("--mock", action="store_true", help="Force mock mode")
    parser.add_argument(
        "--sql",
        default=f"SELECT COUNT(*) AS cnt FROM gamelog_raw.v_presto_log_rolelogin WHERE game_id = {config.GAME_ID} AND ds = '20260630' LIMIT 1",
        help="SQL to execute (default: light count query)",
    )
    args = parser.parse_args()

    use_mock = args.mock or (not args.real and config.DATA_API_MOCK)

    print(f"API name:     {config.DATA_API_API_NAME}")
    print(f"Search URL:   {config.DATA_API_SEARCH_URL}")
    print(f"Download URL: {config.DATA_API_DOWNLOAD_URL}")
    print(f"Client ID:    {config.DATA_API_CLIENT_ID}")
    print(f"Mock mode:    {use_mock}")
    print(f"SQL:          {args.sql}")

    if use_mock:
        config.DATA_API_MOCK = True

    t0 = time.time()
    try:
        rows = dataapi.run_sql_rows(args.sql, max_rows=10)
        elapsed = int((time.time() - t0) * 1000)
        print(f"\n[OK] 成功 ({elapsed}ms)，返回 {len(rows)} 行")
        for i, row in enumerate(rows[:5], 1):
            print(f"  行 {i}: {row}")
        if len(rows) > 5:
            print(f"  ... 还有 {len(rows) - 5} 行")
        return 0
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        print(f"\n[FAIL] 失败 ({elapsed}ms): {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
