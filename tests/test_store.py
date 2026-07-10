import sys, tempfile, os, pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FEISHU_BOT_ROOT", str(tmp_path))
    import json
    cfg = {
        "feishu": {"app_id": "x", "app_secret": "x"},
        "game": {"game_id": 312, "ds_start": "20260615"},
        "channels": {"lock_opgame_ids": [], "aliases": {}},
        "data_api": {"client_id": "1", "key": "k", "search_url": "http://s/",
                     "download_url": "http://d/", "max_rows": 100, "mock": True},
        "claude": {"model": "m", "cli_path": "claude", "max_turns": 5, "timeout": 60},
        "bot": {"max_concurrent": 1, "default_sql_limit": 10, "whitelist": False,
                "user_opgames": {}, "names": {}},
        "logview": {"host": "127.0.0.1", "port": 8900, "key": ""},
        "help_text": "h", "report_triggers": {},
        "reports": {"login_table": "t", "pay_table": "t", "account_login_table": "t"}
    }
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    import importlib, config, store
    importlib.reload(config)
    importlib.reload(store)
    store.init()
    return store


def test_log_in_and_get_session_returns_none(tmp_store):
    tmp_store.log_in("chat1", "user1", "msg1", "hello")
    assert tmp_store.get_session("chat1") is None


def test_set_and_get_session(tmp_store):
    tmp_store.set_session("chat1", "sess_abc")
    assert tmp_store.get_session("chat1") == "sess_abc"


def test_set_and_get_session_per_game(tmp_store):
    tmp_store.set_session("chat1", "sess_312", game_id=312)
    tmp_store.set_session("chat1", "sess_160", game_id=160)
    assert tmp_store.get_session("chat1", game_id=312) == "sess_312"
    assert tmp_store.get_session("chat1", game_id=160) == "sess_160"


def test_get_session_without_game_id_uses_default_key(tmp_store):
    tmp_store.set_session("chat1", "sess_default")
    assert tmp_store.get_session("chat1") == "sess_default"
    assert tmp_store.get_session("chat1", game_id=312) is None


def test_set_session_updates_existing(tmp_store):
    tmp_store.set_session("chat1", "sess_old")
    tmp_store.set_session("chat1", "sess_new")
    assert tmp_store.get_session("chat1") == "sess_new"


def test_log_query_persists(tmp_store):
    tmp_store.log_query("chat1", "msg1", "SELECT 1", 1, "ok", 100)
    import sqlite3
    from pathlib import Path
    db_path = Path(os.environ["FEISHU_BOT_ROOT"]) / "data" / "bot.db"
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT sql, status FROM query_log").fetchone()
    conn.close()
    assert row == ("SELECT 1", "ok")
