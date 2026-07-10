## 表结构

> 游戏：女1_ProM_Dev，game_id = 39
> 数据来源：`C:\YZ_SVN\女1_后端_ProM_Dev\php_trunk`
> 后端语言：PHP

---

### 数仓架构概览

游戏 39 后端存在 **两套** 相互独立的日志体系：

| 体系 | 写入方式 | 主要用途 | 关键文件 |
|------|----------|----------|----------|
| **Scribe / DataCenter** | 通过 Thrift 客户端实时发送到本地 scribe（`127.0.0.1:1464`），失败时落盘 `/data/data/scribelog/local` | 运营数据中心（充值、登录、在线、货币变动等） | `web/kernel/utility/DataCenterLog.class.php`<br>`web/kernel/utility/Tracer.class.php` |
| **MySQL 日志队列（Logger）** | 业务代码把日志推到 Redis 队列，由 `queueManage.php` 启动的独立消费者异步写入 MySQL | 详细行为、道具、战斗、活动、资源流转等 | `web/kernel/utility/Logger.class.php`<br>`manage/src/queueManage.php`<br>`web/kernel/utility/DailyTask.class.php` |

> **重要前提**：源码中没有出现 `presto`、`hive`、`odl`、`eco`、`gamelog`、`v_presto_log_*` 等仓库关键字。本文件中的 Presto 表名均为按代码结构推断的推荐名，需以实际数仓元数据为准。

---

### Scribe / DataCenter 日志体系

`DataCenterLog::send_data_log(...)` 生成一条 `|` 分隔字符串，category 固定为 `{game_id}_{type}`，例如 `39_login`、`39_pay`。

`DataCenterLog.class.php` 中定义的 `file_type_info`：

| type（category 后缀） | file_type_info id | 业务含义 |
|---|---|---|
| `login` | 1 | 玩家登录 |
| `est` | 3 | 注册 / 激活 / 创角 |
| `pay` | 6 | 充值（含直购） |
| `curr` | 7 | 玩家加币（钻石/黑钻获得） |
| `prop` | 9 | 玩家消费钻石 |
| `sub` | 10 | GM / 后台扣币 |
| `ser` | - | 在线人数 / PCU |

> 注意：`curr` 在配置数组里写成 `'curr '=>7`（带空格），但实际调用使用 `'curr'`。

#### 推荐 Presto 视图名

按 `{库}.v_presto_log_{小写 Action}` 约定推断：

| 后端 category | 推荐 Presto 视图名 |
|---|---|
| `39_login` | `gamelog_raw.v_presto_log_login` / `gamelog_odl.v_presto_log_login` |
| `39_est` | `gamelog_raw.v_presto_log_est` / `gamelog_odl.v_presto_log_est` |
| `39_pay` | `gamelog_raw.v_presto_log_pay` / `gamelog_odl.v_presto_log_pay` |
| `39_curr` | `gamelog_raw.v_presto_log_curr` / `gamelog_odl.v_presto_log_curr` |
| `39_prop` | `gamelog_raw.v_presto_log_prop` / `gamelog_odl.v_presto_log_prop` |
| `39_sub` | `gamelog_raw.v_presto_log_sub` / `gamelog_odl.v_presto_log_sub` |
| `39_ser` | `gamelog_raw.v_presto_log_ser` / `gamelog_odl.v_presto_log_ser` |

**表名规则**：`{库}.v_presto_log_{小写 type}`
- `gamelog_raw`：实时 T+0，**默认所有查询使用此库**。
- `gamelog_odl`：T+1 归档，仅当用户明确要求 T+1 / odl 时使用，需要在 SQL 开头单独一行添加 `-- use_odl` 标记。

**查询选库约定**：默认所有 KPI/日志类查询使用 `gamelog_raw`（实时库），不按日期自动切换。只有当用户明确要求 T+1 / odl / 历史归档库时，才使用 `gamelog_odl`。

**重要**：
- 所有表中的 `uid` / `user_id` / `role_id` 在 MySQL 中既有 `bigint(20) unsigned` 也有 `varchar(50)`，Presto 中可能是 **BIGINT 或 VARCHAR**。如果按 role_id 过滤无结果，尝试加引号 `role_id = '123456'` 或不加引号 `role_id = 123456`。
- 所有表中的 `game_id` 为 **整数** `39`。
- `passport` 是字符串账号名。

---

### 通用基础字段（DataCenter / gamelog_raw 表）

DataCenter 消息格式（来自 `DataCenterLog::send_data_log`）：

```
type|pid|gid|sid|pid|daytime|passport|uid|count|str1|str2|str3|str4|str5|str6|str7|str8|userip|level|viplevel|coin|blackcoin|exp
```

| 字段 | 说明 |
|---|---|
| `type` | category 后缀，如 `login`、`pay`、`curr` |
| `pid` / `gid` / `sid` | 平台 ID / 游戏 ID / 服务器 ID |
| `daytime` | 事件时间，格式 `yyyy-MM-dd HH:mm:ss` |
| `passport` | 账号名 |
| `uid` | 角色/用户 ID |
| `count` | 计数（登录时固定 1） |
| `str1` ~ `str8` | 各类型的业务字段，见下表 |
| `userip` | 用户 IP |
| `level` | 角色等级 |
| `viplevel` | VIP 等级 |
| `coin` | 金币 |
| `blackcoin` | 黑钻/黑金 |
| `exp` | 经验 |

ETL 后通常会增加 `ds`（string，yyyyMMdd）、`game_id`（int，39）等分区字段。

---

### 各 DataCenter 类型字段详解

#### `gamelog_raw.v_presto_log_login` — 玩家登录

来源：`Tracer::login_tracer` (1003)

| 字段 | 含义 |
|---|---|
| `str1` | 用户来源 id |
| `str2` | 固定为 `on` |
| `str3` | 在线时长（登录时固定 0） |

#### `gamelog_raw.v_presto_log_est` — 注册 / 激活 / 创角

来源：`Tracer::register_tracer` (1002)

| 字段 | 含义 |
|---|---|
| `str1` | 用户来源 id |
| `str2` | 创角步骤 gid（amount） |
| `str3` | 创角步骤 flags |

#### `gamelog_raw.v_presto_log_pay` — 充值

来源：`Tracer::cash_charge_tracer` (600) / `Tracer::direct_charge_tracer` (601)

| 字段 | 含义 |
|---|---|
| `str1` | 充值类型：1=兑换游戏币，2=直购道具 |
| `str2` | 充值渠道（固定空） |
| `str3` | 充值游戏币数量 |
| `str4` | 订单号 |
| `str5` | 直购礼包 id（直购时） |

> 充值还会写入 MySQL `log_charge` 和 `log_direct_mall`。

#### `gamelog_raw.v_presto_log_curr` — 玩家加币（钻石/黑钻获得）

来源：`Tracer::cash_tracer` (6) amount > 0

| 字段 | 含义 |
|---|---|
| `str1` | 加币来源：`gm` / `game` |
| `str2` | 操作源 class.method |
| `str3` | 加币数量 |
| `str4` | 当前余额（refer） |
| `str5` | 真钻加币数 |
| `str6` | 黑钻加币数 |

#### `gamelog_raw.v_presto_log_prop` — 玩家消费钻石

来源：`Tracer::cash_tracer` (6) amount < 0 且非 GM 扣币

| 字段 | 含义 |
|---|---|
| `str1` | 消费源 class.method |
| `str2` | 空 |
| `str3` | 消费数量 |
| `str4` | 真钻消耗数 |
| `str5` | 黑钻消耗数 |
| `str6` | 当前余额 |

#### `gamelog_raw.v_presto_log_sub` — GM / 后台扣币

来源：`Tracer::cash_tracer` (6) amount < 0 且 source=`api.addGoodsAction`

| 字段 | 含义 |
|---|---|
| `str1` | 固定为 `gm` |
| `str2` | 扣币源 class.method |
| `str3` | 扣币数量 |
| `str4` | 当前余额 |
| `str5` | 真钻数 |
| `str6` | 黑钻数 |

#### `gamelog_raw.v_presto_log_ser` — 在线人数 / PCU

来源：`Tracer::user_online_tracer` (1016)

| 字段 | 含义 |
|---|---|
| `str1` | 固定为 `pcu` |
| `str2` | 时间戳 |
| `str3` | 在线人数 |

---

### MySQL 日志队列体系

业务代码通过 `Logger::xxx()` 将日志推入 Redis 队列，`queueManage.php` 消费后写入 MySQL。这部分日志 **不进 Scribe**，主要用于道具、活动、战斗、英雄等详细行为分析。

#### 主要 MySQL 日志表

| 队列 key | 目标表 | 关键字段 | 业务含义 |
|---|---|---|---|
| `logger:active` | `log_active` | `user_id, create_time, passport, ip` | 激活 |
| `logger:goto` | `log_goto` | `passport, ip, create_time` | 进入游戏页 |
| `logger:login` | `log_login` | `user_id, user_name, passport, ip, login_time, session_id, create_time` | 登录 |
| `logger:levelup` | `log_levelup` | `user_id, level, next_level, passport, create_time` | 升级 |
| `logger:killBoss` | `log_kill_boss` | `user_id, boss_id, kill_time` | 击杀关卡 BOSS |
| `logger:exchangePack` | `log_exchange_pack_{m-d}` | `date, uid, modules, exp, coin, cash, blackcash, insight, integral, prestige, vigour, energy, gift_cash, honour, souls, card_point, exploit, exploit_point, god_exp, items` | 资源/道具获得 |
| `logger:exchangeCost` | `log_exchange_cost_{m-d}` | `date, uid, modules, cost_exp, cost_coin, cost_cash, cost_blackcash, cost_insight, cost_integral, cost_prestige, cost_vigour, cost_energy, cost_gift_cash, cost_honour, cost_souls, cost_card_point, cost_exploit, cost_exploit_point, cost_god_exp, cost_items` | 资源/道具消耗 |
| `logger:actvityReceive` | `log_activity_receive` | `user_id, activity_id, reward_id, receive_time, receive_num` | 精彩活动领取 |
| `logger:actvityNum` | `log_activity_num` | `user_id, activity_id, receive_time` | 活动参与次数 |
| `logger:flowerGive` | `log_flower_give` | `user_id, friend_id, num, create_time` | 送花 |
| `logger:angelLevelUpQuality` | `log_angel_levelup_quality` | - | 女神升阶 |
| `logger:angelTransfer` | `log_angel_transfer` | - | 女神传承 |
| `logger:heroRecruit` | `log_hero_recruit` | - | 英雄招募 |
| `logger:heroFire` | `log_hero_fire` | - | 英雄解雇 |
| `logger:heroTrainUpgrade` | `log_hero_train_upgrade` | - | 英雄培养 |
| `logger:herosoulraisingUp` | `log_hero_soulraising_up` | - | 英雄进阶 |
| `logger:fightReportUp` | `log_fight_report_up` | - | 竞技场战报 |
| `logger:angelLoveUp` | `log_angel_love_up` | - | 女神示爱 |
| `logger:angelBuyBuffUp` | `log_angel_buybuff_up` | - | 女神激活 buff |
| `logger:mineUp` | `log_mine_up` | - | 夺宝奇兵探险 |
| `logger:mineCombCdUp` | `log_mine_combcd_up` | - | 夺宝奇兵合成 CD |
| `logger:itemEnchanting` | `log_item_enchanting` | - | 物品魔化 |
| `logger:kingBet` | `log_king_bet` | - | 大师赛下注 |
| `logger:addSpriteTransfer` | `log_sprite_transfer` | - | 宠物传承 |
| `logger:addRaiseLog` | `log_raise` | - | 游戏进阶日志 |
| - | `log_charge` | `billno, user_id, op_id, passport, level, cash, now_cash, create_time, platform` | 充值流水 |
| - | `log_online` | `time, num` | 在线人数 |

> 这些表如果接入 Presto，推断视图名为 `gamelog_raw.v_presto_log_{表名}`，例如 `gamelog_raw.v_presto_log_exchange_pack`、`gamelog_raw.v_presto_log_activity_num` 等。但实际是否接入需与数仓负责人确认。

#### 按月分表的详细日志

`DailyTask.class.php` 通过 `Logger::logAll($table, $data)` 写入，表名格式 `t_log_{业务}_{YYYY_MM}`，通用字段：`uid, class, method, args, create_time`。

| 表名 | 业务 |
|---|---|
| `t_log_energy_YYYY_MM` | 体力变化 |
| `t_log_soul_YYYY_MM` | 灵魂培养 |
| `t_log_raising_YYYY_MM` | 灵魂升阶 |
| `t_log_tavern_YYYY_MM` | 英雄 / 抽牌 |
| `t_log_dragon_YYYY_MM` | 龙魂 |
| `t_log_soulExchange_YYYY_MM` | 传承 |
| `t_log_element_YYYY_MM` | 元素 |
| `t_log_gem_YYYY_MM` | 宝石 |
| `t_log_item_YYYY_MM` | 物品变化（`type` 字段 `+` / `-`） |
| `t_log_group_YYYY_MM` / `t_log_groupwear_YYYY_MM` | 团购 |
| `t_log_awaken_YYYY_MM` | 觉醒 |
| `t_log_tarot_YYYY_MM` | 塔罗牌 |
| `t_log_angelWeapon_YYYY_MM` | 女神灵器 |
| `t_log_card_YYYY_MM` | 卡牌大师 |
| `t_log_military_horse_lv_YYYY_MM` | 兽栏 |
| `t_log_military_horse_equip_elite_YYYY_MM` | 兽铠精炼 |
| `t_log_fb_praise/invite/gift/request_YYYY_MM` | Facebook 社交 |
| `t_log_elementkernel_YYYY_MM` / `t_log_element_buy_YYYY_MM` | 元素内核 / 元素购买 |
| `t_log_endbattle_buy/fight/status_YYYY_MM` | 一战到底 |
| `t_log_homebaby_addbag/comb/dis/bookskill_YYYY_MM` | 家园 |
| `t_log_homeland_map/scheme_YYYY_MM` | 家园地图/方案 |
| `t_log_orebattle_buy_YYYY_MM` | 矿战商店 |
| `t_log_teamTreasure_buy_YYYY_MM` | 组队寻宝商店 |

---

### Tracer 事件类型常量

`Tracer.class.php` 定义的主要常量：

| 常量 | 值 | 业务含义 | 是否进 DataCenter |
|---|---|---|---|
| `gift_cash_tracer` | 5 | 礼券 | 否 |
| `cash_tracer` | 6 | 钻石变动 | **是** |
| `blackcash_tracer` | 9 | 黑金 | 否 |
| `cash_charge_tracer` | 600 | 充值 | **是** |
| `direct_charge_tracer` | 601 | 直购充值 | **是** |
| `active_value_tracer` | 1000 | 日常活跃值 | 否 |
| `christmas_tree_tracer` | 1001 | 圣诞树经验 | 否 |
| `register_tracer` | 1002 | 注册 | **是** |
| `login_tracer` | 1003 | 登录 | **是** |
| `level_up_tracer` | 1004 | 升级 | 否 |
| `pk_tracer` | 1005 | 争霸赛 | 否 |
| `angel_level_up_tracer` | 1006 | 女神升级 | 否 |
| `vip_level_up_tracer` | 1007 | VIP 等级 | 否 |
| `max_ability_tracer` | 1008 | 最大战斗力 | 否 |
| `user_online_tracer` | 1016 | 在线人数 | **是** |
| `user_offline_tracer` | 1017 | 离线 | 否 |

> 进 DataCenter 的只有 `6 / 600 / 601 / 1002 / 1003 / 1016`，其余事件用于活动 / 跨服逻辑。

---

### 关键业务流程与日志落点

#### 道具获得 / 使用 / 消耗

- **获得道具**：`UserBag::addItem($item, $uid, $action)` → 写 `log_exchange_pack_{m-d}`
- **使用/装备道具**：`UserBag::useItem()` / `putOn()` / `interUse()` → 写 `log_exchange_cost_{m-d}`
- **消耗指定 bid 道具**：`UserItem::useBid($useInfo)` → 写 `log_exchange_cost_{m-d}`
- **纯物品变化**：部分特殊道具还会写 `t_log_item_YYYY_MM`，`type='+'` 或 `'-'`

#### 货币 / 资源变动

统一入口：`User::exchange(Exchange $obj, $action)`

- **增加资源**：`User::raiseField($field, $value)`
- **减少资源**：`User::reduceField($field, $value, $cost)`
- 钻石先扣真钻，真钻不足再扣黑钻
- 资源变动会触发 `Logger::logExchangePack()` / `Logger::logExchangeCost()`，再由消费者调用 `Tracer::trace(6, ...)`，最终写入 DataCenter `curr` / `prop` / `sub`

#### 充值

`passport.php::chargeAction()`：
- 普通充值写入 `log_charge`，并触发 `Tracer::cash_charge_tracer` → DataCenter `pay`
- 直购（gameId==39）额外写入 `log_direct_mall`，并触发 `Tracer::direct_charge_tracer` → DataCenter `pay`

#### 登录 / 注册 / 在线

- 登录：`User::login()` → `Tracer::login_tracer` → DataCenter `login`，同时写 `log_login`
- 注册：`UserRegister::register()` → `Tracer::register_tracer` → DataCenter `est`，同时写 `log_active`
- 在线人数：`UserCommon::getOnlineNum()` → 写 `log_online`，并触发 `Tracer::user_online_tracer` → DataCenter `ser`

---

### 字段类型与分区格式

| 字段/概念 | 源码表现 | 推荐数仓类型 |
|---|---|---|
| `game_id` | `Config::get('gameId')`，整数 39 | `INT` |
| `role_id` / `uid` / `user_id` | numeric string / bigint / varchar | `BIGINT` 或 `VARCHAR` |
| `passport` | 字符串账号名 | `VARCHAR` |
| `server_id` / `sid` | 服务器 ID | `INT` |
| `op_id` / `pid` | 运营商/平台 ID | `INT` |
| `create_time` / `daytime` | 时间戳或 `yyyy-MM-dd HH:mm:ss` | `TIMESTAMP` / `DATETIME` |
| `ds` | 源码无统一字段，需 ETL 从时间字段抽取 | `STRING`（yyyyMMdd） |

**测试服过滤**：代码层没有统一的测试服日志丢弃逻辑，仅通过 `dcEnable` 配置和 `Gateway::isDebug()` 域名白名单控制。数仓侧建议按 `serverName` 或 `server_id` 过滤测试服数据。

---

## 一、DataCenter 实时表（gamelog_raw）

### gamelog_raw.v_presto_log_login — 玩家登录

每次玩家登录产生一条，同时会写 MySQL `log_login`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `uid` | bigint / varchar | 用户 ID |
| `passport` | string | 账号名 |
| `login_source` | string | str1，用户来源 id |
| `online_status` | string | str2，固定 `on` |
| `online_time` | int | str3，登录时固定 0 |
| `level` | int | 角色等级 |
| `viplevel` | int | VIP 等级 |
| `coin` | bigint | 金币 |
| `blackcoin` | bigint | 黑钻 |
| `exp` | bigint | 经验 |

---

### gamelog_raw.v_presto_log_est — 注册 / 激活 / 创角

玩家注册或创角时产生。

| 字段 | 类型 | 说明 |
|---|---|---|
| `uid` | bigint / varchar | 用户 ID |
| `passport` | string | 账号名 |
| `reg_source` | string | str1，用户来源 id |
| `step_gid` | int | str2，创角步骤 gid |
| `step_flags` | int | str3，创角步骤 flags |
| `level` | int | 角色等级 |
| `viplevel` | int | VIP 等级 |

---

### gamelog_raw.v_presto_log_pay — 充值流水

每笔充值产生一条，同时写 MySQL `log_charge` / `log_direct_mall`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `uid` | bigint / varchar | 用户 ID |
| `passport` | string | 账号名 |
| `charge_type` | int | str1，1=兑换游戏币，2=直购道具 |
| `charge_channel` | string | str2，固定空 |
| `game_money` | int | str3，充值游戏币数量 |
| `order_id` | string | str4，订单号 |
| `gift_id` | int | str5，直购礼包 id |
| `level` | int | 角色等级 |
| `viplevel` | int | VIP 等级 |

---

### gamelog_raw.v_presto_log_curr — 玩家加币（钻石/黑钻获得）

玩家获得钻石/黑钻时产生。

| 字段 | 类型 | 说明 |
|---|---|---|
| `uid` | bigint / varchar | 用户 ID |
| `source` | string | str1，`gm` / `game` |
| `source_method` | string | str2，操作源 class.method |
| `amount` | int | str3，加币数量 |
| `balance` | int | str4，当前余额 |
| `cash_add` | int | str5，真钻加币数 |
| `blackcash_add` | int | str6，黑钻加币数 |

---

### gamelog_raw.v_presto_log_prop — 玩家消费钻石

玩家消费钻石时产生。

| 字段 | 类型 | 说明 |
|---|---|---|
| `uid` | bigint / varchar | 用户 ID |
| `source_method` | string | str1，消费源 class.method |
| `amount` | int | str3，消费数量 |
| `cash_cost` | int | str4，真钻消耗数 |
| `blackcash_cost` | int | str5，黑钻消耗数 |
| `balance` | int | str6，当前余额 |

---

### gamelog_raw.v_presto_log_sub — GM / 后台扣币

GM 或后台扣币时产生。

| 字段 | 类型 | 说明 |
|---|---|---|
| `uid` | bigint / varchar | 用户 ID |
| `source` | string | str1，固定 `gm` |
| `source_method` | string | str2，扣币源 class.method |
| `amount` | int | str3，扣币数量 |
| `balance` | int | str4，当前余额 |
| `cash` | int | str5，真钻数 |
| `blackcash` | int | str6，黑钻数 |

---

### gamelog_raw.v_presto_log_ser — 在线人数 / PCU

定时统计在线人数时产生，同时写 MySQL `log_online`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | string | str1，固定 `pcu` |
| `timestamp` | int | str2，时间戳 |
| `online_num` | int | str3，在线人数 |

---

## 二、MySQL 行为日志表（推断接入 Presto）

> 以下表如果已接入 Presto，推断视图名为 `gamelog_raw.v_presto_log_{表名}`。需与数仓负责人确认实际是否接入及字段类型。

### gamelog_raw.v_presto_log_exchange_pack — 资源/道具获得

来源：`Logger::logExchangePack()` → `log_exchange_pack_{m-d}`

| 字段 | 类型 | 说明 |
|---|---|---|
| `date` | string | 日期 |
| `uid` | bigint / varchar | 用户 ID |
| `modules` | string | 来源模块/玩法 |
| `exp` | int | 获得经验 |
| `coin` | int | 获得金币 |
| `cash` | int | 获得真钻 |
| `blackcash` | int | 获得黑钻 |
| `insight` | int | 获得洞察 |
| `integral` | int | 获得积分 |
| `prestige` | int | 获得声望 |
| `vigour` | int | 获得精力 |
| `energy` | int | 获得体力 |
| `gift_cash` | int | 获得礼券 |
| `honour` | int | 获得荣誉 |
| `souls` | int | 获得灵魂 |
| `card_point` | int | 获得卡牌点数 |
| `exploit` | int | 获得功勋 |
| `exploit_point` | int | 获得功勋点 |
| `god_exp` | int | 获得神恩 |
| `items` | string | 获得道具（JSON 或 item_id:count 格式） |

---

### gamelog_raw.v_presto_log_exchange_cost — 资源/道具消耗

来源：`Logger::logExchangeCost()` → `log_exchange_cost_{m-d}`

字段与 `exchange_pack` 对应，前缀为 `cost_`，如 `cost_exp`、`cost_coin`、`cost_cash`、`cost_items` 等。

---

### gamelog_raw.v_presto_log_activity_num — 活动参与次数

来源：`Logger::actvityNum()` → `log_activity_num`

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | bigint / varchar | 用户 ID |
| `activity_id` | int | 活动 ID |
| `receive_time` | int / datetime | 参与时间 |

---

### gamelog_raw.v_presto_log_activity_receive — 精彩活动领取

来源：`Logger::actvityReceive()` → `log_activity_receive`

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | bigint / varchar | 用户 ID |
| `activity_id` | int | 活动 ID |
| `reward_id` | int | 奖励 ID |
| `receive_time` | int / datetime | 领取时间 |
| `receive_num` | int | 领取数量 |

---

### gamelog_raw.v_presto_log_item — 物品变化（按月分表）

来源：`Logger::logAll('t_log_item', ...)`

| 字段 | 类型 | 说明 |
|---|---|---|
| `uid` | bigint / varchar | 用户 ID |
| `class` | string | 调用类 |
| `method` | string | 调用方法 |
| `args` | string | 参数（通常包含 item_id、count） |
| `type` | string | `+` 表示获得，`-` 表示消耗 |
| `create_time` | int / datetime | 创建时间 |

---

## 三、示例 SQL

### 1) 查询某日登录玩家

```sql
SELECT uid, passport, level, viplevel, coin, blackcoin, exp
FROM gamelog_raw.v_presto_log_login
WHERE game_id = 39
  AND ds = '<昨天ds>'
LIMIT 100;
```

### 2) 查询某日充值流水

```sql
SELECT uid, passport, charge_type, game_money, order_id, gift_id
FROM gamelog_raw.v_presto_log_pay
WHERE game_id = 39
  AND ds = '<昨天ds>'
ORDER BY game_money DESC
LIMIT 100;
```

### 3) 查询某玩家昨日获得道具明细

```sql
SELECT date, uid, modules, items, coin, cash, blackcash
FROM gamelog_raw.v_presto_log_exchange_pack
WHERE game_id = 39
  AND ds = '<昨天ds>'
  AND uid = 123456789
  AND (items IS NOT NULL AND items != '')
ORDER BY date;
```

### 4) 查询某玩家昨日消耗道具明细

```sql
SELECT date, uid, modules, cost_items, cost_cash, cost_blackcash
FROM gamelog_raw.v_presto_log_exchange_cost
WHERE game_id = 39
  AND ds = '<昨天ds>'
  AND uid = 123456789
  AND (cost_items IS NOT NULL AND cost_items != '')
ORDER BY date;
```

### 5) 查询某日某活动参与次数

```sql
SELECT user_id, activity_id, receive_time
FROM gamelog_raw.v_presto_log_activity_num
WHERE game_id = 39
  AND ds = '<昨天ds>'
  AND activity_id = 1010
LIMIT 100;
```

### 6) 查询某玩家昨日钻石获得明细

```sql
SELECT uid, source, source_method, amount, cash_add, blackcash_add, balance
FROM gamelog_raw.v_presto_log_curr
WHERE game_id = 39
  AND ds = '<昨天ds>'
  AND uid = 123456789
ORDER BY daytime;
```

### 7) 使用 ODL 库（T+1 归档）

```sql
-- use_odl
SELECT uid, passport, level, viplevel
FROM gamelog_odl.v_presto_log_login
WHERE game_id = 39
  AND ds = '<昨天ds>'
LIMIT 100;
```

---

## 四、注意事项

1. **源码中无 Presto/ODL/ECO 定义**：本文件所有 Presto 库名、表名、分区字段均为根据 PHP 代码结构推断，必须与你们实际的 Hive/Presto 元数据核对。
2. **Action 命名不一致**：源码只有小写 category（`login`、`pay`、`curr` 等），没有 `RoleLogin`、`RoleItem` 这类驼峰名。若数仓存在驼峰名，是下游 ETL 映射结果。
3. **`curr` 配置带空格**：`DataCenterLog.class.php` 中写的是 `'curr '=>7`（带空格），但实际调用使用 `'curr'`。ETL 时需注意。
4. **并非所有 Tracer 事件都进 DataCenter**：只有 `6 / 600 / 601 / 1002 / 1003 / 1016` 会写入 Scribe，其余事件用于活动 / 跨服逻辑。
5. **道具变化不进 Scribe**：道具获得/消耗主要写 MySQL（`log_exchange_pack/cost`、`t_log_item`），DataCenter 只记录货币维度。
6. **分表多样**：资源流转按日分表（`MM-DD`），`t_log_*` 按月分表（`Y_m`），`log_online` 等不分表。如果建 Presto 视图通常需要按日期 union 或按分区字段路由。
7. **`role_id` 类型不确定**：源码中 uid 有时作为字符串处理，有时作为 bigint。按 role_id 过滤时如果无结果，尝试切换引号/整数形式。
8. **测试服过滤**：代码层没有统一的测试服日志丢弃逻辑，建议数仓层按 `serverName` 或 `server_id` 过滤。
