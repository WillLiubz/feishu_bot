"""查询结果后处理：把 ID 列批量翻译成中文名。

在 query_N.csv 生成后、画图/合并 Excel 前调用：
- 按 game_id 的内置规则识别 ID 列（item_id / activity_id / id_name 等）
- 复用 configdb.query 批量 IN 查询静态配置库 / GM 运营库
- 中文名列插在 ID 列右侧；已存在同义名列时不覆盖，仅补空单元格
- 任何失败静默跳过（打印日志），绝不阻塞主流程
"""
import csv
from pathlib import Path

import configdb

_NAME_CANDIDATES = ("name", "title", "activity_name")

# 每个游戏的翻译规则：
#   cols:     CSV 中可能出现的 ID 列名（取第一个命中的）
#   db:       "static"=静态库(config_db.static_database) / "gm"=GM 运营库(config_db.database)
#   table:    配置表名
#   key:      表内主键列
#   where:    额外过滤条件（如 game_id = 160），无则 None
#   new_col:  插入的中文名列名
#   existing: 已存在这些列时不覆盖已有值，仅补空单元格（如 roleitem 的 item_name 可能整列为空）
_COLUMN_RULES = {
    39: [
        {"cols": ["item_id"], "db": "static", "table": "static_item", "key": "id",
         "where": None, "new_col": "道具名称", "existing": ("item_name", "道具名称")},
        {"cols": ["activity_id"], "db": "gm", "table": "activity", "key": "id",
         "where": None, "new_col": "活动名称", "existing": ("activity_name", "活动名称")},
    ],
    160: [
        {"cols": ["item_id", "ident"], "db": "gm", "table": "game_item", "key": "ident",
         "where": "game_id = 160", "new_col": "道具名称", "existing": ("item_name", "道具名称"),
         "quote": True},
        {"cols": ["id_name"], "db": "gm", "table": "game_resource", "key": "id_name",
         "where": "game_id = 160", "new_col": "资源名称", "existing": ("资源名称",),
         "quote": True},
    ],
    312: [
        {"cols": ["item_id", "ident", "道具ID"], "db": "gm", "table": "game_item", "key": "ident",
         "where": "game_id = 312", "new_col": "道具名称", "existing": ("item_name", "道具名称"),
         "quote": True,
         "fallback": {"db": "gm", "table": "game_resource", "key": "id_name",
                      "where": "game_id = 312", "quote": True}},
        {"cols": ["id_name"], "db": "gm", "table": "game_resource", "key": "id_name",
         "where": "game_id = 312", "new_col": "资源名称", "existing": ("资源名称",),
         "quote": True},
    ],
}

# (game_id, table, id) -> 中文名；进程级缓存，避免同次会话重复查配置库
_cache = {}


def _quote(v, force_quote=False):
    """纯数字不加引号，其余按字符串字面值转义；force_quote 强制加引号。"""
    s = str(v).strip()
    if not force_quote and s.isdigit():
        return s
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _fetch_names(game_id, cfg, rule, ids):
    """批量查 id -> 中文名映射。Never raises。"""
    table, key = rule["table"], rule["key"]
    ids = [str(i).strip() for i in ids if str(i).strip()]
    unique = list(dict.fromkeys(ids))
    missing = [i for i in unique if (game_id, table, i) not in _cache]
    if missing:
        force_quote = rule.get("quote", False)
        where = f"{key} IN ({', '.join(_quote(i, force_quote) for i in missing)})"
        if rule["where"]:
            where += f" AND {rule['where']}"
        sql = f"SELECT * FROM {table} WHERE {where}"
        database = cfg.get("static_database") if rule["db"] == "static" else None
        try:
            rows = configdb.query(cfg, sql, database=database)
        except Exception as e:
            print(f"[name_enrich] query {table} failed: {e}", flush=True)
            rows = []
        name_key = None
        if rows:
            cols = set(rows[0].keys())
            name_key = next((c for c in _NAME_CANDIDATES if c in cols), None)
        for row in rows:
            if name_key and key in row:
                _cache[(game_id, table, str(row[key]))] = str(row.get(name_key) or "")
        for i in missing:  # 未命中的 ID 缓存为空串，避免反复查
            _cache.setdefault((game_id, table, i), "")
    return {i: _cache.get((game_id, table, i), "") for i in unique}


def translate_csv(csv_path, game_config) -> bool:
    """翻译单个 CSV 的 ID 列（原地回写）。返回是否有改动。Never raises。"""
    rules = _COLUMN_RULES.get(getattr(game_config, "game_id", None), [])
    cfg = getattr(game_config, "config_db", None) or {}
    if not rules or not cfg:
        return False
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
    except Exception as e:
        print(f"[name_enrich] read {csv_path} failed: {e}", flush=True)
        return False
    if not rows or not fieldnames:
        return False
    changed = False
    for rule in rules:
        col = next((c for c in rule["cols"] if c in fieldnames), None)
        if not col:
            continue
        # 已有同义名列时：全非空则跳过（不覆盖 roleitem 等自带名称）；
        # 若有空单元格（如 312 roleitem 的 item_name 实测恒为空），只补空、不覆盖。
        existing_col = next((a for a in rule["existing"] if a in fieldnames), None)
        if existing_col and all(str(r.get(existing_col, "")).strip() for r in rows):
            continue
        mapping = _fetch_names(game_config.game_id, cfg, rule, [r.get(col, "") for r in rows])
        fb = rule.get("fallback")
        if fb:
            missing_ids = [i for i, n in mapping.items() if not n]
            if missing_ids:
                fb_map = _fetch_names(game_config.game_id, cfg, fb, missing_ids)
                mapping.update({k: v for k, v in fb_map.items() if v})
        if not any(mapping.values()):
            continue
        if existing_col:
            filled = False
            for r in rows:
                if str(r.get(existing_col, "")).strip():
                    continue
                name = mapping.get(str(r.get(col, "")).strip(), "")
                if name:
                    r[existing_col] = name
                    filled = True
            if filled:
                changed = True
            continue
        fieldnames.insert(fieldnames.index(col) + 1, rule["new_col"])
        for r in rows:
            r[rule["new_col"]] = mapping.get(str(r.get(col, "")).strip(), "")
        changed = True
    if not changed:
        return False
    try:
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    except Exception as e:
        print(f"[name_enrich] write {csv_path} failed: {e}", flush=True)
        return False
    return True


def translate_dir(result_dir, game_config) -> int:
    """翻译 result_dir 下所有 query_*.csv，返回改动文件数。Never raises。"""
    n = 0
    try:
        for p in sorted(Path(result_dir).glob("query_*.csv")):
            try:
                if translate_csv(str(p), game_config):
                    n += 1
            except Exception as e:
                print(f"[name_enrich] translate {p} failed: {e}", flush=True)
    except Exception as e:
        print(f"[name_enrich] translate_dir failed: {e}", flush=True)
    return n
