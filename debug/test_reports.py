"""
调试固定报表（KPI / LTV）。

用法：
    python debug/test_reports.py kpi "今日数据"
    python debug/test_reports.py ltv
"""
import argparse
import io
import sys
from pathlib import Path

# Force UTF-8 output on Windows to avoid mojibake
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import account_cache
import config
import reports


def main():
    parser = argparse.ArgumentParser(description="Test fixed reports")
    parser.add_argument("type", choices=["kpi", "ltv"], help="Report type")
    parser.add_argument("question", nargs="?", default="今日数据", help="User question text")
    args = parser.parse_args()

    account_cache.init()

    print(f"当前 mock 模式: {config.DATA_API_MOCK}")
    print(f"报表类型: {args.type}")
    print(f"问题: {args.question}\n")

    try:
        summary, csv_path = reports.run(args.type, args.question)
        print(f"[OK] 报表生成成功")
        print(f"\n{summary}\n")
        print(f"CSV 路径: {csv_path}")

        # Print first few lines of CSV
        p = Path(csv_path)
        if p.exists():
            lines = p.read_text(encoding="utf-8-sig").splitlines()
            print("\nCSV 预览:")
            for line in lines[:10]:
                print(f"  {line}")
            if len(lines) > 10:
                print(f"  ... 还有 {len(lines) - 10} 行")
        return 0
    except Exception as e:
        print(f"[FAIL] 报表生成失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
