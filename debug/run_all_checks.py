"""
一键运行所有调试检查。

用法：
    python debug/run_all_checks.py
"""
import io
import subprocess
import sys
from pathlib import Path

# Force UTF-8 output on Windows to avoid mojibake
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
DEBUG = ROOT / "debug"

SCRIPTS = [
    ("SQL 护栏", "test_sqlguard.py"),
    ("数仓 API", "test_dataapi.py --mock"),
    ("工作区生成", "test_workspace.py"),
    ("MCP query_data", "test_mcp_server.py"),
    ("固定报表 KPI", "test_reports.py kpi \"今日数据\""),
    ("固定报表 LTV", "test_reports.py ltv"),
    ("Bot 组件", "test_bot_components.py"),
]


def run_one(name: str, cmd: str):
    print(f"\n{'=' * 60}")
    print(f"[{name}]")
    print(f"{'=' * 60}")
    full_cmd = f"cd {ROOT} && python {DEBUG / cmd}"
    result = subprocess.run(full_cmd, shell=True, capture_output=False, text=True)
    return result.returncode == 0


def main():
    results = []
    for name, cmd in SCRIPTS:
        ok = run_one(name, cmd)
        results.append((name, ok))

    print(f"\n{'=' * 60}")
    print("汇总")
    print(f"{'=' * 60}")
    for name, ok in results:
        print(f"  [{'OK' if ok else 'FAIL'}] {name}")

    failed = sum(1 for _, ok in results if not ok)
    print(f"\n总计: {len(results)} 项, 失败 {failed} 项")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
