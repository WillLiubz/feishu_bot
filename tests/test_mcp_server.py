import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import mcp_server


def test_load_counter_empty(tmp_path):
    assert mcp_server._load_counter(tmp_path) == 0


def test_load_counter_with_existing_files(tmp_path):
    (tmp_path / "query_1.csv").write_text("a\n1\n")
    (tmp_path / "query_5.csv").write_text("a\n1\n")
    (tmp_path / "query_12.csv").write_text("a\n1\n")
    (tmp_path / "result.csv").write_text("a\n1\n")
    assert mcp_server._load_counter(tmp_path) == 12


def test_load_counter_ignores_non_csv(tmp_path):
    (tmp_path / "query_3.sql").write_text("SELECT 1")
    assert mcp_server._load_counter(tmp_path) == 0
