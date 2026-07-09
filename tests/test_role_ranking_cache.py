import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import pytest


@pytest.fixture
def tmp_ranking(tmp_path, monkeypatch):
    monkeypatch.setenv("FEISHU_BOT_ROOT", str(tmp_path))
    import json
    cfg = {
        "feishu": {"app_id": "x", "app_secret": "x"},
        "games": [
            {"game_id": 312, "ds_start": "20260615",
             "reports": {"login_table": "t", "pay_table": "t", "account_login_table": "t"}}
        ],
        "channels": {"lock_opgame_ids": [], "aliases": {}},
        "data_api": {"client_id": "1", "key": "k", "search_url": "http://s/",
                     "download_url": "http://d/", "max_rows": 100, "mock": False},
        "claude": {"model": "m", "cli_path": "claude", "max_turns": 5, "timeout": 60},
        "bot": {"max_concurrent": 1, "default_sql_limit": 10, "whitelist": False,
                "user_opgames": {}, "names": {}},
        "logview": {"host": "127.0.0.1", "port": 8900, "key": ""},
        "help_text": "h", "report_triggers": {}
    }
    (tmp_path / "config.json").write_text(json.dumps(cfg))

    import importlib
    import config
    import role_ranking_cache
    import dataapi
    importlib.reload(config)
    importlib.reload(role_ranking_cache)

    gcfg = config.GAMES[312]
    role_ranking_cache.init(gcfg)

    # Capture SQL calls
    calls = []

    def fake_run_sql_rows(sql, max_rows=None):
        calls.append((sql, max_rows))
        return [
            {"role_id": 1001, "rank_value": 1},
            {"role_id": 1002, "rank_value": 2},
            {"role_id": 1003, "rank_value": 3},
        ]

    monkeypatch.setattr(dataapi, "run_sql_rows", fake_run_sql_rows)

    return role_ranking_cache, gcfg, calls


def test_init_creates_table(tmp_ranking):
    rc, gcfg, _ = tmp_ranking
    db_path = Path(rc._db_path(gcfg))
    assert db_path.exists()


def test_get_roles_uses_cache_without_dataapi_call(tmp_ranking):
    rc, gcfg, calls = tmp_ranking
    # First call refreshes from "warehouse"
    roles = rc.get_roles(year_month="202606", rank_type="MonthRank", top_n=10, game_config=gcfg)
    assert roles == ["1001", "1002", "1003"]
    assert len(calls) == 1

    # Second call should be served from SQLite cache without hitting dataapi
    calls.clear()
    roles2 = rc.get_roles(year_month="202606", rank_type="MonthRank", top_n=10, game_config=gcfg)
    assert roles2 == ["1001", "1002", "1003"]
    assert len(calls) == 0


def test_get_rank_map_returns_ordered_ranks(tmp_ranking):
    rc, gcfg, _ = tmp_ranking
    rank_map = rc.get_rank_map(year_month="202606", rank_type="MonthRank", top_n=10, game_config=gcfg)
    assert rank_map == {"1001": 1, "1002": 2, "1003": 3}


def test_ttl_expiry_triggers_refresh(tmp_ranking, monkeypatch):
    rc, gcfg, calls = tmp_ranking
    rc.get_roles(year_month="202606", rank_type="MonthRank", top_n=10, game_config=gcfg)
    assert len(calls) == 1

    # Expire the TTL immediately
    key = rc._key(gcfg, "202606", "MonthRank")
    rc._last_refresh[key] = time.time() - rc._TTL - 1

    calls.clear()
    rc.get_roles(year_month="202606", rank_type="MonthRank", top_n=10, game_config=gcfg)
    assert len(calls) == 1


def test_stats(tmp_ranking):
    rc, gcfg, _ = tmp_ranking
    rc.get_roles(year_month="202606", rank_type="MonthRank", top_n=10, game_config=gcfg)
    stats = rc.stats(gcfg)
    assert stats["total"] == 3
    assert stats["months"] == 1
    assert stats["latest_cached_at"] is not None
