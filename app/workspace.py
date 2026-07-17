import json
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import config

_ROOT = Path(config._ROOT)
_APP_DIR = Path(__file__).parent
_WORKSPACES_DIR = _ROOT / "data" / "workspaces"

_RULES_TEMPLATE = """\
你是一个数据分析助手，帮助用户查询数仓数据。

今天日期（ds 分区）：{today}
昨天日期（ds 分区）：{yesterday}
本月起始日期：{month_start}

规则：
1. 只能使用 query_data 工具查询数据，不允许使用任何其他工具（唯一例外是内置的 WaitForMcpServers：如果工具列表里暂时没有 query_data——MCP server 是异步加载的，需要几秒钟——先调用 WaitForMcpServers 等待 dquery 连接，最多重试 3 次，确认仍不可用再向用户说明，不要直接放弃，也不要用 Bash 等其他工具绕过）
2. 只读查询，不允许修改数据
3. 用中文回答用户问题
4. 回答格式：先给一段中文总结（基于实际查到的数据），不需要返回表格
5. 所有 SQL 必须带 game_id = {game_id} 分区条件
6. ds 分区日期格式：yyyyMMdd（如 {today}）
7. 查累计类数据时加 ds >= {ds_start} 条件
8. 如果 SQL 报错，仔细检查原因后重写，最多重试 3 次

复杂查询拆分策略（必须遵守）：
9. 凡是需要跨多张大表 JOIN、或时间跨度超过 7 天的关联查询，必须拆分为多步执行：
   - 第1步：先从主表查出目标 role_id 列表（用 IN 或 LIMIT 控制规模）
   - 第2步：用第1步得到的 role_id 列表（IN ('id1','id2',...)）过滤第二张表
   - 第3步：如需继续关联，依此类推
10. 每一步 SQL 独立执行，结果中间可见，不要把所有逻辑压缩进一条 SQL
11. 跨月大表查询策略：
    - 优先拆成按周查询：第1周 ds BETWEEN {month_start} AND 第7天，第2周以此类推，最后合并
    - 单次 SQL 日期跨度不超过 10 天，避免全月扫描超时
12. 最终必须给出汇总结果，哪怕中间某步数据量有限也要基于实际数据得出结论
13. 本月查询使用本月起始日期 {month_start}，不要自行推算
14. 优先用子查询或临时结果，避免一次性 JOIN 多张大表

用户提问信息要求：
- 查询具体玩家的信息时（例如"玩家 XXX 昨天的付费/道具/行为情况"），需要用户额外提供该玩家的昵称和所在服务器；如果用户没有提供，先在回答中向用户确认这两项信息，不要凭猜测定位 role_id 直接查询

{game_specific_rules}
"""

_DEFAULT_GAME_RULES = """\
15. **默认所有 KPI/日志/ECO 查询使用 RAW 实时库（gamelog_raw / gameeco_raw），不按日期自动切换。** 只有用户明确要求 T+1 / odl 时，才在 SQL 开头单独一行加 `-- use_odl` 使用 ODL 库（gamelog_odl / gameeco_odl）。没有 `-- use_odl` 时，系统会自动把 ODL 表名改写成 RAW。
16. ECO 日志表（roleitem / roleres / rolebehavior）位于 gameeco_raw，不是 gameeco_odl：
    - roleitem: gameeco_raw.v_presto_log_roleitem
    - roleres: gameeco_raw.v_presto_log_roleres
    - rolebehavior: gameeco_raw.v_presto_log_rolebehavior
    - 这些表的 role_id 是 BIGINT，与 VARCHAR 字段比较时必须 CAST(role_id AS VARCHAR)
    - game_id 在 ECO 表中是字符串（如 '312'），比较时直接写 game_id = '312'
17. 付费表 gamelog_raw.v_presto_log_payrecharge 的 role_id 通常也是 BIGINT，用 CAST(role_id AS VARCHAR) IN (...) 过滤
18. 月度排行榜玩家充值类问题必须拆成两步：
    - 第1步：从 gameeco_raw.v_presto_log_rolebehavior 查 b_type='MonthRank'，获取 role_id 列表
    - 第2步：用 CAST(role_id AS VARCHAR) IN (...) 去 gamelog_raw.v_presto_log_payrecharge 查充值
"""

_GAME_SPECIFIC_RULES = {
    39: """\
15. 游戏 39 统一使用 `raw_scribe_log` 库，表名与 behavior 类型对应：
    - 登录：`raw_scribe_log.login`
    - 注册/激活：`raw_scribe_log.est`
    - 充值：`raw_scribe_log.pay`
    - 加币/货币获得：`raw_scribe_log.curr`
    - 消费钻石/货币：`raw_scribe_log.prop`
    - GM 扣币：`raw_scribe_log.sub`
    - 在线人数/PCU：`raw_scribe_log.ser`
    字段含义参考 schema_39.md。
16. **过滤游戏必须用字符串 `gameid = '39'`，绝对不要写 `game_id = 39`**；`game_id` 列虽然存在但会让 Presto 全表扫描，导致超时。
17. 玩家唯一标识用 `iuid`（内部 uid），平台账号用 `ouid`。按玩家关联时用 `iuid`。
18. `raw_scribe_log.pay.custom_pra3` 是**充值获得的游戏币/钻石数量**（字符串，需 CAST）。回答任何游戏 39 的付费/充值问题时，**默认以美元为最终单位**，钻石数仅作为辅助参考；换算公式：`美元金额 = ROUND(CAST(custom_pra3 AS DOUBLE) / 100, 2)`（即 100 钻石 = 1 美元）。付费类型在 `custom_pra1`（`1`=兑换游戏币，`2`=直购道具）。
19. 系统参与/消费行为查 `raw_scribe_log.prop` 的 `custom_pra1`（来源 class.method，如 `UserLevy.levy`）和 `custom_pra3`（数量）。
20. 不要使用 `gameeco_raw`、`gamelog_raw.v_presto_log_*` 等 312/160 项目的表名来查询游戏 39。
21. `raw_scribe_log.*` 的数值列都是 VARCHAR，求和/排序时必须 `CAST(custom_pra3 AS BIGINT)` 或 `CAST(custom_pra3 AS DOUBLE)`。
""",
}

_CONFIG_DB_RULES = """\
静态配置查询（MySQL 配置库）：
- 查道具名称、活动信息等静态配置时，使用 query_config 工具，直接写 MySQL 语法 SQL
- 只允许 SELECT / SHOW / DESCRIBE / EXPLAIN；不知道有哪些表时先 SHOW TABLES 探索
- 配置库与数仓是两个独立数据库：数仓表名（gamelog_raw.* 等）不能用在 query_config 里，反之亦然
- query_config 的 SQL 不需要 game_id 条件
- 查到的配置值用于辅助解读数仓结果（如把 item_id 翻译成道具名），不要对配置库做全表扫描式查询
"""


def _safe(s):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', s)


def prepare(chat_id, message_id, game_config=None, opgames=None):
    """
    Prepare per-chat workspace. Called before every query.
    Returns dict: {cwd, mcp_config, result_dir}
    """
    if game_config is None:
        game_config = config.game_config()

    ws_dir = _WORKSPACES_DIR / _safe(chat_id)
    ws_dir.mkdir(parents=True, exist_ok=True)

    result_dir = ws_dir / "results"
    if result_dir.exists():
        shutil.rmtree(result_dir)
    result_dir.mkdir()

    today = date.today().strftime("%Y%m%d")
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    month_start = date.today().replace(day=1).strftime("%Y%m%d")

    # CLAUDE.md: rules + channel aliases + schema content
    schema_path = _ROOT / game_config.schema
    schema_text = ""
    if schema_path.exists():
        schema_text = schema_path.read_text(encoding="utf-8")
        schema_text = schema_text.replace("<今天ds>", today).replace("<昨天ds>", yesterday)

    channel_block = ""
    if config.CHANNEL_ALIASES:
        lines = "\n".join(f"  {name}：{ids}" for name, ids in config.CHANNEL_ALIASES.items())
        channel_block = f"\n渠道别名（中文名对应的 opgame_id）：\n{lines}\n"

    user_scope = ""
    if opgames:
        user_scope = f"\n当前用户仅可查询以下渠道：{', '.join(str(o) for o in opgames)}\n"

    game_specific_rules = _GAME_SPECIFIC_RULES.get(
        game_config.game_id, _DEFAULT_GAME_RULES
    )
    rules = _RULES_TEMPLATE.format(
        today=today, yesterday=yesterday, month_start=month_start,
        game_id=game_config.game_id, ds_start=game_config.ds_start,
        game_specific_rules=game_specific_rules,
    )

    config_db_block = ""
    config_db = getattr(game_config, "config_db", None) or {}
    if config_db:
        config_db_block = "\n" + _CONFIG_DB_RULES
        config_schema_name = config_db.get("schema")
        if config_schema_name:
            config_schema_path = _ROOT / config_schema_name
            if config_schema_path.exists():
                config_db_block += "\n" + config_schema_path.read_text(encoding="utf-8") + "\n"

    claude_md = rules + channel_block + user_scope + config_db_block + "\n" + schema_text
    (ws_dir / "CLAUDE.md").write_text(claude_md, encoding="utf-8")

    # .claude/settings.json: child CLI only needs the dquery MCP tool.
    # We do not deny built-in tools here; per-tool deny rules referencing
    # TodoRead/TodoWrite cause "Permission deny rule ... matches no known tool"
    # errors in newer claude CLI versions. The parent process already restricts
    # permissions via --permission-mode bypassPermissions and --allowedTools.
    claude_dir = ws_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings = {
        "permissions": {
            "allow": ["mcp__dquery__query_data", "mcp__dquery__query_config"],
        }
    }
    (claude_dir / "settings.json").write_text(
        json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # mcp.json: dquery MCP server config
    opgames_json = json.dumps([str(o) for o in (opgames or [])])
    mcp_cfg = {
        "mcpServers": {
            "dquery": {
                "command": sys.executable,
                "args": [
                    str(_APP_DIR / "mcp_server.py"),
                    "--result-dir", str(result_dir),
                    "--chat-id", chat_id,
                    "--message-id", message_id,
                    "--opgame-ids", opgames_json,
                    "--mock", str(config.DATA_API_MOCK).lower(),
                    "--game-id", str(game_config.game_id),
                ],
                "env": {},
            }
        }
    }
    mcp_config_path = ws_dir / "mcp.json"
    mcp_config_path.write_text(
        json.dumps(mcp_cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "cwd": str(ws_dir),
        "mcp_config": str(mcp_config_path),
        "result_dir": str(result_dir),
        "claude_md_path": str(ws_dir / "CLAUDE.md"),
    }


def get_claude_md_text(ws: dict) -> str:
    """Read the rendered CLAUDE.md text for the active workspace."""
    path = Path(ws.get("claude_md_path", Path(ws["cwd"]) / "CLAUDE.md"))
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""
