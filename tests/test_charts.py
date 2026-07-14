import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import charts


def test_detect_none_for_empty_rows():
    assert charts.detect_chart_type([]) is None


def test_detect_none_without_numeric_column():
    rows = [{"a": "x", "b": "y"}, {"a": "z", "b": "w"}]
    assert charts.detect_chart_type(rows) is None


def test_detect_line_when_first_column_is_date():
    rows = [{"日期": "20260701", "收入": "100"}, {"日期": "20260702", "收入": "200"}]
    assert charts.detect_chart_type(rows) == "line"


def test_detect_line_when_first_column_values_look_like_dates():
    rows = [{"ds": "20260701", "dau": "10"}, {"ds": "20260702", "dau": "20"},
            {"ds": "20260703", "dau": "30"}, {"ds": "20260704", "dau": "40"},
            {"ds": "20260705", "dau": "50"}, {"ds": "20260706", "dau": "60"},
            {"ds": "20260707", "dau": "70"}, {"ds": "20260708", "dau": "80"},
            {"ds": "20260709", "dau": "90"}]
    assert charts.detect_chart_type(rows) == "line"


def test_detect_pie_for_few_categories_single_value_column():
    rows = [{"渠道": f"ch{i}", "收入": str(i * 10 + 10)} for i in range(5)]
    assert charts.detect_chart_type(rows) == "pie"


def test_detect_bar_for_many_categories():
    rows = [{"渠道": f"ch{i}", "收入": str(i)} for i in range(12)]
    assert charts.detect_chart_type(rows) == "bar"


def test_detect_bar_for_multiple_value_columns():
    rows = [{"渠道": "a", "收入": "10", "付费人数": "3"}]
    assert charts.detect_chart_type(rows) == "bar"


def test_id_columns_excluded_from_series():
    rows = [{"排名": "1", "role_id": "1001", "充值金额": "50"},
            {"排名": "2", "role_id": "1002", "充值金额": "60"}]
    assert charts.series_columns(rows) == ["充值金额"]


def test_varchar_numeric_with_thousands_separator():
    # 游戏 39 场景：数值列是 VARCHAR，可能带千分位
    rows = [{"item": "钻石", "cnt": "1,234"}, {"item": "金币", "cnt": "5,678"}]
    assert charts.series_columns(rows) == ["cnt"]
    assert charts.detect_chart_type(rows) == "pie"


def test_to_float():
    assert charts.to_float("1,234.5") == 1234.5
    assert charts.to_float("42") == 42.0
    assert charts.to_float("abc") is None
    assert charts.to_float(None) is None


def test_slice_for_png_limits():
    rows = [{"c": str(i), "v": str(i)} for i in range(100)]
    assert len(charts._slice_for_png(rows, "pie")) == charts.MAX_PIE_CATEGORIES
    assert len(charts._slice_for_png(rows, "line")) == charts.MAX_LINE_POINTS_PNG
    assert len(charts._slice_for_png(rows, "bar")) == charts.MAX_BAR_ROWS_PNG
