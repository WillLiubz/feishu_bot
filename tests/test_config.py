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
                "schema": "schema.md",
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
