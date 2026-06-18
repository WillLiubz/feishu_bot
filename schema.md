## 表结构

> 游戏：女3_ProGoddessIII，game_id = 312
> 双分区：所有表都带 `game_id`（int）+ `ds`（string yyyyMMdd）
> 实时表（gamelog_raw）用今天日期；T+1 表（gamelog_odl / pri_36ji_m）用昨天日期

---

### 通用字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| game_id | int | 必带，值为 312 |
| ds | string | 分区日期，格式 yyyyMMdd |
| opgame_id | string/int | 渠道 ID（gamelog_raw 中为 int；pri_36ji_m 中为 string） |
| op_id | int | 运营商 ID |
| server_id | int | 服务器 / 区 ID |
| createtime | string | 事件发生时间（yyyy-MM-dd HH:mm:ss） |

---

### 1. gamelog_raw.log_payrecharge — 充值流水（实时，T+0）

每次玩家充值一条记录。`pay_money` 单位为人民币元。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 充值日期分区 |
| game_id | int | 312 |
| opgame_id | int | 渠道 ID |
| op_id | int | 运营商 ID |
| server_id | int | 服务器 ID |
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_name | string | 角色名 |
| role_type | int | 角色类型 |
| role_career | string | 职业 |
| role_level | int | 充值时等级 |
| role_vip | int | 充值时 VIP 等级 |
| role_regtime | string | 角色注册时间 |
| role_paid | int | 是否已付费（1=是） |
| pay_type | int | 充值类型（1=购买钻石，2=购买商品） |
| pay_orderid | string | 订单号 |
| pay_discount | string | 折扣率 |
| pay_way | string | 支付方式 |
| pay_itemid | string | 购买商品 ID |
| pay_money | double | 充值金额（元） |
| pay_currency | string | 货币类型 |
| pay_diamond | int | 购得钻石数 |
| diamond | int | 充值后绑定钻石余额 |
| blackdiamond | int | 充值后非绑钻石余额 |
| money | bigint | 充值后金币余额 |
| createtime | string | 充值时间 |

---

### 2. gamelog_raw.log_rolelogin — 角色登录（实时，T+0）

每次角色登录一条记录。适合查当日 DAU。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 登录日期分区 |
| game_id | int | 312 |
| opgame_id | int | 渠道 ID |
| op_id | int | 运营商 ID |
| server_id | int | 服务器 ID |
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_name | string | 角色名 |
| role_type | int | 角色类型 |
| role_career | string | 职业 |
| role_level | int | 登录时等级 |
| role_vip | int | VIP 等级 |
| role_unionid | bigint | 公会 ID |
| role_regtime | string | 角色注册时间 |
| role_paid | int | 是否付费（1=是） |
| role_exp | bigint | 经验值 |
| role_energy | int | 体力 |
| diamond | int | 绑定钻石 |
| blackdiamond | int | 非绑钻石 |
| money | bigint | 金币 |
| client_ip | string | 客户端 IP |
| device | string | 设备信息 |
| createtime | string | 登录时间 |

---

### 3. gamelog_odl.log_rolelogin — 角色登录（T+1，昨日可用）

字段与 gamelog_raw.log_rolelogin 相同，数据延迟一天，适合跑历史报表。

---

### 4. gamelog_raw.log_accountlogin — 账号登录（实时，T+0）

账号级别的登录记录（区别于角色登录）。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 日期分区 |
| game_id | int | 312 |
| account | string | 账号 |
| role_id | string | 角色 ID |
| server_id | int | 服务器 ID |
| client_ip | string | IP |
| createtime | string | 登录时间 |

---

### 5. pri_36ji_m.snap_rolecache — 角色快照（T+1，每日末状态）

每日每个在线角色一条快照，反映当天最新状态。查角色基础信息、注册日、战力等用此表。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 快照日期 |
| game_id | int | 312 |
| opgame_id | string | 渠道 ID（字符串类型） |
| op_id | int | 运营商 ID |
| role_id | string | 角色 ID |
| role_name | string | 角色名 |
| role_level | int | 等级 |
| role_vip | int | VIP 等级 |
| role_power | bigint | 战力 |
| role_type | int | 角色类型 |
| total_pay_money | double | 累计充值金额（元） |
| account_regtime | string | 账号注册时间（yyyy-MM-dd HH:mm:ss） |
| last_logout | string | 最后下线时间 |
| client_ip | string | 最后登录 IP |
| param10 | string | 扩展字段10 |

> 查最新快照：用 `row_number() OVER (PARTITION BY role_id ORDER BY ds DESC)` 取 rank=1，或直接指定最新 ds。

---

### 6. pri_36ji_m.snap_packcache — 道具背包快照（T+1）

每日每个角色持有道具的快照，每种道具一行。注意此表没有 opgame_id 列。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 快照日期 |
| game_id | int | 312 |
| role_id | string | 角色 ID |
| role_level | int | 角色等级 |
| role_vip | int | VIP 等级 |
| name | string | 道具名称 |
| number | int | 持有数量 |

---

### 7. pri_36ji_m.snap_dimcache — 维度快照（T+1）

神将、坐骑、宝物、宝石、兵符等养成维度的快照，通过 `log_type` 区分类型。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 快照日期 |
| game_id | int | 312 |
| op_id | int | 运营商 ID |
| role_id | string | 角色 ID |
| hero_id | string | 神将/坐骑 ID |
| log_type | string | 快照类型（如 '宿命和兵阶快照'、'武将宝物快照'、'坐骑快照'、'宝物宝石快照'、'兵符快照'） |
| param1~param9 | string | 扩展参数，含义随 log_type 而变 |

---

### 8. pri_36ji_m.log_roleres — 资源产销流水（T+1）

玩家货币类资源（点券、金币等）的每次增减记录。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 日期分区 |
| game_id | int | 312 |
| op_id | int | 运营商 ID |
| role_id | string | 角色 ID |
| role_name | string | 角色名 |
| res_id | string | 资源 ID |
| res_name | string | 资源名称（如 '点券'、'金币'） |
| change_type | string | '产出' 或 '消耗' |
| change_amount | double | 变动数量（绝对值） |
| change_reason | string | 变动原因（具体来源/消耗途径） |
| createtime_local | string | 发生时间 |
| param3 | string | 扩展字段3 |
| param4 | string | 扩展字段4 |
| param5 | string | 扩展字段5 |

---

### 9. pri_36ji_m.log_roleitem — 道具产销流水（T+1）

玩家道具的每次增减记录。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 日期分区 |
| game_id | int | 312 |
| op_id | int | 运营商 ID |
| role_id | string | 角色 ID |
| item_id | string | 道具 ID |
| item_name | string | 道具名称 |
| change_type | string | '产出' 或 '消耗' |
| change_reason | string | 变动原因（如 '五行宝盒抽奖'、'心愿单抽'） |
| change_module | string | 功能模块 |
| status_before | bigint | 变动前数量 |
| status_after | bigint | 变动后数量 |

---

### 10. pri_36ji_m.log_rolebehavior — 行为日志（T+1）

玩家行为事件日志，覆盖战斗、活动、关卡、PVP 等各类行为，通过 `b_type`+`b_id` 区分类别。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 日期分区 |
| game_id | int | 312 |
| opgame_id | string | 渠道 ID |
| op_id | int | 运营商 ID |
| server_id | int | 服务器 ID |
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_name | string | 角色名 |
| role_type | int | 角色类型 |
| role_career | string | 职业 |
| role_level | int | 等级 |
| role_vip | int | VIP 等级 |
| role_regtime | string | 注册时间 |
| role_paid | int | 是否付费 |
| b_type | int | 行为大类 ID |
| b_id | int | 行为小类 ID（活动类型、关卡 ID 等） |
| zone_id | int | 场景/地图 ID |
| zone_instance_id | int | 场景实例 ID |
| b_value | string | 行为附加值（竖线分隔多个参数） |
| createtime | string | 发生时间 |

---

## 示例 SQL

### 查昨日 DAU
```sql
SELECT COUNT(DISTINCT role_id) AS dau
FROM gamelog_raw.log_rolelogin
WHERE game_id = 312
AND ds = '<昨天ds>'
```

### 查昨日充值总额和付费人数
```sql
SELECT
  COUNT(DISTINCT role_id) AS payers,
  CAST(SUM(CAST(pay_money AS DOUBLE)) AS DECIMAL(18,2)) AS revenue
FROM gamelog_raw.log_payrecharge
WHERE game_id = 312
AND ds = '<昨天ds>'
```

### 查近 7 日每日 DAU 趋势
```sql
SELECT ds, COUNT(DISTINCT role_id) AS dau
FROM gamelog_raw.log_rolelogin
WHERE game_id = 312
AND ds >= '<7天前ds>'
AND ds <= '<昨天ds>'
GROUP BY ds
ORDER BY ds
```

### 查近 7 日每日收入和付费人数
```sql
SELECT
  ds,
  CAST(SUM(CAST(pay_money AS DOUBLE)) AS DECIMAL(18,2)) AS revenue,
  COUNT(DISTINCT role_id) AS payers
FROM gamelog_raw.log_payrecharge
WHERE game_id = 312
AND ds >= '<7天前ds>'
GROUP BY ds
ORDER BY ds
```

### 查最新角色快照（战力 TOP 20）
```sql
SELECT role_id, role_name, role_level, role_vip, role_power, total_pay_money
FROM (
  SELECT *, row_number() OVER (PARTITION BY role_id ORDER BY ds DESC) AS rn
  FROM pri_36ji_m.snap_rolecache
  WHERE game_id = 312
  AND ds >= '<7天前ds>'
)
WHERE rn = 1
ORDER BY role_power DESC
LIMIT 20
```

### 查昨日新增角色数（注册日 = 昨天）
```sql
SELECT COUNT(DISTINCT role_id) AS new_roles
FROM gamelog_raw.log_rolelogin
WHERE game_id = 312
AND ds = '<昨天ds>'
AND role_regtime LIKE '<昨天ds>%'
```

### 查某道具昨日消耗排行
```sql
SELECT role_id, role_name,
  SUM(status_before - status_after) AS consumed
FROM pri_36ji_m.log_roleitem
WHERE game_id = 312
AND ds = '<昨天ds>'
AND item_name = '体力药水'
AND change_type = '消耗'
GROUP BY role_id, role_name
ORDER BY consumed DESC
LIMIT 50
```

### 查点券消耗来源分布（昨日）
```sql
SELECT change_reason, SUM(ABS(change_amount)) AS total
FROM pri_36ji_m.log_roleres
WHERE game_id = 312
AND ds = '<昨天ds>'
AND res_name = '点券'
AND change_type = '消耗'
GROUP BY change_reason
ORDER BY total DESC
```

### 查各渠道昨日 DAU
```sql
SELECT opgame_id, COUNT(DISTINCT role_id) AS dau
FROM gamelog_raw.log_rolelogin
WHERE game_id = 312
AND ds = '<昨天ds>'
GROUP BY opgame_id
ORDER BY dau DESC
```

### 查昨日行为日志各类型触发次数
```sql
SELECT b_type, b_id, COUNT(*) AS total_events, COUNT(DISTINCT role_id) AS players
FROM pri_36ji_m.log_rolebehavior
WHERE game_id = 312
AND ds = '<昨天ds>'
GROUP BY b_type, b_id
ORDER BY total_events DESC
LIMIT 30
```

### 查VIP等级分布（最新快照）
```sql
SELECT role_vip, COUNT(DISTINCT role_id) AS cnt
FROM pri_36ji_m.snap_rolecache
WHERE game_id = 312
AND ds = '<昨天ds>'
GROUP BY role_vip
ORDER BY role_vip
```

---

## 固定报表口径

### KPI 日报

| 指标 | 来源表 | 口径 |
|---|---|---|
| DAU（日活） | gamelog_raw.log_rolelogin | COUNT(DISTINCT role_id)，ds=当日 |
| 新增账号 | 本地 account_cache（来源：log_rolelogin min(ds)） | 当日首次出现的 role_id 数 |
| 付费人数 | gamelog_raw.log_payrecharge | COUNT(DISTINCT role_id)，ds=当日 |
| 收入（元） | gamelog_raw.log_payrecharge | SUM(CAST(pay_money AS DOUBLE))，ds=当日 |

> 实时表可查今天的实时数据（ds=今天）；T+1 表（pri_36ji_m）只有昨天及之前的数据。

### LTV 报表

按注册日分群（account_cache 记录每个 role_id 在 log_rolelogin 中的 MIN(ds)），计算各群体累计充值：

- LTV1 = 注册当天（day 0）累计充值 ÷ 当天新增人数
- LTV3 = 注册后前 3 天（day 0~2）累计充值 ÷ 当天新增人数
- LTV7 / LTV15 / LTV30 同理

充值数据来自 `gamelog_raw.log_payrecharge`，通过 `role_id` 关联注册日分群。
