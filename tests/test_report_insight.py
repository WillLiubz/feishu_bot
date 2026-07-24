"""Tests for report_insight (LLM 经营解读)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import report_insight


def _write(path, text):
    path.write_text(text, encoding="utf-8-sig")


def test_build_prompt_includes_all_sheets(tmp_path):
    _write(tmp_path / "query_1.csv", "a,b\n1,2\n")
    _write(tmp_path / "query_2.csv", "c,d\n3,4\n")
    prompt = report_insight.build_prompt(str(tmp_path))
    assert "query_1" in prompt and "query_2" in prompt
    assert "1,2" in prompt and "3,4" in prompt


def test_build_prompt_truncates_long_sheet(tmp_path, monkeypatch):
    monkeypatch.setattr(report_insight, "_MAX_ROWS_PER_SHEET", 5)
    rows = "\n".join(f"{i},{i}" for i in range(100))
    _write(tmp_path / "query_1.csv", "a,b\n" + rows + "\n")
    prompt = report_insight.build_prompt(str(tmp_path))
    assert "截断" in prompt


def test_build_prompt_empty_dir(tmp_path):
    assert report_insight.build_prompt(str(tmp_path)) == ""


def test_interpret_returns_stripped_answer(monkeypatch, tmp_path):
    _write(tmp_path / "query_1.csv", "a\n1\n")
    monkeypatch.setattr(
        report_insight.claude_cli, "run_with_system_prompt",
        lambda q, ws, sp: ("  解读文本  ", "sid"),
    )
    assert report_insight.interpret("付费构成", str(tmp_path), MagicMock()) == "解读文本"


def test_interpret_failure_returns_empty(monkeypatch, tmp_path):
    _write(tmp_path / "query_1.csv", "a\n1\n")

    def boom(q, ws, sp):
        raise RuntimeError("处理超时")

    monkeypatch.setattr(report_insight.claude_cli, "run_with_system_prompt", boom)
    assert report_insight.interpret("付费构成", str(tmp_path), MagicMock()) == ""


def test_interpret_no_data_returns_empty(tmp_path):
    assert report_insight.interpret("付费构成", str(tmp_path), MagicMock()) == ""
