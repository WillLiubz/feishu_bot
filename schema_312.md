## 表结构

> 游戏：女3_ProGoddessIII，game_id = 312
> 数据来源：`C:\YZ_SVN\女3_ProGoddessIII\branches\server\src\aegit.com\ae\plugin_uzdatacenter\` 和 `plugin_uzdatacenter2017\`

---

### 数仓架构概览

服务端使用两套推送体系，对应不同数仓位置：

| 体系 | Go 包 | Presto 数据库 | 延迟 | 说明 |
|---|---|---|---|---|
| KPI（默认 RAW） | `plugin_uzdatacenter` / `plugin_uzdatacenter2017/kpi` | `gamelog_raw` | 实时 T+0 | 登录/充值/升级等关键事件；**默认所有查询使用此库** |
| KPI（T+1，仅显式请求） | 同上，入仓延迟 | `gamelog_odl` | T+1 | 同 gamelog_raw 的归档版本；**仅当用户要求 `-- use_odl` 时使用** |
| ECO 快照 | `plugin_uzdatacenter2017/eco` | `gameeco_raw` | 实时 / T+0 | 角色/道具/维度快照 |
| ECO 流水（默认 RAW） | `plugin_uzdatacenter2017/eco` | `gameeco_raw` | 实时 T+0 | 道具/资源/行为等产销流水；**默认所有查询使用此库** |
| ECO 流水（T+1，仅显式请求） | `plugin_uzdatacenter2017/eco` | `gameeco_odl` | T+1 | 同 gameeco_raw 的归档版本；**仅当用户要求 `-- use_odl` 时使用** |

**默认选库规则**：所有 KPI / ECO 查询**默认使用 RAW 库**（`gamelog_raw` / `gameeco_raw`），不按日期自动切换。只有当用户明确要求 T+1 / ODL 时，才在 SQL 开头单独一行加 `-- use_odl` 使用 ODL 库（`gamelog_odl` / `gameeco_odl`）。

**表名规则**：`{库}.v_presto_{snap|log}_{小写表名}`
例：`gameeco_raw.v_presto_snap_rolecache`、`gamelog_raw.v_presto_log_rolelogin`

**重要**：`game_id` 在 ECO 表里为 **字符串** `'312'`，在 KPI 表里为 **整数** `312`，写 SQL 需注意。

**重要**：ECO 表（gameeco_raw/odl）的 `role_id` 为 **VARCHAR 字符串**，不是数字。按 role_id 过滤时直接写 `role_id = '123456'`（字面量加引号），不能写 `role_id = 123456`（整数比较会全表扫描，极慢），也不需要 `CAST(role_id AS VARCHAR)`（列本身就是 VARCHAR，包 CAST 只会阻断谓词下推）。

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

> **⚠ 性能警告（2026-07 实测）**：Presto 中字面量类型必须与列类型**精确匹配**，跨类型比较（varchar 列 vs 数字字面量，或 int 列 vs 字符串字面量）都会触发整列隐式 CAST、阻断谓词下推，单天查询也会超过 6 分钟超时（修正后月级扫描仅 ~5 秒）。实测各列真实类型（与本文档表格中的标注可能不一致，以实测为准）：
>
> | 列 | gamelog_raw | gameeco_raw |
> |---|---|---|
> | `server_id` | **VARCHAR**（必须加引号 `'1448311610'`） | **VARCHAR**（必须加引号） |
> | `game_id` | int（`312`） | VARCHAR（`'312'`） |
> | `role_type` | int（`role_type = 1`，**不可**加引号） | int（不可加引号） |
> | `res_id` / `change_type`（roleres） | — | **VARCHAR**（必须加引号 `'2'`） |
> | `pay_type`（payrecharge） | VARCHAR（值恒为 `'1'`，见 payrecharge 表字段说明） | — |
>
> **⚠ `rolereg.role_id` 为空字符串**：`v_presto_log_rolereg` 的 `role_id` 字段实测为空，统计注册人数请用 `COUNT(DISTINCT account)`。
>
> **⚠ `payrecharge.pay_money` 币种为 USD**：本文档此前标注"人民币元"，实测 `pay_currency` 全部为 `USD`，金额应按美元解读。
>
> **⚠ 数值字段建议 `TRY_CAST` + `COALESCE`**（如 `SUM(COALESCE(TRY_CAST(pay_money AS DOUBLE), 0))`），直接 `CAST` 遇脏数据会导致整查询失败。

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
| role_id | string | 角色 ID（全服唯一，VARCHAR；过滤时字面量必须加引号） |
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

每笔充值一条。`pay_money` 单位为**美元**（2026-07 实测 `pay_currency` 全部为 `USD`；此前标注"人民币元"有误）。

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
| pay_type | int | 充值类型。**实测恒为 1**（源码 `game_log.go` 的 `Log_payRecharge` 硬编码 `pay_type = 1`），文档标注的 1=购买钻石/2=购买商品并不生效，**不要用 `pay_type = '2'` 查直购**（结果恒为 0） |
| pay_orderid | string | 订单号 |
| pay_discount | float | 折扣率 |
| pay_way | int | 支付方式 |
| pay_itemid | string | 充值/直购标识：**普通充值 = `'0'`；直购 = `'activityId:giftId'`**（如 `'14:501001'` 为新手直购商品 501001）。activityId 枚举见源码 `const.pb.go` `DIRECT_PURCHASE_ACT_ID`（6=商店-自动、7=商店-普通、8=商店-节日、9=天使通行证、13=新月卡、14=新手直购、15=女神市场、19=自选礼包、20=代金券商店、34=女神新市场等）。查直购用 `strpos(pay_itemid, ':') > 0`，拆分用 `split_part(pay_itemid, ':', 1/2)` |
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

> 仅当用户明确要求 T+1 / ODL，并在 SQL 开头加 `-- use_odl` 时使用。默认查询使用 `gamelog_raw`。

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

每日每个角色的背包道具快照，背包按 pack1~pack5 JSON 字符串存储。适合分析全量背包、特定道具持有情况。

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
| pack1 | string | 主背包（限量道具），JSON：`{"实例ID":"数量,模板ID", ...}` |
| pack2 | string | 非限量背包，JSON：`{"实例ID":{"num":数量,"templateId":模板ID}, ...}` |
| pack3 | string | 符文背包，格式同 pack2 |
| pack4 | string | 扩展背包4，格式同 pack2 |
| pack5 | string | 扩展背包5，格式同 pack2 |

> **pack 字段 JSON 格式说明**  
> key = 道具**实例 ID**（每个道具唯一，堆叠道具共享一个实例ID）  
> pack1 value = `"数量,模板ID"`（逗号分隔字符串）  
> pack2~5 value = `{"num": 数量, "templateId": 模板ID}`  
> 模板 ID（templateId）= 道具配置表 ID，同类道具相同，可用于统计持有率。

**查道具持有率推荐用 `snap_itemcache`（更简洁），packcache 适合需要完整背包列表的场景。**

---

### gameeco_raw.v_presto_snap_itemcache — 道具快照 ★（推荐用于持有率分析）

每日每个角色持有的每种道具一条，是**查道具拥有率的最直接表**。

| 字段 | 类型 | 说明 |
|---|---|---|
| game_id | int | 312 |
| server_id / opgame_id / op_id | int | 服务器/渠道/运营商 |
| cache_day | string | 快照日期 yyyyMMdd |
| account | string | 账号 |
| role_id | bigint | 角色 ID |
| item_id | int | 道具模板 ID（同类道具相同） |
| item_name | string | 道具名称 |
| item_num | bigint | 持有数量 |

> **注意**：`snap_itemcache` 的 `game_id` 为**整数** 312，不是字符串。

#### 道具拥有率示例 SQL

**查昨日指定道具的拥有率（按活跃玩家为分母）**
```sql
WITH dau AS (
  SELECT COUNT(DISTINCT role_id) AS total
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = 312 AND ds = '<昨天ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
),
holders AS (
  SELECT COUNT(DISTINCT role_id) AS cnt
  FROM gameeco_raw.v_presto_snap_itemcache
  WHERE game_id = 312 AND cache_day = '<昨天ds>'
  AND item_name = '<道具名称>'
  AND item_num > 0
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
)
SELECT
  holders.cnt AS 持有人数,
  dau.total AS 活跃人数,
  ROUND(CAST(holders.cnt AS DOUBLE) / dau.total * 100, 2) AS 拥有率
FROM holders, dau
```

**查昨日多个道具的拥有率排行**
```sql
WITH dau AS (
  SELECT COUNT(DISTINCT role_id) AS total
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = 312 AND ds = '<昨天ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
),
items AS (
  SELECT item_name, item_id,
    COUNT(DISTINCT role_id) AS holders,
    SUM(item_num) AS total_num
  FROM gameeco_raw.v_presto_snap_itemcache
  WHERE game_id = 312 AND cache_day = '<昨天ds>'
  AND item_num > 0
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
  GROUP BY item_name, item_id
)
SELECT
  item_name, item_id, holders, total_num,
  ROUND(CAST(holders AS DOUBLE) / dau.total * 100, 2) AS 拥有率
FROM items, dau
ORDER BY 拥有率 DESC
LIMIT 50
```

---

### gameeco_raw.v_presto_snap_dimcache — 养成维度快照 ★（推荐用于饱和度分析）

每日每个角色的每个养成维度一条，通过 `dim_type` 区分系统，`sub_dim_1~10` 记录各系统的养成等级。**是分析养成饱和度的核心表。**

| 字段 | 类型 | 说明 |
|---|---|---|
| ds / cache_day | string | 日期 |
| game_id | string | '312' |
| role_id | bigint | 角色 ID |
| server_id / op_id | int | 服务器/运营商 |
| dim_type | int | 养成系统类型（见下方枚举） |
| dim_id | bigint | 维度对象 ID（含义随 dim_type 变化） |
| dim_name | string | 维度对象名称 |
| dim_item_id | bigint | 关联道具/模板 ID |
| sub_dim_1~sub_dim_10 | string | 养成子属性（含义随 dim_type 变化，见下表） |
| extra_1~extra_9 | string | 额外扩展参数 |

#### dim_type 枚举值

| dim_type | 系统名称 |
|---|---|
| 1 | 英雄（Hero） |
| 2 | 装备（Equip） |
| 3 | 宝物（Baowu） |
| 4 | 坐骑（Horse） |
| 5 | 翅膀（Wing） |
| 6 | 神将（Goddess） |
| 7 | 符文（Runes） |
| 8 | 符文孔位（Runes Position） |
| 9 | 神武（Shenwu） |
| 10 | 时装（Fashion） |
| 11 | 宝物部件（Baowu Part） |
| 12 | 宠物（Pet） |
| 13 | 英雄皮肤（Hero Skin） |
| 15 | 护符（Talisman） |
| 16 | 护符图鉴（Talisman Illustration） |
| 17 | 翅膀酒馆（Wing Tavern） |
| 18 | 坐骑酒馆（Horse Tavern） |
| 19 | 翅膀/坐骑羽化（Yuhua） |
| 20 | 宝石（Baoshi） |
| 21 | 宠物炼金（Pet LJ） |
| 22 | 灵装（Spirit Equipment） |
| 23 | 灵装图鉴（Spirit Equipment Illustration） |
| 24 | 星阁（Star Pavilion） |
| 25 | 星纹（Star Emblem） |
| 26 | 混沌维度（Chaos Dim） |
| 27 | 称号（Title） |
| 28 | 变装（Disguise） |
| 29 | 龙珠（Dragonball） |
| 30 | 超神（Supergod） |
| 32 | 灵核（Spirit Core） |
| 33 | 灵核图鉴（Spirit Core Book） |
| 34 | 超神装备（Supergod Equip） |
| 35 | 兽魂（Beast Soul） |

#### 各 dim_type 的 sub_dim 字段含义

**dim_type = 1（英雄）**
- dim_id：编队位置
- dim_item_id：英雄模板 ID
- sub_dim_1：战力
- sub_dim_2：等级
- sub_dim_3：突破等级
- sub_dim_4：进阶等级
- sub_dim_5：进阶经验
- sub_dim_6：觉醒等级
- sub_dim_7：主动技能 ID
- sub_dim_8：被动技能1 ID
- sub_dim_9：被动技能2 ID
- sub_dim_10：`星级:星点`（冒号分隔）
- extra_1：起始星级
- extra_2：已装备皮肤 ID
- extra_3：助战位置
- extra_4：晋升等级
- extra_5：涅槃等级（主角专用）
- extra_6：灵魂/灵神 ID
- extra_7：灵魂/灵神等级

**dim_type = 2（装备）**
- dim_id：装备所属英雄 ID
- dim_item_id：装备模板 ID
- sub_dim_1：战力
- sub_dim_2：强化等级
- sub_dim_3：淬炼等级
- sub_dim_4：升星等级
- sub_dim_6：宝石镶嵌 `孔位:道具ID;孔位:道具ID`
- sub_dim_9：破碎等级
- sub_dim_10：吞噬等级
- extra_1：破碎点
- extra_2：锻造等级
- extra_3：是否彩金装备（1=是）
- extra_7：是否灭世装备（1=是）
- extra_8：混沌等级
- extra_9：混沌点

**dim_type = 3（宝物）**
- dim_id：是否当前装备（1=装备中，0=未装备）
- dim_item_id：宝物模板 ID
- sub_dim_2：进阶等级
- sub_dim_6：星级
- sub_dim_7：星级酒馆等级

**dim_type = 4（坐骑）**
- dim_id：是否当前装备（1=装备中）
- dim_item_id：坐骑模板 ID
- sub_dim_2：进阶等级
- sub_dim_3：进阶经验
- sub_dim_4：是否永久（1=永久，0=临时）

**dim_type = 5（翅膀）**
- dim_id：是否当前装备（1=装备中）
- dim_item_id：翅膀模板 ID
- sub_dim_2：进阶等级
- sub_dim_3：进阶经验
- sub_dim_4：是否永久（1=永久，0=临时）

**dim_type = 7（符文）**
- dim_id：装备此符文的英雄 ID
- dim_item_id：符文模板 ID
- sub_dim_1：符文类型（1=普通，2=光耀）

**dim_type = 8（符文孔位强化）**
- dim_id：英雄实例 ID
- sub_dim_1~5：5个孔位各自的强化等级

**dim_type = 9（神武）**
- dim_id：是否当前使用（1=使用中）
- dim_item_id：神武模板 ID
- sub_dim_1：战力
- sub_dim_2：等级
- sub_dim_3：突破等级
- sub_dim_4~6：技能1~3
- sub_dim_7：是否宿命神武（1=是）
- sub_dim_8：超越等级
- sub_dim_9：神武位置编号
- sub_dim_10：超越点

**dim_type = 32（灵核）**
- dim_id / dim_item_id：灵核 ID
- sub_dim_1：状态（1=已获得，2=已装备）
- sub_dim_2：状态标记
- sub_dim_3：装备位置
- sub_dim_4：等级/强度
- sub_dim_5：灵核类型

**dim_type = 35（兽魂）**
- dim_id / dim_name：兽魂品质
- dim_item_id：核心等级
- sub_dim_1：祭坛等级
- sub_dim_2：激活总等级

#### 养成饱和度示例 SQL

**查昨日英雄养成分布（等级、突破、觉醒）**
```sql
SELECT
  CAST(sub_dim_2 AS INT) AS 英雄等级,
  CAST(sub_dim_3 AS INT) AS 突破等级,
  CAST(sub_dim_6 AS INT) AS 觉醒等级,
  COUNT(DISTINCT role_id) AS 人数
FROM gameeco_raw.v_presto_snap_dimcache
WHERE game_id = '312' AND cache_day = '<昨天ds>'
AND dim_type = 1
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY sub_dim_2, sub_dim_3, sub_dim_6
ORDER BY 英雄等级 DESC, 突破等级 DESC
LIMIT 50
```

**查昨日装备强化等级分布（饱和度分析）**
```sql
SELECT
  CAST(sub_dim_2 AS INT) AS 强化等级,
  COUNT(*) AS 装备数,
  COUNT(DISTINCT role_id) AS 持有人数
FROM gameeco_raw.v_presto_snap_dimcache
WHERE game_id = '312' AND cache_day = '<昨天ds>'
AND dim_type = 2
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY sub_dim_2
ORDER BY 强化等级 DESC
LIMIT 30
```

**查昨日各养成系统参与人数（按 dim_type 汇总）**
```sql
SELECT
  dim_type,
  CASE dim_type
    WHEN 1 THEN '英雄' WHEN 2 THEN '装备' WHEN 3 THEN '宝物'
    WHEN 4 THEN '坐骑' WHEN 5 THEN '翅膀' WHEN 6 THEN '神将'
    WHEN 7 THEN '符文' WHEN 9 THEN '神武' WHEN 32 THEN '灵核'
    WHEN 35 THEN '兽魂' ELSE CAST(dim_type AS VARCHAR)
  END AS 养成系统,
  COUNT(DISTINCT role_id) AS 参与人数,
  COUNT(*) AS 记录数
FROM gameeco_raw.v_presto_snap_dimcache
WHERE game_id = '312' AND cache_day = '<昨天ds>'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY dim_type
ORDER BY 参与人数 DESC
```

**查昨日高等级英雄分布（突破满级玩家数）**
```sql
SELECT
  CAST(sub_dim_3 AS INT) AS 突破等级,
  COUNT(DISTINCT role_id) AS 玩家数,
  COUNT(*) AS 英雄数
FROM gameeco_raw.v_presto_snap_dimcache
WHERE game_id = '312' AND cache_day = '<昨天ds>'
AND dim_type = 1
AND sub_dim_3 IS NOT NULL AND sub_dim_3 != ''
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY sub_dim_3
ORDER BY 突破等级 DESC
LIMIT 20
```



---

## 四、ECO 流水表（gameeco_raw，默认）

> 默认所有 ECO 流水查询使用 `gameeco_raw`。仅当用户明确要求 T+1 / ODL，并在 SQL 开头加 `-- use_odl` 时使用 `gameeco_odl`。

### gameeco_raw.v_presto_log_rolebehavior — 玩法行为日志 ★

记录玩家各类玩法参与（战斗/副本/PVP/活动等），是分析留存、活跃度的核心表。每次玩家触发功能模块行为产生一条，`game_id = '312'`（字符串）。

在 EcoBase 基础字段之上，额外有：

| 字段 | 类型 | 说明 |
|---|---|---|
| b_type | string | 功能模块名称（见下方取值表） |
| zone | string | 场景子标识（多数为空） |
| b_id | int | 模块 ID（模块类型枚举整数） |
| zone_id | int | 场景/副本/关卡 ID |
| b_value | string | 行为具体动作（见下方取值表） |
| session_length | int | 停留时长（秒，多数为 0） |
| enemy_id | bigint | 对手角色 ID（PVP 时有效） |
| rank_before | int | 行为前排名（排行榜类行为有效） |
| rank_after | int | 行为后排名（排行榜类行为有效） |
| b_param | string | 附加参数（分号分隔，首段为日志来源 ID） |
| union_name | string | 公会名称 |
| battle_attr | string | 战斗属性（分号分隔） |
| buff_item_consume | string | 消耗的 BUFF 道具 |
| team_power | bigint | 玩家当前战力 |
| other_object | string | 其他关联对象（如强化类型） |
| customized | string | 游戏自定义扩展字段 |

---

#### b_type 取值表（功能模块，来自服务端 module.getName()）

**战斗 / 副本**

| b_type | 模块含义 |
|---|---|
| pve | 关卡/主线副本 |
| PveTeam | 组队副本（深渊等） |
| scene | 场景/地图进出 |
| battle | 战斗通用 |
| Yuanzheng | 远征 |
| MagicExplore | 魔法探索 |
| SpiritCoreGame | 灵核小游戏 |
| pvestrategy | 副本策略 |
| LingEquipmentPve | 灵装副本 |

**PVP / 竞技**

| b_type | 模块含义 |
|---|---|
| Arena | 竞技场 |
| GuildWar | 公会战 |
| GuildMobilize | 公会总动员 |
| Ladder | 阶梯赛（单服） |
| CrossLadder | 跨服阶梯赛 |
| PvpChess | 夺宝奇兵 |
| WorldPk | 世界PK |
| NewGvG | 新公会对战 |
| HolyWar | 圣战 |
| HolyGrailWar | 圣杯战 |
| MineFight | 矿战 |
| PinnaclePvp | 巅峰PVP |
| PvpSimulator | PVP模拟器 |
| Battlefield | 战场 |
| Match | 匹配对战 |

**Boss 战**

| b_type | 模块含义 |
|---|---|
| world_boss | 世界Boss（单服） |
| SupergodBoss | 超神Boss |
| WorldCrossBoss | 跨服世界Boss |

**公会 / 社团**

| b_type | 模块含义 |
|---|---|
| guild | 公会操作（加入/退出/捐献等） |
| club | 社团操作（创建/农场/祭坛等） |

**英雄 / 女神养成**

| b_type | 模块含义 |
|---|---|
| hero | 英雄系统（升级/突破/觉醒/皮肤等） |
| HeroSp | 英雄特殊操作 |
| HeroStory | 英雄传记 |
| Assistant | 英雄小助手 |
| AssistHeros | 助战英雄 |
| GoddessCollectionCard | 女神收集卡 |
| GoddessMarket | 女神市场（旧） |
| GoddessNewmarket | 女神市场（新） |
| GoddessPrivilege | 女神特权 |
| GoddessSanta | 女神圣诞活动 |
| GoddessTreasure | 女神宝库 |
| GoddessMercenary | 女神雇佣兵 |
| GoddnessArk | 女神方舟 |
| GoddnessRose | 女神玫瑰 |
| GoddnessEgg | 女神砸蛋 |

**装备 / 宝物养成**

| b_type | 模块含义 |
|---|---|
| shenwu | 神武装备 |
| Fuwen | 符文 |
| Supergod_Fuwen | 超神符文 |
| SupergodYinwen | 超神印纹 |
| SpiritEquipment | 灵装 |
| StarEmblem | 星纹 |
| StarPavilion | 星阁 |
| star | 星级系统 |
| supergodEquip | 超神装备 |
| Supergod | 超神系统 |
| baowu | 宝物系统 |
| halidom | 法宝 |
| Talisman | 护符 |
| DragonBall | 龙珠 |
| Ce | 策（策略道具） |
| wing | 翅膀 |
| horse | 坐骑 |
| SpiritCore | 灵核 |
| beast_soul | 兽魂 |
| Bright_Fuwen | 光明符文 |

**任务 / 活动**

| b_type | 模块含义 |
|---|---|
| task | 主线任务 |
| daily_task | 日常任务 |
| act_task | 活动任务 |
| WeekTask | 周任务 |
| NewTaskCycle | 新任务循环 |
| activity | 活动通用 |
| achieve | 成就 |
| Seven | 七日活动 |
| sign_data | 签到 |
| online_reward | 在线奖励 |
| OnlineExp | 在线经验 |
| levelaward | 等级奖励 |
| AngelPass | 天使通行证 |
| MiniappPass | 小游戏通行证 |
| SuperLogin | 超级登录 |
| Guide | 引导任务 |
| guide_log | 引导日志 |

**商城 / 抽卡 / 购买**

| b_type | 模块含义 |
|---|---|
| shop | 商城 |
| items | 道具操作 |
| Exchange | 兑换 |
| CreditShop | 积分商城 |
| ArenaShop | 竞技场商城 |
| MonthCard | 月卡 |
| NewMonthCard | 新月卡 |
| Fund | 基金 |
| SummonModule | 召唤 |
| FlashSummon | 限时召唤 |
| LimitedSummon | 限定召唤 |
| Gamble | 抽卡/博彩 |
| Turntable | 转盘 |
| ScratchTicket | 刮刮卡 |
| Scratcher | 刮奖机 |
| RollDice | 掷骰子 |
| Ticket | 票券 |
| TreasureHunt | 寻宝 |
| Kingtreasure | 王者宝藏 |
| CardsOfDestiny | 命运卡 |

**运营活动**

| b_type | 模块含义 |
|---|---|
| Tycoon | 大亨活动 |
| MonthRank | 月度排行 |
| MonthRebate | 月返利 |
| MonthWeal | 月福利 |
| Monthgift | 月礼包 |
| RechargeGift | 充值礼包 |
| UnionPromotion | 公会促销 |
| BuyMoreSaveMore | 买多省多 |
| BuyOneGetOneFree | 买一送一 |
| DirectPurchaseStore | 直购商城 |
| DirectVoucher | 直购凭证 |
| Countdown | 倒计时活动 |
| FestivalActivity | 节日活动 |
| FestivalBlessing | 节日祝福 |
| PlayPreheat | 预热活动 |
| Anniversary | 周年庆 |
| Celebration | 庆典 |
| Christmas | 圣诞活动 |
| Turkey | 火鸡节 |
| Pumpkin | 南瓜节 |
| Zodiac | 十二生肖 |
| NeedUp | 提升活动 |

**社交 / 其他**

| b_type | 模块含义 |
|---|---|
| friend | 好友系统 |
| title | 称号 |
| Fashion | 时装 |
| RoleHead | 头像框 |
| Theme | 主题 |
| Vip | VIP系统 |
| ranking / new_ranking | 排行榜 |
| resource_recovery | 资源回收 |
| stone_to_gold | 魔石换金 |
| bag | 背包 |
| Wenjuan | 问卷 |
| NameChange | 改名 |
| PhoneBind | 手机绑定 |
| Explore | 探索 |
| Fantasy | 幻境 |

---

#### b_value 取值表（按 b_type 分类）

**b_type = "guild"（公会操作）**

| b_value | 含义 |
|---|---|
| 创建公会 | 创建公会 |
| 加入公会 | 加入公会 |
| 退出公会 | 主动退出 |
| 解散公会 | 解散公会 |
| 踢出公会 | 踢出成员 |
| 申请加入公会 | 发送入会申请 |
| 批准加入公会 | 审批通过申请 |
| 拒绝申请加入公会 | 拒绝申请 |
| 公会捐献 | 捐献资源 |
| 公会升级 | 公会整体升级 |
| 公会建筑升级 | 建筑升级 |
| 打开公会宝箱 | 领取宝箱奖励 |
| 设置官职 | 任命/变更职位 |

**b_type = "club"（社团操作）**

| b_value | 含义 |
|---|---|
| club_create | 创建社团（b_param：社团ID;社团名;地区;信条;宠物ID;消耗） |
| club_dissolve | 解散社团 |
| club_join | 加入社团（b_param：社团ID;社团名;加入原因 1=申请 2=邀请） |
| club_leave | 离开社团（b_param：社团ID;社团名;离开原因 1=主动 2=被踢） |
| club_apply_send | 发送申请 |
| club_invite_send | 发送邀请 |
| club_appoint | 任命职位 |
| club_donate | 社团捐献 |
| club_red_packet_send | 发红包 |
| club_red_packet_claim | 领红包 |
| club_prosperity_reward | 繁荣度奖励 |
| club_pet_change | 更换社团宠物 |
| club_pet_feed | 喂养社团宠物（b_param：社团ID;社团名;宠物ID;消耗;获得;前繁荣;新繁荣;宠物经验;前等级信息;新等级信息） |
| club_notice_edit | 修改公告 |
| club_belief_edit | 修改信条 |
| club_altar_upgrade | 祭坛升级 |
| club_altar_refresh | 祭坛刷新 |
| club_personal_tech_upgrade_start | 个人科技开始升级 |
| club_personal_tech_upgrade_done | 个人科技升级完成 |
| club_personal_tech_accelerate | 个人科技加速 |
| club_club_tech_upgrade_start | 社团科技开始升级 |
| club_club_tech_upgrade_done | 社团科技升级完成 |
| club_club_tech_accelerate | 社团科技加速 |
| club_mine_tool_cost | 矿场消耗工具 |
| club_mine_depth_reward | 矿场深度奖励 |
| club_farm_plant | 农场种植 |
| club_farm_fertilize | 农场施肥 |
| club_farm_harvest | 农场收获 |
| club_farm_level_up | 农场升级 |
| club_farm_steal_start | 开始偷菜 |
| club_farm_steal_settle | 偷菜结算 |
| club_farm_steal_evict | 驱逐偷菜者 |
| club_welfare_claim | 领取社团福利 |

**b_type = "Arena"（竞技场）**

| b_value | 含义 |
|---|---|
| 竞技场挑战 | 玩家发起挑战 |
| 竞技场小助手挑战 | 小助手代打 |

> `rank_before`/`rank_after` 记录战前战后排名；`enemy_id` 记录对手角色 ID；`team_power` 记录当前战力。

**b_type = "world_boss" / "SupergodBoss" / "WorldCrossBoss"（Boss战）**

> `enemy_id` 有效（Boss 对象 ID）；`b_param` 含 GLOG_SOURCE + 伤害值 + 排名 + 积分等。

**b_type = "pve" / "PveTeam"（副本）**

> `zone_id` 记录副本/关卡 ID；`b_id` 记录副本模块 ID。

---

#### b_param 字段格式

由服务端 `GenExtraLogParam()` 生成，格式为**分号分隔字符串**：

```
{glog_source_id};{param1};{param2};...
```

第一段 `glog_source_id` 为日志来源枚举整数，常见值：

| glog_source_id | 含义 |
|---|---|
| 1 | 无（默认） |
| 100000 | 英雄突破 |
| 100001 | 英雄培养 |
| 100002 | 英雄觉醒 |
| 100007 | 英雄升级 |
| 101601 | 公会捐献 |
| 101604 | 公会建筑升级 |
| 101606 | 创建公会 |
| 101607 | 离开公会 |
| 103306 | 世界Boss |
| 103308 | Boss战结束 |
| 108036 | 跨服阶梯排名战 |
| 108037 | 跨服阶梯升级 |

---

### gameeco_raw.v_presto_log_roleitem — 道具产销流水

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

> **实测补充（2026-07-24，pay_activity 探针确认）**：
> - `change_type` 为 **varchar**：`'1'`=产出 / `'2'`=消耗，过滤必须加引号。
> - `status_before` / `status_after` 为 **varchar**：聚合必须显式 `CAST(... AS BIGINT)`（隐式算术在 1600 万行/天上超 6 分钟跑不完，显式 CAST 约 5 秒）。单日变动量 = `SUM(ABS(CAST(status_after AS BIGINT) - CAST(status_before AS BIGINT)))`。
> - `game_id` / `role_id` 为 varchar。

---

### gameeco_raw.v_presto_log_roleres — 资源产销流水

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

### gameeco_raw.v_presto_log_rolevip — VIP 升级日志

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

### gameeco_raw.v_presto_log_roletask — 任务完成日志

| 额外字段 | 类型 | 说明 |
|---|---|---|
| task_type | int | 任务类型 ID |
| task_name | string | 任务名称 |
| task_id | int | 任务 ID |
| pre_task_id | int | 前置任务 ID |
| status | int | 状态 |

---

### gameeco_raw.v_presto_log_roleshop — 商店购买日志

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

### gameeco_raw.v_presto_log_rolepromo — 活动参与日志

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

> **实测补充（2026-07-24，pay_activity 探针+源码确认）**：
> - `item_spend` / `item_get` 恒为空：唯一调用点 `module_activity.go:2293` 硬编码传 `""`；2026-07 全月 170 万+ 行无一非空。**不要用这两个字段统计消耗/产出**（道具产销走 `v_presto_log_roleitem`）。
> - `activity_special` / `activity_pay` 同处硬编码 `1` / `0`，不能作为精彩/付费活动标记。
> - `activity_topic` 为多语言 JSON 字符串，中文名用 `json_extract_scalar(activity_topic, '$.cn')` 提取（示例："女神通行证升级福利"、"买一送一送豪礼"、"大亨积分奖励"、"王的财宝限定礼包"、"女神新集市购买礼包"）。
> - `game_id` / `role_id` 为 varchar；`role_type` 为 integer（过滤真实玩家加 `role_type = 1`）。
> - 该表记录的是"领取活动奖励"事件（`handle_ActivityFinish`）。

---

### gameeco_raw.v_presto_log_rolegold — 黄金/钻石消耗分摊日志

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

### gameeco_raw.v_presto_log_unionaction — 公会行为日志

| 额外字段 | 类型 | 说明 |
|---|---|---|
| role_unionid | bigint | 公会 ID |
| union_name | string | 公会名 |
| union_level | int | 公会等级 |
| union_size | int | 公会成员数 |
| action_type | string | 行为类型 |
| action_object | bigint | 行为对象 ID |

---

### gameeco_raw.v_presto_log_unionres — 公会资源流水

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
FROM gamelog_raw.v_presto_log_rolelogin
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
FROM gamelog_raw.v_presto_log_payrecharge
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
FROM gamelog_raw.v_presto_log_rolereg
WHERE game_id = 312
AND ds = '<昨天ds>'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
```

### 查各渠道昨日 DAU
```sql
SELECT opgame_id, COUNT(DISTINCT role_id) AS dau
FROM gamelog_raw.v_presto_log_rolelogin
WHERE game_id = 312
AND ds = '<昨天ds>'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY opgame_id
ORDER BY dau DESC
```

### 查昨日各玩法参与人数（行为日志）
```sql
SELECT b_type, b_id, COUNT(DISTINCT role_id) AS players, COUNT(*) AS events
FROM gameeco_raw.v_presto_log_rolebehavior
WHERE game_id = '312'
AND ds = '<昨天ds>'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY b_type, b_id
ORDER BY events DESC
LIMIT 30
```

### 查昨日竞技场参与人数及挑战次数
```sql
SELECT
  COUNT(DISTINCT role_id) AS players,
  COUNT(*) AS battles
FROM gameeco_raw.v_presto_log_rolebehavior
WHERE game_id = '312'
AND ds = '<昨天ds>'
AND b_type = 'Arena'
AND b_value = '竞技场挑战'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
```

### 查昨日公会行为分布
```sql
SELECT b_value, COUNT(DISTINCT role_id) AS players, COUNT(*) AS events
FROM gameeco_raw.v_presto_log_rolebehavior
WHERE game_id = '312'
AND ds = '<昨天ds>'
AND b_type = 'guild'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY b_value
ORDER BY events DESC
```

### 查昨日社团操作明细
```sql
SELECT b_value, COUNT(DISTINCT role_id) AS players, COUNT(*) AS events
FROM gameeco_raw.v_presto_log_rolebehavior
WHERE game_id = '312'
AND ds = '<昨天ds>'
AND b_type = 'club'
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY b_value
ORDER BY events DESC
```

### 查昨日副本（pve/PveTeam）参与情况
```sql
SELECT b_type, zone_id, COUNT(DISTINCT role_id) AS players, COUNT(*) AS events
FROM gameeco_raw.v_presto_log_rolebehavior
WHERE game_id = '312'
AND ds = '<昨天ds>'
AND b_type IN ('pve', 'PveTeam')
AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY b_type, zone_id
ORDER BY events DESC
LIMIT 30
```

### 查某玩家近7天行为轨迹
```sql
SELECT ds, b_type, b_value, b_id, zone_id, rank_before, rank_after, team_power, createtime_local
FROM gameeco_raw.v_presto_log_rolebehavior
WHERE game_id = '312'
AND ds >= '<7天前ds>'
AND role_id = '<角色ID>'
ORDER BY createtime_local
LIMIT 200
```

### 查昨日资源消耗来源
```sql
SELECT res_name, change_reason, SUM(change_amount) AS total
FROM gameeco_raw.v_presto_log_roleres
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
FROM gameeco_raw.v_presto_log_roleitem
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

> 默认所有查询使用 `gamelog_raw`，不按日期切换。只有用户明确要求 T+1 / ODL 时，才在 SQL 开头加 `-- use_odl` 使用 `gamelog_odl`。

### LTV 报表

按角色注册日（account_cache 中的 MIN(ds)）分群：

- LTV1 = 注册当天（day 0）累计充值 ÷ 当天新增人数
- LTV3 = 注册后前 3 天（day 0~2）累计充值 ÷ 当天新增人数
- LTV7 / LTV15 / LTV30 同理

充值数据来自 `gamelog_raw.v_presto_log_payrecharge`（game_id=312），通过 role_id 关联注册日分群。
# 玩家分群行为分析模板

模板文件：`app/templates/player_segment.json`

## 分群口径

| 群体 | 定义 |
|---|---|
| 付费玩家 | 分析窗口内有过真实货币充值（`gamelog_raw.v_presto_log_payrecharge`） |
| 沉默玩家 | 分析窗口前 30 天内曾真实货币充值，但窗口内未充值 |
| 免费玩家 | 分析窗口内活跃，且分析窗口 + 沉默窗口内均无真实货币充值 |

- 分析窗口默认：近 7 天（用户可在提问时覆盖，如“近14天”“上周”“2026-07-01~2026-07-07”）。
- 沉默窗口默认：30 天。
- Top 明细默认：每群 100 人。

> 注：为避免快照表拉低性能，312 模板使用 `gamelog_raw.v_presto_log_rolelogin` 最新记录获取等级/VIP，分群口径直接通过 `payrecharge` 推导，不再依赖 `gameeco_raw.v_presto_snap_rolecache`。

## 飞书触发词

`玩家分群`、`付费点分析`、`沉默分析`、`免费玩家行为`、`玩家行为分析`

## 输出 Sheet

1. **概览**：三群人数、付费金额、付费渗透率、ARPU、ARPPU。
2. **付费玩家付费点**：按 `pay_itemid` + `pay_type` 汇总充值金额、次数、客单价。
3. **付费玩家玩法参与**：基于 `gamelog_raw.v_presto_log_bhbehavior`，对比付费玩家与全量活跃玩家的 `b_type` 玩法参与率。
4. **沉默玩家现状**：沉默玩家在分析窗口内的 `b_type` 玩法参与、沉默窗付费。
5. **免费玩家行为**：免费玩家的 `b_type` 玩法参与、平均活跃天数、等级/VIP 分布。
6. **Top 明细**：付费 Top、沉默 Top、免费活跃 Top 名单。

## 主要表

- `gamelog_raw.v_presto_log_rolelogin` — 活跃玩家、等级/VIP
- `gamelog_raw.v_presto_log_payrecharge` — 真实货币充值
- `gamelog_raw.v_presto_log_bhbehavior` — 玩法参与（`b_type`）

> SQL 内部使用英文列别名（如 `pay_amount`、`user_count`），输出 Excel 通过 `columns` 映射显示中文表头。
> 为提升查询性能，等级/VIP 通过 `max_by(column, ds)` 从 `rolelogin` 获取，不再使用窗口函数。

## 示例

输入：

```
312 玩家分群 近7天
```

输出：多 Sheet Excel，包含上述 6 个 Sheet。
