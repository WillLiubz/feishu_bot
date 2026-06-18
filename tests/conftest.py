import json
import pytest


@pytest.fixture(autouse=True, scope="session")
def _default_feishu_bot_root(tmp_path_factory):
    """Set FEISHU_BOT_ROOT to a temp dir with a minimal config.json before any test imports config."""
    root = tmp_path_factory.mktemp("config_root")
    cfg = {
        "feishu": {"app_id": "cli_default", "app_secret": "secret_default"},
        "game": {"game_id": 1, "ds_start": "20200101"},
        "channels": {"lock_opgame_ids": [], "aliases": {}},
        "data_api": {
            "client_id": "0", "key": "k",
            "search_url": "http://s/", "download_url": "http://d/",
            "max_rows": 10, "mock": True
        },
        "claude": {"model": "m", "cli_path": "claude", "max_turns": 5, "timeout": 60},
        "bot": {"max_concurrent": 1, "default_sql_limit": 10, "whitelist": False,
                "user_opgames": {}, "names": {}},
        "logview": {"host": "127.0.0.1", "port": 8900, "key": ""},
        "help_text": "h",
        "report_triggers": {"kpi": ["kpi"], "ltv": ["ltv"]},
        "reports": {
            "login_table": "t.login",
            "pay_table": "t.pay",
            "account_login_table": "t.acc"
        }
    }
    (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    import os
    os.environ["FEISHU_BOT_ROOT"] = str(root)
    yield root
