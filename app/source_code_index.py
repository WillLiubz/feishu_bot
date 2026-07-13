import re
from pathlib import Path


# Map from source code function / category suffix to recommended warehouse table.
# These are project conventions from CLAUDE.md; the indexer's job is to surface
# which ones appear in the source code so missing mappings can be added.
_KNOWN_LOG_PATTERNS = {
    "Log_RoleItem": ("gameeco_raw.v_presto_log_roleitem", "道具获得/消耗"),
    "Log_RoleRes": ("gameeco_raw.v_presto_log_roleres", "资源变动"),
    "Log_RoleBehavior": ("gameeco_raw.v_presto_log_rolebehavior", "玩法参与/高阶行为"),
    "BhBehavior": ("gamelog_raw.v_presto_log_bhbehavior", "玩法参与/高阶行为"),
    "RsProduceLog": ("gamelog_raw.v_presto_log_rsproduce", "道具/资源生产消耗"),
    "PayConsume": ("gamelog_raw.v_presto_log_payconsume", "货币/钻石消耗"),
    "PayGift": ("gamelog_raw.v_presto_log_paygift", "货币/钻石获得"),
    "TracePayRecharge": ("gamelog_raw.v_presto_log_payrecharge", "充值"),
    "TraceRoleReg": ("gamelog_raw.v_presto_log_rolereg", "注册/创角"),
    "EVENT_LOGIN": ("gamelog_raw.v_presto_log_rolelogin", "登录"),
    "cash_tracer": ("raw_scribe_log.curr", "货币获得"),
    "logExchangeCost": ("raw_scribe_log.prop", "货币/道具消耗"),
    "login_tracer": ("raw_scribe_log.login", "登录"),
    "register_tracer": ("raw_scribe_log.est", "注册/激活"),
}


def _find_matches(source_dir: Path) -> dict:
    """Scan source files for known log function/category patterns."""
    matches = {}
    if not source_dir.exists():
        return matches
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pattern, (table, desc) in _KNOWN_LOG_PATTERNS.items():
            if pattern in text and pattern not in matches:
                matches[pattern] = (table, desc)
    return matches


def summarize_game_source(game_id: int, source_dir: str) -> str:
    """
    Summarize the game source code to produce missing CLAUDE.md table mappings.
    Returns a markdown string; empty if source_dir is missing.
    """
    matches = _find_matches(Path(source_dir))
    if not matches:
        return ""
    lines = [f"### 游戏 {game_id} 源码日志映射补充（自动扫描）", ""]
    lines.append("| 源码标识 | 含义 | 推荐数仓表 |")
    lines.append("|---|---|---|")
    for pattern, (table, desc) in sorted(matches.items()):
        lines.append(f"| {pattern} | {desc} | {table} |")
    return "\n".join(lines)
