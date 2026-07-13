import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import source_code_index


def test_summarize_logs(tmp_path):
    # Fake source tree for game 312
    src = tmp_path / "src" / "ns3" / "aes_game"
    src.mkdir(parents=True)
    (src / "module_item.go").write_text(
        "func execReward() { Log_RoleItem(1, item_id, amount) }\n"
        "func method_execConsume() { Log_RoleItem(2, item_id, amount) }\n"
        "func Log_RoleRes() { /* gain=1 consume=2 */ }\n",
        encoding="utf-8",
    )
    (src / "behavior.go").write_text(
        "func Log_RoleBehavior() { BhBehavior(b_type, b_value) }\n",
        encoding="utf-8",
    )
    summary = source_code_index.summarize_game_source(312, str(tmp_path / "src"))
    assert "Log_RoleItem" in summary
    assert "Log_RoleBehavior" in summary
    assert "gameeco_raw" in summary or "gamelog_raw" in summary


def test_summarize_no_source_dir(tmp_path):
    summary = source_code_index.summarize_game_source(999, str(tmp_path / "missing"))
    assert summary == ""
