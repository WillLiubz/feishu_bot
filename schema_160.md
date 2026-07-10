## 表结构

> 游戏：女2_ProHaiwai_LOA2_Intranet，game_id = 160
> 数据来源：`C:\YZ_SVN\女2_ProHaiwai_LOA2_Intranet\server\src\depend\datacenter\`

---

### 数仓架构概览

游戏 160 服务端使用自研的轻量级 `depend/datacenter` 包，直接将事件以 **pipe(`|`)-delimited 字符串** 写入 Scribe，类别格式为：

```
log_160_<Action>
```

例如：`log_160_RoleLogin`、`log_160_PayRecharge`、`log_160_BhBehavior`。

与游戏 312 不同，游戏 160 **没有使用 `plugin_uzdatacenter` 的 KPI/ECO 分层架构**，也没有在服务端产出快照表（rolecache / itemcache / dimcache / packcache）。下游 Presto 通常将每个 Action 映射为一张视图：

| 后端 Action | 典型 Presto 视图名 |
|---|---|
| RoleLogin | `gamelog_raw.v_presto_log_rolelogin` / `gamelog_odl.v_presto_log_rolelogin` |
| RoleReg | `gamelog_raw.v_presto_log_rolereg` / `gamelog_odl.v_presto_log_rolereg` |
| RoleAct | `gamelog_raw.v_presto_log_roleact` / `gamelog_odl.v_presto_log_roleact` |
| RoleLogout | `gamelog_raw.v_presto_log_rolelogout` / `gamelog_odl.v_presto_log_rolelogout` |
| RoleLvup | `gamelog_raw.v_presto_log_rolelvup` / `gamelog_odl.v_presto_log_rolelvup` |
| PayRecharge | `gamelog_raw.v_presto_log_payrecharge` / `gamelog_odl.v_presto_log_payrecharge` |
| PayConsume | `gamelog_raw.v_presto_log_payconsume` / `gamelog_odl.v_presto_log_payconsume` |
| PayGift | `gamelog_raw.v_presto_log_paygift` / `gamelog_odl.v_presto_log_paygift` |
| RsProduce | `gamelog_raw.v_presto_log_rsproduce` / `gamelog_odl.v_presto_log_rsproduce` |
| RsStateChange | `gamelog_raw.v_presto_log_rsstatechange` / `gamelog_odl.v_presto_log_rsstatechange` |
| RsLvup | `gamelog_raw.v_presto_log_rslvup` / `gamelog_odl.v_presto_log_rslvup` |
| BhRookie | `gamelog_raw.v_presto_log_bhrookie` / `gamelog_odl.v_presto_log_bhrookie` |
| BhBehavior | `gamelog_raw.v_presto_log_bhbehavior` / `gamelog_odl.v_presto_log_bhbehavior` |
| SerPcu | `gamelog_raw.v_presto_log_serpcu` / `gamelog_odl.v_presto_log_serpcu` |

**表名规则**：`{库}.v_presto_log_{小写 Action 名}`
- `gamelog_raw`：实时 T+0，**默认所有查询使用此库**。
- `gamelog_odl`：T+1 归档，仅当用户明确要求 T+1 / odl 时使用，需要在 SQL 开头单独一行添加 `-- use_odl` 标记。

**查询选库约定**：默认所有 KPI/日志类查询使用 `gamelog_raw`（实时库），不按日期自动切换。只有当用户明确要求 T+1 / odl / 历史归档库时，才使用 `gamelog_odl`。ECO 表（`gameeco_raw` / `gameeco_odl`）不受此约定影响。

**重要**：
- 所有表中的 `role_id` 均为 **字符串**，过滤时写 `role_id = '123456'`，不要写整数。
- 所有表中的 `game_id` 为 **整数** `160`。
- `opgame_id` 由 `server_id` 的前 4 位推导而来（`SUBSTR(CAST(server_id AS VARCHAR), 1, 4)`）。
- 过滤测试服：通常 `SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'`，但需以实际渠道规划为准。

---

### 通用基础字段（所有 gamelog_raw/odl 表均包含）

来自 `datacenter.Base` 以及 ETL 附加字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| ds | string | 分区日期 yyyyMMdd（ETL 从 createtime 抽取） |
| game_id | int | 160 |
| event_id | string | 事件唯一 ID，格式 `{Action}_{role_id}_{毫秒时间戳}_{随机数}` |
| ver | string | SDK 版本 |
| op_id | int | 运营商 ID |
| opgame_id | int | 渠道 ID（server_id 前 4 位） |
| server_id | int | 服务器 ID |
| createtime | string | 事件时间 yyyy-MM-dd HH:mm:ss |
| micro | int | 微客户端类型 |
| gtasdk | int | GTA SDK 标识 |
| timestamp | int | Unix 时间戳（秒），日志写入时追加 |

> 注：后端 `Base` 本身不携带 `ds` 与 `game_id`，这两列由下游 ETL 在入库/映射 Presto 视图时补充。

---

## 一、KPI 实时表（gamelog_raw）

### gamelog_raw.v_presto_log_rolelogin — 角色登录（实时 T+0）

每次角色登录产生一条。适合查当日 DAU、新增登录、在线分布。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| client_ip | string | 客户端 IP |
| device | string | 设备信息 |
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型（后端未明确区分，通常 0/1） |
| role_name | string | 角色名 |
| role_career | string | 职业（当前固定为 `"0"`） |
| role_level | int | 等级 |
| role_vip | int | VIP 等级 |
| role_unionid | bigint | 公会/家族 ID |
| role_regtime | string | 角色注册时间（yyyy-MM-dd HH:mm:ss） |
| role_paid | int | 是否付费（0=否，1=是） |
| role_exp | bigint | 当前经验 |
| role_energy | int | 当前体力 |
| diamond | int | 充值钻石（绑钻/充值钻）余额 |
| blackdiamond | int | 非绑钻石余额 |
| money | bigint | 金币余额 |

> `diamond` 对应 `RES_TYPE_RECHARGE_DIAMOND`，`blackdiamond` 对应 `RES_TYPE_DIAMOND`，`money` 对应 `RES_TYPE_GOLD`。

---

### gamelog_raw.v_presto_log_rolereg — 角色注册（实时 T+0）

每次角色注册产生一条，用于统计新增角色。

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

---

### gamelog_raw.v_presto_log_rolelogout — 角色登出（实时 T+0）

每次角色登出产生一条，用于统计在线时长、PCU/ACU 推算。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| logintime | string | 本次登录时间（RFC3339 格式） |
| onlinetime | bigint | 本次在线时长（秒） |
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
| reason | int | 登出原因（1=正常，2=被踢，3=人数过多，4=防沉迷，5=合服删除） |
| diamond | int | 充值钻石余额 |
| blackdiamond | int | 非绑钻石余额 |
| money | bigint | 金币余额 |

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
| diamond | int | 充值钻石余额 |
| blackdiamond | int | 非绑钻石余额 |
| money | bigint | 金币余额 |

---

### gamelog_raw.v_presto_log_payrecharge — 充值流水（实时 T+0）

每笔充值一条。`pay_money` 单位为人民币元（config 中固定 `pay_currency = "USD"`，但以实际货币口径为准）。

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
| pay_type | int | 充值类型（1=购买钻石，2=购买商品） |
| pay_orderid | string | 订单号 |
| pay_discount | string | 折扣率（当前固定 `"1"`） |
| pay_way | string | 支付方式（当前固定 `"0"`） |
| pay_itemid | string | 购买商品 ID |
| pay_money | double | 充值金额 |
| pay_currency | string | 货币类型 |
| pay_diamond | int | 购得钻石数 |
| diamond | int | 充值后充值钻石余额 |
| blackdiamond | int | 充值后非绑钻余额 |
| money | bigint | 充值后金币余额 |

---

### gamelog_raw.v_presto_log_payconsume — 钻石消耗（实时 T+0）

仅记录钻石/黑钻消耗（代码注释说明“仅记录钻石”）。

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
| consume_type | int | 消耗类型（当前固定 5） |
| consume_diamond | int | 消耗充值钻石数 |
| consume_blackdiamond | int | 消耗非绑钻石数 |
| b_type | int | 行为/来源类型（通常对应 `proto.GLOG_SOURCE`，见附录 A） |
| b_id | int | 行为 ID |
| consume_rs_id | int | 消耗资源 ID（对应 `RES_TYPE`，见附录 B） |
| consume_rs_property_id | int | 消耗资源属性 ID |
| other_role_id | string | 关联角色 ID |
| diamond | int | 消耗后充值钻石余额 |
| blackdiamond | int | 消耗后非绑钻余额 |
| money | bigint | 消耗后金币余额 |

> `b_type` / `b_id` 常与 `GLOG_SOURCE` 枚举对应，可用于按系统分析钻石消耗去向。

---

### gamelog_raw.v_presto_log_paygift — 游戏内货币获取（实时 T+0）

记录钻石/金币等游戏内货币的获取（赠送、活动、系统邮件等）。

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
| gift_type | int | 赠送/来源类型（对应 `proto.GLOG_SOURCE`，见附录 A） |
| gift_diamond | int | 获得充值钻石数 |
| gift_blackdiamond | int | 获得非绑钻石数 |
| b_type | int | 行为类型 |
| b_id | int | 行为 ID |
| other_role_id | string | 关联角色 ID |
| diamond | int | 获得后充值钻石余额 |
| blackdiamond | int | 获得后非绑钻余额 |
| money | bigint | 获得后金币余额 |

---

## 二、资源/养成/行为流水表（gamelog_raw，通常也有 T+1 对应 odl 视图）

### gamelog_raw.v_presto_log_rsproduce — 资源产出/消耗/转移（实时 T+0）

每次道具/英雄/资源等产生变化时产生一条。

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
| rs_type | int | 资源类型（1=道具，2=英雄，3=货币，4=VIP；货币类型见附录 B `RES_TYPE`） |
| rs_id | int | 资源/道具/英雄 ID（货币时对应 `RES_TYPE`） |
| rs_behavior | int | 变动行为（1=增加，2=消耗，3=转移） |
| rs_reason_id | int | 原因 ID（对应 `proto.GLOG_SOURCE`，见附录 A） |
| other_role_id | string | 关联角色 ID |
| rs_quality | int | 变动数量 |
| rs_quality_before | int | 变动前数量 |

> `rs_behavior` 常量：`1=RS_BEHAVIOR_ADD`、`2=RS_BEHAVIOR_CONSUME`、`3=RS_BEHAVIOR_TRANSFER`。

---

### gamelog_raw.v_presto_log_rsstatechange — 资源状态变化（实时 T+0）

资源状态（如装备穿戴、英雄上阵等）变化时记录。

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
| rs_type | int | 资源类型 |
| rs_id | int | 资源 ID |
| rs_status_id | int | 状态对象 ID |
| rs_status | int | 变化后状态 |
| rs_status_before | int | 变化前状态 |

> 状态常量：`RS_STATUS_ON=1`，`RS_STATUS_OFF=2`。

---

### gamelog_raw.v_presto_log_rslvup — 资源等级/属性升级（实时 T+0）

资源（英雄、装备、宝物等）升级时记录。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| account | string | 账号 |
| role_id | string | 角色 ID |
| role_type | int | 角色类型 |
| role_name | string | 角色名 |
| role_career | bigint | 职业/资源 UID（后端复用了该字段） |
| role_level | int | 角色等级 |
| role_vip | int | VIP |
| role_regtime | string | 注册时间 |
| role_paid | int | 是否付费 |
| rs_type | int | 资源类型 |
| rs_id | int | 资源 ID |
| rs_property_id | int | 升级属性/来源 ID |
| rs_level | int | 变化后等级 |
| rs_level_before | int | 变化前等级 |

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
| status | int | 状态（1=未完成/即将完成，2=已完成） |

---

### gamelog_raw.v_presto_log_bhbehavior — 通用行为（实时 T+0）

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
| b_type | int | 行为类型（后端基本未使用，多为 0） |
| b_id | int | 行为/模块 ID（对应 `proto.BEHAVIOR` 枚举） |
| zone_id | int | 场景/副本/关卡 ID |
| zone_instance_id | int | 场景实例 ID |
| b_value | string | 行为参数（分号分隔字符串，含义随 b_id 变化） |

#### BEHAVIOR 枚举值（b_id）

`b_id` 对应 `proto.BEHAVIOR` 枚举，标识玩家触发的具体玩法/系统行为。`b_type` 在代码中基本未使用，恒为 0。

##### 战斗 / 副本 / 挂机

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 10028 | 通天塔战斗 | `layer;monsterPosition;btlResult` |
| 10029 | 通天塔一键通关 | `currentLayer` |
| 10030 | 挂机 | `fightCount` |
| 10031 | 挂机 BOSS | `difficulty;btlResult` |
| 10032 | 关卡战斗 | （未明确参数） |
| 10033 | 关卡扫荡 | （未明确参数） |
| 10023 | 关卡重置 | （未明确参数） |
| 10024 | 进入场景 | （未明确参数） |
| 10025 | 离开场景 | （未明确参数） |
| 10036 | 通天塔开宝箱 | `layer;boxOpenNum` |
| 90001 | 新通天塔开宝箱 | `layer;boxOpenNum` |
| 20040 | 副本记录 | `level;costTime;grade` |
| 20041 | 副本通关 | `level` |
| 21025 | 怪物入侵战斗 | `ability;damage;defeat;rewardMulti` |

##### 竞技场 / PVP

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 10001 | 竞技场挑战 | `btlResult;oldRank;newRank` |
| 10002 | 竞技场购买次数 | `beforeTimes;afterTimes` |
| 22080 | 世界 PK 轮次奖励 | `rank;rewardString` |
| 22081 | 世界 PK 排名奖励 | `rank;rewardString` |
| 22082 | 世界 PK 帝王奖励 | `emperor;rewardString` |
| 22083 | 世界 PK 购买次数 | `count` |

##### 公会 / 家族

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 10004 | 家族任命 | `memberId;oldHighPost;newHighPost` |
| 10005 | 家族领取工资 | （无参数） |
| 10006 | 家族领取捐献奖励 | （无参数） |
| 10007 | 家族获得经验 | `exp;oldExp;newExp` |
| 10008 | 家族升级 | `oldLevel;newLevel` |
| 10009 | 家族战购买次数 | （未明确参数） |
| 10010 | 家族战领取奖励 | （未明确参数） |
| 10037 | 增加家族贡献 | `oldCon;newCon;addCon` |
| 20011 | 家族任务接取 | `familyId;familyRank;taskId;expireTime;taskScore;times;score;questScore` |
| 20012 | 家族任务完成 | 同上 |
| 20013 | 家族任务取消 | 同上 |
| 20014 | 家族成员日活跃 | `familyId` |
| 20015 | 家族成员进入 | `familyId;rank;memberCount;first` |
| 20016 | 家族成员离开 | `familyId;rank;memberCount;kick` |
| 20017 | 家族任务超时 | 同接取 |
| 20018 | 家族任务奖励选择 | `familyId;grade;score;level;index;result` |

##### 英雄 / 宠物 / 战宠养成

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 10003 | 英雄重生 | `heroModelNode` |
| 10011 | 英雄练习 | `nodeId;totalTimes` |
| 10016 | 徽章升级 | `rankModelId;seq` |
| 22010 | 英雄升级 | `heroBaseId;oldLevel;newLevel` |
| 22011 | 英雄突破 | `heroBaseId;tupoLevel` |
| 22012 | 英雄升星 | `heroBaseId;sjLevel` |
| 22040 | 战宠激活 | `petId` |
| 22041 | 战宠升级 | `petId;oldLevel;newLevel` |
| 22042 | 战宠升星 | `petId;oldStar;newStar` |
| 22043 | 战宠升阶 | `petId;oldGrade;newGrade` |

##### 羁绊 / 契约

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 22000 | 羁绊激活 | `fetterKind;fetterNode` |
| 22001 | 羁绊升级 | `fetterKind;fetterNode;oldLv;newLv` |
| 22002 | 羁绊升星 | `fetterKind;fetterNode;oldStar;newStar` |
| 22004 | 命运羁绊激活 | `destingKind;destingNode` |
| 22005 | 命运羁绊升级 | `destingKind;destingNode;oldLv;newLv` |
| 22006 | 命运羁绊升星 | `destingKind;destingNode;oldStar;newStar` |

##### 宝物 / 装备 / 神武 / 圣印

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 10017 | 宝物强化 | `itemModelId;oldExp;newExp;oldLevel;newLevel` |
| 10018 | 宝物开启 | `itemModelId;place` |
| 10019 | 宝物镶嵌 | `itemModelId;baoshiId;place` |
| 10020 | 宝物镶嵌移除 | `itemModelId;moshiId;place` |
| 10021 | 宝物魔石合成 | `id;num` |
| 10022 | 宝物魔石转移 | `targetId;num` |
| 10034 | 宝物一键强化 | 同强化 |
| 90004 | 装备觉醒节点激活 | `type;nodeId` |
| 90005 | 装备觉醒 | `type;awakenLayer` |
| 90008 | 装备觉醒技能激活 | `skillId` |
| 95048 | 圣剑升星 | `unitId;oldLevel;newLevel;levelExp` |
| 95049 | 圣剑升级 | `unitId;oldLevel;newLevel;levelExp` |
| 95050 | 圣剑升阶 | `unitId;nodeId` |
| 95051 | 圣剑觉醒 | `unitId;nodeId` |
| 95052 | 圣剑融合 | （无参数） |
| 95053 | 圣剑快照 | `vip;unitId;layer;nodeCount;level;star;fuseLevel` |
| 95072 | 圣遗物升星 | `hkind;unitId;oldLevel;newLevel;levelExp` |
| 95073 | 圣遗物升级 | `hkind;unitId;oldLevel;newLevel;levelExp` |
| 95074 | 圣遗物升阶 | `hkind;unitId;nodeId` |
| 95075 | 圣遗物觉醒 | `hkind;unitId;nodeId` |
| 95076 | 圣遗物融合 | （无参数） |
| 95077 | 圣遗物快照 | `vip;hkind;unitId;layer;nodeCount;level;star;fuseLevel` |

##### 坐骑 / 翅膀 / 时装 / 衣柜

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 10014 | 坐骑激活 | `horseId` |
| 10015 | 坐骑技能升级 | （未明确参数） |
| 10035 | 坐骑军衔升级 | （未明确参数） |
| 21135 | 衣柜选中 | `comboId;pos;cloth;status` |
| 21136 | 衣柜升级 | `comboId;level;levelExp` |
| 21137 | 衣柜升星 | `comboId;star;starExp` |

##### 元素符文 / 图腾

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 90002 | 元素符文刻印 | `runestoneId;oldNode;newNode` 等 |
| 90003 | 元素符文刻印重置 | 同上 |
| 21015 | 元素符文觉醒 | `normalNodeString+keyNodeString` |
| 21016 | 元素符文觉醒重置 | （未明确参数） |
| 21020 | 图腾获取 | `totemId` |
| 21021 | 图腾强化 | `totemId;oldLevel;newLevel` 等 |
| 21022 | 图腾升星 | `totemId;oldStar;newStar` 等 |
| 21023 | 图腾雕刻 | `totemId` 等 |
| 21024 | 图腾点亮 | `totemId` 等 |
| 21026 | 图腾上阵 | `totemId` 等 |
| 21110 | 图腾图鉴激活 | `tujianId` |
| 21111 | 图腾图鉴注入 | `tujianModelId;star;step` |

##### 魔Forge / 天空石 / 从者

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 90006 | 魔法锻造 | （未明确参数） |
| 90007 | 领取锻造每日奖励 | （未明确参数） |
| 90009 | 天空石合成 | `id;num` |
| 90010 | 天空石一键合成 | `id;num` |
| 90021 | 从者图鉴注入 | `tujianModelId;star;step` |
| 90022 | 从者图鉴激活 | `cardId` |
| 90023 | 从者主从 | `masterLv` |
| 90024 | 从者装备 | 卡片列表 |
| 90025 | 从者卸下 | 卡片列表 |

##### 活动 / 节日 / 运营活动

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 90000 | 活动领奖 | `activityModelId;desc1;activityId;desc2;status` |
| 20001 | 黑色星期五积分 | `isWin;oldScore;addScore;totalScore` |
| 20002 | 黑色星期五抽奖 | `prize1;prize2;randomItem;playTime` |
| 90040 | 圣诞猜题普通出题 | `easyTimes;maxTimes` |
| 90041 | 圣诞猜题困难出题 | `difficultTimes;maxTimes` |
| 90042 | 圣诞猜题普通提交 | `titleIndex;answer;result` 等 |
| 90043 | 圣诞猜题困难提交 | 同上 |
| 90044 | 新年计时领奖 | `serialDays` |
| 90045 | 周任务领奖 | （未明确参数） |
| 90046 | 新兵激活 | `diffDay;code` |
| 90047 | 新兵最终奖励 | `rewardDays`（冒号分隔） |
| 90048 | 新兵任务完成 | `taskId;isNewbie7DaysTask` |
| 21140 | 活动日历领奖 | `id` |
| 21141 | 活动日历积分领奖 | `kind;score;monthScore` |
| 21171 | 活动日历积分 | （未明确参数） |
| 21172 | 活动日历积分领奖 | （未明确参数） |
| 21280 | 刮刮卡设置奖励 | （未明确参数） |
| 21281 | 刮刮卡抽奖 | （未明确参数） |
| 21282 | 刮刮卡下一轮 | （未明确参数） |
| 21283 | 刮刮卡商店购买 | `id;num;costString;rewardString` |

#####  Demon Field / 巨龙战役 / 封魔殿

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 95060 | 恶魔之岛参战 | `1/2（队长/队员）;ability;level;todayCoin` |
| 95061 | 恶魔之岛正常退出 | `killNum;helpNum;...` |
| 95062 | 恶魔之岛强制退出 | 同上 |
| 95040 | 巨龙战役 BOSS 准备战斗 | `killedBossId...` |
| 95041 | 巨龙战役 BOSS 最终战斗 | `bossId;btlResult` |
| 95042 | 巨龙战役 BOSS 排名奖励 | `rank;hasTicket` |
| 95043 | 巨龙战役 BOSS 加超级 Buff | `energy;hasTicket` |
| 95044 | 巨龙战役战斗 | `version;kind;id;btlResult;addScore;score;power;buffs` |
| 95045 | 巨龙战役 Buff | `version;power;buffs` |
| 95046 | 巨龙战役清除积分 | `version;score` |
| 95047 | 巨龙战役起义攻击 | （未明确参数） |
| 95063 | 封魔殿战斗 | `stageId;ability;btlResult;todayPlay` 等 |
| 95064 | 封魔殿领奖 | `stageId;addItem;addCoin` |
| 95065 | 封魔殿购买奖励 | `stageId;buyTime;buyAll` |
| 95066 | 封魔殿首通奖励 | `stageId` |
| 95067 | 圣印突破 | `node;quality;sealQuality` |
| 95068 | 圣印升级 | `node;quality;sealQuality;att;def;hp;agi;black` 等 |
| 95069 | 圣印升阶 | `oldLevel;newLevel;exp` 或 `node;quality;sealLevel` |
| 95070 | 圣印激活技能 | `skillId;needPt;skillPtAll;skillPt` |
| 95071 | 圣印 CL 技能 | 同上 |

##### 夺宝 / 矿战 BOSS / 女神之家

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 10044 | 夺宝开始 | `teamId;memNum;quality;horse1;horse2` |
| 10045 | 夺宝协助 | 同上 |
| 10046 | 夺宝完成 | `deads` |
| 10047 | 夺宝抢劫 | `quality;isWin` |
| 21001 | 矿战 BOSS 进入 | `difficulty` |
| 21002 | 矿战 BOSS 正常离开 | `name;unlockRemain;unlockUsed` |
| 21003 | 矿战 BOSS 手动离开 | 同上 |
| 21004 | 矿战 BOSS 结束统计 | `roomId;name;unlockRemain;damage;stageClear;difficulty;resetGameStatus;score;teamSize;finalStage;bossId` |
| 21005 | 矿战 BOSS 队伍开始 | `name;difficulty` |
| 21006 | 矿战 BOSS 额外挑战购买 | `name;extraChallenge` |
| 21007 | 矿战 BOSS 额外解锁购买 | `name;extraUnlock` |
| 21008 | 矿战 BOSS 拍卖行获取门票 | `name` 等 |
| 21010 | 矿战 BOSS 挖矿掉落门票 | `name;rewardCountNormal;rewardCountHard` |
| 21027 | 金叶子激活 | `gear` |
| 21028 | 金叶子使用 | `gear` |
| 21050 | 女神之家合成女神 | `goddessId;1` |
| 21051 | 女神之家女神升级 | `goddessId;level` |
| 21052 | 女神之家女神升星 | `goddessId;star;stage` |
| 21053 | 女神之家房间重新布置 | `beautyScore;nextLevelGrid` |
| 21054 | 女神之家房间进入 | （无参数） |
| 21055 | 女神之家家具购买 | `itemId;count` 或 `modelId;count` |
| 21056 | 女神之家房间扩建 | （未明确参数） |
| 21057 | 女神之家美丽值 | `beautyScore` |
| 21058 | 女神之家访问次数 | （未明确参数） |
| 21059 | 女神之家觉醒层数 | `goddessId;maxFloor;talentNum` |
| 21060 | 女神之家扩层 | `maxLayer` |
| 21100 | 女神梦境副本战斗 | `stageId;btlResult` |
| 21101 | 女神梦境副本额外次数 | `extraAttempts` |

##### 拍卖 / 商店 / 基金 / 通行证

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 10038 | 拍卖行出售宝物 | `itemId;reqId` |
| 10039 | 拍卖行下架宝物 | `modelId;id` |
| 21130 | 博彩游玩 | `prize1;prize2;randomItem;playTime` |
| 21131 | 博彩商店购买 | `id;num;shopBuyCount` |
| 21132 | 博彩领取每日 | （无参数） |
| 21162 | BK 获取奖励 | `level` |
| 21163 | BK 奖励 | `level` |
| 21161 | BK 战斗 | `isWin` |
| 22020 | 购买欢乐币 | （未明确参数） |
| 22060 | 周年庆新通行证购买类型 | `packId;3` 或 `giftId;2` |
| 22070 | 定制礼包购买 | `directKind;packId;priceString;rewardString` |
| 22050 | 使用代金券 | `costVoucher;remainVoucher;directType;giftId;diamond` |
| 90031 | 充值商店 | （未明确参数） |
| 21273 | 充值商店购买日志 | （未明确参数） |
| 21274 | 充值商店转盘 | （未明确参数） |
| 21120 | 新充值奖励 | （未明确参数） |
| 21121 | 抢红包 | （未明确参数） |

##### 新手 / 社交 / 其他

| b_id | 含义 | 典型 `b_value` 参数 |
|---|---|---|
| 10012 | 添加好友 | `dstFriendId` |
| 10013 | 领取激活码 | （未明确参数） |
| 10026 | 玩家引导 | （未明确参数） |
| 10027 | 玩家首次战斗 | （无参数） |
| 3161 | 玩家首次战斗（复用） | （无参数） |
| 10000 | 充值行为标记 | （未明确参数） |
| 95054 | 首充 | `1/2/3/4;payNum` |
| 21151 | 大富翁加入 | （未明确参数） |
| 21152 | 大富翁积分 | （未明确参数） |
| 21153 | 大富翁积分排名 | （未明确参数） |
| 21162 | BK 获取奖励 | `level` |

##### b_value 字段说明

`b_value` 是**分号(`;`)分隔**的字符串，由 `BehaviorLog()` 将多个整数/字符串参数拼接而成：

```go
strArr := make([]string, 0)
for _, v := range param {
    // int/uint32/int32/uint64/int64/string 均转为字符串
    strArr = append(strArr, strconv.Format...)
}
bh.B_value = strings.Join(strArr, ";")
```

因此分析时通常需要按 `b_id` 解析对应位置的字段含义。例如：

- `b_id = 10001`（竞技场挑战）：`b_value` = `战斗结果;战前排名;战后排名`
- `b_id = 10028`（通天塔战斗）：`b_value` = `层数;怪物位置;战斗结果`
- `b_id = 22010`（英雄升级）：`b_value` = `英雄模板ID;升级前等级;升级后等级`

##### 查询示例

**查昨日竞技场参与人数及挑战次数**

```sql
SELECT
  COUNT(DISTINCT role_id) AS players,
  COUNT(*) AS battles
FROM gamelog_raw.v_presto_log_bhbehavior
WHERE game_id = 160
  AND ds = '<昨天ds>'
  AND b_id = 10001
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
```

**查昨日英雄养成行为分布**

```sql
SELECT
  b_id,
  COUNT(DISTINCT role_id) AS players,
  COUNT(*) AS events
FROM gamelog_raw.v_presto_log_bhbehavior
WHERE game_id = 160
  AND ds = '<昨天ds>'
  AND b_id IN (22010, 22011, 22012, 10003)
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY b_id
ORDER BY events DESC
```

> 完整枚举定义见 `C:\YZ_SVN\女2_ProHaiwai_LOA2_Intranet\server\src\proto\web.pb.go` 中 `BEHAVIOR`。

---

### gamelog_raw.v_presto_log_serpcu — 服务器 PCU（实时 T+0）

记录服务器同时在线峰值。

| 额外字段 | 类型 | 说明 |
|---|---|---|
| pcu | int | 当前同时在线人数 |

---

## 三、T+1 归档表（gamelog_odl）

与 `gamelog_raw` 对应，字段完全相同，数据延迟一天，适合历史报表。常见视图包括：

- `gamelog_odl.v_presto_log_rolelogin`
- `gamelog_odl.v_presto_log_rolereg`
- `gamelog_odl.v_presto_log_roleact`
- `gamelog_odl.v_presto_log_rolelogout`
- `gamelog_odl.v_presto_log_rolelvup`
- `gamelog_odl.v_presto_log_payrecharge`
- `gamelog_odl.v_presto_log_payconsume`
- `gamelog_odl.v_presto_log_paygift`
- `gamelog_odl.v_presto_log_rsproduce`
- `gamelog_odl.v_presto_log_rsstatechange`
- `gamelog_odl.v_presto_log_rslvup`
- `gamelog_odl.v_presto_log_bhrookie`
- `gamelog_odl.v_presto_log_bhbehavior`
- `gamelog_odl.v_presto_log_serpcu`

---

## 四、关于 ECO 快照表

游戏 160 后端**没有**使用 `plugin_uzdatacenter2017/eco` 快照体系，因此没有像 312 那样的：

- `gameeco_raw.v_presto_snap_rolecache`
- `gameeco_raw.v_presto_snap_itemcache`
- `gameeco_raw.v_presto_snap_dimcache`
- `gameeco_raw.v_presto_snap_packcache`

如需角色/道具/养成维度的“末态”分析，通常需基于 `gamelog_odl` 的事件流水（`rolelogin`、`rsproduce`、`rslvup`、`bhbehavior` 等）自行聚合。具体以数仓实际提供的视图为准。

---

## 示例 SQL

### 查昨日 DAU（登录人数）

```sql
SELECT COUNT(DISTINCT role_id) AS dau
FROM gamelog_raw.v_presto_log_rolelogin
WHERE game_id = 160
  AND ds = '<昨天ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
```

### 查今日实时充值

```sql
SELECT
  COUNT(DISTINCT role_id) AS payers,
  CAST(SUM(CAST(pay_money AS DOUBLE)) AS DECIMAL(18,2)) AS revenue
FROM gamelog_raw.v_presto_log_payrecharge
WHERE game_id = 160
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
WHERE game_id = 160
  AND ds >= '<7天前ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY ds
ORDER BY ds
```

### 查昨日新增角色

```sql
SELECT COUNT(DISTINCT role_id) AS new_roles
FROM gamelog_raw.v_presto_log_rolereg
WHERE game_id = 160
  AND ds = '<昨天ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
```

### 查各渠道昨日 DAU

```sql
SELECT opgame_id, COUNT(DISTINCT role_id) AS dau
FROM gamelog_raw.v_presto_log_rolelogin
WHERE game_id = 160
  AND ds = '<昨天ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY opgame_id
ORDER BY dau DESC
```

### 查昨日各玩法参与人数（按 b_id 汇总）

```sql
SELECT b_id, COUNT(DISTINCT role_id) AS players, COUNT(*) AS events
FROM gamelog_raw.v_presto_log_bhbehavior
WHERE game_id = 160
  AND ds = '<昨天ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY b_id
ORDER BY events DESC
LIMIT 30
```

### 查昨日钻石消耗去向

```sql
SELECT b_type, b_id, SUM(consume_diamond + consume_blackdiamond) AS total_diamond
FROM gamelog_raw.v_presto_log_payconsume
WHERE game_id = 160
  AND ds = '<昨天ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY b_type, b_id
ORDER BY total_diamond DESC
LIMIT 30
```

### 查昨日资源产出/消耗 TOP

```sql
SELECT
  rs_id,
  rs_type,
  CASE rs_behavior WHEN 1 THEN '产出' WHEN 2 THEN '消耗' WHEN 3 THEN '转移' END AS behavior,
  SUM(rs_quality) AS total_change,
  COUNT(DISTINCT role_id) AS players
FROM gamelog_raw.v_presto_log_rsproduce
WHERE game_id = 160
  AND ds = '<昨天ds>'
  AND SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'
GROUP BY rs_id, rs_type, rs_behavior
ORDER BY total_change DESC
LIMIT 30
```

### 查某玩家近 7 天行为轨迹

```sql
SELECT ds, b_id, b_value, zone_id, createtime
FROM gamelog_raw.v_presto_log_bhbehavior
WHERE game_id = 160
  AND ds >= '<7天前ds>'
  AND role_id = '<角色ID>'
ORDER BY createtime
LIMIT 200
```

---

## 固定报表口径

### KPI 日报

| 指标 | 来源表 | 口径 |
|---|---|---|
| DAU（日活） | `gamelog_raw.v_presto_log_rolelogin` | `COUNT(DISTINCT role_id)`，ds=今天，排除测试服 |
| 新增角色 | `gamelog_raw.v_presto_log_rolereg` | `COUNT(DISTINCT role_id)`，ds=今天，排除测试服 |
| 激活角色 | `gamelog_raw.v_presto_log_roleact` | `COUNT(DISTINCT role_id)`，ds=今天，排除测试服 |
| 付费人数 | `gamelog_raw.v_presto_log_payrecharge` | `COUNT(DISTINCT role_id)`，ds=今天 |
| 收入 | `gamelog_raw.v_presto_log_payrecharge` | `SUM(CAST(pay_money AS DOUBLE))`，ds=今天 |

> 默认使用 `gamelog_raw`；只有用户明确要求 T+1 / odl 时才使用 `gamelog_odl`。

### LTV 报表

按角色注册日分群：

- LTV1 = 注册当天累计充值 ÷ 当天新增人数
- LTV3 = 注册后前 3 天累计充值 ÷ 当天新增人数
- LTV7 / LTV15 / LTV30 同理

充值数据来自 `gamelog_raw.v_presto_log_payrecharge`（`game_id = 160`），通过 `role_id` 关联注册日分群。

---

## 查询注意事项

1. **`role_id` 是字符串**：所有表都按 `role_id = 'xxx'` 过滤，避免整数比较导致的全表扫描。
2. **`game_id` 是整数**：写 `game_id = 160`，不要加引号。
3. **`opgame_id` 来自 server_id 前 4 位**：如需从 server_id 反推，用 `CAST(SUBSTR(CAST(server_id AS VARCHAR), 1, 4) AS INTEGER)`。
4. **时间字段**：
   - `createtime` 是 `yyyy-MM-dd HH:mm:ss` 字符串；
   - `timestamp` 是 Unix 秒整数；
   - 按天统计用分区字段 `ds`（yyyyMMdd）。
5. **测试服过滤**：一般通过 `server_id` 第 5 位判断，但需以实际运营配置为准。
6. **货币口径**：`payrecharge.pay_money` 在代码中写死 `pay_currency = "USD"`，实际分析时建议结合运营侧货币换算表。
7. **无 ECO 快照**：养成/道具末态需从 `rsproduce`、`rslvup`、`bhbehavior`、`rolelogin` 等事件表自行聚合，不能直接用 `gameeco_raw` 快照。
8. **`rs_reason_id` / `gift_type` / `b_type` 含义**：这些字段通常对应 `GLOG_SOURCE` 枚举（见下方附录），可用于区分钻石/资源变动的业务来源。
9. **`rs_id` 在 `rs_type = 3`（货币）时**：对应 `RES_TYPE` 资源类型枚举（见下方附录），例如 1=金币、3=钻石、4=充值钻石。

---

## 附录 A：`GLOG_SOURCE` 枚举（常见值）

`GLOG_SOURCE` 用于标识资源/钻石变动的业务来源。在数仓表中主要出现位置：

- `payconsume.b_type` / `payconsume.b_id`
- `paygift.gift_type`
- `rsproduce.rs_reason_id`
- `rslvup.rs_property_id`

| 枚举值 | 业务含义 | 枚举值 | 业务含义 |
|---|---|---|---|
| 0 | 无 | 1 | GM |
| 2 | 测试 | 3 | 宝物附魔 |
| 4 | 宝物附魔开启 | 5 | 宝物刻印 |
| 6 | 家族签到 | 7 | 英雄加经验 |
| 8 | 合成英雄 | 9 | 培养英雄 |
| 10 | 创建英雄 | 11 | 英雄突破 |
| 12 | 英雄升阶 | 13 | 装备强化 |
| 14 | 合成道具 | 15 | 装备精炼 |
| 16 | 邮件 | 17 | 玩家创建 |
| 18 | 普通抽奖 | 19 | 超级抽奖 |
| 20 | 军衔升级 | 21 | BOSS 召唤 |
| 22 | 资源副本 | 23 | 剧情副本 |
| 24 | 激活坐骑 | 25 | 研究坐骑 |
| 26 | 商店 | 27 | 章节 |
| 28 | 家族捐献 | 29 | 通天塔 |
| 30 | 挂机战斗 | 31 | 家族清除 CD |
| 32 | 家族购买增益 | 33 | 家族购买高级增益 |
| 34 | 家族解封 BOSS | 35 | 家族 BOSS 通关 |
| 36 | 家族 BOSS 额外奖励 | 37 | 家族 BOSS 击杀奖励 |
| 38 | 宝物魔石合成 | 39 | 宝物魔石转移 |
| 40 | 商店刷新 | 41 | 背包道具出售 |
| 42 | 运镖打劫 | 43 | 运镖奖励 |
| 46 | 任务 | 47 | 商城 |
| 48 | 重置关卡 | 49 | 背包道具使用 |
| 50 | 竞技场历史排名奖励 | 51 | 竞技场掉落 |
| 52 | 竞技场清除 CD | 53 | 竞技场购买次数 |
| 54 | 回收装备 | 55 | 重置 |
| 56 | 关卡开宝箱 | 57 | 抽奖奖励 |
| 58 | 购买体力 | 59 | 玩家升级 |
| 60 | 好友赠送 | 61 | 每日任务重置 |
| 62 | 交换操作 | 63 | 竞技场换敌 |
| 64 | 竞技场战斗 | 65 | 竞技场重置 |
| 66 | 竞技场领取排名奖励 | 67 | 好友庆祝接收 |
| 68 | 好友庆祝发送 | 69 | 家族捐献奖励 |
| 70 | 家族创建 | 71 | 精英入侵 |
| 72 | 竞技博彩 | 73 | 竞技博彩奖励 |
| 74 | 竞技排名奖励 | 75 | 家族副本最后战斗 |
| 76 | 家族副本战斗 | 77 | 签到 |
| 78 | 英雄练习 | 79 | 机器人 |
| 80 | 场景 | 81 | 英雄练习胜利 |
| 82 | 英雄练习首杀 | 83 | 购买家族副本次数 |
| 84 | 宝物强化 | 85 | 活动 |
| 86 | 购买挂机精力 | 87 | 七日登录 |
| 88 | 七日商店 | 89 | 七日任务 |
| 90 | 英雄练习购买次数 | 91 | 回收宝物 |
| 92 | 回收英雄 | 93 | 家族副本通关 |
| 94 | 英雄重生 | 95 | 宝物重生 |
| 96 | 通天塔商店 | 97 | 神秘商店 |
| 98 | 竞技场商店 | 99 | 挂机商店 |
| 100 | 家族商店 | 101 | 刷新通天塔商店 |
| 102 | 刷新神秘商店 | 103 | 刷新竞技场商店 |
| 104 | 刷新挂机商店 | 105 | 刷新家族商店 |
| 106 | 购买挂机 PVP 掠夺 | 107 | 充值钻石 |
| 108 | 宝物一键强化 | 109 | 家族踢人 |
| 110 | 坐骑升级 | 111 | 一键研究坐骑 |
| 112 | VIP 奖励 | 113 | 挂机 BOSS 战斗 |
| 114 | 挂机分享奖励 | 115 | 挂机领取背包奖励 |
| 116 | 挂机 PVP | 117 | 挂机切换 |
| 118 | 过期 | 119 | 家族科技 |
| 120 | 购买家族 BOSS 次数 | 121 | 宝物 Changez 开启 |
| 122 | 宝物 Changez 关闭 | 123 | 战场结算 |
| 124 | 家族 BOSS 奖励 | 125 | 首充 |
| 126 | 激活码 | 127 | 英雄装备宝物 |
| 128 | 客户端下载 | 129 | 网页保存 |
| 130 | 战场称号奖励 | 131 | 战场商店 |
| 132 | 刷新战场商店 | 133 | 挂机 PVP 战斗 |
| 134 | 挂机创建 | 135 | 挂机 PVP 战斗免疫 |
| 136 | 购买次数 | 137 | 家族 BOSS 鼓舞 |
| 138 | 超值购购买 | 139 | 超值购充值 |
| 140 | 家族 BOSS 击杀 | 141 | 超级抽奖 |
| 142 | 超级购奖励 | 143 | QQ 购买商品 |
| 144 | 新手指引 | 145 | 日志 1 |
| 146 | 日志 2 | 147 | 拍卖行出售税费 |
| 148 | 拍卖行购买 | 149 | 拍卖行出售错误返还 |
| 150 | 拍卖行购买错误返还 | 151 | 拍卖行设置出价 |
| 152 | 跨服拍卖 | 153 | 开基金购买 |
| 154 | 开基金福利 | 155~162 | QQ 相关礼包 |
| 163 | 装备加星 | 164 | 跨服竞技场购买次数 |
| 165~169 | 拍卖行相关 | 171~174 | 拍卖行占位 |
| 175 | 商城首页 | 176 | 装备重生 |
| 177~188 | 平台/渠道相关奖励 | 189 | 激活称号 |
| 190~192 | 十四日登录/商店/任务 | 193 | 神格插入 |
| 194 | 周掉落 | 195 | 战场开始 |
| 196 | 战场补签 | 197 | 跨服竞技场助威 |
| 198 | 顺网 VIP | 199~200 | 开服挑战排行 |
| 201 | 绝路购买次数 | 202 | 跨服竞技场助威信息 |
| 203~209 | 春节/情人节活动 | 210~212 | 购买次数（跨服竞技） |
| 213 | 元宵商店 | 214 | QQ 邀请 |
| 215 | 家族远征战斗 | 216 | 跨服竞技场战斗积分 |
| 217 | 战斗掉落 | 218~221 | 国战投票 |
| 222~230 | QQ 联合礼包 | 231 | 女神积分奖励 |
| 232 | 女神领取 | 233 | 女神 |
| 234~237 | 跨服竞技场/白色情人节商店 | 239 | 白色情人节 |
| 240~241 | QQ 联合登录礼包 | 242~244 | 世界 BOSS 奖励/伤害/击杀 |
| 245 | 白色情人节 | 246 | 团购购买 |
| 247 | 团购领奖 | 248 | 团购结束 |
| 249 | 世界 BOSS 超级奖励 | 250 | 团购设置资源类型 |
| 251 | 购买世界 BOSS 次数 | 252 | 白色情人节送巧克力 |
| 253 | G360 加速奖励 | 254~255 | QQ 礼包 |
| 256~261 | 转盘单抽/十连/奖励/商店 | 262 | 英雄天赋升级 |
| 263~264 | 转盘商店 | 265~271 | 家族远征相关 |
| 272 | QQ 花样礼包 | 273 | 宠物状态 |
| 274 | 宠物升星 | 275 | 家族远征购买次数 |
| 277 | 宠物升级 | 278~279 | 鲜花节 |
| 280~283 | 幸运树 | 284~286 | 秘境探险 |
| 287 | 镜像 | 288~290 | 幸运树助威/重置 |
| 291 | 秘境探险 | 293 | 找回资源 |
| 294 | 宠物升阶 | 295~296 | 幸运树 |
| 297 | 回收宠物 | 300~302 | 基金 |
| 303 | 国战城市移动 CD 清除 | 304~307 | 扫雷 |
| 310~313 | 母亲节 | 314~315 | 时装洗练/制作 |
| 316~321 | 跨服组队 | 322 | 宝物黄金合成 |
| 323 | 国战报名 | 350~355 | 端午节 |
| 356 | 宠物唤醒 | 357~360 | 国战 |
| 361 | 国战每日城市 | 362~363 | 国战排名军功奖励 |
| 370 | 七日大任务 | 371 | 宠物唤醒玩法 |
| 372~374 | 宝物重塑/净化/锁定 | 375 | 客户端游戏日志 |
| 376~377 | 跨服组队决赛下注/奖励 | 378~382 | 神器锻造/加星/进阶/洗练/重铸 |
| 383~384 | 过期钻石出/入 | 385 | 金钻通宝兑换 |
| 390~394 | 爬塔 | 395~401 | 矿战 |
| 410 | 国战放置祖龙 | 415~416 | 跨服转盘 |
| 419 | 战斗 PVP | 425 | 军团创建 |
| 430~434 | 卡牌 | 440~442 | 跨服转盘购买/积分/清除 |
| 443~448 | 国战军团 | 450~451 | 国战骷髅炸弹/攻击机关 |
| 452~466 | 结婚相关 | 467~469 | 坐骑占星 |
| 470 | 装备加星突破 | 471~472 | 坐骑升阶/开启保护 |
| 473~475 | 结婚 | 476 | 坐骑装备强化 |

> 完整枚举见 `C:\YZ_SVN\女2_ProHaiwai_LOA2_Intranet\server\src\proto\web.pb.go` 中 `GLOG_SOURCE`。

---

## 附录 B：`RES_TYPE` 资源类型枚举（常见值）

`RES_TYPE` 用于标识 `rsproduce`/`rslvup` 等资源流水表中的资源/货币类型。

| 枚举值 | 含义 | 枚举值 | 含义 |
|---|---|---|---|
| 1 | 金币 | 2 | 体力 |
| 3 | 钻石 | 4 | 充值钻石 |
| 5 | 竞技场代币 | 6 | 公会贡献/勇者印记 |
| 7 | 挂机商店代币（屠魔印记） | 8 | 挂机精力 |
| 9 | 缺失/金钻（推测） | 10 | 玩家经验 |
| 11 | 英雄经验 | 12 | 深渊代币（地狱节杖） |
| 14 | 跨服战场荣誉 | 15 | 将魂 |
| 17 | 跨服竞技货币 | 18 | 公会跨服远征货币 |
| 19 | 跨服组队货币 | 20 | 物品/道具 |
| 22 | 每日任务积分 | 23 | 每日竞技场积分 |
| 24 | 跨服个人竞技助威点 | 25 | 将军竞选选票 |
| 26 | 元帅竞选选票 | 27 | 团购券 |
| 28 | 团购积分 | 30 | 英雄 |
| 31 | 转盘幸运币 | 33 | 兽魂 |
| 34 | 秘境积分 | 35 | 幸运树幸运币 |
| 36 | 扫雷代币（魔灵币） | 37 | 母亲节代币 |
| 39 | 端午节积分代币 | 42 | 战宠玩法代币 |
| 43 | 跨服转盘玩法代币 | 44 | 混沌远征湮没之证 |
| 45 | 混沌远征湮没之眼 | 46 | 每日福利低级代币 |
| 47 | 每日福利高级代币 | 48 | 每日福利积分 |
| 50 | 挖矿玩法产出（矿石） | 60 | 国战功勋 |
| 61 | 国战军功 | 63 | 军团贡献 |
| 64 | 荣耀徽记 | 65~66 | 爬塔代币 |
| 70 | 挖矿额外产出（永恒结晶） | 71~73 | 国战军团资源 |
| 90 | 邪能陨铁 | 91 | 卡牌兑换资源 |
| 92 | 坐骑占星资源 | 93 | 一元抢购资源 |
| 94 | 勇士联赛代币 | 95 | 罪恶之地代币 |
| 96 | 末日回响代币 | 97 | 金钻通宝 |
| 101 | 结婚互动资源 | 102 | 充值额度 |
| 103 | 闪钻（仅限当日使用） | 105 | 巨龙战役代币 |
| 106 | 恶魔之岛战役代币 | 107 | 恶魔之岛战役勋章 |
| 108 | 矿战 BOSS 代币 | 109 | 女神梦境入场券 |
| 120 | 宝石 | 122 | 宝石（神佑） |
| 500 | 新深渊代币 | 501 | 充值钻石代金券 |
| 502 | 钻石代金券 | 503 | 月之印记 |
| 504 | 天使之羽 | 505 | 女神之泪 |
| 510 | 个人跨服争霸新代币 | 518 | 世界争霸赛代币 1 |
| 519 | 世界争霸赛代币 2 | 520 | 渔场免费体力 |
| 521 | 渔场付费体力 | 671 | 每周任务积分 |
| 672 | 每周任务代币 | 1314 | 微端通行经验 |

> 完整枚举见 `C:\YZ_SVN\女2_ProHaiwai_LOA2_Intranet\server\src\game\drop.go` 中 `RES_TYPE_*` 定义。

---

## 玩家分群行为分析模板

模板文件：`app/templates/player_segment.json`

### 分群口径

| 群体 | 定义 |
|---|---|
| 付费玩家 | 分析窗口内有过真实货币充值（`gamelog_raw.v_presto_log_payrecharge`） |
| 沉默玩家 | 分析窗口前 30 天内曾真实货币充值，但窗口内未充值 |
| 免费玩家 | 分析窗口内活跃，且 `gamelog_raw.v_presto_log_rolelogin.role_paid = 0` |

- 分析窗口默认：近 7 天（用户可在提问时覆盖）。
- 沉默窗口默认：30 天。
- Top 明细默认：每群 100 人。

### 飞书触发词

`玩家分群`、`付费点分析`、`沉默分析`、`免费玩家行为`、`玩家行为分析`

### 输出 Sheet

1. **概览**：三群人数、付费金额、ARPU、ARPPU。
2. **付费玩家付费点**：按 `pay_itemid` + `pay_type` 汇总充值金额、次数、客单价。
3. **付费玩家玩法参与**：基于 `gamelog_raw.v_presto_log_bhbehavior`，对比付费玩家与全量活跃玩家的 `b_id` 行为参与率。
4. **沉默玩家现状**：沉默玩家在分析窗口内的 `b_id` 行为参与、沉默窗付费。
5. **免费玩家行为**：免费玩家的 `b_id` 行为参与、平均活跃天数、等级/VIP 分布。
6. **Top 明细**：付费 Top、沉默 Top、免费活跃 Top 名单。

### 主要表

- `gamelog_raw.v_presto_log_rolelogin` — 活跃玩家、role_paid
- `gamelog_raw.v_presto_log_payrecharge` — 真实货币充值
- `gamelog_raw.v_presto_log_bhbehavior` — 玩法参与（`b_id`）

### 示例

输入：

```
160 玩家分群 近7天
```

输出：多 Sheet Excel，包含上述 6 个 Sheet。

