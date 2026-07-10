# 玩家分群行为分析模板

模板文件：`app/templates/player_segment.json`

## 用途

对指定时段内的活跃用户进行三群划分，并分别分析其付费点、玩法参与、行为分布，为运营提供：

- 付费玩家：重点付费点位与玩法联动。
- 沉默玩家：历史付费但当前未付费用户的现状。
- 免费玩家：未付费用户的主要行为与留存线索。

## 分群口径

| 群体 | 通用定义 |
|---|---|
| 付费玩家 | 分析窗口内有过充值/付费记录 |
| 沉默玩家 | 分析窗口前 N 天内曾付费，但窗口内未付费 |
| 免费玩家 | 分析窗口内活跃，且窗口内 + 沉默窗口内均无付费 |

- 分析窗口默认：近 7 天（支持自然语言覆盖，如“近14天”“上周”“2026-07-01~2026-07-07”）。
- 沉默窗口默认：30 天。
- Top 明细默认：每群 100 人。

具体字段/表随游戏不同，详见 `schema_312.md` / `schema_160.md` / `schema_39.md` 的“玩家分群行为分析模板”章节。

## 飞书触发词

`玩家分群`、`付费点分析`、`沉默分析`、`免费玩家行为`、`玩家行为分析`

## 输出 Sheet

1. **概览**：三群人数、付费金额/钻石、ARPU/ARPPU（或人均充值钻石）。
2. **付费玩家付费点**：按充值商品/类型汇总金额与次数。
3. **付费玩家玩法参与**：付费玩家 vs 全量活跃玩家的玩法/消费系统参与率。
4. **沉默玩家现状**：沉默玩家在当前窗口的行为分布与历史付费。
5. **免费玩家行为**：免费玩家的行为分布、活跃天数、等级/VIP。
6. **Top 明细**：每群 Top 100 玩家名单及关键标签。

## 新增模板的方法

1. 在 `player_segment.json` 的 `games` 下新增游戏 ID 节点。
2. 每个游戏提供 6 个 Sheet，键名固定为：
   - `overview`
   - `paid_recharge`
   - `paid_engagement`
   - `silent_behavior`
   - `free_behavior`
   - `top_detail`
3. SQL 中使用占位符：
   - `{analysis_start}` / `{analysis_end}` — 分析窗口起止（yyyyMMdd）
   - `{silent_start}` / `{silent_end}` — 沉默窗口起止（yyyyMMdd）
   - `{game_id}` / `{game_id_str}` — 游戏 ID
   - `{top_n}` — Top 明细行数
   - `{server_filter}` — 测试服过滤条件
4. 在 `config.json` 的 `report_triggers.player_segment` 中保留触发词。
5. 在对应 `schema_*.md` 中补充模板口径说明。

## 开发注意事项

- 模板渲染使用标准库，不引入新依赖。
- SQL 占位符必须是 `{key}` 形式，渲染时只替换已知参数。
- 每条 SQL 必须包含对应游戏的 `game_id` / `gameid` 过滤，避免跨游戏扫描。
- 312 使用 `gameeco_odl.v_presto_log_rolebehavior`（T+1 行为流水）；160 使用 `gamelog_raw.v_presto_log_bhbehavior`；39 使用 `raw_scribe_log.prop` 作为玩法/消费代理。
