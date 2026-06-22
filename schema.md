## 表结构

> 游戏：女3_ProGoddessIII，game_id = 312
> 数据来源：`C:\YZ_SVN\女3_ProGoddessIII\branches\server\src\aegit.com\ae\plugin_uzdatacenter\` 和 `plugin_uzdatacenter2017\`

---

### 数仓架构概览

服务端使用两套推送体系，对应不同数仓位置：

| 体系 | Go 包 | Presto 数据库 | 延迟 | 说明 |
|---|---|---|---|---|
| KPI（实时） | `plugin_uzdatacenter` / `plugin_uzdatacenter2017/kpi` | `gamelog_raw` | 实时 T+0 | 登录/充值/升级等关键事件 |
| KPI（T+1） | 同上，入仓延迟 | `gamelog_odl` | T+1 | 同 gamelog_raw 的昨日版本 |
| ECO 快照 | `plugin_uzdatacenter2017/eco` | `gameeco_raw` | 实时 / T+0 | 角色/道具/维度快照 |
| ECO 流水 | `plugin_uzdatacenter2017/eco` | `gameeco_odl` | T+1 | 道具/资源/行为等产销流水 |

**表名规则**：`{库}.v_presto_{snap|log}_{小写表名}`
例：`gameeco_raw.v_presto_snap_rolecache`、`gamelog_odl.v_presto_log_rolelogin`

**重要**：`game_id` 在 ECO 表里为 **字符串** `'312'`，在 KPI 表里为 **整数** `312`，写 SQL 需注意。

**重要**：ECO 表（gameeco_raw/odl）的 `role_id` 为 **VARCHAR 字符串**，不是数字。按 role_id 过滤时必须写 `CAST(role_id AS VARCHAR) = '123456'`，不能写 `role_id = 123456`（整数比较会全表扫描，极慢）。

---

### 通用 KPI 基础字段（所有 gamelog_raw/odl 表均包含）

来自 `KpiBase`：

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 分区日期 yyyyMMdd |
| game_id | int | 312 |
| event_id | bigint | 事件唯一 ID |
| ver | string | SDK 版本 |
| op_id | int | 运营商 ID |
| opgame_id | int | 渠道 ID（server_id 前 4 位） |
| server_id | int | 服务器 ID |
| createtime | string | 事件时间 yyyy-MM-dd HH:mm:ss |
| channel_id | int | 手机分包渠道 ID |
| multiscreen_type | string | 多屏类型 |

**过滤测试服**：`AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'`

---

### 通用 ECO 基础字段（所有 gameeco 表均包含）

来自 `EcoBase`：

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 分区日期 yyyyMMdd |
| game_id | string | '312'（字符串！） |
| event_id | bigint | 事件唯一 ID |
| server_id | int | 服务器 ID |
| opgame_id | int | 渠道 ID |
| server_type | int | 服务器类型（1=正式服，2=测试服） |
| op_id | int | 运营商 ID |
| createtime_local | string | 当地时间 yyyy-MM-dd HH:mm:ss |
| timestamp | int | Unix 时间戳（10位，秒） |
| time_zone | string | 时区（如 Asia/Chongqing） |
| account | string | 账号 |
| account_regtime | int | 账号注册时间（Unix 秒） |
| client_ip | string | 客户端 IP |
| role_id | bigint | 角色 ID（全服唯一） |
| role_name | string | 角色名 |
| role_regtime | int | 角色注册时间（Unix 秒） |
| role_career | int | 职业 |
| role_level | int | 等级 |
| role_vip | int | VIP 等级 |
| role_power | bigint | 战力 |
| role_unionid | bigint | 公会 ID |
| role_paid | int | 是否付费（0=否，1=是） |
| role_type | int | 角色类型（1=正常，2=测试，3=GM，4=机器人） |
| channel_id | int | CPS 分包 ID |
| device_type | string | 设备型号 |
| device_os | string | 操作系统 |
| game_ver | string | 游戏版本 |

---

## 一、KPI 实时表（gamelog_raw）

### gamelog_raw.v_presto_log_rolelogin — 角色登录（实时 T+0）

每次角色登录产生一条。适合查当日 DAU、新增。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| client_ip | string | 客户端 IP |
| device | string | 设备信息 |
| account | string | 账号 |
| role_id | string | 角色 ID（KPI 表中为字符串） |
| role_type | int | 角色类型 |
| role_name | string | 角色名 |
| role_career | string | 职业 |
| role_level | int | 等级 |
| role_vip | int | VIP |
| role_unionid | bigint | 公会 ID |
| role_regtime | string | 注册时间 |
| role_paid | int | 是否付费 |
| role_exp | bigint | 经验 |
| role_energy | int | 体力 |
| diamond | int | 绑定钻石 |
| blackdiamond | int | 非绑钻石 |
| money | bigint | 金币 |

---

### gamelog_raw.v_presto_log_payrecharge — 充值流水（实时 T+0）

每笔充值一条。`pay_money` 单位为人民币元。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型 |
| role_name | string | 角色名 |
| role_career | int | 职业 |
| role_level | int | 等级 |
| role_vip | int | VIP |
| role_regtime | string | 注册时间 |
| role_paid | int | 是否付费 |
| pay_type | int | 充值类型（1=购买钻石，2=购买商品） |
| pay_orderid | string | 订单号 |
| pay_discount | float | 折扣率 |
| pay_way | int | 支付方式 |
| pay_itemid | string | 购买商品 ID |
| pay_money | double | 充值金额（元） |
| pay_currency | string | 货币类型 |
| pay_diamond | bigint | 购得钻石数 |
| diamond | int | 充值后绑钻余额 |
| blackdiamond | int | 充值后非绑钻余额 |
| money | bigint | 充值后金币余额 |

---

### gamelog_raw.v_presto_log_rolelvup — 角色升级（实时 T+0）

| 额外字段 | 类型 | 说明 |
|---|---|---|
| role_level | int | 升级后等级 |
| role_level_before | int | 升级前等级 |
| role_exp | bigint | 当前经验 |
| diamond / blackdiamond / money | int/bigint | 当前资产 |

---

### gamelog_raw.v_presto_log_rolereg — 角色注册（实时 T+0）

| 额外字段 | 类型 | 说明 |
|---|---|---|
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型 |
| ad_id | string | 广告 ID |
| pt_account_regtime | string | 平台账号注册时间 |
| channel_id | int | 渠道 ID |
| client_ip | string | IP |
| device | string | 设备 |

---

## 二、KPI T+1 表（gamelog_odl）

与 gamelog_raw 对应，字段完全相同，数据延迟一天，适合查历史报表。

- `gamelog_odl.v_presto_log_rolelogin`
- `gamelog_odl.v_presto_log_payrecharge`
- `gamelog_odl.v_presto_log_rolelvup`
- `gamelog_odl.v_presto_log_rolereg`

---

## 三、ECO 快照表（gameeco_raw）

### gameeco_raw.v_presto_snap_rolecache — 角色快照

每日每个角色一条，记录当天末状态。`game_id` 为字符串 `'312'`。

在 EcoBase 基础字段之上，额外有：

| 字段 | 类型 | 说明 |
|---|---|---|
| cache_day | string | 快照日期 yyyyMMdd |
| country | string | 国家 |
| state | string | 地区 |
| union_name | string | 公会名称 |
| ad_user | int | 广告用户（1=广告，2=非广告） |
| diamond | bigint | 绑定钻石余额 |
| blackdiamond | bigint | 非绑钻石余额 |
| money | bigint | 金币余额 |
| role_exp | int | 经验 |
| role_create_time | int | 角色创建时间（Unix秒） |
| guide_id_max | int | 最高完成引导 ID |
| last_map_id | int | 最后停留地图 ID |
| last_login | int | 最后登录时间（Unix秒） |
| last_logout | int | 最后下线时间（Unix秒） |
| total_login_days | int | 累计登录天数 |
| daily_pay_diamond | bigint | 当日付费钻石 |
| max_daily_pay_diamond | bigint | 历史单日最高付费钻石 |
| total_pay_diamond | bigint | 累计付费钻石 |
| total_pay_money | double | 累计充值金额（元） |
| total_pay_days | int | 累计付费天数 |
| total_pay_times | int | 累计付费次数 |
| first_pay_time | int | 首次付费时间（Unix秒） |
| last_pay_time | int | 最后付费时间（Unix秒） |
| arena_rank | int | 竞技场排名 |
| game_ver | string | 游戏版本 |
| customized | string | 游戏自定义扩展字段 |

> 查最新快照：`row_number() OVER (PARTITION BY role_id ORDER BY ds DESC)` 取 rank=1，或直接用最新 ds。

---

### gameeco_raw.v_presto_snap_packcache — 背包道具快照

每日每个角色的背包道具快照，背包按 pack1~pack5 字符串打包存储。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds / cache_day | string | 日期 |
| game_id | string | '312' |
| server_id / op_id | int | 服务器/运营商 |
| account | string | 账号 |
| role_id | bigint | 角色 ID |
| role_name | string | 角色名 |
| role_regtime | int | 注册时间 |
| role_level | int | 等级 |
| role_vip | int | VIP |
| last_login | int | 最后登录时间 |
| pack1~pack5 | string | 各背包格子内容（格式由游戏定义） |

---

### gameeco_raw.v_presto_snap_dimcache — 维度快照（神将/坐骑/宝物等）

每日每个角色的养成维度快照，通过 `dim_type` 区分类型（不同 `dim_type` 对应不同的 `sub_dim_1~10` 含义）。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds / cache_day | string | 日期 |
| game_id | string | '312' |
| role_id | bigint | 角色 ID |
| op_id | int | 运营商 ID |
| dim_type | int | 维度类型（区分神将/坐骑/宝物等） |
| dim_id | bigint | 维度对象 ID |
| dim_name | string | 维度对象名称 |
| dim_item_id | bigint | 关联道具 ID |
| sub_dim_1~sub_dim_10 | string | 维度子属性参数（含义随 dim_type 变化） |
| extra_1~extra_9 | string | 额外扩展参数 |

---

## 四、ECO 流水表（gameeco_odl，T+1）

### gameeco_odl.v_presto_log_rolebehavior — 玩法行为日志 ★

记录玩家各类玩法参与（战斗/副本/PVP/活动等），是分析留存、活跃度的核心表。

在 EcoBase 基础字段之上，额外有：

| 字段 | 类型 | 说明 |
|---|---|---|
| b_type | string | 玩法大类（如 "pve"/"pvp"/"活动" 等字符串） |
| zone | string | 玩法子类 |
| b_id | int | 玩法 ID（副本/关卡/活动具体 ID） |
| zone_id | int | 副本/地图 ID |
| b_value | string | 参与状态（竖线分隔多个参数） |
| session_length | int | 玩法停留时长（秒） |
| enemy_id | bigint | 对手角色 ID |
| rank_before | int | 战前排名 |
| rank_after | int | 战后排名 |
| b_param | string | 附加参数 |
| union_name | string | 公会名称 |
| battle_attr | string | 战斗属性（竖线分隔） |
| buff_item_consume | string | 消耗的 BUFF 道具 |
| team_power | bigint | 队伍总战力 |
| other_object | string | 其他相关对象 |
| customized | string | 游戏自定义扩展 |

---

### gameeco_odl.v_presto_log_roleitem — 道具产销流水

每次道具增减一条记录。

在 EcoBase 基础字段之上，额外有：

| 字段 | 类型 | 说明 |
|---|---|---|
| item_type | string | 道具类型 |
| item_id | int | 道具 ID |
| item_name | string | 道具名称 |
| change_type | int | 变动类型（产出/消耗方向） |
| status_before | bigint | 变动前数量 |
| status_after | bigint | 变动后数量 |
| change_reason | int | 变动原因 ID |
| change_module | int | 功能模块 ID |
| relation_id | string | 关联事件 ID |
| diamond | bigint | 变动后绑钻余额 |
| blackdiamond | bigint | 变动后非绑钻余额 |
| money | bigint | 变动后金币余额 |
| customized | string | 扩展 |

---

### gameeco_odl.v_presto_log_roleres — 资源产销流水

每次资源（钻石/金币/其他货币）增减一条。

在 EcoBase 基础字段之上，额外有：

| 字段 | 类型 | 说明 |
|---|---|---|
| res_id | int | 资源 ID |
| res_name | string | 资源名称 |
| amount_before | bigint | 变动前数量 |
| amount_after | bigint | 变动后数量 |
| change_type | int | 变动类型（产出/消耗） |
| change_amount | int | 变动数量（绝对值） |
| change_reason | int | 原因 ID |
| change_module | int | 功能模块 ID |
| related_id | string | 关联 ID |
| diamond | bigint | 变动后绑钻余额 |
| blackdiamond | bigint | 变动后非绑钻余额 |
| money | bigint | 变动后金币余额 |
| customized | string | 扩展 |

---

### gameeco_odl.v_presto_log_rolevip — VIP 升级日志

每次 VIP 等级变化一条。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| role_vip_before | int | 升级前 VIP |
| role_vip | int | 升级后 VIP |
| role_vipexp_before | int | 升级前 VIP 经验 |
| role_vipexp | int | 升级后 VIP 经验 |
| role_energy | int | 当前体力 |
| diamond | bigint | 绑钻余额 |
| blackdiamond | bigint | 非绑钻余额 |
| money | bigint | 金币余额 |

---

### gameeco_odl.v_presto_log_roletask — 任务完成日志

| 额外字段 | 类型 | 说明 |
|---|---|---|
| task_type | int | 任务类型 ID |
| task_name | string | 任务名称 |
| task_id | int | 任务 ID |
| pre_task_id | int | 前置任务 ID |
| status | int | 状态 |

---

### gameeco_odl.v_presto_log_roleshop — 商店购买日志

| 额外字段 | 类型 | 说明 |
|---|---|---|
| shop_name | string | 商店名称 |
| shop_id | int | 商店 ID |
| one_vs_one | int | 是否限购 |
| items_spend | string | 消耗的道具/资源 |
| items_get | string | 获得的道具/资源 |
| item_unit | int | 单价 |
| item_amount | int | 购买数量 |
| amount_limit | int | 购买上限 |
| discount_rate | double | 折扣率 |

---

### gameeco_odl.v_presto_log_rolepromo — 活动参与日志

| 额外字段 | 类型 | 说明 |
|---|---|---|
| activity_topic | string | 活动主题 |
| activity_step | string | 活动子类 |
| step_id | int | 子步骤 ID |
| activity_id | int | 活动唯一 ID |
| item_spend | string | 消耗的道具/资源 |
| item_get | string | 获得的奖励 |
| activity_begin | bigint | 活动开始时间 |
| activity_end | bigint | 活动结束时间 |
| activity_special | int | 是否精彩活动 |
| activity_pay | int | 是否充值活动 |
| enter_level | string | 可参与等级范围 |
| enter_vip | string | 可参与 VIP 范围 |

---

### gameeco_odl.v_presto_log_rolegold — 黄金/钻石消耗分摊日志

| 额外字段 | 类型 | 说明 |
|---|---|---|
| consume_type | int | 消耗类型（function/item） |
| reason | int | 产生原因 ID |
| gold | bigint | 消耗总量 |
| item_id | int | 关联道具 ID |
| item_name | string | 关联道具名 |
| item_number | bigint | 道具数量 |
| audit_type | int | 分摊类型（混合/消耗/长期） |
| long_ratio | int | 长期型占比 |
| short_ratio | int | 短期型占比 |
| param1 | bigint | UUID |
| param2 | string | 预留参数 |

---

### gameeco_odl.v_presto_log_unionaction — 公会行为日志

| 额外字段 | 类型 | 说明 |
|---|---|---|
| role_unionid | bigint | 公会 ID |
| union_name | string | 公会名 |
| union_level | int | 公会等级 |
| union_size | int | 公会成员数 |
| action_type | string | 行为类型 |
| action_object | bigint | 行为对象 ID |

---

### gameeco_odl.v_presto_log_unionres — 公会资源流水

| 额外字段 | 类型 | 说明 |
|---|---|---|
| role_unionid | bigint | 公会 ID |
| union_name | string | 公会名 |
| union_level | int | 公会等级 |
| union_size | int | 公会成员数 |
| res_id | int | 资源 ID |
| res_name | string | 资源名 |
| amount_before | bigint | 变动前 |
| amount_after | bigint | 变动后 |
| change_type | int | 变动类型 |
| change_amount | bigint | 变动量 |
| change_reason | int | 原因 ID |

---

### gameeco_raw.v_presto_snap_itemcache — 道具快照（精简版）

| 字段 | 类型 | 说明 |
|---|---|---|
| game_id | int | 312 |
| server_id / opgame_id / op_id | int | 服务器/渠道/运营商 |
| cache_day | string | 快照日期 |
| account | string | 账号 |
| role_id | bigint | 角色 ID |
| item_id | int | 道具 ID |
| item_name | string | 道具名 |
| item_num | bigint | 数量 |

---

## 示例 SQL

### 查昨日 DAU（登录人数）
```sql
SELECT COUNT(DISTINCT role_id) AS dau
FROM gamelog_odl.v_presto_log_rolelogin
WHERE game_id = 312
AND ds = '<昨天ds>'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
```

### 查今日实时充值（实时表用今天 ds）
```sql
SELECT
  COUNT(DISTINCT role_id) AS payers,
  CAST(SUM(CAST(pay_money AS DOUBLE)) AS DECIMAL(18,2)) AS revenue
FROM gamelog_raw.v_presto_log_payrecharge
WHERE game_id = 312
AND ds = '<今天ds>'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
```

### 查近 7 日每日充值趋势
```sql
SELECT
  ds,
  COUNT(DISTINCT role_id) AS payers,
  CAST(SUM(CAST(pay_money AS DOUBLE)) AS DECIMAL(18,2)) AS revenue
FROM gamelog_odl.v_presto_log_payrecharge
WHERE game_id = 312
AND ds >= '<7天前ds>'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY ds
ORDER BY ds
```

### 查最新角色快照（战力 TOP 20）
```sql
SELECT role_id, role_name, role_level, role_vip, role_power, total_pay_money
FROM (
  SELECT *, row_number() OVER (PARTITION BY role_id ORDER BY ds DESC) AS rn
  FROM gameeco_raw.v_presto_snap_rolecache
  WHERE game_id = '312'
  AND ds >= '<7天前ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
)
WHERE rn = 1
ORDER BY role_power DESC
LIMIT 20
```

### 查昨日新增角色（注册日=昨天）
```sql
SELECT COUNT(DISTINCT role_id) AS new_roles
FROM gamelog_odl.v_presto_log_rolereg
WHERE game_id = 312
AND ds = '<昨天ds>'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
```

### 查各渠道昨日 DAU
```sql
SELECT opgame_id, COUNT(DISTINCT role_id) AS dau
FROM gamelog_odl.v_presto_log_rolelogin
WHERE game_id = 312
AND ds = '<昨天ds>'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY opgame_id
ORDER BY dau DESC
```

### 查昨日各玩法参与人数（行为日志）
```sql
SELECT b_type, b_id, COUNT(DISTINCT role_id) AS players, COUNT(*) AS events
FROM gameeco_odl.v_presto_log_rolebehavior
WHERE game_id = '312'
AND ds = '<昨天ds>'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY b_type, b_id
ORDER BY events DESC
LIMIT 30
```

### 查昨日资源消耗来源
```sql
SELECT res_name, change_reason, SUM(change_amount) AS total
FROM gameeco_odl.v_presto_log_roleres
WHERE game_id = '312'
AND ds = '<昨天ds>'
AND change_type = 2
GROUP BY res_name, change_reason
ORDER BY total DESC
LIMIT 30
```

### 查昨日道具产出 TOP（按道具名）
```sql
SELECT item_name, COUNT(*) AS times, SUM(status_after - status_before) AS total_gain
FROM gameeco_odl.v_presto_log_roleitem
WHERE game_id = '312'
AND ds = '<昨天ds>'
AND change_type = 1
GROUP BY item_name
ORDER BY total_gain DESC
LIMIT 20
```

---

## 固定报表口径

### KPI 日报

| 指标 | 来源表 | 口径 |
|---|---|---|
| DAU（日活） | gamelog_raw.v_presto_log_rolelogin | COUNT(DISTINCT role_id)，ds=今天，排除测试服 |
| 新增角色 | gamelog_raw.v_presto_log_rolereg | COUNT(DISTINCT role_id)，ds=今天，排除测试服 |
| 付费人数 | gamelog_raw.v_presto_log_payrecharge | COUNT(DISTINCT role_id)，ds=今天 |
| 收入（元） | gamelog_raw.v_presto_log_payrecharge | SUM(CAST(pay_money AS DOUBLE))，ds=今天 |

> 实时表（gamelog_raw）查今天数据；T+1 表（gamelog_odl）查昨天及历史。

### LTV 报表

按角色注册日（account_cache 中的 MIN(ds)）分群：

- LTV1 = 注册当天（day 0）累计充值 ÷ 当天新增人数
- LTV3 = 注册后前 3 天（day 0~2）累计充值 ÷ 当天新增人数
- LTV7 / LTV15 / LTV30 同理

充值数据来自 `gamelog_odl.v_presto_log_payrecharge`（game_id=312），通过 role_id 关联注册日分群。
