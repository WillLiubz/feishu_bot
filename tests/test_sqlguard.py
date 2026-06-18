import sys, os, json, pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))


@pytest.fixture(autouse=True)
def patch_config(tmp_path, monkeypatch):
    cfg = {
        "feishu": {"app_id": "x", "app_secret": "x"},
        "game": {"game_id": 312, "ds_start": "20260615"},
        "channels": {"lock_opgame_ids": [], "aliases": {}},
        "data_api": {"client_id": "1", "key": "k", "search_url": "http://s/",
                     "download_url": "http://d/", "max_rows": 100, "mock": True},
        "claude": {"model": "m", "cli_path": "claude", "max_turns": 5, "timeout": 60},
        "bot": {"max_concurrent": 1, "default_sql_limit": 200, "whitelist": False,
                "user_opgames": {}, "names": {}},
        "logview": {"host": "127.0.0.1", "port": 8900, "key": ""},
        "help_text": "h", "report_triggers": {},
        "reports": {"login_table": "t", "pay_table": "t", "account_login_table": "t"}
    }
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    monkeypatch.setenv("FEISHU_BOT_ROOT", str(tmp_path))
    import importlib, config, sqlguard
    importlib.reload(config)
    importlib.reload(sqlguard)


def test_valid_select_passes():
    import sqlguard
    sql = "SELECT COUNT(*) FROM t WHERE game_id = 312 AND ds = '20260617'"
    result = sqlguard.sanitize(sql)
    assert "SELECT" in result.upper()


def test_auto_adds_limit():
    import sqlguard
    sql = "SELECT * FROM t WHERE game_id = 312 AND ds = '20260617'"
    result = sqlguard.sanitize(sql)
    assert "LIMIT 200" in result


def test_does_not_double_limit():
    import sqlguard
    sql = "SELECT * FROM t WHERE game_id = 312 AND ds = '20260617' LIMIT 50"
    result = sqlguard.sanitize(sql)
    assert result.upper().count("LIMIT") == 1


def test_rejects_delete():
    import sqlguard
    with pytest.raises(ValueError, match="禁止"):
        sqlguard.sanitize("DELETE FROM t WHERE game_id = 312")


def test_rejects_insert():
    import sqlguard
    with pytest.raises(ValueError, match="禁止"):
        sqlguard.sanitize("INSERT INTO t VALUES (1)")


def test_rejects_double_dash_comment():
    import sqlguard
    with pytest.raises(ValueError, match="禁止"):
        sqlguard.sanitize("SELECT 1 -- comment WHERE game_id = 312")


def test_rejects_missing_game_id():
    import sqlguard
    with pytest.raises(ValueError, match="game_id"):
        sqlguard.sanitize("SELECT * FROM t WHERE ds = '20260617'")


def test_string_literal_with_delete_does_not_false_positive():
    import sqlguard
    sql = "SELECT * FROM t WHERE game_id = 312 AND ds = '20260617' AND name = 'delete item'"
    result = sqlguard.sanitize(sql)
    assert result is not None


def test_rejects_multiple_statements():
    import sqlguard
    with pytest.raises(ValueError, match="多条"):
        sqlguard.sanitize("SELECT 1; DROP TABLE t")


def test_with_cte_passes():
    import sqlguard
    sql = ("WITH cte AS (SELECT 1 as x) "
           "SELECT x FROM cte WHERE game_id = 312 AND ds = '20260617'")
    result = sqlguard.sanitize(sql)
    assert result is not None


def test_subquery_limit_still_adds_top_level_limit():
    import sqlguard
    sql = ("SELECT * FROM (SELECT * FROM t WHERE game_id = 312 LIMIT 10) sub "
           "WHERE ds = '20260617'")
    result = sqlguard.sanitize(sql)
    assert result.upper().endswith("LIMIT 200")


def test_channel_lock_blocks_other_opgame():
    import sqlguard, config
    config.LOCK_OPGAME_IDS = ["3553"]
    with pytest.raises(ValueError, match="渠道"):
        sqlguard.sanitize(
            "SELECT * FROM t WHERE game_id = 312 AND ds = '20260617' AND opgame_id = '9999'"
        )
    config.LOCK_OPGAME_IDS = []


def test_channel_lock_allows_locked_opgame():
    import sqlguard, config
    config.LOCK_OPGAME_IDS = ["3553"]
    sql = ("SELECT * FROM t WHERE game_id = 312 AND ds = '20260617' "
           "AND opgame_id = '3553'")
    result = sqlguard.sanitize(sql)
    assert result is not None
    config.LOCK_OPGAME_IDS = []
