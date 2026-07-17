# 游戏 255 静态配置库说明

- 配置库连接：待填写 `config_db.database` 与 `config_db.static_database`。
- 请先确认 255 的 GM 运营库名和游戏静态库名（可能合并为一个库，也可能分开）。

## 待补充

1. 在 `config.json` 中填写 255 的真实 `database` 和 `static_database`。
2. 用 `SHOW TABLES` 确认库中有哪些表。
3. 确认道具中文名来源表：
   - 若存在 `static_item`，则与游戏 39 类似，用 `id`/`name` 查询。
   - 若道具配置在 GM 库中，可能为 `game_item`，需按 `game_id = 255` 过滤，用 `ident`/`name` 查询。

## 通用提示

- 不确定表名时先用 `SHOW TABLES` 探索。
- 实际字段以 `DESC <表名>` 结果为准。
