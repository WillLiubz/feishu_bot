## 表结构

> 游戏：女2_手游_M_00010，game_id = 255
> 数据来源：`C:\YZ_SVN\女2_手游_M_00010\server\src\server\core\` 和 `src\lib\youzu\dts\`

---

### 数仓架构概览

游戏 255 服务端同时产出 **两套日志体系**，对应不同的数仓库：

| 体系 | 后端实现 | 典型 Presto 数据库 | 延迟 | 说明 |
|---|---|---|---|---|
| Scribe 实时 KPI 日志 | `server/core/base_scribe.go` → `native.Tracer` | `gamelog_raw` | 实时 T+0 | 登录/注册/充值/升级/在线/行为等关键事件；**默认 KPI 查询使用此库** |
| Scribe T+1 归档 | 同上 | `gamelog_odl` | T+1 | 同 `gamelog_raw` 的归档版本；**仅当用户要求 `-- use_odl` 时使用** |
| DTS（Data Warehouse SDK）ECO 日志 | `server/core/base_dts.go` → `lib/youzu/dts.Collector` | `gameeco_raw` | 实时 T+0 | 角色/道具/资源/行为/养成维度/公会等快照与流水；**默认 ECO 查询使用此库** |
| DTS T+1 归档 | 同上 | `gameeco_odl` | T+1 | 同 `gameeco_raw` 的归档版本；**仅当用户要求 `-- use_odl` 时使用** |

**默认选库规则**：所有 KPI / ECO 查询**默认使用 RAW 库**（`gamelog_raw` / `gameeco_raw`），不按日期自动切换。只有当用户明确要求 T+1 / ODL 时，才在 SQL 开头单独一行加 `-- use_odl` 使用 ODL 库（`gamelog_odl` / `gameeco_odl`）。

**表名规则**：
- Scribe KPI 表：`{库}.v_presto_log_{小写 Action 名}`，例如 `gamelog_raw.v_presto_log_rolelogin`
- DTS ECO 表：`{库}.v_presto_log_{小写 LogType 名}` 或 `v_presto_snap_{小写 LogType 名}`，例如 `gameeco_raw.v_presto_log_rolebehavior`、`gameeco_raw.v_presto_snap_rolecache`

**重要**：
- `gameeco_raw` 的 `game_id` 通常为**字符串** `'255'`，`gamelog_raw` 的 `game_id` 为**整数** `255`，写 SQL 时需注意。
- `gameeco_raw` 的 `role_id` 为 **BIGINT**，`gamelog_raw` 的 `role_id` 通常为 **VARCHAR 字符串**。
- 过滤测试服：通常 `SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'`，具体以运营侧渠道规划为准。

---

### 通用 Scribe KPI 基础字段（`gamelog_raw` / `gamelog_odl`）

来自 `base_scribe.go` 的日志头：

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 分区日期 yyyyMMdd |
| game_id | int | 255 |
| event_id | string | 事件唯一 ID |
| ver | string | SDK/版本号 |
| op_id | int | 运营商/战区 ID（`player.Zone`） |
| opgame_id | int | 混服组 ID（`server_id` 前 4 位） |
| server_id | int | 服务器 ID |
| createtime | string | 事件时间 yyyy-MM-dd HH:mm:ss |
| channel_id | int | 分包渠道 ID |
| multiscreen_type | string | 多屏类型 |

> 注：后端 `base_scribe.go` 在 category 为 `log_255_<event>`，消息体为 pipe-delimited；上述部分基础字段由下游 ETL 补充。

---

### 通用 DTS ECO 基础字段（`gameeco_raw` / `gameeco_odl`）

来自 `lib/youzu/dts/data.go` 的玩家中心行首（所有以角色为主体的 DTS 表均包含）：

| # | 字段 | 类型 | 说明 |
|---|---|---|---|
| 1 | log_type | string | 表名，如 `RoleBehavior` |
| 2 | game_id | string | '255'（字符串） |
| 3 | event_id | string | `<LogType>_<role_id>_<unix>_<rand>` |
| 4 | server_id | int | 服务器 ID |
| 5 | opgame_id | int | 混服组 ID（`server_id` 前 4 位） |
| 6 | server_type | int | 1=正式服，0/2=测试/开发服 |
| 7 | op_id | int | 战区/运营商 ID |
| 8 | createtime_local | string | 当地时间 yyyy-MM-dd HH:mm:ss |
| 9 | timestamp | bigint | Unix 时间戳（秒） |
| 10 | time_zone | string | 时区 |
| 11 | account | string | 平台账号（`player.Username`） |
| 12 | account_regtime | int | 账号注册时间（Unix 秒） |
| 13 | account_firstingametime | int | 首次进入游戏时间 |
| 14 | client_ip | string | 客户端 IP |
| 15 | country | string | 国家 |
| 16 | language | string | 语言 |
| 17 | role_id | bigint | 角色 ID |
| 18 | role_name | string | 角色名 |
| 19 | role_regtime | int | 角色注册时间（Unix 秒） |
| 20 | role_career | string | 职业（当前多为空） |
| 21 | role_level | int | 等级 |
| 22 | role_vip | int | VIP 等级 |
| 23 | role_power | bigint | 战力 |
| 24 | role_unionid | bigint | 公会 ID |
| 25 | role_paid | int | 是否付费（1=是，0=否） |
| 26 | role_type | int | 1=正常，2=测试，3=GM/福利，4=其他 |
| 27 | ad_user | int | 1=广告用户，2=非广告用户 |
| 28 | channel_id | int | CPS 分包 ID |
| 29 | device_type | string | 设备型号 |
| 30 | device_os | string | 操作系统及版本 |
| 31 | device_id | string | 设备 ID |
| 32 | game_ver | string | 游戏版本号 |
| 33 | ver | string | DTS SDK 版本，固定 `V1.0` |

> 注：后端 `lib/youzu/dts` 将行首字段 pipe-delimited 写入本地小时文件 `unieco_255_<LogType>_<YYYYMMDDHH>`，下游 ETL 映射为 Presto 视图。字段名以数仓实际视图为准，上表按 312/160 项目的 `EcoBase` 命名约定做对齐。

---

## 一、KPI 实时表（`gamelog_raw`）

> 由 Scribe `log_255_*` category 映射而来。默认所有 KPI 查询使用 `gamelog_raw`；仅当用户明确要求 T+1 / ODL 时，才用 `gamelog_odl`。

### gamelog_raw.v_presto_log_rolelogin — 角色登录（实时 T+0）

每次角色登录产生一条。适合查 DAU、新增登录。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| client_ip | string | 客户端 IP |
| device | string | 设备信息 |
| account | string | 账号 |
| role_id | string | 角色 ID |
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
| diamond | int | 充值钻石/真钻余额 |
| blackdiamond | int | 非绑钻石余额 |
| money | bigint | 金币余额 |
| device_info | string | 设备详情 |
| bundle_id | string | 包名 |
| country | string | 国家 |
| timezone | string | 时区 |
| logd | int | 日志 Unix 时间戳 |
| language | string | 语言 |
| top_level | int | 历史最高等级 |

---

### gamelog_raw.v_presto_log_rolereg — 角色注册（实时 T+0）

每次角色注册/创角产生一条，用于统计新增角色。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| client_ip | string | 客户端 IP |
| device | string | 设备信息 |
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型 |
| ad_id | string | 广告 ID |
| pt_account_regtime | string | 平台账号注册时间 |
| channel_id | int | 渠道 ID |
| multiscreen_type | string | 多屏类型 |
| device_info | string | 设备详情 |
| bundle_id | string | 包名 |
| country | string | 国家 |
| timezone | string | 时区 |
| logd | int | 日志 Unix 时间戳 |
| language | string | 语言 |

---

### gamelog_raw.v_presto_log_roleact — 角色激活（实时 T+0）

首次创角后触发，定义为激活。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| client_ip | string | 客户端 IP |
| device | string | 设备信息 |
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型 |
| role_name | string | 角色名 |
| role_career | string | 职业 |
| role_level | int | 等级 |
| role_vip | int | VIP |
| role_regtime | string | 注册时间 |
| ad_id | string | 广告 ID |
| pt_account_regtime | string | 平台账号注册时间 |
| channel_id | int | 渠道 ID |
| multiscreen_type | string | 多屏类型 |
| device_info | string | 设备详情 |
| top_level | int | 历史最高等级 |

---

### gamelog_raw.v_presto_log_rolelogout — 角色登出（实时 T+0）

每次角色登出产生一条，用于统计在线时长、PCU/ACU 推算。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| login_time | string | 本次登录时间 |
| online_time | bigint | 本次在线时长（秒） |
| client_ip | string | 客户端 IP |
| device | string | 设备信息 |
| account | string | 账号 |
| role_id | string | 角色 ID |
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
| reason | int | 登出原因：1=正常，2=维护/升级，3=重复登录，4=其他 |
| diamond | int | 真钻余额 |
| blackdiamond | int | 非绑钻余额 |
| money | bigint | 金币余额 |
| device_info | string | 设备详情 |
| bundle_id | string | 包名 |
| country | string | 国家 |
| timezone | string | 时区 |
| logd | int | 日志 Unix 时间戳 |
| language | string | 语言 |
| top_level | int | 历史最高等级 |

---

### gamelog_raw.v_presto_log_rolelvup — 角色升级（实时 T+0）

每次主角升级产生一条。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| client_ip | string | 客户端 IP |
| device | string | 设备信息 |
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型 |
| role_name | string | 角色名 |
| role_career | string | 职业 |
| role_level | int | 升级后等级 |
| role_level_before | int | 升级前等级 |
| role_vip | int | VIP |
| role_unionid | bigint | 公会 ID |
| role_regtime | string | 注册时间 |
| role_paid | int | 是否付费 |
| role_exp | bigint | 经验 |
| role_energy | int | 体力 |
| diamond | int | 真钻余额 |
| blackdiamond | int | 非绑钻余额 |
| money | bigint | 金币余额 |
| device_info | string | 设备详情 |
| top_level | int | 历史最高等级 |

---

### gamelog_raw.v_presto_log_payrecharge — 充值流水（实时 T+0）

每笔真实充值产生一条。过滤掉代金券充值（订单号前缀 `AS_DAIJIN`）和假充值（`flags == 1`）。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型 |
| role_name | string | 角色名 |
| role_career | string | 职业 |
| role_level | int | 等级 |
| role_vip | int | VIP |
| role_regtime | string | 注册时间 |
| role_paid | int | 是否付费 |
| pay_type | int | 充值类型（当前固定 1） |
| pay_orderid | string | 订单号 |
| pay_discount | double | 折扣率 |
| pay_way | int | 支付方式 |
| pay_itemid | string | 购买商品/礼包 ID（`action.Extra["entry"]`） |
| pay_money | double | 充值金额（`action.Amount / 100`，单位以运营侧货币口径为准） |
| pay_currency | string | 货币类型 |
| pay_diamond | int | 购得钻石数（`action.Extra["true_diamond"]`） |
| diamond | int | 充值后真钻余额 |
| blackdiamond | int | 充值后非绑钻余额 |
| money | bigint | 充值后金币余额 |
| device_info | string | 设备详情 |
| imei | string | 设备 IMEI |
| bundle_id | string | 包名 |
| country | string | 国家 |
| timezone | string | 时区 |
| logd | int | 日志 Unix 时间戳 |
| language | string | 语言 |

**充值模式（`func_recharge.go` 中的 mold，可能通过额外字段或扩展传入）**：

| mold | 含义 |
|---|---|
| 0 | 正常充值 |
| 1 | 活动充值 |
| 2 | 兑换礼包充值 |
| 3 | 圣印试炼充值 |
| 4 | 福利充值 |
| 5 | GM 特权充值 |
| 6 | 永久卡充值 |
| 7 | 折扣券充值 |
| 8 | 代金券充值（会被过滤） |

---

### gamelog_raw.v_presto_log_payconsume — 钻石消耗（实时 T+0）

仅记录钻石/非绑钻消耗（`EVENT_ITEM_CHANGED` 且 `Refer = PRIZE_DIAMOND_ENTRY`，`Amount < 0`）。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型 |
| role_name | string | 角色名 |
| role_career | string | 职业 |
| role_level | int | 等级 |
| role_vip | int | VIP |
| role_regtime | string | 注册时间 |
| role_paid | int | 是否付费 |
| consume_type | int | 消耗类型：1=购买道具，2=游戏玩法，3=玩家间交易，4=系统扣除(GM)，5=其他 |
| consume_diamond | int | 消耗真钻数 |
| consume_blackdiamond | int | 消耗非绑钻数 |
| b_type | int | 行为类型（多为 0） |
| b_id | int | 行为/模块 ID（`action.Type`） |
| consume_rs_id | int | 消耗资源 ID |
| consume_rs_property_id | int | 消耗资源属性 ID |
| other_role_id | string | 关联角色 ID |
| diamond | int | 消耗后真钻余额 |
| blackdiamond | int | 消耗后非绑钻余额 |
| money | bigint | 消耗后金币余额 |

---

### gamelog_raw.v_presto_log_paygift — 钻石获取（实时 T+0）

记录钻石/非绑钻的获得（`EVENT_ITEM_CHANGED` 且 `Refer = PRIZE_DIAMOND_ENTRY`，`Amount > 0`）。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型 |
| role_name | string | 角色名 |
| role_career | string | 职业 |
| role_level | int | 等级 |
| role_vip | int | VIP |
| role_regtime | string | 注册时间 |
| role_paid | int | 是否付费 |
| gift_type | int | 赠送类型：1=玩法任务奖励，2=充值赠送（月卡），3=玩家间交易，4=系统加(GM)，5=其他 |
| gift_diamond | int | 获得真钻数 |
| gift_blackdiamond | int | 获得非绑钻数 |
| b_type | int | 行为类型 |
| b_id | int | 行为/模块 ID |
| other_role_id | string | 关联角色 ID |
| diamond | int | 获得后真钻余额 |
| blackdiamond | int | 获得后非绑钻余额 |
| money | bigint | 获得后金币余额 |

---

### gamelog_raw.v_presto_log_rsproduce — 资源产出/消耗（实时 T+0）

目前仅记录钻石变动（`PRIZE_DIAMOND_ENTRY`）。每条记录资源的一次获得或消耗。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型 |
| role_name | string | 角色名 |
| role_career | string | 职业 |
| role_level | int | 等级 |
| role_vip | int | VIP |
| role_regtime | string | 注册时间 |
| role_paid | int | 是否付费 |
| rs_category | int | 资源大类（`native.PRIZE_ITEM = 20`） |
| rs_id | int | 资源 ID（`action.Refer`，钻石为 3） |
| rs_type | int | 资源类型：1=获得，2=消耗 |
| rs_behavior | int | 变动行为来源（`action.Source`） |
| rs_reason_id | int | 原因 ID（`action.Source`） |
| other_role_id | string | 关联角色 ID |
| rs_quality | int | 变动数量 |
| rs_quality_before | int | 变动前数量 |
| device_info | string | 设备详情 |

---

### gamelog_raw.v_presto_log_bhbehavior — 通用行为日志（实时 T+0）

记录各类玩法/系统行为，是分析活跃度、玩法参与的核心表。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型 |
| role_name | string | 角色名 |
| role_career | string | 职业 |
| role_level | int | 等级 |
| role_vip | int | VIP |
| role_regtime | string | 注册时间 |
| role_paid | int | 是否付费 |
| b_type | int | 行为类型（当前固定 0） |
| b_id | int | 行为/事件 ID（`action.Type`，见下方事件枚举） |
| zone_id | int | 场景/副本/关卡 ID（当前多为 0） |
| zone_instance_id | int | 场景实例 ID（当前多为 0） |
| b_value | string | 行为参数：通常为 `"1"`；竞技场挑战时为对手排名/ID |
| device_info | string | 设备详情 |

**常见 `b_id` 取值（来自 `native/event.go`）**：

| b_id | 含义 |
|---|---|
| 10 | 角色升级 |
| 11 | VIP 升级 |
| 21 | 道具/资源变动（行为日志中较少直接用） |
| 40 | 英雄获得 |
| 61 | 关卡完成 |
| 71 | 商店购买 |
| 96 | 任务完成 |
| 110 | 竞技场挑战 |
| 136 | 公会加入 |
| 255 | 赏金任务完成 |
| 270 | 遗物抢夺 |
| 290 | 神器合成 |

> 完整行为语义需结合 `b_id` 与 `action.Source` 共同判断；`b_value` 字段内容较少，复杂参数通常需要关联 `gameeco_raw.v_presto_log_rolebehavior` 的 `b_param`。

---

### gamelog_raw.v_presto_log_bhrookie — 新手引导（实时 T+0）

记录新手引导任务/步骤完成情况。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| client_ip | string | 客户端 IP |
| device | string | 设备信息 |
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型 |
| role_name | string | 角色名 |
| role_career | string | 职业 |
| role_level | int | 等级 |
| role_vip | int | VIP |
| role_regtime | string | 注册时间 |
| role_paid | int | 是否付费 |
| task_id | int | 引导任务 ID |
| pre_task_id | int | 前置任务 ID |
| step_id | string | 步骤 ID |
| pre_step_id | string | 前置步骤 ID |
| status | int | 状态（当前固定 2=已完成） |
| device_info | string | 设备详情 |

---

### gamelog_raw.v_presto_log_serpcu — 服务器 PCU（实时 T+0）

记录服务器同时在线峰值。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| pcu | int | 当前同时在线人数 |
| spare_one | int | 预留字段 |

---

## 二、KPI T+1 表（`gamelog_odl`）

> 仅当用户明确要求 T+1 / ODL，并在 SQL 开头加 `-- use_odl` 时使用。默认查询使用 `gamelog_raw`。

与 `gamelog_raw` 对应，字段相同，数据延迟一天。

- `gamelog_odl.v_presto_log_rolelogin`
- `gamelog_odl.v_presto_log_rolereg`
- `gamelog_odl.v_presto_log_roleact`
- `gamelog_odl.v_presto_log_rolelogout`
- `gamelog_odl.v_presto_log_rolelvup`
- `gamelog_odl.v_presto_log_payrecharge`
- `gamelog_odl.v_presto_log_payconsume`
- `gamelog_odl.v_presto_log_paygift`
- `gamelog_odl.v_presto_log_rsproduce`
- `gamelog_odl.v_presto_log_bhbehavior`
- `gamelog_odl.v_presto_log_bhrookie`
- `gamelog_odl.v_presto_log_serpcu`

---

## 三、ECO 快照表（`gameeco_raw`）

> 由 DTS `lib/youzu/dts` 产出，默认所有 ECO 查询使用 `gameeco_raw`；仅当用户要求 `-- use_odl` 时使用 `gameeco_odl`。

### gameeco_raw.v_presto_snap_rolecache — 角色快照

每日/每小时每个角色一条，记录角色末态。`game_id` 为字符串 `'255'`。

| 字段 | 类型 | 说明 |
|---|---|---|
| cache_day | string | 快照日期 yyyyMMdd |
| country | string | 国家 |
| state | string | 地区/州 |
| union_name | string | 公会名称 |
| ad_user | int | 1=广告用户，2=非广告用户 |
| diamond | bigint | 真钻余额 |
| blackdiamond | bigint | 非绑钻余额 |
| money | bigint | 金币余额 |
| role_exp | int | 经验 |
| role_create_time | int | 角色创建时间（Unix 秒） |
| guide_id_max | int | 最高完成引导 ID |
| last_map_id | int | 最后停留地图 ID |
| last_login | int | 最后登录时间（Unix 秒） |
| last_logout | int | 最后下线时间（Unix 秒） |
| total_login_days | int | 累计登录天数 |
| daily_pay_diamond | bigint | 当日付费钻石 |
| max_daily_pay_diamond | bigint | 历史单日最高付费钻石 |
| total_pay_diamond | bigint | 累计付费钻石 |
| total_pay_money | double | 累计充值金额 |
| total_pay_days | int | 累计付费天数 |
| total_pay_times | int | 累计付费次数 |
| first_pay_time | int | 首次付费时间（Unix 秒） |
| last_pay_time | int | 最后付费时间（Unix 秒） |
| arena_rank | int | 竞技场排名 |
| game_ver | string | 游戏版本 |
| customized | string | 游戏自定义扩展字段 |

> 查最新快照：`row_number() OVER (PARTITION BY role_id ORDER BY ds DESC)` 取 rn=1，或直接用最新 `cache_day`。

---

### gameeco_raw.v_presto_snap_packcache — 背包道具快照

每日每个角色的背包道具快照，背包按 pack1~packN JSON 字符串存储。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds / cache_day | string | 日期 |
| game_id | string | '255' |
| server_id / op_id | int | 服务器/运营商 |
| account | string | 账号 |
| role_id | bigint | 角色 ID |
| role_name | string | 角色名 |
| role_regtime | int | 注册时间 |
| role_level | int | 等级 |
| role_vip | int | VIP |
| last_login | int | 最后登录时间 |
| pack1 ~ packN | string | 各背包 JSON，具体字段数以数仓视图为准 |

> 查道具持有率更推荐用 `snap_itemcache`（如果数仓已生成）。

---

### gameeco_raw.v_presto_snap_itemcache — 道具快照 ★（推荐用于持有率分析）

每日每个角色持有的每种道具一条（如果 DTS/ETL 已生成此视图）。

| 字段 | 类型 | 说明 |
|---|---|---|
| game_id | int / string | 255 / '255'，以数仓实际类型为准 |
| server_id / opgame_id / op_id | int | 服务器/混服组/战区 |
| cache_day | string | 快照日期 yyyyMMdd |
| account | string | 账号 |
| role_id | bigint | 角色 ID |
| item_id | int | 道具模板 ID |
| item_name | string | 道具名称 |
| item_num | bigint | 持有数量 |

---

### gameeco_raw.v_presto_snap_dimcache — 养成维度快照 ★（推荐用于饱和度分析）

每日每个角色的每个养成维度一条，通过 `dim_type` 区分系统，`sub_dim_1~10` 记录各系统养成等级。

| 字段 | 类型 | 说明 |
|---|---|---|
| ds / cache_day | string | 日期 |
| game_id | string | '255' |
| role_id | bigint | 角色 ID |
| server_id / op_id | int | 服务器/运营商 |
| dim_type | int | 养成系统类型 |
| dim_id | bigint | 维度对象 ID |
| dim_name | string | 维度对象名称 |
| dim_item_id | bigint | 关联道具/模板 ID |
| sub_dim_1 ~ sub_dim_10 | string | 养成子属性 |
| extra_1 ~ extra_9 | string | 额外扩展参数 |

**常见 `dim_type`（需以游戏实际配置为准）**：

| dim_type | 系统名称 |
|---|---|
| 1 | 英雄 |
| 2 | 装备 |
| 3 | 宝物/神器 |
| 4 | 坐骑 |
| 5 | 翅膀 |
| 7 | 符文 |
| 9 | 神武/圣印 |
| 32 | 灵核 |
| 35 | 兽魂 |

---

### gameeco_raw.v_presto_snap_unioncache — 公会快照

每日每个公会一条，记录公会末态。

| 字段 | 类型 | 说明 |
|---|---|---|
| role_unionid | bigint | 公会 ID |
| union_name | string | 公会名 |
| union_level | int | 公会等级 |
| union_size | int | 公会成员数 |
| union_leader_id | bigint | 会长角色 ID |
| union_create_time | int | 创建时间（Unix 秒） |
| customized | string | 扩展字段 |

---

## 四、ECO 流水表（`gameeco_raw`，默认）

> 默认所有 ECO 流水查询使用 `gameeco_raw`。仅当用户明确要求 T+1 / ODL，并在 SQL 开头加 `-- use_odl` 时使用 `gameeco_odl`。

### gameeco_raw.v_presto_log_rolebehavior — 玩法行为日志 ★

记录玩家各类玩法参与（战斗/副本/PVP/活动等），是分析留存、活跃度的核心表。

在 DTS 通用行首之后，额外字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| b_type | string | 功能模块中文名称（如 `竞技场`、`普通副本`、`英雄养成`） |
| zone | string | 场景子标识（多数为空） |
| b_id | int | 模块/功能 ID（`native.FUNC_*` 常量） |
| zone_id | int | 场景/副本/关卡 ID |
| b_value | string | 行为具体动作描述（中文） |
| session_length | int | 停留时长（秒，多数为 0） |
| enemy_id | bigint | 对手角色 ID（PVP 时有效） |
| rank_before | int | 行为前排名 |
| rank_after | int | 行为后排名 |
| b_param | string | 附加参数，格式为 `Type;Amount;Refer;Owner;Flags;Source` |
| union_name | string | 公会名称 |
| battle_attr | string | 战斗属性 |
| buff_item_consume | string | 消耗的 BUFF 道具 |
| team_power | bigint | 玩家当前战力 |
| other_object | string | 其他关联对象 |
| customized | string | 游戏自定义扩展字段 |
| device | string | 设备详情 |
| bundle_id | string | 包名 |
| model | string | 设备型号 |
| extras[0..49] | string | 50 个可选扩展字段 |

**常见 `b_type` 取值**：

| b_type | 含义 |
|---|---|
| 竞技场 | 竞技场挑战、购买次数等 |
| 勇气试炼 | 探索 BOSS 战斗/击杀 |
| 海岛矿场 | 矿场占领/延长时间 |
| 虚空神殿 | 通天塔通关/扫荡 |
| 地牢迷宫 | 迷宫战斗/通关 |
| 普通副本 | 普通关卡完成/扫荡 |
| 精英关卡 | 精英关卡完成 |
| 噩梦关卡 | 噩梦关卡完成 |
| 英雄养成 | 英雄获得/升级/突破等 |
| 装备养成 | 装备强化/升星等 |
| 魔石养成 | 神器合成/升级 |
| 公会 | 公会创建/加入/捐献等 |
| 巅峰对决 | 巅峰对决参与/竞猜 |
| 活动打点 | 客户端活动查看/商城购买 |
| 占卜 | 占卜/抽卡 |
| 翅膀 | 翅膀激活/成长 |

完整事件注册列表见 `server/core/base_dts.go` 第 287~937 行。

---

### gameeco_raw.v_presto_log_roleres — 资源产销流水

每次资源/货币增减一条记录。当前 `EVENT_ITEM_CHANGED` 触发，覆盖金币、体力、钻石、公会币等所有资源变动。

| 字段 | 类型 | 说明 |
|---|---|---|
| res_id | string | 资源条目 ID（`action.Refer`） |
| res_name | string | 资源名称（当前与 ID 相同） |
| amount_before | string | 变动前数量 |
| amount_after | string | 变动后数量（`action.Flags`） |
| change_type | string | `产出` / `消耗` |
| change_amount | string | 变动数量（`action.Amount`，消耗为负） |
| change_reason | string | 原因 ID（`action.Source`） |
| change_module | string | 模块 ID（`action.Source`） |
| related_id | string | 关联 ID（当前为空） |
| diamond | bigint | 变动后真钻余额 |
| blackdiamond | bigint | 变动后非绑钻余额 |
| money | bigint | 变动后金币余额 |
| customized | string | 扩展字段 |

**常见资源条目（`native/prize.go`）**：

| res_id | 含义 |
|---|---|
| 1 | 金币 |
| 2 | 体力 |
| 3 | 钻石 |
| 14 | 公会币 |
| 16 | 公会资金 |
| 114 | 代金券 |

> 钻石消耗会拆分真钻与非绑钻：真钻变动写入 `player.True_diamond`，非绑钻变动写入 `player.BlackDiamond()`。

---

### gameeco_raw.v_presto_log_roleitem — 道具/英雄产销流水

当前主要记录 **英雄获得**（`EVENT_HERO_GET`）。通用道具变化通常进入 `RoleRes`。

| 字段 | 类型 | 说明 |
|---|---|---|
| item_type | string | 道具类型（当前多为 `英雄`） |
| item_id | int | 道具/英雄模板 ID（`action.Refer`） |
| item_name | string | 名称（当前与 ID 相同） |
| change_type | string | `产出` / `消耗` |
| status_before | bigint | 变动前数量 |
| status_after | bigint | 变动后数量 |
| change_reason | int | 原因 ID（`action.Source`） |
| change_module | int | 模块 ID（`action.Source`） |
| related_id | string | 关联 ID |
| diamond | bigint | 变动后真钻余额 |
| blackdiamond | bigint | 变动后非绑钻余额 |
| money | bigint | 变动后金币余额 |
| customized | string | 扩展字段 |

---

### gameeco_raw.v_presto_log_roleshop — 商店购买日志

| 字段 | 类型 | 说明 |
|---|---|---|
| shop_name | string | 商店名称（`action.Refer`，商店条目 ID） |
| shop_id | int | 商店 ID |
| one_vs_one | int | 是否限购（当前固定 1） |
| items_spend | string | 消耗的道具/资源，格式 `{price_item:price}` |
| items_get | string | 获得的道具/资源，格式 `{action.Flags:action.Amount}` |
| item_unit | int | 单价（当前固定 1） |
| item_amount | int | 购买数量 |
| amount_limit | int | 购买上限 |
| discount_rate | double | 折扣率 |
| diamond | bigint | 购买后真钻余额 |
| blackdiamond | bigint | 购买后非绑钻余额 |
| money | bigint | 购买后金币余额 |
| customized | string | 扩展字段 |

---

### gameeco_raw.v_presto_log_rolevip — VIP 升级日志

每次 VIP 等级变化一条。

| 字段 | 类型 | 说明 |
|---|---|---|
| role_vip_before | int | 升级前 VIP |
| role_vip | int | 升级后 VIP（`action.Amount`） |
| role_vipexp_before | int | 升级前 VIP 经验 |
| role_vipexp | int | 升级后 VIP 经验（`action.Flags`） |
| role_energy | int | 当前体力 |
| diamond | bigint | 真钻余额 |
| blackdiamond | bigint | 非绑钻余额 |
| money | bigint | 金币余额 |
| customized | string | 扩展字段 |

---

### gameeco_raw.v_presto_log_roletask — 任务完成日志

| 字段 | 类型 | 说明 |
|---|---|---|
| task_type | string | 任务类型：`成就` / `日常` 等 |
| task_name | string | 任务名称（当前为空） |
| task_id | int | 任务 ID（`action.Refer`） |
| pre_task_id | int | 前置任务 ID |
| status | int | 状态（当前固定 2=完成） |
| diamond | bigint | 真钻余额 |
| blackdiamond | bigint | 非绑钻余额 |
| money | bigint | 金币余额 |
| customized | string | 扩展字段 |

---

### gameeco_raw.v_presto_log_rolepromo — 活动参与日志

| 字段 | 类型 | 说明 |
|---|---|---|
| activity_topic | string | 活动主题/标题 |
| activity_step | string | 活动子类描述 |
| step_id | int | 子步骤 ID（`act.Id`） |
| activity_id | int | 活动唯一 ID（`action.Flags`） |
| item_spend | string | 消耗的道具/资源 |
| item_get | string | 获得的奖励 |
| activity_begin | bigint | 活动开始 Unix 时间 |
| activity_end | bigint | 活动结束 Unix 时间 |
| activity_special | int | 是否精彩活动（当前多为 1） |
| activity_pay | int | 是否充值活动（当前多为 0） |
| activity_range | int | 活动范围 |
| enter_level | string | 可参与等级范围 |
| enter_vip | string | 可参与 VIP 范围 |
| diamond | bigint | 真钻余额 |
| blackdiamond | bigint | 非绑钻余额 |
| money | bigint | 金币余额 |

---

### gameeco_raw.v_presto_log_rolegold — 黄金/钻石消耗分摊日志

| 字段 | 类型 | 说明 |
|---|---|---|
| factory | string | 预留 |
| model | string | 预留 |
| consume_type | string | 消耗类型：`FUNCTIONAL` / `ITEM` |
| reason | string | 原因：`F_<func_id>` / `I_<func_id>` |
| gold | bigint | 消耗总量 |
| item_id | string | 关联道具 ID |
| item_name | string | 道具名称（当前为空） |
| item_number | string | 道具数量 |
| audit_type | string | 分摊类型：`消耗型` / `长期型` / `混合型` |
| long_ratio | int | 长期型占比 |
| short_ratio | int | 短期型占比 |
| param1 | bigint | UUID |
| param2 | string | 预留参数 |
| customized | string | 扩展字段 |

---

### gameeco_raw.v_presto_log_unionaction — 公会行为日志

| 字段 | 类型 | 说明 |
|---|---|---|
| role_unionid | bigint | 公会 ID |
| union_name | string | 公会名 |
| union_level | int | 公会等级 |
| union_size | int | 公会成员数 |
| action_type | string | 行为类型：创建公会、加入公会、退出公会、更改公告、解散公会等 |
| action_object | string | 行为对象/内容 |
| customized | string | JSON 扩展，如 `{notice:...}` |

---

### gameeco_raw.v_presto_log_unionres — 公会资源流水

| 字段 | 类型 | 说明 |
|---|---|---|
| role_unionid | bigint | 公会 ID |
| union_name | string | 公会名 |
| union_level | int | 公会等级 |
| union_size | int | 公会成员数 |
| res_id | int | 资源 ID（`action.Refer`） |
| res_name | string | 资源名（如 `公会资金`） |
| amount_before | string | 变动前数量 |
| amount_after | string | 变动后数量 |
| change_type | int | 1=获得，2=消耗 |
| change_amount | bigint | 变动量 |
| change_reason | int | 原因 ID（`action.Source`） |
| related_id | string | 关联角色 ID（`action.Owner`） |

---

### gameeco_raw.v_presto_log_rolechat — 聊天日志

| 字段 | 类型 | 说明 |
|---|---|---|
| chat_channel | string | 聊天频道：系统消息、世界聊天、公会聊天、玩家私聊、战区聊天等 |
| chat_object | string | 聊天对象（私聊时为对方 ID） |
| chat_content | string | 聊天内容 |
| device | string | 设备详情 |
| bundle_id | string | 包名 |
| model | string | 设备型号 |

---

### gameeco_raw.v_presto_log_rolefriend — 好友行为日志

| 字段 | 类型 | 说明 |
|---|---|---|
| friend_server_id | int | 好友服务器 ID |
| friend_account | string | 好友账号 |
| friend_role_id | bigint | 好友角色 ID |
| friend_name | string | 好友角色名 |
| friend_group | string | 好友分组 |
| action_type | string | 行为：`add`/`agree`/`refuse`/`delete` |
| bundle_id | string | 包名 |
| model | string | 设备型号 |

---

### gameeco_raw.v_presto_log_serlive — 在线心跳日志

每小时整点产生，记录各战区在线角色列表。

| 字段 | 类型 | 说明 |
|---|---|---|
| event_id | string | `SerLive_<unix>` |
| op_id | int | 战区 ID |
| opgame_id | int | 混服组 ID |
| server_id | int | 服务器 ID |
| server_type | int | 正式/测试服标记 |
| createtime_local | string | 时间戳 |
| timestamp | bigint | Unix 秒 |
| time_zone | string | 时区 |
| live_role | string | 在线角色 ID 逗号分隔列表 |
| game_ver | string | 游戏版本 |

---

## 五、示例 SQL

### 查昨日 DAU（登录人数）

```sql
SELECT COUNT(DISTINCT role_id) AS dau
FROM gamelog_raw.v_presto_log_rolelogin
WHERE game_id = 255
  AND ds = '<昨天ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
```

### 查今日实时充值

```sql
SELECT
  COUNT(DISTINCT role_id) AS payers,
  CAST(SUM(CAST(pay_money AS DOUBLE)) AS DECIMAL(18,2)) AS revenue
FROM gamelog_raw.v_presto_log_payrecharge
WHERE game_id = 255
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
WHERE game_id = 255
  AND ds >= '<7天前ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY ds
ORDER BY ds
```

### 查昨日新增角色

```sql
SELECT COUNT(DISTINCT role_id) AS new_roles
FROM gamelog_raw.v_presto_log_rolereg
WHERE game_id = 255
  AND ds = '<昨天ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
```

### 查各渠道昨日 DAU

```sql
SELECT opgame_id, COUNT(DISTINCT role_id) AS dau
FROM gamelog_raw.v_presto_log_rolelogin
WHERE game_id = 255
  AND ds = '<昨天ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY opgame_id
ORDER BY dau DESC
```

### 查昨日各玩法参与人数（DTS 行为日志）

```sql
SELECT b_type, b_id, COUNT(DISTINCT role_id) AS players, COUNT(*) AS events
FROM gameeco_raw.v_presto_log_rolebehavior
WHERE game_id = '255'
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
WHERE game_id = '255'
  AND ds = '<昨天ds>'
  AND b_type = '竞技场'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
```

### 查昨日副本参与情况

```sql
SELECT b_type, zone_id, COUNT(DISTINCT role_id) AS players, COUNT(*) AS events
FROM gameeco_raw.v_presto_log_rolebehavior
WHERE game_id = '255'
  AND ds = '<昨天ds>'
  AND b_type IN ('普通副本', '精英关卡', '噩梦关卡')
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY b_type, zone_id
ORDER BY events DESC
LIMIT 30
```

### 查昨日资源消耗来源

```sql
SELECT
  res_id,
  change_reason,
  SUM(CAST(change_amount AS DOUBLE)) AS total
FROM gameeco_raw.v_presto_log_roleres
WHERE game_id = '255'
  AND ds = '<昨天ds>'
  AND change_type = '消耗'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY res_id, change_reason
ORDER BY total DESC
LIMIT 30
```

### 查最新角色快照（战力 TOP 20）

```sql
SELECT role_id, role_name, role_level, role_vip, role_power, total_pay_money
FROM (
  SELECT *, row_number() OVER (PARTITION BY role_id ORDER BY ds DESC) AS rn
  FROM gameeco_raw.v_presto_snap_rolecache
  WHERE game_id = '255'
    AND ds >= '<7天前ds>'
    AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
)
WHERE rn = 1
ORDER BY role_power DESC
LIMIT 20
```

### 查某玩家近 7 天行为轨迹

```sql
SELECT ds, b_type, b_id, b_value, zone_id, createtime_local
FROM gameeco_raw.v_presto_log_rolebehavior
WHERE game_id = '255'
  AND ds >= '<7天前ds>'
  AND CAST(role_id AS VARCHAR) = '<角色ID>'
ORDER BY createtime_local
LIMIT 200
```

---

## 六、固定报表口径

### KPI 日报

| 指标 | 来源表 | 口径 |
|---|---|---|
| DAU（日活） | `gamelog_raw.v_presto_log_rolelogin` | `COUNT(DISTINCT role_id)`，`ds = 今天`，排除测试服 |
| 新增角色 | `gamelog_raw.v_presto_log_rolereg` | `COUNT(DISTINCT role_id)`，`ds = 今天`，排除测试服 |
| 激活角色 | `gamelog_raw.v_presto_log_roleact` | `COUNT(DISTINCT role_id)`，`ds = 今天`，排除测试服 |
| 付费人数 | `gamelog_raw.v_presto_log_payrecharge` | `COUNT(DISTINCT role_id)`，`ds = 今天` |
| 收入 | `gamelog_raw.v_presto_log_payrecharge` | `SUM(CAST(pay_money AS DOUBLE))`，`ds = 今天` |
| PCU | `gamelog_raw.v_presto_log_serpcu` | `MAX(pcu)`，`ds = 今天` |

> 默认所有查询使用 `gamelog_raw`，不按日期切换。只有用户明确要求 T+1 / ODL 时，才在 SQL 开头加 `-- use_odl` 使用 `gamelog_odl`。

### LTV 报表

按角色注册日分群：

- LTV1 = 注册当天（day 0）累计充值 ÷ 当天新增人数
- LTV3 = 注册后前 3 天（day 0~2）累计充值 ÷ 当天新增人数
- LTV7 / LTV15 / LTV30 同理

充值数据来自 `gamelog_raw.v_presto_log_payrecharge`（`game_id = 255`），通过 `role_id` 关联注册日分群。

---

## 七、Source / Reason 常量

资源/钻石变动的业务来源由 `action.Source` 标识，主要出现在：

- `gameeco_raw.v_presto_log_roleres.change_reason`
- `gameeco_raw.v_presto_log_roleitem.change_reason`
- `gameeco_raw.v_presto_log_rolebehavior.b_param` 末段
- `gamelog_raw.v_presto_log_payconsume.b_id`
- `gamelog_raw.v_presto_log_paygift.gift_type`

部分常量（`native/source.go`）：

| source | 业务含义 |
|---|---|
| 0 | SOURCE_FIND（自动检测） |
| 1000 | SOURCE_GM |
| 1011 | 竞技场购买次数 |
| 1015 | 竞技场挑战 |
| 1070 | 公会创建 |
| 1071 | 公会捐献 |
| 2001 | 钻石召唤/抽卡 |
| 2002 | 神秘召唤 |
| 2007 | 领地征收消耗 |
| 2011 | 全球竞技场购买次数 |
| 32768 | SOURCE_IGNORE（忽略来源） |

---

## 八、关键源码路径

| 路径 | 用途 |
|---|---|
| `C:\YZ_SVN\女2_手游_M_00010\server\src\native\tracer.go` | Scribe `Tracer` 实现 |
| `C:\YZ_SVN\女2_手游_M_00010\server\src\native\event.go` | 事件常量（`EVENT_*`） |
| `C:\YZ_SVN\女2_手游_M_00010\server\src\native\source.go` | 来源常量（`SOURCE_*`） |
| `C:\YZ_SVN\女2_手游_M_00010\server\src\native\prize.go` | 资源/奖品条目（`PRIZE_*`） |
| `C:\YZ_SVN\女2_手游_M_00010\server\src\server\core\base_scribe.go` | Scribe category 组装与消息体格式 |
| `C:\YZ_SVN\女2_手游_M_00010\server\src\server\core\base_dts.go` | DTS 服务、事件注册、行生成器 |
| `C:\YZ_SVN\女2_手游_M_00010\server\src\server\core\base_prize.go` | `commit_item` / `commit_hero` 资源发放 |
| `C:\YZ_SVN\女2_手游_M_00010\server\src\server\core\func_recharge.go` | 充值流程与充值模式 |
| `C:\YZ_SVN\女2_手游_M_00010\server\src\server\core\player_state.go` | 登录/登出回调 |
| `C:\YZ_SVN\女2_手游_M_00010\server\src\lib\youzu\dts\data.go` | DTS 结构体与 `ToString()` 字段顺序 |
| `C:\YZ_SVN\女2_手游_M_00010\server\src\lib\youzu\dts\collector.go` | DTS 缓冲与刷新策略 |
| `C:\YZ_SVN\女2_手游_M_00010\server\src\lib\youzu\dts\file\manager.go` | DTS 本地文件命名 |
| `C:\YZ_SVN\女2_手游_M_00010\server\src\loris\context\environ.go` | GameId/PlatformId/Zone 默认值 |
