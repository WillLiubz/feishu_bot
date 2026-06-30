"""
调试工作区生成。

用法：
    python debug/test_workspace.py
    python debug/test_workspace.py --chat-id debug_chat_001 --opgames 3553,3554
"""
import argparse
import io
import sys
from pathlib import Path

# Force UTF-8 output on Windows to avoid mojibake
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import workspace


def main():
    parser = argparse.ArgumentParser(description="Test workspace generation")
    parser.add_argument("--chat-id", default="debug_chat_001", help="Chat ID to use")
    parser.add_argument("--opgames", default="", help="Comma-separated opgame IDs")
    parser.add_argument("--keep", action="store_true", help="Keep generated workspace")
    args = parser.parse_args()

    opgames = [int(x.strip()) for x in args.opgames.split(",") if x.strip()]
    ws = workspace.prepare(args.chat_id, "debug_msg_001", opgames=opgames or None)

    print("生成的关键路径:")
    print(f"  cwd:        {ws['cwd']}")
    print(f"  mcp_config: {ws['mcp_config']}")
    print(f"  result_dir: {ws['result_dir']}")

    cwd = Path(ws["cwd"])
    for name in ["CLAUDE.md", ".claude/settings.json", "mcp.json"]:
        p = cwd / name
        if p.exists():
            print(f"\n--- {name} ---")
            print(p.read_text(encoding="utf-8")[:1500])
            if p.stat().st_size > 1500:
                print("... (truncated)")
        else:
            print(f"\n❌ 未找到 {name}")

    if not args.keep:
        import shutil
        shutil.rmtree(cwd, ignore_errors=True)
        print(f"\n已清理工作区: {ws['cwd']}")
    else:
        print(f"\n保留工作区: {ws['cwd']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
