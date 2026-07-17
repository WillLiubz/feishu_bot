import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import mcp_server


def test_load_counter_empty(tmp_path):
    assert mcp_server._load_counter(tmp_path) == 0


def test_load_counter_with_existing_files(tmp_path):
    (tmp_path / "query_1.csv").write_text("a\n1\n")
    (tmp_path / "query_5.csv").write_text("a\n1\n")
    (tmp_path / "query_12.csv").write_text("a\n1\n")
    (tmp_path / "result.csv").write_text("a\n1\n")
    assert mcp_server._load_counter(tmp_path) == 12


def test_load_counter_ignores_non_csv(tmp_path):
    (tmp_path / "query_3.sql").write_text("SELECT 1")
    assert mcp_server._load_counter(tmp_path) == 0


def test_prepare_sql_rewrites_gamelog_odl_to_raw():
    sql = "SELECT COUNT(*) FROM gamelog_odl.v_presto_log_payrecharge WHERE game_id = 312"
    final, use_odl = mcp_server._prepare_sql(sql)
    assert use_odl is False
    assert "gamelog_raw.v_presto_log_payrecharge" in final
    assert "gamelog_odl" not in final


def test_prepare_sql_rewrites_gameeco_odl_to_raw():
    sql = "SELECT * FROM gameeco_odl.v_presto_log_rolebehavior WHERE game_id = '312'"
    final, use_odl = mcp_server._prepare_sql(sql)
    assert use_odl is False
    assert "gameeco_raw.v_presto_log_rolebehavior" in final
    assert "gameeco_odl" not in final


def test_prepare_sql_keeps_odl_when_hint_present():
    sql = "-- use_odl\nSELECT * FROM gamelog_odl.v_presto_log_payrecharge WHERE game_id = 312"
    final, use_odl = mcp_server._prepare_sql(sql)
    assert use_odl is True
    assert "gamelog_odl.v_presto_log_payrecharge" in final
    # hint is stripped before sqlguard, so no -- remains
    assert "-- use_odl" not in final


def test_prepare_sql_adds_default_limit():
    sql = "SELECT * FROM gamelog_odl.v_presto_log_rolelogin WHERE game_id = 312"
    final, use_odl = mcp_server._prepare_sql(sql)
    assert use_odl is False
    assert "LIMIT" in final


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

    def _query(cfg, sql, max_rows=500, *, database=None):
        assert database == "d"
        return fake_rows

    monkeypatch.setattr(mcp_server.configdb, "query", _query)
    out = mcp_server.run_config_query("SELECT * FROM item_config", "c1", "m1")
    assert out["row_count"] == 2
    assert out["columns"] == ["item_id", "name"]
    assert out["rows"] == fake_rows


def test_run_config_query_can_target_static_database(monkeypatch):
    calls = []
    cdb = {"host": "h", "user": "u", "database": "d", "static_database": "static_db", "max_rows": 500}
    monkeypatch.setattr(mcp_server.config, "game_config", lambda gid=None: _gc_with_config_db(cdb))
    monkeypatch.setattr(mcp_server.store, "log_query", lambda *a, **k: None)

    def _query(cfg, sql, max_rows=500, *, database=None):
        calls.append(database)
        return [{"id": 1, "name": "药水"}]

    monkeypatch.setattr(mcp_server.configdb, "query", _query)
    out = mcp_server.run_config_query("SELECT * FROM static_item", "c1", "m1")
    assert out["row_count"] == 1
    assert calls == ["static_db"]


def test_run_config_query_logs_sql_with_config_prefix(monkeypatch):
    logged = []
    cdb = {"host": "h", "user": "u", "database": "d"}
    monkeypatch.setattr(mcp_server.config, "game_config", lambda gid=None: _gc_with_config_db(cdb))
    monkeypatch.setattr(mcp_server.store, "log_query", lambda *a, **k: logged.append(a))
    monkeypatch.setattr(mcp_server.configdb, "query", lambda cfg, sql, max_rows=500, *, database=None: [])
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

    def _boom(cfg, sql, max_rows=500, *, database=None):
        raise RuntimeError("连接失败")

    monkeypatch.setattr(mcp_server.configdb, "query", _boom)
    with pytest.raises(RuntimeError, match="连接失败"):
        mcp_server.run_config_query("SELECT 1", "c1", "m1")
    assert logged[0][4] == "error"
