# 游戏 312 静态配置库说明

- 配置库连接：`config_db.database` 与 `config_db.static_database` 当前都指向 `xgame_gm`。
- 该库同时服务多个游戏，查 312 的道具/资源时**必须加 `game_id = 312` 条件**。

## 常用表

### `game_item`
道具/装备中文名来源。

| 字段 | 说明 |
|---|---|
| `ident` | 道具/装备 ID（与数仓日志中的 item_id 对应） |
| `name` | 中文名 |
| `description` | 描述 |
| `game_id` | 游戏 ID，查询时必须 = 312 |

示例：
```sql
SELECT ident, name, description
FROM game_item
WHERE game_id = 312 AND ident = '2014003';
```

### `game_resource`
通用资源/货币名称来源。

| 字段 | 说明 |
|---|---|
| `id_name` | 资源 ID |
| `name` | 中文名 |
| `description` | 描述 |
| `game_id` | 游戏 ID，查询时必须 = 312 |

示例：
```sql
SELECT id_name, name, description
FROM game_resource
WHERE game_id = 312 AND id_name = '261';
```

### 其他 GM 运营库常用表

| 表名 | 说明 |
|---|---|
| `activity` | 活动配置 |
| `activity_group` | 活动分组 |
| `activity_reward` | 活动奖励 |
| `activity_action` | 活动动作/触发条件 |
| `activity_ratio` | 活动倍率 |
| `activity_type` | 活动类型定义 |
| `game_hero` | 英雄/女神静态配置 |
| `game_itemarg` | 道具扩展参数 |
| `game_res` | 资源详细参数 |
| `game_logorigin` | 日志来源/埋点配置 |
| `game_mall` | 商城/付费点配置 |
| `gift_bag` | GM 礼包/兑换码配置 |
| `server` | 区服名称、server_id、状态；`dc_server_id` 与数仓 `server_id` 对应 |
| `operator` | 运营商信息 |
| `opgame` | 渠道与游戏的关联关系 |
| `allserverinfo` | 全服合服/跨服信息 |
| `singleserverinfo` | 单服详细信息 |

实际字段以 `DESC <表名>` 为准；不确定表名时先用 `SHOW TABLES` 探索。
