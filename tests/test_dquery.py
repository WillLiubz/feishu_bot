import sys, csv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))


def test_write_csv_to_creates_file(tmp_path):
    import dquery
    rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
    p = tmp_path / "out.csv"
    dquery.write_csv_to(rows, p)
    assert p.exists()


def test_write_csv_to_has_utf8_bom(tmp_path):
    import dquery
    rows = [{"名称": "测试"}]
    p = tmp_path / "out.csv"
    dquery.write_csv_to(rows, p)
    raw = p.read_bytes()
    assert raw[:3] == b'\xef\xbb\xbf', "Missing UTF-8 BOM"


def test_write_csv_to_correct_columns(tmp_path):
    import dquery
    rows = [{"a": "1", "b": "2"}]
    p = tmp_path / "out.csv"
    dquery.write_csv_to(rows, p)
    with open(p, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        data = list(reader)
    assert data[0]["a"] == "1"
    assert data[0]["b"] == "2"


def test_write_csv_empty_rows(tmp_path):
    import dquery
    p = tmp_path / "out.csv"
    dquery.write_csv_to([], p)
    assert p.exists()


def test_write_csv_returns_temp_path():
    import dquery
    rows = [{"x": "1"}]
    path = dquery.write_csv(rows)
    assert path.endswith(".csv")
    assert Path(path).exists()
