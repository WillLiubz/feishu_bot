import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import pytest

import dataapi


def test_run_sql_rows_timeout_raises():
    """If _submit hangs, run_sql_rows(..., timeout=2) must raise RuntimeError."""

    def slow_submit(sql):
        time.sleep(10)
        return "task_id"

    with patch.object(dataapi, "_submit", side_effect=slow_submit):
        with patch.object(dataapi.config, "DATA_API_MOCK", False):
            with pytest.raises(RuntimeError, match="SQL 执行超时"):
                dataapi.run_sql_rows("SELECT 1", timeout=2)


def test_run_sql_rows_respects_max_rows():
    """Mock data path returns rows up to max_rows."""
    with patch.object(dataapi.config, "DATA_API_MOCK", True):
        rows = dataapi.run_sql_rows("SELECT 1", max_rows=1)
        assert len(rows) == 1
