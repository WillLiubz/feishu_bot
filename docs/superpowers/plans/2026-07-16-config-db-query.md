# 静态配置库查询能力 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为飞书数仓机器人新增静态配置库查询能力——子 Claude 通过新 MCP 工具 `query_config` 直连各游戏独立的 MySQL 配置库（只读），实现道具 ID→名称、活动 ID→活动信息等静态配置查找。

**Architecture:** 每个游戏在 `config.json` 的 `games[]` 条目内配置可选的 `config_db` 段（连接信息 + `gm_schema_<game_id>.md` 文档名）。新模块 `app/configdb.py` 提供只读护栏 `sanitize()` 与 pymysql 查询执行 `query()`；`app/mcp_server.py` 注册新工具 `query_config` 调用它们；`app/workspace.py` 在配置了 `config_db` 时向工作区 CLAUDE.md 注入使用规则与 gm_schema 文档；`app/claude_cli.py` 的 `--allowedTools` 放行新工具。未配置 `config_db` 的游戏行为与现状完全一致。

**Tech Stack:** Python 3.12+、pymysql（新依赖，已获用户批准）、FastMCP、pytest。

**Spec:** `docs/superpowers/specs/2026-07-16-config-db-query-design.md`

## Global Constraints

- Python 3.12+，所有文件 UTF-8 编码。
- 不得安装未经用户同意的新依赖；本计划仅安装 `pymysql`（已获明确同意），并写入 `requirements.txt`。
- `config.json` 含密钥、已在 `.gitignore` 中，任何提交不得包含它；提交前执行 `git diff --cached --name-only | grep -i config` 应只有 docs/tests/app 文件（注意：此 grep 会匹配 `test_config.py`/`config.py` 等正当文件名，仅确认 `config.json` 本身不在其中）。
- 提交信息使用中文，格式 `<type>: <简短描述>`，结尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`。
- 不直接提交 master/main；工作分支为 `feat-config-db-query`（已从 fix-game39-raw-scribe-tables 切出）。
- 每个 Task 提交前必须 `python -m pytest tests/ -q` 全量通过。
- 未配置 `config_db` 的游戏，行为必须与现状完全一致（workspace 不提 query_config、工具调用直接报错）。
- 测试导入模式：`sys.path.insert(0, str(Path(__file__).parent.parent / "app"))`；`tests/conftest.py` 已提供基于 `FEISHU_BOT_ROOT` 环境变量的隔离 config（legacy 单游戏模式，game_id=1）。

---

### Task 1: 安装 pymysql + config.py 解析与校验 config_db

**Files:**
- Modify: `requirements.txt`
- Modify: `app/config.py`（GameConfig 定义 line 12-20、games 解析循环 line 47-57、`check()` line 155-186）
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: 无（首个任务）。
- Produces: `config.GameConfig.config_db: dict`（缺省 `{}`，含 `host/port/user/password/database/schema/charset/connect_timeout/read_timeout/max_rows` 键，全部原样取自 config.json）；后续 Task 3 通过 `config.game_config(game_id).config_db` 读取。

- [ ] **Step 1: 安装 pymysql 并写入 requirements.txt**

```bash
pip install pymysql
python -c "import pymysql; print(pymysql.__version__)"
```

Expected: 打印版本号（如 `1.1.1`），无 ImportError。

`requirements.txt` 全文变为：

```
lark-oapi
fastmcp
openpyxl
matplotlib
pymysql
```

- [ ] **Step 2: 写失败测试**

在 `tests/test_config.py` 末尾追加（文件头部已有 `import sys, os, json, tempfile, pytest` 与 `_write_config` helper）：

```python
def _games_with_config_db(config_db):
    return [{
        "game_id": 312,
        "ds_start": "20260615",
        "schema": "schema_312.md",
        "aliases": ["女3"],
        "reports": {
            "login_table": "gamelog_raw.log_rolelogin",
            "pay_table": "gamelog_raw.log_payrecharge",
            "account_login_table": "gamelog_raw.log_accountlogin"
        },
        "lock_opgame_ids": [],
        "config_db": config_db,
    }]


def test_config_db_defaults_empty(tmp_path, monkeypatch):
    root = _write_config(tmp_path)
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    assert config.GAMES[312].config_db == {}


def test_config_db_loaded_from_games(tmp_path, monkeypatch):
    cdb = {"host": "10.0.0.1", "user": "ro", "password": "p", "database": "cfg",
           "schema": "gm_schema_312.md"}
    root = _write_config(tmp_path, {"games": _games_with_config_db(cdb)})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    assert config.GAMES[312].config_db["host"] == "10.0.0.1"
    assert config.GAMES[312].config_db["schema"] == "gm_schema_312.md"


def test_check_rejects_config_db_missing_host(tmp_path, monkeypatch):
    cdb = {"user": "ro", "database": "cfg"}
    root = _write_config(tmp_path, {"games": _games_with_config_db(cdb)})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    with pytest.raises(ValueError, match="config_db"):
        config.check()


def test_check_rejects_config_db_non_int_port(tmp_path, monkeypatch):
    cdb = {"host": "h", "user": "u", "database": "d", "port": "3306"}
    root = _write_config(tmp_path, {"games": _games_with_config_db(cdb)})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    with pytest.raises(ValueError, match="port"):
        config.check()


def test_check_accepts_valid_config_db_and_warns_on_missing_schema(tmp_path, monkeypatch, capsys):
    cdb = {"host": "h", "user": "u", "database": "d", "schema": "gm_schema_missing.md"}
    root = _write_config(tmp_path, {"games": _games_with_config_db(cdb)})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    config.check()  # 不抛错
    assert "gm_schema_missing.md" in capsys.readouterr().out
```

- [ ] **Step 3: 运行测试确认失败**

```bash
python -m pytest tests/test_config.py -q
```

Expected: 新测试 FAIL（`AttributeError: 'GameConfig' object has no attribute 'config_db'`）。

- [ ] **Step 4: 实现 config.py 改动**

改动 1 — `app/config.py` line 3 的 dataclass 导入改为：

```python
from dataclasses import dataclass, field
```

改动 2 — `GameConfig`（line 12-20）改为：

```python
@dataclass(frozen=True)
class GameConfig:
    """Per-game configuration."""
    game_id: int
    ds_start: str
    schema: str
    aliases: List[str]
    reports: dict
    lock_opgame_ids: List[int]
    config_db: dict = field(default_factory=dict)
```

改动 3 — games 解析循环（line 49-57）的 `GameConfig(...)` 调用追加一个关键字参数：

```python
        gc = GameConfig(
            game_id=g["game_id"],
            ds_start=g.get("ds_start", "20200101"),
            schema=g.get("schema", "schema_312.md"),
            aliases=g.get("aliases", []),
            reports=g.get("reports", {}),
            lock_opgame_ids=g.get("lock_opgame_ids", []),
            config_db=g.get("config_db", {}) or {},
        )
```

改动 4 — legacy 单游戏模式（line 91-102 的 `game_config()` 兜底构造）**不改**：`config_db` 字段有默认值 `{}`，legacy 模式自动获得空配置（即不支持 config_db，属预期）。

改动 5 — `check()` 中，在 chat_games 校验循环（line 167-172）之后、`import re` 之前插入：

```python
    # config_db validation (multi-game mode)
    if MULTI_GAME_MODE:
        for gid, gc in _GAMES.items():
            cdb = gc.config_db or {}
            if not cdb:
                continue
            for field_name in ("host", "user", "database"):
                if not cdb.get(field_name):
                    raise ValueError(f"config.json game {gid} config_db 缺少必填项: {field_name}")
            port = cdb.get("port", 3306)
            if not isinstance(port, int):
                raise ValueError(f"config.json game {gid} config_db.port 必须是整数: {port!r}")
            schema_name = cdb.get("schema")
            if schema_name and not (_ROOT / schema_name).exists():
                print(f"[config] 警告: game {gid} config_db.schema 文件不存在: {schema_name}")
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest tests/test_config.py -q
python -m pytest tests/ -q
```

Expected: 全部 PASS（含既有测试）。

- [ ] **Step 6: Commit**

```bash
git add requirements.txt app/config.py tests/test_config.py
git commit -m "feat: GameConfig 支持 config_db 静态配置库连接段解析与启动校验

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: app/configdb.py — 只读护栏 sanitize + pymysql 查询执行

**Files:**
- Create: `app/configdb.py`
- Test: `tests/test_configdb.py`

**Interfaces:**
- Consumes: `sqlguard._mask_literals()`、`sqlguard._strip_parens()`（既有私有函数，同包内复用，避免重复实现字面量掩码）。
- Produces:
  - `configdb.ConfigGuardError(ValueError)` — 护栏异常
  - `configdb.sanitize(sql: str, max_rows: int = 500) -> str` — 校验并返回清洗后 SQL（SELECT 无 LIMIT 时自动追加；SHOW/DESCRIBE/EXPLAIN 豁免）
  - `configdb.query(cfg: dict, sql: str, max_rows: int = 500) -> list[dict]` — 直连 MySQL 执行，连接即用即关，结果钳制到 max_rows

- [ ] **Step 1: 写失败测试**

创建 `tests/test_configdb.py`：

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import configdb


# ---------- sanitize: 合法语句 ----------

def test_select_passes_and_gets_default_limit():
    assert configdb.sanitize("SELECT * FROM item_config") == "SELECT * FROM item_config LIMIT 500"


def test_select_keeps_existing_limit():
    assert configdb.sanitize("SELECT * FROM item_config LIMIT 10") == "SELECT * FROM item_config LIMIT 10"


def test_custom_max_rows():
    assert configdb.sanitize("SELECT * FROM t", max_rows=50).endswith("LIMIT 50")


def test_show_tables_no_limit_appended():
    assert configdb.sanitize("SHOW TABLES") == "SHOW TABLES"


def test_describe_no_limit_appended():
    assert configdb.sanitize("DESCRIBE item_config") == "DESCRIBE item_config"


def test_explain_no_limit_appended():
    assert configdb.sanitize("EXPLAIN SELECT 1") == "EXPLAIN SELECT 1"


def test_trailing_semicolon_stripped():
    assert configdb.sanitize("SELECT 1;") == "SELECT 1 LIMIT 500"


def test_string_literal_with_banned_word_not_misjudged():
    # 'drop'/'delete' 出现在字符串字面量里不应触发护栏
    out = configdb.sanitize("SELECT * FROM t WHERE name = 'drop table' AND memo = 'delete'")
    assert out.endswith("LIMIT 500")


# ---------- sanitize: 非法语句 ----------

@pytest.mark.parametrize("sql", [
    "INSERT INTO t VALUES (1)",
    "UPDATE t SET a = 1",
    "DELETE FROM t",
    "DROP TABLE t",
    "ALTER TABLE t ADD c INT",
    "CREATE TABLE t (a INT)",
    "TRUNCATE TABLE t",
    "GRANT SELECT ON t TO u",
    "REPLACE INTO t VALUES (1)",
    "SET NAMES utf8",
    "USE other_db",
    "LOAD DATA INFILE '/tmp/x' INTO TABLE t",
    "LOCK TABLES t READ",
    "KILL 123",
])
def test_write_statements_rejected(sql):
    with pytest.raises(configdb.ConfigGuardError):
        configdb.sanitize(sql)


def test_multi_statement_rejected():
    with pytest.raises(configdb.ConfigGuardError, match="多条"):
        configdb.sanitize("SELECT 1; SELECT 2")


def test_comment_rejected():
    with pytest.raises(configdb.ConfigGuardError):
        configdb.sanitize("SELECT 1 -- comment")


def test_into_outfile_rejected():
    with pytest.raises(configdb.ConfigGuardError):
        configdb.sanitize("SELECT * INTO OUTFILE '/tmp/x' FROM t")


def test_sleep_rejected():
    with pytest.raises(configdb.ConfigGuardError):
        configdb.sanitize("SELECT sleep(5)")


def test_with_cte_rejected():
    # MySQL 配置库只允许 SELECT/SHOW/DESCRIBE/EXPLAIN 开头，WITH 被拒绝（LLM 可改写为普通 SELECT）
    with pytest.raises(configdb.ConfigGuardError, match="SELECT"):
        configdb.sanitize("WITH x AS (SELECT 1) SELECT * FROM x")


# ---------- query: 打桩 pymysql ----------

class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql):
        self.executed = sql

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows, sink):
        self._cursor = _FakeCursor(rows)
        self._sink = sink

    def cursor(self):
        return self._cursor

    def close(self):
        self._sink["closed"] = True


def _stub_connect(monkeypatch, rows):
    sink = {}

    def _connect(**kw):
        sink["kwargs"] = kw
        return _FakeConn(rows, sink)

    monkeypatch.setattr(configdb.pymysql, "connect", _connect)
    return sink


def test_query_connects_with_defaults_and_closes(monkeypatch):
    sink = _stub_connect(monkeypatch, [{"id": 1, "name": "经验药水"}])
    rows = configdb.query(
        {"host": "h", "user": "u", "password": "p", "database": "d"},
        "SELECT * FROM item_config",
    )
    assert rows == [{"id": 1, "name": "经验药水"}]
    assert sink["closed"] is True
    kw = sink["kwargs"]
    assert kw["port"] == 3306
    assert kw["charset"] == "utf8mb4"
    assert kw["connect_timeout"] == 5
    assert kw["read_timeout"] == 30


def test_query_respects_custom_timeouts_and_charset(monkeypatch):
    sink = _stub_connect(monkeypatch, [])
    configdb.query(
        {"host": "h", "port": 3307, "user": "u", "database": "d",
         "charset": "utf8", "connect_timeout": 3, "read_timeout": 9},
        "SELECT 1",
    )
    kw = sink["kwargs"]
    assert kw["port"] == 3307
    assert kw["charset"] == "utf8"
    assert kw["connect_timeout"] == 3
    assert kw["read_timeout"] == 9


def test_query_clamps_rows_to_max_rows(monkeypatch):
    _stub_connect(monkeypatch, [{"i": 1}, {"i": 2}, {"i": 3}])
    rows = configdb.query({"host": "h", "user": "u", "database": "d"},
                          "SELECT * FROM t", max_rows=2)
    assert rows == [{"i": 1}, {"i": 2}]


def test_query_closes_connection_on_error(monkeypatch):
    class _BoomCursor(_FakeCursor):
        def execute(self, sql):
            raise RuntimeError("boom")

    class _BoomConn(_FakeConn):
        def cursor(self):
            return _BoomCursor([])

    sink = {}
    monkeypatch.setattr(configdb.pymysql, "connect", lambda **kw: _BoomConn([], sink))
    with pytest.raises(RuntimeError, match="boom"):
        configdb.query({"host": "h", "user": "u", "database": "d"}, "SELECT 1")
    assert sink["closed"] is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_configdb.py -q
```

Expected: 全部 FAIL（`ModuleNotFoundError: No module named 'configdb'`）。

- [ ] **Step 3: 实现 app/configdb.py**

创建 `app/configdb.py`：

```python
"""静态配置 MySQL 库访问：只读护栏 + 查询执行。

游戏静态配置库（道具表、活动表等）与 Presto 数仓是两个独立数据库。
本模块提供：
- sanitize(): 只允许 SELECT / SHOW / DESCRIBE / EXPLAIN 的只读护栏
- query():    用 pymysql 直连配置库执行，连接即用即关（不做连接池）
"""
import re

import pymysql
import pymysql.cursors

import sqlguard


class ConfigGuardError(ValueError):
    """Raised when config SQL fails the safety guard."""


_BANNED_KEYWORDS = re.compile(
    r'\b(insert|update|delete|drop|alter|create|truncate|merge|grant|revoke'
    r'|replace|exec|call|use|set|load|handler|lock|unlock|kill|shutdown)\b',
    re.IGNORECASE,
)
_BANNED_PHRASES = re.compile(
    r'(--|/\*|\*/|#\s|into\s+outfile|into\s+dumpfile|load_file|sleep\s*\(|benchmark\s*\()',
    re.IGNORECASE,
)
_ALLOWED_START = re.compile(r'^\s*(select|show|describe|desc|explain)\b', re.IGNORECASE)
_LIMIT_EXEMPT = re.compile(r'^\s*(show|describe|desc|explain)\b', re.IGNORECASE)


def sanitize(sql: str, max_rows: int = 500) -> str:
    """
    Validate config SQL. Returns cleaned SQL on success
    (auto-LIMIT appended for SELECT lacking one; SHOW/DESCRIBE/EXPLAIN exempt).
    Raises ConfigGuardError on any violation.
    """
    sql = sql.strip()
    if sql.endswith(';'):
        sql = sql[:-1].rstrip()

    masked = sqlguard._mask_literals(sql)

    # No multiple statements
    if ';' in masked:
        raise ConfigGuardError("不支持多条 SQL 语句")

    # Banned keywords (checked on masked SQL so string literals don't false-positive)
    m = _BANNED_KEYWORDS.search(masked)
    if m:
        raise ConfigGuardError(f"包含禁止操作: {m.group()}")

    # Must start with SELECT / SHOW / DESCRIBE / EXPLAIN
    if not _ALLOWED_START.match(masked):
        raise ConfigGuardError("只支持 SELECT / SHOW / DESCRIBE / EXPLAIN 查询")

    # Banned phrases
    m = _BANNED_PHRASES.search(masked)
    if m:
        raise ConfigGuardError(f"包含禁止内容: {m.group()}")

    # Auto-add LIMIT for SELECT without one
    if not _LIMIT_EXEMPT.match(masked):
        top = sqlguard._strip_parens(masked)
        if not re.search(r'\blimit\b', top, re.IGNORECASE):
            sql = f"{sql} LIMIT {max_rows}"

    return sql


def query(cfg: dict, sql: str, max_rows: int = 500) -> list:
    """
    Execute read-only SQL against the game's config MySQL DB.

    cfg: the game's config_db dict (host/port/user/password/database/charset/
    connect_timeout/read_timeout). Connection is opened per call and always
    closed. Result rows are clamped to max_rows.
    Returns list[dict].
    """
    conn = pymysql.connect(
        host=cfg["host"],
        port=int(cfg.get("port", 3306)),
        user=cfg["user"],
        password=cfg.get("password", ""),
        database=cfg["database"],
        charset=cfg.get("charset", "utf8mb4"),
        connect_timeout=int(cfg.get("connect_timeout", 5)),
        read_timeout=int(cfg.get("read_timeout", 30)),
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    finally:
        conn.close()
    return list(rows[:max_rows])
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_configdb.py -q
python -m pytest tests/ -q
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/configdb.py tests/test_configdb.py
git commit -m "feat: 新增 configdb 静态配置库只读护栏与 pymysql 查询执行

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: mcp_server.py 注册 query_config 工具

**Files:**
- Modify: `app/mcp_server.py`（import 区 line 10-15、`main()` 内 query_data 工具之后 line 118 附近）
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `config.game_config(config.GAME_ID).config_db`（Task 1）、`configdb.sanitize()` / `configdb.query()`（Task 2）、`store.log_query(chat_id, message_id, sql, row_count, status, latency_ms, error=None)`（既有）。
- Produces:
  - `mcp_server.run_config_query(sql: str, chat_id: str, message_id: str) -> dict` — 模块级核心逻辑，返回 `{"row_count": int, "columns": list[str], "rows": list[dict]}`
  - MCP 工具 `mcp__dquery__query_config` — `main()` 内注册，转发到 `run_config_query`

- [ ] **Step 1: 写失败测试**

在 `tests/test_mcp_server.py` 末尾追加（文件头部已有 `import mcp_server`；需补充 `import types` 和 `import pytest`）：

```python
import types

import pytest


def _gc_with_config_db(cdb):
    return types.SimpleNamespace(config_db=cdb)


def test_run_config_query_unconfigured_game_raises(monkeypatch):
    monkeypatch.setattr(mcp_server.config, "game_config", lambda gid=None: _gc_with_config_db({}))
    monkeypatch.setattr(mcp_server.store, "log_query", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="未配置静态配置库"):
        mcp_server.run_config_query("SELECT 1", "c1", "m1")


def test_run_config_query_returns_full_rows(monkeypatch):
    cdb = {"host": "h", "user": "u", "database": "d", "max_rows": 500}
    monkeypatch.setattr(mcp_server.config, "game_config", lambda gid=None: _gc_with_config_db(cdb))
    monkeypatch.setattr(mcp_server.store, "log_query", lambda *a, **k: None)
    fake_rows = [{"item_id": 1001, "name": "经验药水"}, {"item_id": 1002, "name": "金币"}]
    monkeypatch.setattr(mcp_server.configdb, "query", lambda cfg, sql, max_rows=500: fake_rows)
    out = mcp_server.run_config_query("SELECT * FROM item_config", "c1", "m1")
    assert out["row_count"] == 2
    assert out["columns"] == ["item_id", "name"]
    assert out["rows"] == fake_rows


def test_run_config_query_logs_sql_with_config_prefix(monkeypatch):
    logged = []
    cdb = {"host": "h", "user": "u", "database": "d"}
    monkeypatch.setattr(mcp_server.config, "game_config", lambda gid=None: _gc_with_config_db(cdb))
    monkeypatch.setattr(mcp_server.store, "log_query", lambda *a, **k: logged.append(a))
    monkeypatch.setattr(mcp_server.configdb, "query", lambda cfg, sql, max_rows=500: [])
    mcp_server.run_config_query("SHOW TABLES", "c1", "m1")
    assert logged[0][2].startswith("[config] ")
    assert logged[0][4] == "ok"


def test_run_config_query_guard_error_logged(monkeypatch):
    logged = []
    cdb = {"host": "h", "user": "u", "database": "d"}
    monkeypatch.setattr(mcp_server.config, "game_config", lambda gid=None: _gc_with_config_db(cdb))
    monkeypatch.setattr(mcp_server.store, "log_query", lambda *a, **k: logged.append(a))
    with pytest.raises(ValueError):
        mcp_server.run_config_query("DROP TABLE t", "c1", "m1")
    assert logged[0][4] == "guard_error"


def test_run_config_query_db_error_logged(monkeypatch):
    logged = []
    cdb = {"host": "h", "user": "u", "database": "d"}
    monkeypatch.setattr(mcp_server.config, "game_config", lambda gid=None: _gc_with_config_db(cdb))
    monkeypatch.setattr(mcp_server.store, "log_query", lambda *a, **k: logged.append(a))

    def _boom(cfg, sql, max_rows=500):
        raise RuntimeError("连接失败")

    monkeypatch.setattr(mcp_server.configdb, "query", _boom)
    with pytest.raises(RuntimeError, match="连接失败"):
        mcp_server.run_config_query("SELECT 1", "c1", "m1")
    assert logged[0][4] == "error"
```

说明：`log_query` 位置参数下标 2 = sql、4 = status。"不写 query_N.csv"由结构保证——`run_config_query` 不接收 `result_dir`，无从写 CSV，无需文件断言。

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_mcp_server.py -q
```

Expected: 新测试 FAIL（`AttributeError: module 'mcp_server' has no attribute 'run_config_query'`）。

- [ ] **Step 3: 实现 mcp_server.py 改动**

改动 1 — import 区（line 10-15）追加：

```python
import config
import configdb
import dataapi
```

（即：在 `import config` 与 `import dataapi` 之间插入 `import configdb`。）

改动 2 — 在 `_prepare_sql` 函数之后、`main()` 之前插入模块级函数：

```python
def run_config_query(sql: str, chat_id: str, message_id: str) -> dict:
    """
    query_config 工具的核心逻辑（独立于 MCP 注册，便于单测）。

    护栏校验 → 直连当前游戏的 MySQL 配置库 → 全量返回行（不写 CSV，
    配置查找是中间步骤，不混入最终合并的 Excel）。
    """
    t0 = time.time()
    cfg = config.game_config(config.GAME_ID).config_db or {}
    if not cfg:
        latency_ms = int((time.time() - t0) * 1000)
        store.log_query(chat_id, message_id, f"[config] {sql}", 0, "error",
                        latency_ms, "当前游戏未配置静态配置库")
        raise RuntimeError("当前游戏未配置静态配置库（config_db），无法查询道具/活动等静态配置")
    try:
        clean_sql = configdb.sanitize(sql, int(cfg.get("max_rows", 500)))
    except ValueError as e:
        latency_ms = int((time.time() - t0) * 1000)
        store.log_query(chat_id, message_id, f"[config] {sql}", 0, "guard_error",
                        latency_ms, str(e))
        raise
    try:
        rows = configdb.query(cfg, clean_sql, max_rows=int(cfg.get("max_rows", 500)))
        latency_ms = int((time.time() - t0) * 1000)
        store.log_query(chat_id, message_id, f"[config] {clean_sql}", len(rows), "ok", latency_ms)
        print(f"[mcp_server] query_config ok rows={len(rows)} latency={latency_ms}ms", flush=True)
        return {
            "row_count": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows,
        }
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        store.log_query(chat_id, message_id, f"[config] {clean_sql}", 0, "error",
                        latency_ms, str(e))
        raise
```

改动 3 — `main()` 内 `query_data` 工具定义结束之后（`mcp.run()` 之前）注册新工具：

```python
    @mcp.tool()
    def query_config(sql: str) -> dict:
        """
        查询当前游戏的静态配置 MySQL 库（只读）。
        用途：道具ID→道具名称、活动ID→活动信息等静态配置查找。
        仅允许 SELECT / SHOW / DESCRIBE / EXPLAIN；禁止任何写操作。
        结果上限 config_db.max_rows 行（默认 500），单次查询超时 read_timeout 秒（默认 30）。
        不知道有哪些表时先 SHOW TABLES 探索。SQL 使用 MySQL 语法，不需要 game_id 条件。
        """
        return run_config_query(sql, chat_id, message_id)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_mcp_server.py -q
python -m pytest tests/ -q
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: mcp_server 新增 query_config 静态配置库查询工具

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: workspace.py 规则注入 + claude_cli.py 放行新工具

**Files:**
- Modify: `app/workspace.py`（常量区 line 82 附近、`prepare()` line 125-150）
- Modify: `app/claude_cli.py:98`
- Test: `tests/test_workspace.py`、`tests/test_claude_cli.py`

**Interfaces:**
- Consumes: `game_config.config_db`（Task 1，经 `getattr(game_config, "config_db", None)` 读取以兼容测试桩）。
- Produces:
  - `workspace._CONFIG_DB_RULES: str` — 配置库使用规则文本块
  - `prepare()` 行为变更：配置了 `config_db` 时 CLAUDE.md 追加规则块 + gm_schema 全文；`settings.json` 的 `permissions.allow` 恒含 `mcp__dquery__query_config`

- [ ] **Step 1: 写失败测试**

在 `tests/test_workspace.py` 末尾追加（文件头部已有 `import workspace`；需补充 `import json` 和 `import types`）：

```python
import json
import types


def _gc(game_id=312, config_db=None):
    return types.SimpleNamespace(
        game_id=game_id,
        ds_start="20200101",
        schema="missing_schema.md",
        config_db=config_db or {},
    )


def _prepare_in_tmp(tmp_path, monkeypatch, gc):
    monkeypatch.setattr(workspace, "_ROOT", tmp_path)
    monkeypatch.setattr(workspace, "_WORKSPACES_DIR", tmp_path / "data" / "workspaces")
    return workspace.prepare("chat_cfg", "msg_1", game_config=gc)


def test_prepare_injects_config_db_rules_and_schema(tmp_path, monkeypatch):
    (tmp_path / "gm_schema_312.md").write_text(
        "# 配置库\nitem_config: 道具静态表", encoding="utf-8"
    )
    gc = _gc(config_db={"host": "h", "user": "u", "database": "d", "schema": "gm_schema_312.md"})
    _prepare_in_tmp(tmp_path, monkeypatch, gc)
    text = (tmp_path / "data" / "workspaces" / "chat_cfg" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "query_config" in text
    assert "SHOW TABLES" in text
    assert "item_config: 道具静态表" in text


def test_prepare_omits_config_db_rules_when_unconfigured(tmp_path, monkeypatch):
    _prepare_in_tmp(tmp_path, monkeypatch, _gc())
    text = (tmp_path / "data" / "workspaces" / "chat_cfg" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "query_config" not in text


def test_prepare_settings_allow_query_config(tmp_path, monkeypatch):
    _prepare_in_tmp(tmp_path, monkeypatch, _gc())
    settings = json.loads(
        (tmp_path / "data" / "workspaces" / "chat_cfg" / ".claude" / "settings.json")
        .read_text(encoding="utf-8")
    )
    assert "mcp__dquery__query_config" in settings["permissions"]["allow"]
    assert "mcp__dquery__query_data" in settings["permissions"]["allow"]
```

在 `tests/test_claude_cli.py` 末尾追加：

```python
def test_run_allowed_tools_includes_query_config():
    procs = [_FakeProc(_json_stdout("ok"))]
    with patch.object(claude_cli.subprocess, "Popen", side_effect=procs) as popen:
        claude_cli.run("问题", dict(_WS), session_id=None)
    cmd = popen.call_args[0][0]
    i = cmd.index("--allowedTools")
    assert "mcp__dquery__query_data" in cmd[i + 1]
    assert "mcp__dquery__query_config" in cmd[i + 1]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_workspace.py tests/test_claude_cli.py -q
```

Expected: 新测试 FAIL（`query_config` 未出现在 CLAUDE.md / settings.json / allowedTools 中）。

- [ ] **Step 3: 实现 workspace.py 与 claude_cli.py 改动**

改动 1 — `app/workspace.py` 在 `_GAME_SPECIFIC_RULES` 字典定义之后追加常量：

```python
_CONFIG_DB_RULES = """\
静态配置查询（MySQL 配置库）：
- 查道具名称、活动信息等静态配置时，使用 query_config 工具，直接写 MySQL 语法 SQL
- 只允许 SELECT / SHOW / DESCRIBE / EXPLAIN；不知道有哪些表时先 SHOW TABLES 探索
- 配置库与数仓是两个独立数据库：数仓表名（gamelog_raw.* 等）不能用在 query_config 里，反之亦然
- query_config 的 SQL 不需要 game_id 条件
- 查到的配置值用于辅助解读数仓结果（如把 item_id 翻译成道具名），不要对配置库做全表扫描式查询
"""
```

改动 2 — `prepare()` 中，将 line 133 的：

```python
    claude_md = rules + channel_block + user_scope + "\n" + schema_text
```

改为：

```python
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
```

改动 3 — `prepare()` 中 settings（line 143-147）改为：

```python
    settings = {
        "permissions": {
            "allow": ["mcp__dquery__query_data", "mcp__dquery__query_config"],
        }
    }
```

改动 4 — `app/claude_cli.py` line 98 改为：

```python
        "--allowedTools", "mcp__dquery__query_data,mcp__dquery__query_config",
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_workspace.py tests/test_claude_cli.py -q
python -m pytest tests/ -q
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add app/workspace.py app/claude_cli.py tests/test_workspace.py tests/test_claude_cli.py
git commit -m "feat: 工作区注入配置库查询规则并放行 query_config 工具

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: debug 冒烟脚本 + CLAUDE.md 项目文档 + 全量收尾

**Files:**
- Create: `debug/test_configdb_live.py`
- Modify: `CLAUDE.md`（目录结构节与查询路由节附近）

**Interfaces:**
- Consumes: `config.game_config(game_id).config_db`（Task 1）、`configdb.sanitize()` / `configdb.query()`（Task 2）。
- Produces: 无新接口（冒烟脚本与文档）。

- [ ] **Step 1: 创建 debug/test_configdb_live.py**

```python
"""真实 MySQL 冒烟：需先在 config.json 为某游戏填好 config_db 后运行。

用法: python debug/test_configdb_live.py [game_id]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import configdb


def main():
    game_id = int(sys.argv[1]) if len(sys.argv) > 1 else config.GAME_ID
    gc = config.game_config(game_id)
    cfg = gc.config_db or {}
    if not cfg:
        print(f"游戏 {game_id} 未配置 config_db，请先在 config.json 填写")
        sys.exit(1)

    print(f"[1/3] SHOW TABLES (game={game_id}, db={cfg.get('database')}@{cfg.get('host')})")
    tables = configdb.query(cfg, configdb.sanitize("SHOW TABLES", int(cfg.get("max_rows", 500))))
    for row in tables[:20]:
        print("  ", list(row.values())[0])
    print(f"  ... 共 {len(tables)} 张表")

    print("[2/3] SELECT 抽查第一张表前 5 行")
    if tables:
        first = list(tables[0].values())[0]
        rows = configdb.query(cfg, configdb.sanitize(f"SELECT * FROM `{first}` LIMIT 5"))
        for r in rows:
            print("  ", r)

    print("[3/3] 护栏拦截验证（DROP 应报错）")
    try:
        configdb.sanitize("DROP TABLE t")
        print("  !! 护栏未拦截，异常")
        sys.exit(1)
    except ValueError as e:
        print(f"  OK: {e}")

    print("冒烟通过")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 更新 CLAUDE.md 项目文档**

在 `CLAUDE.md` 的 `## 聊天群游戏绑定` 一节之后插入新节：

```markdown
## 静态配置库查询

- 每个游戏可在 `config.json` 的 `games[]` 条目内配置可选的 `config_db` 段（MySQL 连接信息 + `schema` 指向 `gm_schema_<game_id>.md`），用于查询道具名称、活动信息等静态配置。
- 配置后子 Claude 可使用 `mcp__dquery__query_config` 工具（只读：仅 SELECT / SHOW / DESCRIBE / EXPLAIN），与数仓 `query_data` 相互独立：两个库的表名不可混用，`query_config` 的 SQL 不需要 game_id 条件。
- `config_db` 建议使用只有 SELECT 权限的只读 MySQL 账号（代码层另有 configdb 护栏，双保险）；未配置的游戏调用该工具直接报错。
- 配置库表结构文档为 `gm_schema_<game_id>.md`，与数仓的 `schema_<game_id>.md` 是两个不同数据库的文档，勿复用。
```

同时在 `## 目录结构` 的文件清单中 `mcp_server.py` 一行之后插入：

```
  configdb.py       # 静态配置 MySQL 库只读护栏与查询执行
```

在 `## 调试入口` 列表末尾追加：

```
- `debug/test_configdb_live.py` — 静态配置库真实 MySQL 冒烟（需先在 config.json 填好 config_db）
```

- [ ] **Step 3: 全量检查**

```bash
python -m py_compile app/*.py
python -m pytest tests/ -q
git diff --cached --name-only | grep -i config
```

Expected: 编译无错误；测试全部 PASS；grep 只可能匹配到 `app/config.py`、`tests/test_config.py` 等正当文件名，确认 `config.json` 不在暂存区。

- [ ] **Step 4: Commit**

```bash
git add debug/test_configdb_live.py CLAUDE.md
git commit -m "docs: 静态配置库查询能力项目文档与真实 MySQL 冒烟脚本

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 5: 提醒用户填写 config.json**

实现完成后向用户展示需在 `config.json` 对应游戏条目内填写的 `config_db` 骨架（host/port/user/password/database/schema），并说明：填好后运行 `python debug/test_configdb_live.py <game_id>` 验证连通性，同时创建 `gm_schema_<game_id>.md` 骨架（可先只写库名与"待补充"）。

---

## Self-Review 记录

- **Spec coverage**：spec 的 config.json 结构（Task 1）、护栏规则表（Task 2）、query_config 行为含全量返回/不写 CSV/[config] 日志前缀/未配置报错/无连接池（Task 3）、claude_cli allowedTools 与 workspace 注入（Task 4）、测试方案五项与 debug 冒烟（Tasks 1-5）、pymysql 依赖（Task 1 Step 1）、双 schema 文档约定（Task 4 注入 + Task 5 文档）均有对应任务。
- **Placeholder scan**：无 TBD/TODO；所有代码步骤均含完整代码。
- **Type consistency**：`configdb.sanitize(sql, max_rows)`、`configdb.query(cfg, sql, max_rows=500)`、`mcp_server.run_config_query(sql, chat_id, message_id)` 签名在定义与调用处一致；`ConfigGuardError` 继承 `ValueError`，Task 3 用 `except ValueError` 捕获一致；`GameConfig.config_db` 字段名各处一致。
