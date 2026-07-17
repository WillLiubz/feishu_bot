# 静态配置库查询能力 — 设计文档

日期：2026-07-16
状态：已获用户批准（四节设计逐节确认）

## 背景与目标

飞书数仓查询机器人目前只能查 Presto 数仓（`query_data`）。业务上经常需要把数仓结果里的 ID 翻译成可读信息，例如：

- 道具 ID → 道具名称
- 活动 ID → 活动名称 / 开启时间 / 类型

这些静态配置存放在**每个游戏各自独立的 MySQL 配置库**中，与 Presto 数仓是两个不同的数据库。目标：为 Bot 增加静态配置库查询能力，子 Claude（生成 SQL 的 LLM）可自主决定何时查询配置库。

## 关键决策（经用户确认）

| 决策点 | 结论 |
|---|---|
| 配置数据位置 | 每游戏独立 MySQL 库（39 / 312 / 160 / 255 各自一套） |
| 查询入口 | 新增独立 MCP 工具 `query_config`，与 `query_data` 对称 |
| 表访问范围 | 不限制、自由探索（可 `SHOW TABLES`），不做表白名单 |
| MySQL 驱动 | 安装 `pymysql`（已获用户明确同意），写入 requirements.txt |
| 配置库 schema 文档 | 新增独立的 `gm_schema_<game_id>.md`，**不复用**数仓的 `schema_<game_id>.md`（两个不同的数据库） |

## config.json 配置结构

在每个游戏的 `games[]` 条目内新增可选的 `config_db` 段；哪个游戏配了哪个游戏就有此能力，未配置的游戏自动禁用、行为与现状完全一致：

```json
{
  "game_id": 312,
  "ds_start": "20260615",
  "schema": "schema_312.md",
  "aliases": ["女3", "ProGoddessIII"],
  "reports": { ... },
  "lock_opgame_ids": [],
  "config_db": {
    "host": "填MySQL主机",
    "port": 3306,
    "user": "填只读账号",
    "password": "填密码",
    "database": "填配置库名",
    "schema": "gm_schema_312.md",
    "charset": "utf8mb4",
    "connect_timeout": 5,
    "read_timeout": 30,
    "max_rows": 500
  }
}
```

### 字段说明

| 字段 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `host` / `user` / `password` / `database` | ✅（配了 `config_db` 则必填） | — | MySQL 连接信息，**建议使用只有 SELECT 权限的只读账号** |
| `port` | 否 | `3306` | |
| `schema` | 否 | 无 | 配置库表结构文档文件名（如 `gm_schema_312.md`），放项目根目录 |
| `charset` | 否 | `utf8mb4` | |
| `connect_timeout` | 否 | `5`（秒） | 连接超时 |
| `read_timeout` | 否 | `30`（秒） | 单次查询超时 |
| `max_rows` | 否 | `500` | 单次配置查询返回行数上限 |

### 双 schema 文档约定

每个游戏有两个 schema 文档，各司其职：

- `schema` → `schema_312.md`：描述 Presto 数仓表（现有，不变）
- `config_db.schema` → `gm_schema_312.md`：**新增**，描述该游戏 MySQL 配置库的表结构（表名、字段、中文含义）

`gm_schema_xxx.md` 初始可以是空骨架（只写库名和"待补充"），LLM 仍能 `SHOW TABLES` 自由探索；后续逐步充实。配置了 `config_db` 时该文档全文注入子 Claude 的工作区规则。

## 新 MCP 工具 query_config

加在 `app/mcp_server.py`，与 `query_data` 并列：

```python
@mcp.tool()
def query_config(sql: str) -> dict:
    """
    查询当前游戏的静态配置 MySQL 库（只读）。
    用途：道具ID→道具名称、活动ID→活动信息等静态配置查找。
    仅允许 SELECT / SHOW / DESCRIBE / EXPLAIN；禁止任何写操作。
    结果上限 config_db.max_rows 行（默认 500），单次查询超时 read_timeout 秒（默认 30）。
    """
```

行为：

- 返回 `{row_count, columns, rows}`——与 `query_data` 只给 20 行 preview 不同，配置查询结果**全量返回**（上限 `max_rows` 行），因为 LLM 要靠这些值做 ID→名称翻译
- **不写** `query_N.csv`：配置查找是中间步骤，不应混进最终合并的 Excel
- 查询日志照常写入 `store.log_query`，SQL 加 `[config]` 前缀便于区分
- 当前游戏未配 `config_db` 时，工具仍注册但直接报错"当前游戏未配置静态配置库"
- 连接每次查询新建、用完即关，**不做连接池**（配置查询是低频辅助操作，避免长连接占用游戏 DB）

## 安全护栏（新增 app/configdb.py 模块）

复用 sqlguard 的字符串字面量掩码思路，但规则独立：

| 护栏 | 规则 |
|---|---|
| 语句类型 | 只允许 `SELECT` / `SHOW` / `DESCRIBE` / `EXPLAIN` 开头 |
| 写操作 | 禁 `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/SET/CALL/USE` 等（在掩码后文本上匹配，防止字符串字面量误伤） |
| 多语句 | 禁 `;` 多语句，防堆叠注入 |
| 注释/危险内容 | 禁 `--`、`/*`、`*/`、`into outfile`、`load_file`、`sleep(`、`benchmark(` |
| 行数 | 无 `LIMIT` 时自动追加 `LIMIT {max_rows}`（SHOW/DESCRIBE/EXPLAIN 除外） |
| 超时 | `read_timeout` 通过 pymysql 连接参数控制（socket 级超时） |
| **不校验** `game_id` | 与数仓护栏不同——配置库本身按游戏分独立连接，SQL 里不需要也没有 game_id 条件 |

双保险：`config_db.user` 在 MySQL 侧本身就是只读账号，即使代码护栏有漏洞也写不了。

## 链路改动点

### 1. app/claude_cli.py

`--allowedTools` 增加新工具：

```python
"--allowedTools", "mcp__dquery__query_data,mcp__dquery__query_config",
```

### 2. app/workspace.py

- `settings.json` 的 `permissions.allow` 增加 `"mcp__dquery__query_config"`
- 生成 CLAUDE.md 时，若当前游戏配了 `config_db`，在规则末尾追加配置库说明块，并拼接 `gm_schema_xxx.md` 全文（复用现有 schema 文档注入方式）；未配置则完全不提，避免 LLM 调用不存在的后端：

```
静态配置查询（MySQL 配置库）：
- 查道具名称、活动信息等静态配置时，使用 query_config 工具，直接写 MySQL 语法 SQL
- 只允许 SELECT / SHOW / DESCRIBE / EXPLAIN；不知道有哪些表时先 SHOW TABLES 探索
- 配置库与数仓是两个独立数据库：数仓表名（gamelog_raw.* 等）不能用在 query_config 里，反之亦然
- query_config 的 SQL 不需要 game_id 条件
- 查到的配置值用于辅助解读数仓结果（如把 item_id 翻译成道具名），不要对配置库做全表扫描式查询

<gm_schema_xxx.md 全文>
```

### 3. app/config.py

- `GameConfig` 增加 `config_db: dict` 字段（缺省 `{}`）
- `check()` 增加校验：若某游戏配了 `config_db`，则 `host`/`user`/`database` 必填、`port` 为整数；`schema` 指向的文件不存在时仅告警不阻断（允许先配连接后补文档）

## 数据流

```
用户提问 → bot.py 路由到游戏
  → workspace.prepare() 注入 CLAUDE.md（含 gm_schema 文档，如已配置）
  → 子 Claude 判断需要静态配置 → 调用 query_config(MySQL SQL)
  → mcp_server → configdb 护栏校验 → pymysql 查该游戏 MySQL
  → 返回行数据给子 Claude → 继续用 query_data 查数仓或组织中文回答
```

## 错误处理

`query_config` 内部分三类，均返回明确中文报错给子 Claude，不 crash MCP server：

| 场景 | 行为 |
|---|---|
| 当前游戏未配 `config_db` | 报错"当前游戏未配置静态配置库"，记入 query_log |
| SQL 被护栏拦截 | 报错并附原因（同 sqlguard 风格），记 `guard_error` |
| MySQL 连接失败 / 超时 / SQL 语法错 | 报错含原始 MySQL 错误信息（LLM 可据此改写重试），记 `error` |

## 测试方案

- `tests/test_configdb.py` — 护栏纯逻辑单测：合法 SELECT/SHOW/DESC/EXPLAIN 通过；写操作、多语句、注释、堆叠注入、`into outfile`、`sleep(`、字符串字面量里含 "drop" 字样（不应误伤）等用例
- `tests/test_config.py` 补充 — `config_db` 解析与 `check()` 校验用例（缺 host 报错、未配置时默认为 `{}`）
- `tests/test_workspace.py` 补充 — 配置/未配置 `config_db` 两种情况下，生成的 CLAUDE.md 分别包含/不包含配置库说明块
- `tests/test_mcp_server.py` 补充 — `query_config` 打桩 pymysql 后的返回结构、未配置游戏报错、不写 `query_N.csv` 的断言
- `debug/test_configdb_live.py` — 真实连 MySQL 的冒烟脚本（需先在 config.json 填好连接信息），验证 `SHOW TABLES` 和一次真实道具名查询

## 依赖变更

- `pip install pymysql`（已获用户明确同意），加入 `requirements.txt`

## 实施顺序

1. 装依赖 + config.json 骨架 + config.py 解析
2. configdb 护栏 + 单测
3. mcp_server 工具 + workspace 注入 + claude_cli allowedTools
4. 全部测试通过 + debug 冒烟（等用户填好真实连接信息）

## 影响面与兼容性

- 未配置 `config_db` 的游戏行为与现状完全一致，零影响
- `config.json` 本就在 `.gitignore` 中，新增的数据库密码不会入库
- 不改 `query_data`、sqlguard、dataapi 的任何现有逻辑
