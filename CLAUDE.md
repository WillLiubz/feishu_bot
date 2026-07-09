# Feishu 数仓查询机器人 — 项目指引

## 项目概述

一个基于飞书机器人 + Claude CLI + MCP 的数据仓库查询服务。用户用中文向飞书机器人提问，Bot 调用 Claude CLI 生成并执行 Presto SQL，返回中文总结和 CSV/Excel 结果。

## 目录结构

```
app/                # 主应用代码
  bot.py            # 飞书消息处理、查询路由
  claude_cli.py     # 调用 claude 子进程
  mcp_server.py     # dquery MCP server（暴露 query_data 工具）
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
schema.md           # 312 游戏表结构文档
schema_160.md       # 160 游戏表结构文档
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
- **库选择**：默认 KPI/日志用 `gamelog_raw`；ECO 流水/行为/道具表用 `gameeco_raw`；只有用户明确要求 T+1/odl 时才用 `gamelog_odl`。
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

## 注意事项

- 子 Claude CLI 每次调用超时 600 秒（`claude.timeout`），复杂查询靠拆分为多步避免单步超时。
- `data/workspaces/<chat_id>/<game_id>/results/` 保存每次查询的 CSV，每次查询前会清空。
- `data/bot.db` 记录会话、查询日志、执行详情，本地生成，已忽略。
