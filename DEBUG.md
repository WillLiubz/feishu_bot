# 飞书 ChatBI 机器人调试文档

> 生成日期：2026/06/30  
> 对应项目：`C:\Users\liubz\Desktop\mycode\feishu_bot`

---

## 1. 项目架构速览

本机器人将用户的中文自然语言问题，通过 Claude Code CLI 子进程 + MCP `query_data` 工具，转换为 Presto SQL 查询数仓，最后以中文总结 + CSV/Excel 文件的形式回复到飞书。固定口径报表（KPI/LTV）走 Python 旁路，不经 LLM。

主要模块：

| 文件 | 职责 |
|---|---|
| `app/bot.py` | 飞书 WebSocket 收发、消息路由、并发控制 |
| `app/claude_cli.py` | 启动 `claude` 子进程、超时回收、解析 JSON 输出 |
| `app/workspace.py` | 为每个聊天生成 `CLAUDE.md` / `mcp.json` / `.claude/settings.json` |
| `app/mcp_server.py` | FastMCP 服务，提供唯一工具 `query_data` |
| `app/sqlguard.py` | SQL 只读护栏：禁止 DDL/DML、检查 game_id、渠道锁、自动补 LIMIT |
| `app/dataapi.py` | 数仓 Data-API 客户端：签名、提交任务、轮询下载 TSV |
| `app/dquery.py` | 查询结果写入 UTF-8 BOM CSV，并合并多 sheet Excel |
| `app/reports.py` | KPI / LTV 固定报表旁路 |
| `app/store.py` | SQLite 记录消息、会话、查询日志 |
| `schema.md` | 数仓表结构、字段说明、示例 SQL |
| `config.json` | 项目配置：飞书凭证、game_id、数仓凭证、模型等 |

---

## 2. 调试脚本清单

所有调试脚本位于 `debug/` 目录，可在**不启动完整飞书长连接**的情况下单独测试各个环节。

| 脚本 | 作用 | 常用命令 |
|---|---|---|
| `test_sqlguard.py` | 扫描 `schema.md` 中的示例 SQL，逐一验证 SQL 护栏 | `python debug/test_sqlguard.py` |
| `test_dataapi.py` | 测试数仓 API 连通性 | `python debug/test_dataapi.py --mock` |
| `test_workspace.py` | 生成工作区并检查三个配置文件 | `python debug/test_workspace.py --keep` |
| `test_mcp_server.py` | 直接复现 `query_data` 完整流程 | `python debug/test_mcp_server.py "SELECT ..."` |
| `test_reports.py` | 测试 KPI / LTV 固定报表 | `python debug/test_reports.py kpi "今日数据"` |
| `test_bot_components.py` | 测试消息提取、白名单、报表触发词 | `python debug/test_bot_components.py` |
| `run_all_checks.py` | 一键运行上述全部检查 | `python debug/run_all_checks.py` |

所有脚本默认读取项目根目录的 `config.json`。`--mock` 参数可强制使用 mock 数据，避免真实访问数仓。

---

## 3. 一键检查

```powershell
cd C:\Users\liubz\Desktop\mycode\feishu_bot
python debug/run_all_checks.py
```

---

## 4. 当前检查结果（基线）

执行日期：2026/06/30

| 检查项 | 结果 | 说明 |
|---|---|---|
| SQL 护栏 | `[OK]` | `schema.md` 中 20 条示例 SQL 全部通过 `sqlguard.sanitize()` |
| 数仓 API | `[OK]` | mock 模式返回正常；真实模式已验证可查到数据 |
| 工作区生成 | `[OK]` | `CLAUDE.md` / `mcp.json` / `.claude/settings.json` 生成正确 |
| MCP `query_data` | `[OK]` | 真实数仓查询返回 2778 行示例，CSV 写入成功 |
| 固定报表 KPI | `[OK]` | 可生成单日/多日 KPI 总结和 CSV |
| 固定报表 LTV | `[OK]` | 共 15 个注册日队列，CSV 输出正常 |
| Bot 组件 | `[OK]` | 消息提取、权限策略、报表触发词匹配均正常 |
| 单元测试 | `26 passed` | `pytest tests/ -v` 全部通过 |

---

## 5. 各脚本详细用法

### 5.1 `test_sqlguard.py`

默认从 `schema.md` 提取 `SELECT` / `WITH` 示例 SQL，并逐一验证。

```powershell
# 验证 schema.md 中所有示例
python debug/test_sqlguard.py

# 验证单条 SQL
python debug/test_sqlguard.py "SELECT COUNT(*) FROM t WHERE game_id = 312 AND ds = '20260630'"
```

> 注意：`schema.md` 中示例 SQL 使用 `<昨天ds>` / `<今天ds>` 占位符，会被护栏放行（因为占位符本身不影响语法检查），实际注入 `CLAUDE.md` 时由 `workspace.py` 替换为真实日期。

### 5.2 `test_dataapi.py`

```powershell
# 使用 config.json 中的 mock 设置
python debug/test_dataapi.py

# 强制 mock
python debug/test_dataapi.py --mock

# 强制真实 API（会提交一条轻量 COUNT SQL）
python debug/test_dataapi.py --real

# 自定义 SQL
python debug/test_dataapi.py --real --sql "SELECT COUNT(*) FROM gameeco_raw.v_presto_snap_rolecache WHERE game_id = '312'"
```

### 5.3 `test_workspace.py`

```powershell
# 默认生成 debug_chat_001 工作区，测试后自动清理
python debug/test_workspace.py

# 指定 chat_id 和渠道权限
python debug/test_workspace.py --chat-id my_chat --opgames 3553,3554

# 保留生成的工作区供后续检查
python debug/test_workspace.py --keep
```

### 5.4 `test_mcp_server.py`

```powershell
# 默认执行轻量 COUNT 查询
python debug/test_mcp_server.py

# 自定义 SQL
python debug/test_mcp_server.py "SELECT COUNT(*) FROM gamelog_raw.v_presto_log_rolelogin WHERE game_id = 312 AND ds = '20260630'"
```

### 5.5 `test_reports.py`

```powershell
python debug/test_reports.py kpi "今日数据"
python debug/test_reports.py kpi "昨日数据"
python debug/test_reports.py kpi "近7日数据"
python debug/test_reports.py ltv
```

### 5.6 `test_bot_components.py`

```powershell
python debug/test_bot_components.py
```

输出包括：消息提取测试、白名单策略测试、报表触发词匹配测试。

---

## 6. 单元测试

```powershell
cd C:\Users\liubz\Desktop\mycode\feishu_bot
python -m pytest tests/ -v
```

当前结果：

```
26 passed in 0.44s
```

---

## 7. 已知注意点

1. **mock 模式**：`config.json` 中 `data_api.mock` 为 `false`，所以调试脚本默认会真实访问数仓。只想本地跑不通网时，请加 `--mock`。
2. **日期占位符**：`schema.md` 中的 `<昨天ds>` / `<今天ds>` / `<7天前ds>` 等占位符是设计如此，`workspace.py` 注入 `CLAUDE.md` 时会替换。
3. **Windows 控制台乱码**：调试脚本已强制 `stdout` / `stderr` 使用 UTF-8，避免中文/emoji 在 GBK 控制台下乱码。
4. **权限配置**：当前 `bot.whitelist` 为 `false`，所有用户均可使用。如需按用户限制渠道，修改 `config.json` 中 `bot.user_opgames`。
5. **dataapi 轮询超时提示**：`app/dataapi.py` 中“已等待 9 分钟”的提示与实际轮询次数（59 次 × 5 秒 ≈ 5 分钟）不完全一致。若后续出现下载超时，可优先检查此处逻辑。

---

## 8. 排查问题流程

当机器人出现以下现象时，可按顺序使用调试脚本定位：

| 现象 | 优先检查 |
|---|---|
| 飞书无响应 | `test_bot_components.py` → 检查 `run_bot.py` 是否启动 |
| 用户收到“该查询不符合权限限制” | `test_sqlguard.py "你的SQL"` |
| 用户收到“数仓暂时无法访问” | `test_dataapi.py --real` |
| LLM 没查到数据或 SQL 报错 | `test_workspace.py --keep` 检查 `CLAUDE.md` 是否注入正确 schema |
| CSV/Excel 没上传 | `test_mcp_server.py` 检查 `result.csv` / `query_*.csv` 是否生成 |
| KPI/LTV 不准 | `test_reports.py` 查看 CSV 明细 |

---

## 9. 启动完整机器人

```powershell
# 前台启动（带崩溃 10 秒自重启）
run_bot.bat

# 同时启动 bot 和日志查看器
start_all.bat

# 单独启动日志查看器
python app/logview.py
```

日志查看器地址：`http://127.0.0.1:8900`

---

*本文档由 Claude Code 生成，用于记录项目调试基线和常用命令。*
