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
