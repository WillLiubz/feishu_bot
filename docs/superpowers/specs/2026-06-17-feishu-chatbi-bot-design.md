# 飞书 ChatBI 机器人 · 设计规格

**日期**：2026-06-17  
**状态**：已确认，待实施

---

## 1. 一句话

策划/运营在飞书里用中文提问 → 机器人起 Claude Code CLI 子进程，让它多轮自调 MCP 工具 `query_data` 写 Presto SQL 取数 → 回中文总结 + CSV 文件。固定口径报表走 Python 旁路，不经 LLM。

---

## 2. 目标与范围

**目标用户**：不会写 SQL 但需要看数的策划/运营/客服。

**做**：自然语言 → SQL → 数仓 → 飞书（AI 总结 + CSV）、固定报表旁路（KPI/LTV）。

**不做**：结构化表单查询、Excel 导出、Web 前端、角色权限/多用户管理。

**多项目复用**：`app/` 目录零业务配置，换项目只改根目录 `config.json` 和 `schema.md`，其余代码不动。

---

## 3. 目录结构

```
feishu_bot/
├── app/                   # 源码（所有项目共用）
│   ├── run_bot.py         # 启动入口
│   ├── config.py          # 读 config.json，校验，暴露配置常量
│   ├── bot.py             # 飞书长连接收发 + 并发调度
│   ├── workspace.py       # 每聊天工作区（CLAUDE.md / mcp.json / settings.json）
│   ├── claude_cli.py      # 起 claude 子进程，整树超时回收，解析 JSON
│   ├── mcp_server.py      # FastMCP "dquery"，唯一工具 query_data
│   ├── sqlguard.py        # SQL 只读护栏
│   ├── dataapi.py         # Data-API 客户端（签名 + 提交 + TSV 下载）
│   ├── dquery.py          # list[dict] → CSV（UTF-8 BOM）
│   ├── reports.py         # 固定报表旁路（KPI / LTV）
│   ├── account_cache.py   # 账号创号日本地缓存（SQLite）
│   ├── store.py           # SQLite 落库（messages / conversations / query_log）
│   ├── names.py           # open_id / chat_id → 显示名
│   └── logview.py         # 本地只读网页日志查看器
├── data/                  # 运行时自动生成（不提交）
│   ├── bot.db
│   ├── account_dim.db
│   └── workspaces/
├── config.json            # ★ 项目差异化配置
├── schema.md              # ★ 数仓表结构 + few-shot（项目独立编写）
├── run_bot.bat            # 前台启动 + 崩溃 10s 自重启
└── start_all.bat          # 一键启动 bot + logview
```

---

## 4. config.json 完整结构

```json
{
  "feishu": {
    "app_id": "",
    "app_secret": ""
  },
  "game": {
    "game_id": 0,
    "ds_start": "20200101"
  },
  "channels": {
    "lock_opgame_ids": [],
    "aliases": {}
  },
  "data_api": {
    "client_id": "",
    "key": "",
    "search_url": "http://data-api.dc.uuzu.com/search/",
    "download_url": "http://data-api.download.dc.uuzu.com/download/",
    "max_rows": 10000,
    "mock": false
  },
  "claude": {
    "model": "claude-sonnet-4-6",
    "cli_path": "claude",
    "max_turns": 25,
    "timeout": 600
  },
  "bot": {
    "max_concurrent": 3,
    "default_sql_limit": 200,
    "whitelist": false,
    "user_opgames": {},
    "names": {}
  },
  "logview": {
    "host": "127.0.0.1",
    "port": 8900,
    "key": ""
  },
  "help_text": "我可以帮你查询数仓数据，直接用中文提问即可。",
  "report_triggers": {
    "kpi": ["kpi", "日报", "今日数据"],
    "ltv": ["ltv"]
  }
}
```

**config.py** 负责：从 `config.json`（相对于 `app/` 的上级目录）读取，做非空/类型校验，以模块级常量形式暴露（`FEISHU_APP_ID`、`GAME_ID` 等），其余所有模块只从 `config` 导入，不直接读文件。

---

## 5. schema.md 结构约定

纯 Markdown，直接注入每个聊天的 `CLAUDE.md`：

```markdown
## 表结构

（描述该项目有哪些表、哪些关键字段、查询约定、ds 分区规则等）

## 示例 SQL

（few-shot：典型问题 → 对应 SQL，占位日期用 <今天ds>/<昨天ds>）

## 固定报表口径

（KPI/LTV 等指标定义，供 reports.py 参考）
```

`workspace.py` 读取 `schema.md` 全文注入 `CLAUDE.md`，`<今天ds>` / `<昨天ds>` 占位符在注入时替换为真实日期。

---

## 6. 数据流（LLM 路径）

```
飞书消息
  1. bot._on_message: 提取文本 → store.log_in → 白名单校验
  2. 即时指令（whoami/help）→ 直接回，结束
  3. reports.match(问题)？→ 走固定报表路径（Python 直算）
  4. 并发闸：同 chat_id 串行 + 全局信号量（max_concurrent=3）
  5. daemon 线程 _handle:
     a. 取 session_id（store.get_session）
     b. workspace.prepare → 生成 CLAUDE.md / mcp.json / settings.json
     c. 回"🔎 正在处理…"
     d. claude_cli.run(问题, ws, sid)：
        - 起 claude 子进程（--resume sid, cwd=ws, --allowedTools query_data）
        - claude 多轮：写 SQL → query_data → 看 preview/报错 → 纠正
          每次 query_data：sqlguard → dataapi → 写 result.csv（覆盖）→ store.log_query
        - claude 退出 → stdout JSON → (总结, new_sid)
     e. store.set_session(chat_id, new_sid)
     f. 回总结文本
     g. 上传 result.csv → 回文件消息
     h. store.log_out(ok, latency)
  异常：分级回提示（超时/护栏拒/其它），详情只落库
  finally：释放信号量 + 移出 active 集合
```

---

## 7. 安全护栏（四层）

| 层 | 位置 | 作用 |
|---|---|---|
| 工具收口 | `workspace.py` `.claude/settings.json` | `deny` 所有内置工具，只 `allow` `mcp__dquery__query_data` |
| SQL 护栏 | `sqlguard.py` | 先剥字符串字面量，再：单条 SELECT/WITH、禁 DDL/写操作/注释/文件读写、game_id 必带、渠道锁、ds 下限、自动补 LIMIT |
| 业务硬锁 | `config.json` → `sqlguard.py` | `game_id`、`lock_opgame_ids`、`ds_start` 全从配置读，不写死 |
| 应用白名单 | `bot.py` | `whitelist=false` 全放行；`true` 时按 `user_opgames` 控制 |

---

## 8. 固定报表旁路

`reports.match(问题)` 按 `config.json` 里的 `report_triggers` 关键词匹配，命中则走 Python 直算，不起 claude 子进程：

- **KPI**：活跃/付费实时查仓，新增账号/付费读本地 account_cache
- **LTV**：拉付费明细，按创号日分群，本地计算 LTV1/3/7/15/30

---

## 9. 存储

| 文件 | 内容 |
|---|---|
| `data/bot.db` | `messages`（收发审计）、`conversations`（chat_id ↔ session_id）、`query_log`（每条 SQL） |
| `data/account_dim.db` | 账号创号日缓存，仅固定报表使用 |
| `data/workspaces/<chat_id>/` | CLI 工作区，`results/result.csv` 每次覆盖 |

---

## 10. 依赖

```
lark-oapi    # 飞书 SDK
fastmcp      # MCP server
requests     # HTTP
```

Python 3.9+，其余用标准库。

---

## 11. 错误分级回复

| 错误 | 用户看到 |
|---|---|
| 查询超时 | "查询超时，请简化问题后重试" |
| SQL 护栏拒绝 | "该查询不符合权限限制" |
| 数仓访问失败 | "数仓暂时无法访问，请稍后重试" |
| 其他 | "处理失败，请稍后重试" |

详细错误信息只写入 `data/bot.db`，不回飞书。

---

## 12. 部署（换新项目）

1. 复制 `feishu_bot/` 目录
2. 修改 `config.json`（填新项目飞书凭证、game_id、渠道配置、数仓凭证）
3. 重写 `schema.md`（填新项目表结构和示例 SQL）
4. 双击 `run_bot.bat` 启动

---

## 13. 当前项目初始配置

| 项 | 值 |
|---|---|
| `feishu.app_id` | `cli_aab8ddcd70fa5cc3` |
| `feishu.app_secret` | `dTNWQkkbMgUnsSgn7mQtHQaYm6IyrE3W` |
| `game.game_id` | `312` |
| `game.ds_start` | `20260615` |
| `channels.lock_opgame_ids` | `[]`（不锁渠道） |
| `channels.aliases` | `{}` |
| `data_api.client_id` | `92` |
| `data_api.key` | `dd6753b542b5d678692da5c52c404d56` |
