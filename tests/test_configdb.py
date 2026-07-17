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

def test_comment_without_space_rejected():
    with pytest.raises(configdb.ConfigGuardError):
        configdb.sanitize("SELECT 1 #comment")


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
    "PREPARE stmt FROM 'SELECT 1'",
    "EXECUTE stmt",
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
    assert kw["database"] == "d"


def test_query_can_override_database(monkeypatch):
    sink = _stub_connect(monkeypatch, [{"id": 2, "name": "金币"}])
    configdb.query(
        {"host": "h", "user": "u", "password": "p", "database": "d"},
        "SELECT * FROM static_item",
        database="static_db",
    )
    assert sink["kwargs"]["database"] == "static_db"


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
