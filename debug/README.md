# 飞书 Bot 调试工具

这些脚本用于在不启动完整飞书长连接的情况下，单独测试各个关键组件。

## 使用前提

所有脚本默认从项目根目录运行，且会读取根目录的 `config.json`：

```powershell
cd C:\Users\liubz\Desktop\mycode\feishu_bot
python debug/test_sqlguard.py
```

## 脚本清单

| 脚本 | 作用 |
|---|---|
| `test_sqlguard.py` | 测试 SQL 护栏：验证 schema.md 中的示例 SQL 是否能通过校验 |
| `test_dataapi.py` | 测试数仓 API：mock 模式直接返回，真实模式会提交一条轻量 SQL |
| `test_workspace.py` | 测试工作区生成：检查 CLAUDE.md / mcp.json / settings.json 是否正确 |
| `test_mcp_server.py` | 直接调用 MCP 工具的 `query_data`（跳过 claude 子进程） |
| `test_reports.py` | 测试固定报表（KPI/LTV）在 mock 或真实模式下的输出 |
| `test_bot_components.py` | 测试消息解析、白名单策略等 bot 组件 |
| `run_all_checks.py` | 一键运行上述所有检查 |

## 安全提示

- `test_dataapi.py` 默认使用 `config.json` 中的 `data_api.mock` 设置；如需测真实 API，请确认 SQL 是只读且轻量的。
- 所有脚本只读 `data/` 目录中的数据库，不会修改 `config.json`。
