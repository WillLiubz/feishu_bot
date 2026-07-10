## 表结构

> 游戏：女1_ProM_Dev，game_id = 39
> 数据来源：`C:\YZ_SVN\女1_后端_ProM_Dev\php_trunk`
> 后端语言：PHP
> 数仓数据库：`raw_scribe_log`

---

### 数仓架构概览

游戏 39 后端通过 `DataCenterLog.class.php` 将玩家行为以 **pipe(`|`)-delimited** 字符串实时写入 Scribe，category 固定为 `{game_id}_{type}`，例如 `39_login`、`39_pay`。下游 ETL 把每个 category 映射到 `raw_scribe_log` 下的**同名表**，表名就是 category 后缀（`login`、`est`、`pay`、`curr`、`prop`、`sub`、`ser`）。

因此查询游戏 39 的 Scribe 日志时，统一使用：

```sql
SELECT ... FROM raw_scribe_log.<behavior> WHERE gameid = '39' AND ds = '<日期>'
```

> **重要**：`gameid` 是字符串分区字段，必须写 `gameid = '39'`；用 `game_id = 39` 会导致全表扫描而超时。`game_id` 列仅作为参考，不建议用于过滤。

| 后端 category | 数仓表名 | 业务含义 | 代码入口 |
|---|---|---|---|
| `39_login` | `raw_scribe_log.login` | 玩家登录 | `User::login()` → `Tracer::login_tracer` (1003) |
| `39_est` | `raw_scribe_log.est` | 注册 / 激活 / 创角 | `UserRegister::register()` → `Tracer::register_tracer` (1002) |
| `39_pay` | `raw_scribe_log.pay` | 充值（含直购） | `passport.php::chargeAction()` → `Tracer::cash_charge_tracer` (600) / `direct_charge_tracer` (601) |
| `39_curr` | `raw_scribe_log.curr` | 玩家加币（钻石/黑钻/货币获得） | `User::raiseField()` / `Logger::logExchangePack()` → `Tracer::cash_tracer` (6) amount>0 |
| `39_prop` | `raw_scribe_log.prop` | 玩家消费钻石/货币 | `User::reduceField()` / `Logger::logExchangeCost()` → `Tracer::cash_tracer` (6) amount<0 且非 GM |
| `39_sub` | `raw_scribe_log.sub` | GM / 后台扣币 | `Logger::logExchangeCost()` → `Tracer::cash_tracer` (6) amount<0 且 source=`api.addGoodsAction` |
| `39_ser` | `raw_scribe_log.ser` | 在线人数 / PCU | `UserCommon::getOnlineNum()` → `Tracer::user_online_tracer` (1016) |

> `raw_scribe_log` 是**多游戏共用库**，所有查询必须带 `game_id = 39`。`gameid` 列来自原始消息，`game_id` 列由 ETL 补充；实际样本中两者一致，建议用 `game_id` 过滤。

---

### 通用字段（所有 raw_scribe_log.* 表）

实际数仓列名如下（已从 `raw_scribe_log.pay` 等表采样确认）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `behavior` | string | 行为类型，`login`/`est`/`pay`/`curr`/`prop`/`sub`/`ser` |
| `operatorid` | string | 平台/运营商 ID（pid） |
| `gameid` | string | 原始消息中的游戏 ID（39） |
| `serverid` | string | 服务器 ID（原始消息中的 sid） |
| `platform` | string | 平台 ID（与 operatorid 相同） |
| `timestamp` | bigint | Unix 时间戳（秒） |
| `ouid` | string | 平台账号/通行证（passport） |
| `iuid` | string | 玩家内部唯一 ID（uid） |
| `count` | int | 计数，通常固定为 1 |
| `custom_pra1` ~ `custom_pra8` | string | 各类型的业务字段，含义见下表 |
| `client_ip` | string | 客户端 IP |
| `user_level` | string | 角色等级 |
| `vip_level` | string | VIP 等级 |
| `moneycoin` | string | 金币/普通货币余额 |
| `blackmoneycoin` | string | 黑钻/黑金余额 |
| `is_test` | string | 样本中为数字，含义待确认，不建议用于测试服过滤 |
| `version` | string | 版本号 |
| `entrance` | string | 入口 |
| `device` | string | 设备信息 |
| `user_exp` | string | 玩家经验 |
| `firstintime` | string | 首次进入时间 |
| `gamecoin` | string | 游戏币余额（含义待确认） |
| `sdk_version` | string | SDK 版本 |
| `debug` | string | 调试信息 |
| `ds` | string | 分区日期 yyyyMMdd |
| `game_id` | int | ETL 补充的游戏 ID，过滤用 `game_id = 39` |

> 时间字段：`timestamp` 是 Unix 秒；按天统计用分区字段 `ds`（yyyyMMdd）。
> 玩家标识：`iuid` 是玩家内部唯一 ID，`ouid` 是平台账号。按玩家分析时通常用 `iuid`。

---

### 各 behavior 字段详解

#### `raw_scribe_log.login` — 玩家登录

来源：`Tracer::login_tracer` (1003)

`DataCenterLog::send_data_log(..., $refer, 'on', 0, '', '', '', '', '', 'login')`

| 字段 | 含义 |
|---|---|
| `custom_pra1` | 用户来源 id（`refer` / `$param`） |
| `custom_pra2` | 固定为 `on`（上线） |
| `custom_pra3` | 在线时长，登录时固定为 0 |
| `custom_pra4` ~ `custom_pra8` | 空 |

---

#### `raw_scribe_log.est` — 注册 / 激活 / 创角

来源：`Tracer::register_tracer` (1002)

`DataCenterLog::send_data_log(..., $refer, $amount, $flags, '', '', '', '', '', 'est')`

| 字段 | 含义 |
|---|---|
| `custom_pra1` | 用户来源 id（`refer` / `$param`） |
| `custom_pra2` | 创角步骤 gid（`amount` / `$guide_info['gid']`） |
| `custom_pra3` | 创角步骤 flags |
| `custom_pra4` ~ `custom_pra8` | 扩展字段 |

---

#### `raw_scribe_log.pay` — 充值流水

来源：`Tracer::cash_charge_tracer` (600) / `direct_charge_tracer` (601)

- 普通充值：`send_data_log(..., 1, '', $amount, $order_id, '', '', '', '', 'pay')`
- 直购充值：`send_data_log(..., 2, '', $amount, $order_id, $gift_id, '', '', '', 'pay')`

| 字段 | 含义 |
|---|---|
| `custom_pra1` | 充值类型：`1`=兑换游戏币，`2`=直购道具 |
| `custom_pra2` | 充值渠道（当前固定为空） |
| `custom_pra3` | 充值游戏币/钻石数量 |
| `custom_pra4` | 充值对账流水号/订单号 |
| `custom_pra5` | 直购礼包 id（仅直购时） |
| `custom_pra6` ~ `custom_pra8` | 扩展字段 |

> 充值同时还会写入 MySQL `log_charge` 和 `log_direct_mall`。

---

#### `raw_scribe_log.curr` — 玩家加币（钻石/黑钻/货币获得）

来源：`Tracer::cash_tracer` (6) amount > 0

`send_data_log(..., $param, $source, $amount, $refer, $cash_add, $blackcash_add, '', '', 'curr')`

| 字段 | 含义 |
|---|---|
| `custom_pra1` | 加币来源：`gm` / `game` |
| `custom_pra2` | 操作源 class.method |
| `custom_pra3` | 加币数量 |
| `custom_pra4` | 充值对账流水号/当前余额（`refer`） |
| `custom_pra5` | 加币真钻数（`cash_add`） |
| `custom_pra6` | 加币黑钻数（`blackcash_add`） |
| `custom_pra7` ~ `custom_pra8` | 扩展字段 |

---

#### `raw_scribe_log.prop` — 玩家消费钻石/货币

来源：`Tracer::cash_tracer` (6) amount < 0 且非 GM 扣币

`send_data_log(..., $source, '', -$amount, $cash_add, $blackcash_add, $refer, '', '', 'prop')`

| 字段 | 含义 |
|---|---|
| `custom_pra1` | 消费源 class.method |
| `custom_pra2` | 消费等级/道具等级（当前固定为空） |
| `custom_pra3` | 消费数量（正数） |
| `custom_pra4` | 真钻消耗数（`cash_add`） |
| `custom_pra5` | 黑钻消耗数（`blackcash_add`） |
| `custom_pra6` | 当前余额/对账流水号（`refer`） |
| `custom_pra7` ~ `custom_pra8` | 扩展字段 |

> `custom_pra1` 通常形如 `UserMall.buy`、`UserLevy.levy`，可用于判断玩家参与了哪个系统。

---

#### `raw_scribe_log.sub` — GM / 后台扣币

来源：`Tracer::cash_tracer` (6) amount < 0 且 source=`api.addGoodsAction`

`send_data_log(..., 'gm', $source, -$amount, $refer, $cash_add, $blackcash_add, '', '', 'sub')`

| 字段 | 含义 |
|---|---|
| `custom_pra1` | 固定为 `gm` |
| `custom_pra2` | 扣币源 class.method |
| `custom_pra3` | 扣币数量（正数） |
| `custom_pra4` | 扣币对账流水号/当前余额（`refer`） |
| `custom_pra5` | 真钻数（`cash_add`） |
| `custom_pra6` | 黑钻数（`blackcash_add`） |
| `custom_pra7` ~ `custom_pra8` | 扩展字段 |

---

#### `raw_scribe_log.ser` — 在线人数 / PCU

来源：`Tracer::user_online_tracer` (1016)

`send_data_log(..., 'pcu', $refer, $amount, '', '', '', '', '', 'ser')`

| 字段 | 含义 |
|---|---|
| `custom_pra1` | 固定为 `pcu` |
| `custom_pra2` | 时间戳（`refer`，Unix 秒） |
| `custom_pra3` | 在线人数（`amount`） |
| `custom_pra4` ~ `custom_pra8` | 空 |

---

### MySQL 日志队列体系（后端本地，未接入 raw_scribe_log）

业务代码通过 `Logger::xxx()` 将日志推到 Redis 队列，由 `queueManage.php` 消费后写入 MySQL。这部分日志**不进 Scribe / raw_scribe_log**，主要用于道具、活动、战斗、英雄等详细行为分析。如果后续确认这些 MySQL 表已同步到 Presto，再补充对应库表名；**当前请不要让 LLM 直接查询以下表名**。

| 队列 key | 后端目标表 | 关键字段 | 业务含义 |
|---|---|---|---|
| `logger:active` | `log_active` | `user_id, create_time, passport, ip` | 激活 |
| `logger:goto` | `log_goto` | `passport, ip, create_time` | 进入游戏页 |
| `logger:login` | `log_login` | `user_id, user_name, passport, ip, login_time, session_id` | 登录 |
| `logger:levelup` | `log_levelup` | `user_id, level, next_level, passport` | 升级 |
| `logger:killBoss` | `log_kill_boss` | `user_id, boss_id, kill_time` | 击杀关卡 BOSS |
| `logger:exchangePack` | `log_exchange_pack_{m-d}` | `date, uid, modules, exp, coin, cash, blackcash, items, ...` | 资源/道具获得 |
| `logger:exchangeCost` | `log_exchange_cost_{m-d}` | `date, uid, modules, cost_exp, cost_coin, cost_cash, cost_items, ...` | 资源/道具消耗 |
| `logger:actvityReceive` | `log_activity_receive` | `user_id, activity_id, reward_id, receive_time, receive_num` | 精彩活动领取 |
| `logger:actvityNum` | `log_activity_num` | `user_id, activity_id, receive_time` | 活动参与次数 |
| `logger:flowerGive` | `log_flower_give` | `user_id, friend_id, num` | 送花 |
| `logger:angelLevelUpQuality` | `log_angel_levelup_quality` | — | 女神升阶 |
| `logger:heroRecruit` | `log_hero_recruit` | — | 英雄招募 |
| `logger:fightReportUp` | `log_fight_report_up` | — | 竞技场战报 |
| `logger:mineUp` | `log_mine_up` | — | 夺宝奇兵探险 |
| `logger:kingBet` | `log_king_bet` | — | 大师赛下注 |
| - | `log_charge` | `billno, user_id, op_id, passport, level, cash, now_cash, create_time` | 充值流水 |
| - | `log_online` | `time, num` | 在线人数 |

> 当前数仓可查询的玩家行为主要来自 `raw_scribe_log` 的 7 张表。道具/资源明细在数仓中是否有对应表，请与数仓负责人确认。

---

### Tracer 事件类型常量

`Tracer.class.php` 定义的主要常量：

| 常量 | 值 | 业务含义 | 是否进 DataCenter / raw_scribe_log |
|---|---|---|---|
| `cash_tracer` | 6 | 钻石变动 | 是（`curr`/`prop`/`sub`） |
| `cash_charge_tracer` | 600 | 充值 | 是（`pay`） |
| `direct_charge_tracer` | 601 | 直购充值 | 是（`pay`） |
| `register_tracer` | 1002 | 注册 | 是（`est`） |
| `login_tracer` | 1003 | 登录 | 是（`login`） |
| `user_online_tracer` | 1016 | 在线人数 | 是（`ser`） |
| 其他（level_up、pk、angel 等） | — | 活动/跨服逻辑 | 否 |

---

## 一、DataCenter 实时表（raw_scribe_log）

### `raw_scribe_log.login` — 玩家登录

每次玩家登录产生一条。

| 字段 | 类型 | 说明 |
|---|---|---|
| `iuid` | string | 玩家内部 ID |
| `ouid` | string | 平台账号 |
| `custom_pra1` | string | 用户来源 id |
| `custom_pra2` | string | 固定 `on` |
| `custom_pra3` | string | 在线时长（登录时 0） |
| `user_level` | string | 等级 |
| `vip_level` | string | VIP 等级 |
| `moneycoin` | string | 金币 |
| `blackmoneycoin` | string | 黑钻 |

---

### `raw_scribe_log.est` — 注册 / 激活 / 创角

玩家注册或创角时产生。

| 字段 | 类型 | 说明 |
|---|---|---|
| `iuid` | string | 玩家内部 ID |
| `ouid` | string | 平台账号 |
| `custom_pra1` | string | 用户来源 id |
| `custom_pra2` | string | 创角步骤 gid |
| `custom_pra3` | string | 创角步骤 flags |
| `user_level` | string | 等级 |
| `vip_level` | string | VIP 等级 |

---

### `raw_scribe_log.pay` — 充值流水

每笔充值产生一条。

| 字段 | 类型 | 说明 |
|---|---|---|
| `iuid` | string | 玩家内部 ID |
| `ouid` | string | 平台账号 |
| `custom_pra1` | string | 充值类型：`1`=兑换游戏币，`2`=直购道具 |
| `custom_pra2` | string | 充值渠道（空） |
| `custom_pra3` | string | 充值游戏币/钻石数量 |
| `custom_pra4` | string | 订单号 |
| `custom_pra5` | string | 直购礼包 id（仅直购） |
| `user_level` | string | 等级 |
| `vip_level` | string | VIP 等级 |

---

### `raw_scribe_log.curr` — 玩家加币（钻石/黑钻/货币获得）

| 字段 | 类型 | 说明 |
|---|---|---|
| `iuid` | string | 玩家内部 ID |
| `custom_pra1` | string | 加币来源：`gm` / `game` |
| `custom_pra2` | string | 操作源 class.method |
| `custom_pra3` | string | 加币数量 |
| `custom_pra4` | string | 对账流水号/余额 |
| `custom_pra5` | string | 真钻加币数 |
| `custom_pra6` | string | 黑钻加币数 |

---

### `raw_scribe_log.prop` — 玩家消费钻石/货币

| 字段 | 类型 | 说明 |
|---|---|---|
| `iuid` | string | 玩家内部 ID |
| `custom_pra1` | string | 消费源 class.method（如 `UserLevy.levy`） |
| `custom_pra2` | string | 消费等级/道具等级（通常空） |
| `custom_pra3` | string | 消费数量 |
| `custom_pra4` | string | 真钻消耗数 |
| `custom_pra5` | string | 黑钻消耗数 |
| `custom_pra6` | string | 当前余额/对账流水号 |

---

### `raw_scribe_log.sub` — GM / 后台扣币

| 字段 | 类型 | 说明 |
|---|---|---|
| `iuid` | string | 玩家内部 ID |
| `custom_pra1` | string | 固定 `gm` |
| `custom_pra2` | string | 扣币源 class.method |
| `custom_pra3` | string | 扣币数量 |
| `custom_pra4` | string | 对账流水号/余额 |
| `custom_pra5` | string | 真钻数 |
| `custom_pra6` | string | 黑钻数 |

---

### `raw_scribe_log.ser` — 在线人数 / PCU

| 字段 | 类型 | 说明 |
|---|---|---|
| `custom_pra1` | string | 固定 `pcu` |
| `custom_pra2` | string | 时间戳 |
| `custom_pra3` | string | 在线人数 |

---

## 二、示例 SQL

### 1) 查询某日登录玩家

```sql
SELECT iuid, ouid, user_level, vip_level, moneycoin, blackmoneycoin
FROM raw_scribe_log.login
WHERE gameid = '39'
  AND ds = '<昨天ds>'
LIMIT 100;
```

### 2) 查询某日充值流水

```sql
SELECT iuid, ouid, custom_pra1 AS charge_type, custom_pra3 AS amount,
       custom_pra4 AS order_id, custom_pra5 AS gift_id,
       user_level, vip_level
FROM raw_scribe_log.pay
WHERE gameid = '39'
  AND ds = '<昨天ds>'
ORDER BY CAST(custom_pra3 AS BIGINT) DESC
LIMIT 100;
```

### 3) 查询昨日付费 TOP 玩家及其系统参与情况

**第 1 步：找出昨日付费最多的玩家**

```sql
SELECT iuid,
       SUM(CAST(custom_pra3 AS BIGINT)) AS total_pay,
       COUNT(*) AS pay_times
FROM raw_scribe_log.pay
WHERE gameid = '39'
  AND ds = '<昨天ds>'
GROUP BY iuid
ORDER BY total_pay DESC
LIMIT 10;
```

**第 2 步：用第 1 步得到的 `iuid` 查其昨日消费/行为分布**

```sql
SELECT custom_pra1 AS system_method,
       COUNT(*) AS times,
       SUM(CAST(custom_pra3 AS BIGINT)) AS total_cost
FROM raw_scribe_log.prop
WHERE gameid = '39'
  AND ds = '<昨天ds>'
  AND iuid = '<目标iuid>'
GROUP BY custom_pra1
ORDER BY total_cost DESC
LIMIT 50;
```

> 也可以用同样的 `iuid` 去 `raw_scribe_log.curr` 查昨日货币获得明细，或去 `raw_scribe_log.login` 查登录次数。

### 4) 查询某玩家昨日货币获得明细

```sql
SELECT custom_pra1 AS source, custom_pra2 AS method,
       custom_pra3 AS amount, custom_pra5 AS cash_add,
       custom_pra6 AS blackcash_add
FROM raw_scribe_log.curr
WHERE gameid = '39'
  AND ds = '<昨天ds>'
  AND iuid = '<目标iuid>'
ORDER BY timestamp;
```

### 5) 查询某日在线人数峰值

```sql
SELECT MAX(CAST(custom_pra3 AS INTEGER)) AS pcu
FROM raw_scribe_log.ser
WHERE gameid = '39'
  AND ds = '<昨天ds>';
```

### 6) 查询某日新增玩家（注册/激活）

```sql
SELECT COUNT(DISTINCT iuid) AS new_users
FROM raw_scribe_log.est
WHERE gameid = '39'
  AND ds = '<昨天ds>';
```

---

## 三、注意事项

1. **库名固定为 `raw_scribe_log`**：不要写成 `gamelog_raw`、`gamelog_odl`、`gameeco_raw` 等 312/160 项目的库名。
2. **表名就是 behavior**：`raw_scribe_log.login`、`raw_scribe_log.pay`、`raw_scribe_log.prop` 等。
3. **所有查询必须带 `game_id = 39`**：`raw_scribe_log` 是多游戏共享库，不带会查到其他游戏数据。
4. **玩家标识**：按玩家分析用 `iuid`；`ouid` 是平台账号/通行证。
5. **数值字段都是 string**：`custom_pra*`、`user_level`、`moneycoin` 等在 Presto 中都是 VARCHAR，求和/排序时必须 `CAST(... AS BIGINT)` 或 `CAST(... AS DOUBLE)`。
6. **时间字段**：`timestamp` 是 Unix 秒 BIGINT；按天过滤用 `ds`（yyyyMMdd）。
7. **测试服过滤**：代码层没有统一测试服丢弃逻辑；`is_test` 字段含义待确认。建议按 `operatorid`/`platform` 或 `serverid` 与运营侧确认测试服范围。
8. **MySQL 日志未接入 raw_scribe_log**：`log_exchange_pack`、`log_activity_num`、`t_log_item` 等当前不在 `raw_scribe_log` 中，查询道具/活动明细时需先确认数仓是否有对应同步表。
9. **充值金额口径**：`raw_scribe_log.pay.custom_pra3` 是充值获得的游戏币/钻石数量，不是人民币金额；如需人民币金额，需结合 `log_charge` 或平台对账数据。
