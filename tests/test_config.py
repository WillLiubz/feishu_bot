import sys, os, json, tempfile, pytest
from pathlib import Path

# Allow running tests from project root
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))


def _write_config(tmp_path, overrides=None):
    base = {
        "feishu": {"app_id": "cli_test", "app_secret": "secret_test"},
        "games": [
            {
                "game_id": 312,
                "ds_start": "20260615",
                "schema": "schema_312.md",
                "aliases": ["女3"],
                "reports": {
                    "login_table": "gamelog_raw.log_rolelogin",
                    "pay_table": "gamelog_raw.log_payrecharge",
                    "account_login_table": "gamelog_raw.log_accountlogin"
                },
                "lock_opgame_ids": []
            }
        ],
        "channels": {"lock_opgame_ids": [], "aliases": {}},
        "data_api": {
            "client_id": "92", "key": "testkey",
            "search_url": "http://search/", "download_url": "http://dl/",
            "max_rows": 10000, "mock": False
        },
        "claude": {"model": "claude-sonnet-4-6", "cli_path": "claude", "max_turns": 25, "timeout": 600},
        "bot": {"max_concurrent": 3, "default_sql_limit": 200, "whitelist": False, "user_opgames": {}, "names": {}},
        "logview": {"host": "127.0.0.1", "port": 8900, "key": ""},
        "help_text": "help",
        "report_triggers": {"kpi": ["kpi"], "ltv": ["ltv"]},
    }
    if overrides:
        for k, v in overrides.items():
            if isinstance(base.get(k), dict):
                base[k].update(v)
            elif isinstance(base.get(k), list):
                base[k] = v
            else:
                base.update({k: v})
    p = tmp_path / "config.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    return str(tmp_path)


def test_loads_game_id(tmp_path, monkeypatch):
    root = _write_config(tmp_path)
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    assert config.GAME_ID == 312
    assert config.MULTI_GAME_MODE is True
    assert config.GAMES[312].game_id == 312


def test_loads_feishu_credentials(tmp_path, monkeypatch):
    root = _write_config(tmp_path)
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    assert config.FEISHU_APP_ID == "cli_test"
    assert config.FEISHU_APP_SECRET == "secret_test"


def test_check_raises_on_missing_app_id(tmp_path, monkeypatch):
    root = _write_config(tmp_path, {"feishu": {"app_id": "", "app_secret": "s"}})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    with pytest.raises(ValueError, match="app_id"):
        config.check()


def test_lock_opgame_ids_default_empty(tmp_path, monkeypatch):
    root = _write_config(tmp_path)
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    assert config.LOCK_OPGAME_IDS == []


def test_game_config_returns_configured_game(tmp_path, monkeypatch):
    root = _write_config(tmp_path)
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    gc = config.game_config(312)
    assert gc.game_id == 312
    assert gc.ds_start == "20260615"
    assert gc.reports["pay_table"] == "gamelog_raw.log_payrecharge"


def test_game_config_defaults_to_game_id(tmp_path, monkeypatch):
    root = _write_config(tmp_path)
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    gc = config.game_config()
    assert gc.game_id == 312


def test_chat_games_default_empty(tmp_path, monkeypatch):
    root = _write_config(tmp_path)
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    assert config.CHAT_GAMES == {}


def test_chat_games_parsed_as_int(tmp_path, monkeypatch):
    root = _write_config(tmp_path, {"bot": {"chat_games": {"oc_a": "312"}}})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    assert config.CHAT_GAMES == {"oc_a": 312}


def test_check_rejects_unknown_chat_game(tmp_path, monkeypatch):
    root = _write_config(tmp_path, {"bot": {"chat_games": {"oc_a": 999}}})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    with pytest.raises(ValueError, match="chat_games"):
        config.check()


def test_check_accepts_valid_chat_game(tmp_path, monkeypatch):
    root = _write_config(tmp_path, {"bot": {"chat_games": {"oc_a": 312}}})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    config.check()  # 不应抛错


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
    cdb = {"host": "h", "user": "u", "password": "p", "database": "d", "port": "3306"}
    root = _write_config(tmp_path, {"games": _games_with_config_db(cdb)})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    with pytest.raises(ValueError, match="port"):
        config.check()


def test_check_rejects_config_db_missing_password(tmp_path, monkeypatch):
    cdb = {"host": "h", "user": "u", "database": "d"}
    root = _write_config(tmp_path, {"games": _games_with_config_db(cdb)})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    with pytest.raises(ValueError, match="password"):
        config.check()


def test_check_rejects_config_db_non_int_connect_timeout(tmp_path, monkeypatch):
    cdb = {"host": "h", "user": "u", "password": "p", "database": "d", "connect_timeout": "5"}
    root = _write_config(tmp_path, {"games": _games_with_config_db(cdb)})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    with pytest.raises(ValueError, match="connect_timeout"):
        config.check()


def test_check_rejects_config_db_non_int_read_timeout(tmp_path, monkeypatch):
    cdb = {"host": "h", "user": "u", "password": "p", "database": "d", "read_timeout": "30"}
    root = _write_config(tmp_path, {"games": _games_with_config_db(cdb)})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    with pytest.raises(ValueError, match="read_timeout"):
        config.check()


def test_check_rejects_config_db_non_int_max_rows(tmp_path, monkeypatch):
    cdb = {"host": "h", "user": "u", "password": "p", "database": "d", "max_rows": "500"}
    root = _write_config(tmp_path, {"games": _games_with_config_db(cdb)})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    with pytest.raises(ValueError, match="max_rows"):
        config.check()


def test_check_accepts_config_db_with_static_database(tmp_path, monkeypatch):
    cdb = {
        "host": "h", "user": "u", "password": "p", "database": "d",
        "static_database": "static_db",
    }
    root = _write_config(tmp_path, {"games": _games_with_config_db(cdb)})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    config.check()  # 不抛错


def test_check_rejects_config_db_invalid_static_database(tmp_path, monkeypatch):
    cdb = {
        "host": "h", "user": "u", "password": "p", "database": "d",
        "static_database": 123,
    }
    root = _write_config(tmp_path, {"games": _games_with_config_db(cdb)})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    with pytest.raises(ValueError, match="static_database"):
        config.check()


def test_check_accepts_valid_config_db_and_warns_on_missing_schema(tmp_path, monkeypatch, capsys):
    cdb = {"host": "h", "user": "u", "password": "p", "database": "d", "schema": "gm_schema_missing.md"}
    root = _write_config(tmp_path, {"games": _games_with_config_db(cdb)})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    config.check()  # 不抛错
    assert "gm_schema_missing.md" in capsys.readouterr().out