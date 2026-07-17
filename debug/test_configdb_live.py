"""真实 MySQL 冒烟：需先在 config.json 为某游戏填好 config_db 后运行。

用法: python debug/test_configdb_live.py [game_id]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import configdb


def main():
    game_id = int(sys.argv[1]) if len(sys.argv) > 1 else config.GAME_ID
    gc = config.game_config(game_id)
    cfg = gc.config_db or {}
    if not cfg:
        print(f"游戏 {game_id} 未配置 config_db，请先在 config.json 填写")
        sys.exit(1)

    print(f"[1/3] SHOW TABLES (game={game_id}, db={cfg.get('database')}@{cfg.get('host')})")
    tables = configdb.query(cfg, configdb.sanitize("SHOW TABLES", int(cfg.get("max_rows", 500))))
    for row in tables[:20]:
        print("  ", list(row.values())[0])
    print(f"  ... 共 {len(tables)} 张表")

    print("[2/3] SELECT 抽查第一张表前 5 行")
    if tables:
        first = list(tables[0].values())[0]
        rows = configdb.query(cfg, configdb.sanitize(f"SELECT * FROM `{first}` LIMIT 5"))
        for r in rows:
            print("  ", r)

    print("[3/3] 护栏拦截验证（DROP 应报错）")
    try:
        configdb.sanitize("DROP TABLE t")
        print("  !! 护栏未拦截，异常")
        sys.exit(1)
    except ValueError as e:
        print(f"  OK: {e}")

    print("冒烟通过")


if __name__ == "__main__":
    main()
