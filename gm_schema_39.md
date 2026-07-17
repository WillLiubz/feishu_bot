# 游戏 39 静态配置库说明

- 配置库连接：`config_db.database` 指向 GM 运营库；`config_db.static_database` 指向游戏静态库。
- 已确认当前环境：`database = nslm_uuzuom_gm`，`static_database = angel_static`。

## 常用表

### `static_item`（静态库）
道具/装备中文名来源。

| 字段 | 说明 |
|---|---|
| `id` | 道具/装备 ID（与数仓日志中的 item_id 对应） |
| `name` | 中文名 |
| `describe` | 描述 |
| `type` | 类型 |
| `quality` | 品质 |
| `use_level` | 使用等级 |

示例：
```sql
SELECT id, name, describe
FROM static_item
WHERE id = 10010;
```

### GM 运营库常用表

| 表名 | 说明 |
|---|---|
| `activity` | 活动配置 |
| `activity_group` | 活动分组 |
| `activity_reward` | 活动奖励 |
| `activity_action` | 活动动作/触发条件 |
| `activity_ratio` | 活动倍率 |
| `game_resource` | 游戏资源/道具类配置 |
| `gift_bag` | GM 礼包/兑换码配置 |
| `server` | 区服名称、server_id、状态；`dc_server_id` 与数仓 `server_id` 对应 |
| `operator` | 运营商信息 |

实际字段以 `DESC <表名>` 为准；不确定表名时先用 `SHOW TABLES` 探索。
