import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import name_enrich


@pytest.fixture(autouse=True)
def _clear_cache():
    name_enrich._cache.clear()
    yield
    name_enrich._cache.clear()


def _gc(game_id=39, with_db=True):
    gc = MagicMock()
    gc.game_id = game_id
    gc.config_db = {"host": "h", "user": "u", "database": "gm_db",
                    "static_database": "static_db"} if with_db else {}
    return gc


def _write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_translate_39_item_id(monkeypatch, tmp_path):
    calls = []

    def fake_query(cfg, sql, max_rows=500, *, database=None):
        calls.append((sql, database))
        return [{"id": 10010, "name": "钻石礼包"}, {"id": 10011, "name": "金币箱"}]

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_1.csv"
    _write_csv(p, ["item_id", "数量"], [["10010", "5"], ["10011", "3"], ["10010", "2"]])
    assert name_enrich.translate_csv(str(p), _gc(39)) is True
    rows = _read_csv(p)
    assert list(rows[0].keys()) == ["item_id", "道具名称", "数量"]
    assert rows[0]["道具名称"] == "钻石礼包"
    assert rows[2]["道具名称"] == "钻石礼包"
    # 去重后一次 IN 查询，且走静态库
    assert len(calls) == 1
    assert "static_item" in calls[0][0] and "IN (10010, 10011)" in calls[0][0]
    assert calls[0][1] == "static_db"


def test_translate_39_activity_id_uses_gm_db(monkeypatch, tmp_path):
    calls = []

    def fake_query(cfg, sql, max_rows=500, *, database=None):
        calls.append((sql, database))
        return [{"id": 7, "name": "每日登陆"}]

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_1.csv"
    _write_csv(p, ["activity_id", "参与人数"], [["7", "100"]])
    assert name_enrich.translate_csv(str(p), _gc(39)) is True
    rows = _read_csv(p)
    assert rows[0]["活动名称"] == "每日登陆"
    assert "activity" in calls[0][0]
    assert calls[0][1] is None  # GM 运营库用默认 database


def test_translate_160_item_id_filters_game_id(monkeypatch, tmp_path):
    calls = []

    def fake_query(cfg, sql, max_rows=500, *, database=None):
        calls.append(sql)
        return [{"ident": "601229", "name": "屠龙刀"}]

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_1.csv"
    _write_csv(p, ["item_id", "数量"], [["601229", "1"]])
    assert name_enrich.translate_csv(str(p), _gc(160)) is True
    assert _read_csv(p)[0]["道具名称"] == "屠龙刀"
    assert "game_item" in calls[0] and "game_id = 160" in calls[0]
    assert "'601229'" in calls[0]  # 160/312 强制加引号


def test_skip_when_name_column_exists(monkeypatch, tmp_path):
    def fake_query(cfg, sql, max_rows=500, *, database=None):
        raise AssertionError("不应查询配置库")

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_1.csv"
    _write_csv(p, ["item_id", "item_name", "数量"], [["1", "已有名", "5"]])
    assert name_enrich.translate_csv(str(p), _gc(312)) is False


def test_no_config_db_returns_false(tmp_path):
    p = tmp_path / "query_1.csv"
    _write_csv(p, ["item_id", "数量"], [["10010", "5"]])
    assert name_enrich.translate_csv(str(p), _gc(39, with_db=False)) is False


def test_query_failure_keeps_csv_unchanged(monkeypatch, tmp_path):
    def fake_query(cfg, sql, max_rows=500, *, database=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_1.csv"
    _write_csv(p, ["item_id", "数量"], [["10010", "5"]])
    assert name_enrich.translate_csv(str(p), _gc(39)) is False
    assert list(_read_csv(p)[0].keys()) == ["item_id", "数量"]


def test_translate_dir_only_touches_query_csvs(monkeypatch, tmp_path):
    def fake_query(cfg, sql, max_rows=500, *, database=None):
        return [{"id": 1, "name": "X"}]

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    _write_csv(tmp_path / "query_1.csv", ["item_id", "数量"], [["1", "5"]])
    _write_csv(tmp_path / "other.csv", ["item_id", "数量"], [["1", "5"]])
    n = name_enrich.translate_dir(str(tmp_path), _gc(39))
    assert n == 1
    assert "道具名称" in _read_csv(tmp_path / "query_1.csv")[0]
    assert "道具名称" not in _read_csv(tmp_path / "other.csv")[0]


def test_translate_312_chinese_header(monkeypatch, tmp_path):
    calls = []

    def fake_query(cfg, sql, max_rows=500, *, database=None):
        calls.append(sql)
        return [{"ident": "2014003", "name": "屠龙刀"}]

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_5.csv"
    _write_csv(p, ["分层", "道具ID", "数量"], [["<$10", "2014003", "5"]])
    assert name_enrich.translate_csv(str(p), _gc(312)) is True
    rows = _read_csv(p)
    assert list(rows[0].keys()) == ["分层", "道具ID", "道具名称", "数量"]
    assert rows[0]["道具名称"] == "屠龙刀"
    assert "game_item" in calls[0] and "game_id = 312" in calls[0]


def test_translate_312_fallback_game_resource(monkeypatch, tmp_path):
    calls = []

    def fake_query(cfg, sql, max_rows=500, *, database=None):
        calls.append(sql)
        if "game_item" in sql:
            return []  # 道具表未命中
        return [{"id_name": "261", "name": "钻石"}]

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_6.csv"
    _write_csv(p, ["item_id", "amount"], [["261", "100"]])
    assert name_enrich.translate_csv(str(p), _gc(312)) is True
    rows = _read_csv(p)
    assert rows[0]["道具名称"] == "钻石"
    assert any("game_resource" in s and "id_name" in s for s in calls)


def test_translate_312_fallback_failure_silent(monkeypatch, tmp_path):
    def fake_query(cfg, sql, max_rows=500, *, database=None):
        if "game_resource" in sql:
            raise RuntimeError("db down")
        return []

    monkeypatch.setattr(name_enrich.configdb, "query", fake_query)
    p = tmp_path / "query_6.csv"
    _write_csv(p, ["item_id", "amount"], [["999", "1"]])
    # 不抛异常；主表与 fallback 都未命中时无改动
    assert name_enrich.translate_csv(str(p), _gc(312)) is False
