# Feishu 数仓查询机器人 — 项目指引

## 项目概述

一个基于飞书机器人 + Claude CLI + MCP 的数据仓库查询服务。用户用中文向飞书机器人提问，Bot 调用 Claude CLI 生成并执行 Presto SQL，返回中文总结和 CSV/Excel 结果。

## 查询路由

Bot 不再依赖固定关键词判断是否需要分步查询。每次提问时：

1. `query_analyzer` 会读取当前 workspace 的 `CLAUDE.md`（含游戏 schema、表映射、业务规则）。
2. 由 LLM 判断问题是否涉及：
   - 跨多张表 JOIN
   - 多时间段对比 / 归因
   - 先找目标对象再查明细（如 Top 付费玩家 → 道具/行为）
3. 若判定为复杂查询，自动拆分为最多 5 步，每步一次 SQL，结果合并为 Excel。
4. 若 `CLAUDE.md` 中的表映射明显不足（少于 2 个库表提及），系统会自动扫描配置的游戏源码目录，补充日志函数 → 数仓表映射。

默认所有查询仍走 RAW 库；只有用户明确要求 T+1/odl 时才加 `-- use_odl`。

**玩家信息查询要求**：查询具体玩家的信息时（如"玩家 XXX 昨日的付费/道具/行为"），提问需要额外提供该玩家的**昵称**和**所在服务器**，用于定位 role_id / server_id。未提供时 Bot 会先向用户确认这两项信息，而不是凭猜测查询。

## 聊天群游戏绑定

- `config.json` 的 `bot.chat_games` 可把聊天群绑定到固定游戏：`"bot": {"chat_games": {"oc_群ID": 312}}`，重启生效；绑定的 game_id 必须在 `games` 中已配置，否则启动时报错。
- 已绑定的群只查该游戏：跳过数字前缀与别名匹配；显式输入其他游戏前缀会被拒绝并提示。未绑定的群保持原有解析（前缀 → 别名 → 默认）。
- 群里发 `chatid` 可获取该群的 chat_id，用于填写 `chat_games`。

## 静态配置库查询

- 每个游戏可在 `config.json` 的 `games[]` 条目内配置可选的 `config_db` 段（MySQL 连接信息 + `schema` 指向 `gm_schema_<game_id>.md`），用于查询道具名称、活动信息等静态配置。
- 配置后子 Claude 可使用 `mcp__dquery__query_config` 工具（只读：仅 SELECT / SHOW / DESCRIBE / EXPLAIN），与数仓 `query_data` 相互独立：两个库的表名不可混用，`query_config` 的 SQL 不需要 game_id 条件。
- `config_db` 建议使用只有 SELECT 权限的只读 MySQL 账号（代码层另有 configdb 护栏，双保险）；未配置的游戏调用该工具直接报错。
- 配置库表结构文档为 `gm_schema_<game_id>.md`，与数仓的 `schema_<game_id>.md` 是两个不同数据库的文档，勿复用。

### 39 静态配置库表映射（从 GM 代码 `C:\YZ_SVN\女神GM\nslm1` 确认）

该 GM 后台的 `models/ModelBase.php` 按**类名转小写**作为 MySQL 表名（下划线保留），因此：

| 配置概念 | PHP Model 类 | 对应 MySQL 表 | 常见用途 |
|---|---|---|---|
| 活动配置 | `Activity` | `activity` | 活动列表、活动开关状态 |
| 活动分组 | `Activity_Group` | `activity_group` | 活动分组/批次 |
| 活动奖励 | `Activity_Reward` | `activity_reward` | 活动奖励配置 |
| 活动操作 | `Activity_Action` | `activity_action` | 活动动作/触发条件 |
| 活动倍率 | `Activity_Ratio` | `activity_ratio` | 活动倍率参数 |
| 游戏资源 | `Game_Resource` | `game_resource` | 游戏内资源/道具类配置 |
| 礼包配置 | `Gift_Bag` | `gift_bag` | GM 礼包/兑换码配置 |
| 服务器区服 | `Server` | `server` | 区服名称、server_id、运营商、状态 |
| 游戏 API | `Game_Api` | `game_api` | 区服接口配置 |
| 游戏参数 | `Game_Arg` | `game_arg` | 游戏运行参数 |
| 游戏功能 | `Game_Func` | `game_func` | 功能开关 |
| 游戏邮件 | `Game_Mail` | `game_mail` | 邮件模板 |
| 游戏公告 | `Game_Notice` | `game_notice` | 公告配置 |
| 游戏菜单 | `Game_Menu` | `game_menu` | GM 菜单配置 |
| 运营账号 | `Operator` | `operator` | 运营商信息 |

> **说明**：实际字段需以配置库 `DESC <表名>` 结果为准；不确定表名时先用 `SHOW TABLES` 探索。`Server` 表通常可按 `game_id = 39` 过滤，`dc_server_id` 与数仓中的 `server_id` 对应，可用于把玩家数据与区服名称关联。

### 160 静态配置库表映射（从 GM 代码 `C:\YZ_SVN\女神GM\nslm2` 确认）

该 GM 后台的 `models/ModelBase.php` 同样按**类名转小写**作为 MySQL 表名（下划线保留）。与 nslm1 相比，nslm2 在活动、英雄、道具/资源方面模型更丰富：

| 配置概念 | PHP Model 类 | 对应 MySQL 表 | 常见用途 |
|---|---|---|---|
| 活动配置 | `Activity` | `activity` | 活动列表、活动开关状态 |
| 活动分组 | `Activity_Group` | `activity_group` | 活动分组/批次 |
| 活动奖励 | `Activity_Reward` | `activity_reward` | 活动奖励配置 |
| 活动操作 | `Activity_Action` | `activity_action` | 活动动作/触发条件 |
| 活动倍率 | `Activity_Ratio` | `activity_ratio` | 活动倍率参数 |
| 活动类型 | `Activity_Type` | `activity_type` | 活动类型定义 |
| 活动答题 | `Activity_Question` | `activity_question` | 答题活动题库 |
| 活动题目奖励 | `Activity_Questionreward` | `activity_questionreward` | 答题活动奖励配置 |
| 英雄配置 | `Game_Hero` | `game_hero` | 英雄/武将静态配置 |
| 道具配置 | `Game_Item` | `game_item` | 道具 ID、名称、类型 |
| 道具参数 | `Game_Itemarg` | `game_itemarg` | 道具扩展参数 |
| 游戏资源 | `Game_Resource` | `game_resource` | 通用资源/货币配置 |
| 资源参数 | `Game_Res` | `game_res` | 资源详细参数 |
| 商城配置 | `Game_Mall` | `game_mall` | 商城/付费点配置 |
| 礼包配置 | `Gift_Bag` | `gift_bag` | GM 礼包/兑换码配置 |
| 服务器区服 | `Server` | `server` | 区服名称、server_id、运营商、状态 |
| 运营账号 | `Operator` | `operator` | 运营商信息 |
| 渠道游戏 | `Opgame` | `opgame` | 渠道与游戏的关联关系 |
| 全服信息 | `AllServerInfo` | `allserverinfo` | 全服合服/跨服信息 |
| 单服信息 | `SingleServerInfo` | `singleserverinfo` | 单服详细信息 |
| 网关配置 | `Cgateway` | `cgateway` | 网关配置 |
| 区服配置 | `Cserver` | `cserver` | 区服连接/运行配置 |

> **说明**：实际字段需以配置库 `DESC <表名>` 结果为准；不确定表名时先用 `SHOW TABLES` 探索。游戏 160 的数仓 `role_id` 是字符串，`Server` 表中的 `dc_server_id` 通常与数仓中的 `server_id` 对应。

### 312 静态配置库表映射（从 GM 代码 `C:\YZ_SVN\女神GM\nslm3` 确认）

该 GM 后台的 `models/ModelBase.php` 同样按**类名转小写**作为 MySQL 表名（下划线保留）。与 nslm1/nslm2 同源，结构与 nslm2 高度相似，但额外包含日志来源相关模型：

| 配置概念 | PHP Model 类 | 对应 MySQL 表 | 常见用途 |
|---|---|---|---|
| 活动配置 | `Activity` | `activity` | 活动列表、活动开关状态 |
| 活动分组 | `Activity_Group` | `activity_group` | 活动分组/批次 |
| 活动奖励 | `Activity_Reward` | `activity_reward` | 活动奖励配置 |
| 活动操作 | `Activity_Action` | `activity_action` | 活动动作/触发条件 |
| 活动倍率 | `Activity_Ratio` | `activity_ratio` | 活动倍率参数 |
| 活动类型 | `Activity_Type` | `activity_type` | 活动类型定义 |
| 活动答题 | `Activity_Question` | `activity_question` | 答题活动题库 |
| 活动题目奖励 | `Activity_Questionreward` | `activity_questionreward` | 答题活动奖励配置 |
| 英雄配置 | `Game_Hero` | `game_hero` | 英雄/女神静态配置 |
| 道具配置 | `Game_Item` | `game_item` | 道具 ID、名称、类型 |
| 道具参数 | `Game_Itemarg` | `game_itemarg` | 道具扩展参数 |
| 游戏资源 | `Game_Resource` | `game_resource` | 通用资源/货币配置 |
| 资源参数 | `Game_Res` | `game_res` | 资源详细参数 |
| 日志来源 | `Game_LogOrigin` | `game_logorigin` | 日志来源/埋点配置 |
| 商城配置 | `Game_Mall` | `game_mall` | 商城/付费点配置 |
| 礼包配置 | `Gift_Bag` | `gift_bag` | GM 礼包/兑换码配置 |
| 服务器区服 | `Server` | `server` | 区服名称、server_id、运营商、状态 |
| 运营账号 | `Operator` | `operator` | 运营商信息 |
| 渠道游戏 | `Opgame` | `opgame` | 渠道与游戏的关联关系 |
| 全服信息 | `AllServerInfo` | `allserverinfo` | 全服合服/跨服信息 |
| 单服信息 | `SingleServerInfo` | `singleserverinfo` | 单服详细信息 |
| 网关配置 | `Cgateway` | `cgateway` | 网关配置 |
| 区服配置 | `Cserver` | `cserver` | 区服连接/运行配置 |

> **说明**：实际字段需以配置库 `DESC <表名>` 结果为准；不确定表名时先用 `SHOW TABLES` 探索。游戏 312 的数仓 `role_id` 在 `gameeco_raw` 表中是 BIGINT、`gamelog_raw` 表中也常为 BIGINT，`Server` 表中的 `dc_server_id` 通常与数仓中的 `server_id` 对应。

## 游戏源码参考

- **游戏 ID 312 服务端代码库**：`C:\YZ_SVN\女3_ProGoddessIII\branches\server`
  - 用于核对玩家行为日志、道具获得/消耗日志与数仓表（`gamelog_raw` / `gameeco_raw` / `gamelog_odl`）的映射关系。
- **游戏 ID 160 服务端代码库**：`C:\YZ_SVN\女2_ProHaiwai_LOA2_Intranet\server`
  - 用于核对 160 项目玩家行为日志与数仓表（`gamelog_raw` / `gamelog_odl`）的映射关系。
- **游戏 ID 39 服务端代码库**：`C:\YZ_SVN\女1_后端_ProM_Dev\php_trunk`
  - 用于核对 39 项目（女1）玩家行为日志与数仓表（`raw_scribe_log`）的映射关系。
- **游戏 ID 39 GM 后台代码库**：`C:\YZ_SVN\女神GM\nslm1`
  - 用于确认 39 项目静态配置库（`config_db` 对应 MySQL 库）的表结构。该 GM 后台通过 `models/ModelBase.php` 按“类名小写”规则映射 PHP Model 到 MySQL 表名；`config_db` 应指向与 GM 后台相同的配置库。
- **游戏 ID 160 GM 后台代码库**：`C:\YZ_SVN\女神GM\nslm2`
  - 用于确认 160 项目静态配置库（`config_db` 对应 MySQL 库）的表结构。与 nslm1 同源，同样通过 `models/ModelBase.php` 按“类名小写”映射 Model 到 MySQL 表名，但活动、英雄、道具/资源、区服相关模型更丰富。
- **游戏 ID 312 GM 后台代码库**：`C:\YZ_SVN\女神GM\nslm3`
  - 用于确认 312 项目静态配置库（`config_db` 对应 MySQL 库）的表结构。与 nslm2 高度同源，同样通过 `models/ModelBase.php` 按“类名小写”映射 Model 到 MySQL 表名，额外包含日志来源相关模型。
  - 用于核对 255 项目玩家行为日志与数仓表（`gamelog_raw` / `gameeco_raw`）的映射关系。

### 312 道具/玩家行为日志映射（从源码确认）

| 行为 | 代码入口 | change_type | 推荐数仓表 |
|---|---|---|---|
| 玩家获得道具 | `src/ns3/aes_game/module_item.go` → `execReward` → `Log_RoleItem` | `1` | `gameeco_raw.v_presto_log_roleitem` |
| 玩家使用/消耗道具 | `src/ns3/aes_game/module_item.go` → `method_execConsume` → `Log_RoleItem` | `2` | `gameeco_raw.v_presto_log_roleitem` |
| 货币/资源变动 | `Log_RoleRes` | `1`=获得 / `2`=消耗 | `gameeco_raw.v_presto_log_roleres` |
| 玩法参与/高阶行为 | `Log_RoleBehavior` / `BhBehavior` | — | `gameeco_raw.v_presto_log_rolebehavior` / `gamelog_raw.v_presto_log_bhbehavior` |

> **注意**：行为日志 `RoleBehavior` 没有 `item_id` / 数量字段；要查“玩家获得/使用了哪些道具、各多少”，必须走 `gameeco_raw.v_presto_log_roleitem`。常用过滤：`game_id = 312`、`substr(server_id, 5, 1) != '4'`、`role_type = 1`。

### 160 道具/玩家行为日志映射（从源码确认）

| 行为 | 代码入口 | rs_type / rs_behavior | 推荐数仓表 |
|---|---|---|---|
| 玩家获得道具 | `src/game/bag.go` → `AddItem` → `RsProduceLog` | `rs_type = 1`, `rs_behavior = 1` | `gamelog_raw.v_presto_log_rsproduce` |
| 玩家使用/消耗道具 | `src/game/bag.go` → `consumeItemById` / `consumeItemByItemId` → `RsProduceLog` | `rs_type = 1`, `rs_behavior = 2` | `gamelog_raw.v_presto_log_rsproduce` |
| 英雄/武将获得/消耗 | `src/game/...` → `RsProduceLog` | `rs_type = 2` | `gamelog_raw.v_presto_log_rsproduce` |
| 货币/资源变动 | `PayConsume` / `PayGift` / `RsProduce(rs_type=3)` | — | `gamelog_raw.v_presto_log_payconsume` / `paygift` / `rsproduce` |
| 玩法参与/高阶行为 | `src/depend/datacenter/BhBehavior.go` → `BehaviorLog` | — | `gamelog_raw.v_presto_log_bhbehavior` |

> **注意**：游戏 160 **没有** `RoleItem` / `RoleRes` / `RoleBehavior` 分层，道具/资源统一走 `RsProduce` Action，默认数仓表为 `gamelog_raw.v_presto_log_rsproduce`（实时 T+0）。仅当用户明确要求 T+1 / odl 时才用 `gamelog_odl`，需要在 SQL 开头单独一行加 `-- use_odl`。常用过滤：`game_id = 160`、`rs_type = 1`、`rs_behavior = 1/2`。`role_id` 是字符串，比较时加引号。

### 39 道具/玩家行为日志映射（从源码确认）

游戏 39 的 Scribe 数据中心日志统一落在 **`raw_scribe_log`** 库，表名与后端 `category` 后缀一致。查询时必须带 `game_id = 39`。

| 行为 | 代码入口 | 类型/字段 | 数仓表 |
|---|---|---|---|
| 玩家登录 | `User::login()` → `Tracer::login_tracer` | `login_tracer = 1003` | `raw_scribe_log.login` |
| 玩家注册/激活 | `UserRegister::register()` → `Tracer::register_tracer` | `register_tracer = 1002` | `raw_scribe_log.est` |
| 充值 | `passport.php::chargeAction()` → `Tracer::cash_charge_tracer` / `direct_charge_tracer` | `600` / `601` | `raw_scribe_log.pay` |
| 玩家获得钻石/货币 | `User::raiseField()` → `Logger::logExchangePack()` → `Tracer::cash_tracer` amount>0 | `category = 39_curr` | `raw_scribe_log.curr` |
| 玩家消耗钻石/货币 | `User::reduceField()` → `Logger::logExchangeCost()` → `Tracer::cash_tracer` amount<0 | `category = 39_prop` / `39_sub` | `raw_scribe_log.prop` / `sub` |
| 在线人数 / PCU | `UserCommon::getOnlineNum()` → `Tracer::user_online_tracer` | `1016` | `raw_scribe_log.ser` |

> **字段约定**：`raw_scribe_log.*` 表中的 `iuid` 是玩家内部唯一 ID，`ouid` 是平台账号/通行证；业务字段在 `custom_pra1` ~ `custom_pra8` 中，具体含义见 `schema_39.md`。**过滤游戏必须使用字符串 `gameid = '39'`，不要写 `game_id = 39`，后者会导致全表扫描超时。** 数值列（如 `custom_pra3`）在 Presto 中是 VARCHAR，求和/排序时必须 `CAST(... AS BIGINT)` 或 `CAST(... AS DOUBLE)`。
>
> **MySQL 日志队列**：`log_exchange_pack/cost`、`log_activity_num`、`t_log_item` 等是后端 MySQL 异步日志表，**未接入 `raw_scribe_log`**。若后续确认已同步到 Presto，再补充对应库表名；目前不要让 LLM 直接查询这些表。
>
> **库选择**：游戏 39 只使用 `raw_scribe_log`，不要使用 `gamelog_raw` / `gamelog_odl` / `gameeco_raw` 等 312/160 项目的库名。

### 255 道具/玩家行为日志映射（从源码确认）

游戏 255 同时存在 **Scribe 实时 KPI 日志** 和 **DTS（Data Warehouse SDK）ECO 日志** 两套体系：

- KPI 实时日志（登录/注册/充值/升级/在线/行为等）→ `gamelog_raw`
- ECO 实时日志（角色/道具/资源/养成/行为/公会等快照与流水）→ `gameeco_raw`

| 行为 | 代码入口 | 关键字段 | 推荐数仓表 |
|---|---|---|---|
| 玩家登录 | `server/core/player_state.go` → `EVENT_LOGIN` | — | `gamelog_raw.v_presto_log_rolelogin` |
| 玩家注册/创角 | `server/core/base_scribe.go` → `TraceRoleReg` | — | `gamelog_raw.v_presto_log_rolereg` |
| 充值 | `server/core/base_scribe.go` → `TracePayRecharge` | `pay_money = action.Amount / 100` | `gamelog_raw.v_presto_log_payrecharge` |
| 钻石/货币获得 | `server/core/base_scribe.go` → `TraceDiamond` (amount>0) | `gift_type` | `gamelog_raw.v_presto_log_paygift` |
| 钻石/货币消耗 | `server/core/base_scribe.go` → `TraceDiamond` (amount<0) | `consume_type` | `gamelog_raw.v_presto_log_payconsume` |
| 通用资源（金币/体力/钻石等）变动 | `server/core/base_prize.go` → `commit_item` → `EVENT_ITEM_CHANGED` | `change_type = 产出/消耗` | `gameeco_raw.v_presto_log_roleres` |
| 英雄获得 | `server/core/base_dts.go` → `EVENT_HERO_GET` → `RoleItem()` | `item_type = 英雄` | `gameeco_raw.v_presto_log_roleitem` |
| 玩法参与/高阶行为 | `server/core/base_dts.go` → `createRoleBehaviorData()` | `b_type` / `b_id` / `b_param` | `gameeco_raw.v_presto_log_rolebehavior` |
| 在线人数 / PCU | `server/core/base_scribe.go` → `EVENT_ACTIVE_CONNECTIONS` | `pcu` | `gamelog_raw.v_presto_log_serpcu` |

> **注意**：
> - 255 的 `gamelog_raw` 中 `role_id` 通常为**字符串**，`gameeco_raw` 中 `role_id` 为 **BIGINT**；过滤时注意类型匹配。
> - `gameeco_raw` 的 `game_id` 为**字符串** `'255'`，`gamelog_raw` 的 `game_id` 为**整数** `255`。
> - 默认所有查询走 RAW 库（`gamelog_raw` / `gameeco_raw`）；仅当用户明确要求 T+1 / ODL 时，在 SQL 开头加 `-- use_odl` 切换到 `gamelog_odl` / `gameeco_odl`。
> - 常用过滤：`game_id = 255` / `game_id = '255'`、`SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'`（排除测试服）。
> - 完整字段与示例 SQL 见 `schema_255.md`。

## 目录结构

```
app/                # 主应用代码
  bot.py            # 飞书消息处理、查询路由
  claude_cli.py     # 调用 claude 子进程
  mcp_server.py     # dquery MCP server（暴露 query_data 工具）
  configdb.py       # 静态配置 MySQL 库只读护栏与查询执行
  query_planner.py  # 复杂查询自动拆分
  reports.py        # 固定报表（KPI / LTV / 月度充值榜等）
  workspace.py      # 为每次对话生成 Claude 工作区/规则
  dataapi.py        # 异步 Presto 数据仓库 API 封装
  sqlguard.py       # SQL 权限/安全校验
  db_rewrite.py     # ODL -> RAW 库自动改写
  dquery.py         # CSV/Excel 结果合并
  store.py          # SQLite 会话/日志/缓存
  config.py         # 配置读取
config.json         # 运行时配置（含密钥，已 gitignored）
schema_312.md      # 312 游戏表结构文档
schema_160.md       # 160 游戏表结构文档
schema_255.md       # 255 游戏表结构文档
tests/              # pytest 单元测试
debug/              # 调试脚本
run_bot.bat         # Windows 启动脚本
```

## 开发约定

- **Python 版本**：3.12+
- **依赖**：通过 `requirements.txt` 管理，不要未经用户同意安装新包。
- **编码**：所有文件使用 UTF-8。
- **测试**：新增逻辑必须配 `tests/test_*.py` 或 `debug/test_*.py`。运行全部测试：
  ```bash
  python -m pytest tests/ -q
  ```
- **MCP server 子进程**：子 Claude CLI 只暴露 `mcp__dquery__query_data`，禁用其他工具（见 `.claude/settings.json`）。
- **复杂查询**：`query_planner.is_complex()` 命中时，自动拆分为最多 5 步，每步一次 Claude CLI 调用，结果保存为 `results/query_N.csv`，最后合并为 `result.xlsx`。
- **库选择**：默认 KPI/日志用 `gamelog_raw`；ECO 流水/行为/道具表用 `gameeco_raw`；游戏 39 统一使用 `raw_scribe_log`；只有用户明确要求 T+1/odl 时才用 `gamelog_odl`。
- **敏感信息**：`config.json` 已加入 `.gitignore`，不得提交。

## 常用命令

```bash
# 启动飞书机器人
python app/run_bot.py
# 或 Windows 批处理
run_bot.bat

# 运行全部测试
python -m pytest tests/ -q

# 调试 MCP server
python debug/test_mcp_server.py

# 调试复杂查询规划
python debug/test_query_planner.py

# 调试固定报表
python debug/test_reports.py
```

## Git 工作流

- **不要直接提交到 main/master**。功能开发前确认当前分支，必要时新建分支。
- **自动提交规则**：
  1. 每次完成一个独立功能/修复后，先运行测试通过。
  2. `git status` 确认变更范围。
  3. 提交信息使用中文，格式：`<type>: <简短描述>`，例如：
     - `feat: 新增复杂查询自动拆分工作流`
     - `fix: 修复 help 触发词误匹配问题`
     - `test: 增加 query_planner 单元测试`
  4. 提交结尾添加：
     ```
     Co-Authored-By: Claude <noreply@anthropic.com>
     ```
  5. 只有在用户明确同意后才 `git push`。
- **忽略文件**：`config.json` 和运行时数据 `data/` 已忽略，提交前请确认未纳入敏感文件。

## 修改后必须检查

1. 语法：`python -m py_compile app/*.py`
2. 测试：`python -m pytest tests/ -q`
3. 敏感配置未进入暂存区：`git diff --cached --name-only | grep -i config` 应无输出。

## 调试入口

- `debug/test_bot_components.py` — Bot 纯逻辑组件
- `debug/test_query_planner.py` — 复杂查询规划工作流
- `debug/test_mcp_server.py` — MCP server
- `debug/test_reports.py` — 固定报表
- `debug/test_dataapi.py` — 数仓 API
- `debug/test_mcp_mount.py` — 复刻 bot spawn 方式验证子 CLI 的 MCP 工具挂载
- `debug/test_mcp_handshake.py` — 裸 MCP stdio 握手，验证 mcp_server 工具 schema
- `debug/test_configdb_live.py` — 静态配置库真实 MySQL 冒烟（需先在 config.json 填好 config_db）

## 注意事项

- 子 Claude CLI 每次调用超时 600 秒（`claude.timeout`），复杂查询靠拆分为多步避免单步超时。
- **新版子 CLI（2.1.210+）异步连接 MCP server**：会话开始的几秒内 `mcp__dquery__query_data` 可能尚未注入工具列表。工作区规则与分步提示词已引导模型先用 `WaitForMcpServers` 等待；`claude_cli.run` 检测到"工具不可用"答案时会以全新进程重试一次（不限于 resume 场景）。
- **子进程环境必须干净**：`claude_cli._child_env` 会剥离所有 `CLAUDE*` / `AI_AGENT` 环境变量。若从 Claude Code 会话内启动 bot（例如调试时用 Bash 调 `run_bot.bat`），不剥离这些变量会导致子 CLI 附着到父会话、MCP 工具必挂。
- `--allowedTools mcp__dquery__query_data` 在新版 CLI 中**不限制内置工具**（Bash/Read/Write 仍可用），提示词已明确禁止绕行；直连 `dataapi` 会绕过 sqlguard 校验和 query_log 日志。
- `data/workspaces/<chat_id>/<game_id>/results/` 保存每次查询的 CSV，每次查询前会清空。
- `data/bot.db` 记录会话、查询日志、执行详情，本地生成，已忽略。
