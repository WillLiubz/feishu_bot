import json
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import config
import configdb


def query(game_id, sql, database=None, max_rows=5000):
    gc = config.game_config(game_id)
    cdb = gc.config_db
    cfg = {
        "host": cdb["host"],
        "port": cdb["port"],
        "user": cdb["user"],
        "password": cdb["password"],
        "database": database or cdb["database"],
        "charset": cdb.get("charset", "utf8mb4"),
        "connect_timeout": cdb.get("connect_timeout", 5),
        "read_timeout": cdb.get("read_timeout", 30),
    }
    clean = configdb.sanitize(sql, max_rows=max_rows)
    return configdb.query(cfg, clean, max_rows=max_rows)


def fetch_activities(month_start, month_end):
    """Fetch activities whose start_time falls within [month_start, month_end)."""
    acts = query(39, f"""
        SELECT *
        FROM activity
        WHERE game_id = 39
          AND start_time >= '{month_start}'
          AND start_time < '{month_end}'
        ORDER BY start_time, id
    """)
    ids = [a["id"] for a in acts]
    if not ids:
        return acts

    id_list = ",".join(str(i) for i in ids)

    rewards = query(39, f"""
        SELECT *
        FROM activity_reward
        WHERE activity_id IN ({id_list})
        ORDER BY activity_id, id
    """)

    reward_map = defaultdict(list)
    for r in rewards:
        reward_map[r["activity_id"]].append(r)

    for a in acts:
        a["rewards"] = reward_map[a["id"]]

    return acts


def reward_rule_skeleton(r):
    """Reward fields that define the rule/condition, excluding actual reward content."""
    return {
        "reward_type": r.get("reward_type"),
        "type_value": r.get("type_value"),
        "type_times": r.get("type_times"),
        "button_type": r.get("button_type"),
        "cond_desc": r.get("cond_desc"),
        "func_type": r.get("func_type"),
        "func_content": r.get("func_content"),
        "relation": r.get("relation"),
        "send_msg": r.get("send_msg"),
    }


def reward_content_signature(r):
    """Reward fields that are expected to vary: cost and reward content."""
    return {
        "cost": r.get("cost"),
        "reward": r.get("reward"),
    }


def rule_signature(a):
    """Signature based on rules/conditions (exclude time fields, names, ids, and reward content)."""
    sig = {
        "tpl_id": a.get("tpl_id"),
        "activity_type": a.get("activity_type"),
        "reward_type": a.get("reward_type"),
        "type_value": a.get("type_value"),
        "type_times": a.get("type_times"),
        "activity_group_id": a.get("activity_group_id"),
        "url_type": a.get("url_type"),
        "target_id": a.get("target_id"),
        "hot": a.get("hot"),
        "sort": a.get("sort"),
        "status": a.get("status"),
        "desc_info": a.get("desc_info"),
        # reward 骨架（规则/条件，不含实际奖励数值/道具）
        "rewards": [reward_rule_skeleton(x) for x in a.get("rewards", [])],
    }
    return json.dumps(sig, ensure_ascii=False, sort_keys=True, default=str)


def reward_signature(a):
    """Full reward content signature for detecting reward changes."""
    return json.dumps(
        [reward_content_signature(r) for r in a.get("rewards", [])],
        ensure_ascii=False, sort_keys=True, default=str
    )


def summary(a):
    return {
        "id": a["id"],
        "name": a["name"],
        "start_time": a["start_time"],
        "end_time": a["end_time"],
        "start_get_time": a["start_get_time"],
        "end_get_time": a["end_get_time"],
        "panel_stime": a["panel_stime"],
        "panel_etime": a["panel_etime"],
        "reward_ids": a["reward_ids"],
        "status": a["status"],
    }


def compare_months(may_acts, jun_acts):
    """Compare May and June activities by rule signature."""
    may_by_sig = defaultdict(list)
    jun_by_sig = defaultdict(list)

    for a in may_acts:
        may_by_sig[rule_signature(a)].append(a)
    for a in jun_acts:
        jun_by_sig[rule_signature(a)].append(a)

    results = []
    for sig, mays in may_by_sig.items():
        juns = jun_by_sig.get(sig)
        if not juns:
            continue

        # 同一规则组内，按奖励内容再细分
        reward_groups = defaultdict(lambda: {"may": [], "jun": []})
        for a in mays:
            reward_groups[reward_signature(a)]["may"].append(a)
        for a in juns:
            reward_groups[reward_signature(a)]["jun"].append(a)

        results.append({
            "rule_signature": sig,
            "may_count": len(mays),
            "jun_count": len(juns),
            "may_activities": [summary(a) for a in mays],
            "jun_activities": [summary(a) for a in juns],
            "reward_variants": [
                {
                    "reward_signature": r_sig,
                    "may_ids": [a["id"] for a in g["may"]],
                    "jun_ids": [a["id"] for a in g["jun"]],
                }
                for r_sig, g in reward_groups.items()
            ],
            "rewards_identical": len(reward_groups) == 1,
        })

    return results


if __name__ == "__main__":
    print("Fetching May 2026 activities...")
    may = fetch_activities("2026-05-01", "2026-06-01")
    print(f"  count: {len(may)}")

    print("Fetching June 2026 activities...")
    jun = fetch_activities("2026-06-01", "2026-07-01")
    print(f"  count: {len(jun)}")

    print("Comparing by rules/conditions...")
    similar = compare_months(may, jun)
    print(f"  similar rule groups: {len(similar)}")

    may_matched = sum(g["may_count"] for g in similar)
    jun_matched = sum(g["jun_count"] for g in similar)
    identical_rewards = sum(1 for g in similar if g.get("rewards_identical"))

    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    raw_path = out_dir / "activity_39_may_jun_2026_raw.json"
    raw_path.write_text(
        json.dumps({"may": may, "june": jun, "similar_groups": similar},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Raw data saved to {raw_path}")

    doc_lines = [
        "# 游戏 39 运营活动相似性分析 — 2026 年 5 月 vs 6 月",
        "",
        "## 统计摘要",
        "",
        f"- 5 月活动数：{len(may)}",
        f"- 6 月活动数：{len(jun)}",
        f"- 发现规则/条件基本一致的活动组：{len(similar)}",
        f"- 5 月中存在 6 月对应相似活动的数量：{may_matched}（占比 {may_matched/len(may)*100:.1f}%）",
        f"- 6 月中存在 5 月对应相似活动的数量：{jun_matched}（占比 {jun_matched/len(jun)*100:.1f}%）",
        f"- 规则一致且奖励内容也完全一致的活动组：{identical_rewards} / {len(similar)}",
        f"- 规则一致但奖励内容存在差异的活动组：{len(similar) - identical_rewards} / {len(similar)}",
        "",
        "## 判断标准",
        "",
        "1. **规则/条件一致**：活动模板ID（tpl_id）、activity_type、reward_type、type_value、type_times、activity_group_id、url_type、target_id、hot、sort、status、desc_info 以及关联的 activity_reward 规则骨架（reward_type / type_value / type_times / button_type / cond_desc / func_type / func_content / relation / send_msg）完全一致。",
        "2. **允许变化**：活动时间（start_time / end_time / start_get_time / end_get_time / panel_stime / panel_etime）、活动主键 id、名称 name、图片 URL、created_by / modify_by 等发布信息，以及奖励具体内容（cost / reward 字段中的道具/数量）。",
        "",
        "## 相似活动组详情",
        "",
    ]

    for idx, group in enumerate(similar, start=1):
        may_names = sorted({a["name"] for a in group["may_activities"]})
        jun_names = sorted({a["name"] for a in group["jun_activities"]})
        doc_lines.append(f"### 组 {idx}")
        doc_lines.append("")
        doc_lines.append(f"- 5 月活动数：{group['may_count']}；6 月活动数：{group['jun_count']}")
        doc_lines.append(f"- 5 月活动名称：{', '.join(may_names) or '(无名称)'}")
        doc_lines.append(f"- 6 月活动名称：{', '.join(jun_names) or '(无名称)'}")
        doc_lines.append("")
        doc_lines.append("#### 5 月活动")
        doc_lines.append("")
        doc_lines.append("| ID | 名称 | 开始时间 | 结束时间 | 奖励领取开始 | 奖励领取结束 | 面板开始 | 面板结束 | reward_ids | 状态 |")
        doc_lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for a in group["may_activities"]:
            doc_lines.append(
                f"| {a['id']} | {a['name']} | {a['start_time']} | {a['end_time']} | "
                f"{a['start_get_time']} | {a['end_get_time']} | {a['panel_stime']} | {a['panel_etime']} | "
                f"{a['reward_ids']} | {a['status']} |"
            )
        doc_lines.append("")
        doc_lines.append("#### 6 月活动")
        doc_lines.append("")
        doc_lines.append("| ID | 名称 | 开始时间 | 结束时间 | 奖励领取开始 | 奖励领取结束 | 面板开始 | 面板结束 | reward_ids | 状态 |")
        doc_lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for a in group["jun_activities"]:
            doc_lines.append(
                f"| {a['id']} | {a['name']} | {a['start_time']} | {a['end_time']} | "
                f"{a['start_get_time']} | {a['end_get_time']} | {a['panel_stime']} | {a['panel_etime']} | "
                f"{a['reward_ids']} | {a['status']} |"
            )
        doc_lines.append("")
        if group.get("rewards_identical"):
            doc_lines.append("- 奖励内容：5 月与 6 月完全一致（cost / reward 字段均相同）。")
        else:
            doc_lines.append("- 奖励内容：5 月与 6 月存在差异，具体变体如下：")
            for rv in group["reward_variants"]:
                doc_lines.append(f"  - 5 月活动 ID：{rv['may_ids']}；6 月活动 ID：{rv['jun_ids']}")
        doc_lines.append("")

    doc_path = out_dir / "activity_39_may_jun_2026_analysis.md"
    doc_path.write_text("\n".join(doc_lines), encoding="utf-8")
    print(f"Analysis document saved to {doc_path}")
