"""
调试 SQL 护栏。

用法：
    python debug/test_sqlguard.py
    python debug/test_sqlguard.py "SELECT * FROM t WHERE game_id = 312"

默认会扫描 schema.md 中的示例 SQL（代码块内以 SELECT/WITH 开头），
并逐一测试它们能否通过 sqlguard.sanitize()。
"""
import io
import sys
import re
from pathlib import Path

# Force UTF-8 output on Windows to avoid mojibake
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import sqlguard


def _extract_sql_examples(schema_path: Path):
    """Extract SQL statements from markdown code blocks."""
    if not schema_path.exists():
        return []
    text = schema_path.read_text(encoding="utf-8")
    examples = []
    # Match ```sql ... ``` or ``` ... ``` blocks
    for block in re.findall(r"```(?:sql)?\n(.*?)\n```", text, re.DOTALL):
        # Collect lines into statements (semicolon-terminated or whole block)
        buffer = []
        for line in block.strip().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--") or stripped.startswith("#"):
                continue
            buffer.append(stripped)
            if stripped.rstrip().endswith(";"):
                sql = " ".join(buffer).rstrip(";")
                if re.match(r"^(SELECT|WITH|INSERT|UPDATE|DELETE|DROP)", sql, re.IGNORECASE):
                    examples.append(sql)
                buffer = []
        if buffer:
            sql = " ".join(buffer)
            if re.match(r"^(SELECT|WITH|INSERT|UPDATE|DELETE|DROP)", sql, re.IGNORECASE):
                examples.append(sql)
    return examples


def _test_one(sql: str):
    print(f"\nSQL: {sql[:120]}{'...' if len(sql) > 120 else ''}")
    try:
        result = sqlguard.sanitize(sql)
        print(f"  [OK] 通过")
        print(f"       处理后: {result[:160]}{'...' if len(result) > 160 else ''}")
        return True
    except Exception as e:
        print(f"  [FAIL] 拒绝: {e}")
        return False


def main():
    root = Path(__file__).parent.parent
    schema_path = root / "schema.md"

    if len(sys.argv) > 1:
        sqls = [" ".join(sys.argv[1:])]
    else:
        sqls = _extract_sql_examples(schema_path)
        print(f"从 schema.md 提取到 {len(sqls)} 条示例 SQL")

    print(f"当前 game_id={config.GAME_ID}, ds_start={config.DS_START}")

    passed = 0
    failed = 0
    for sql in sqls:
        if _test_one(sql):
            passed += 1
        else:
            failed += 1

    print(f"\n结果: 通过 {passed}, 失败 {failed}, 总计 {passed + failed}")
    if failed:
        print("提示：schema.md 中的示例 SQL 如果包含 <昨天ds>/<今天ds> 等占位符，")
        print("      会被护栏拒绝。请替换为真实日期，或仅用于阅读参考。")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
