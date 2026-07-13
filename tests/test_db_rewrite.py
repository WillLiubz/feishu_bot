import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import db_rewrite


def test_rewrite_single_odl_table():
    sql = "SELECT COUNT(*) FROM gamelog_odl.v_presto_log_rolelogin WHERE game_id = 312"
    assert db_rewrite.rewrite_odl_to_raw(sql) == (
        "SELECT COUNT(*) FROM gamelog_raw.v_presto_log_rolelogin WHERE game_id = 312"
    )


def test_raw_unchanged():
    sql = "SELECT * FROM gamelog_raw.v_presto_log_payrecharge WHERE game_id = 160"
    assert db_rewrite.rewrite_odl_to_raw(sql) == sql


def test_multiple_odl_occurrences():
    sql = (
        "WITH a AS (SELECT * FROM gamelog_odl.v_presto_log_rolelogin),"
        " b AS (SELECT * FROM gamelog_odl.v_presto_log_payrecharge)"
        " SELECT * FROM a, b"
    )
    expected = (
        "WITH a AS (SELECT * FROM gamelog_raw.v_presto_log_rolelogin),"
        " b AS (SELECT * FROM gamelog_raw.v_presto_log_payrecharge)"
        " SELECT * FROM a, b"
    )
    assert db_rewrite.rewrite_odl_to_raw(sql) == expected


def test_gameeco_odl_rewritten():
    sql = "SELECT * FROM gameeco_odl.v_presto_log_rolebehavior WHERE game_id = '312'"
    assert db_rewrite.rewrite_odl_to_raw(sql) == (
        "SELECT * FROM gameeco_raw.v_presto_log_rolebehavior WHERE game_id = '312'"
    )


def test_literal_not_rewritten():
    sql = "SELECT 'gamelog_odl literal' AS note FROM t WHERE game_id = 312"
    assert db_rewrite.rewrite_odl_to_raw(sql) == sql


def test_extract_odl_hint_lowercase():
    sql = "-- use_odl\nSELECT * FROM gamelog_odl.v_presto_log_rolelogin WHERE game_id = 312"
    cleaned, use_odl = db_rewrite.extract_odl_hint(sql)
    assert use_odl is True
    assert cleaned == "SELECT * FROM gamelog_odl.v_presto_log_rolelogin WHERE game_id = 312"


def test_extract_odl_hint_uppercase():
    sql = "  -- USE_ODL\nSELECT 1 FROM gamelog_odl.v_presto_log_payrecharge"
    cleaned, use_odl = db_rewrite.extract_odl_hint(sql)
    assert use_odl is True
    assert cleaned == "SELECT 1 FROM gamelog_odl.v_presto_log_payrecharge"


def test_no_hint_returns_false():
    sql = "SELECT * FROM gamelog_odl.v_presto_log_rolelogin WHERE game_id = 312"
    cleaned, use_odl = db_rewrite.extract_odl_hint(sql)
    assert use_odl is False
    assert cleaned == sql


def test_hint_not_in_middle():
    sql = "SELECT 1 -- use_odl FROM t"
    cleaned, use_odl = db_rewrite.extract_odl_hint(sql)
    assert use_odl is False
    assert cleaned == sql
