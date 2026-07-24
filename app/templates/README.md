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

## 付费构成与活动分析模板（pay_activity，仅 312）

模板文件：`app/templates/pay_activity.json`

对指定日期（默认昨日单日）输出 7 个 Sheet：

1. **付费概览**：DAU、付费人数、收入(USD)、付费率、ARPPU。
2. **付费构成**：普通充值 vs 直购（按 actId 细分：14 新手直购 / 13 新月卡 / 9 天使通行证 / 7、8 商店）。
3. **充值档位分布**：单笔金额档位（<$1 ~ ≥$100）的笔数/人数/金额。
4. **付费用户分层**：按当日累计充值 9 档（<$10 / 10~20 / 20~40 / 40~80 / 80~100 / 100~150 / 150~200 / 200~300 / ≥$300）。
5. **分层×活动参与**：分层 × 活动主题（`json_extract_scalar(activity_topic,'$.cn')`）的参与人数/次数（`rolepromo` 领奖记录）。
6. **活动总览**：全量玩家当日全部活动主题，按参与人数排序。
7. **分层×道具产销**：分层 × 产出/消耗 × 道具（`roleitem`，数量=变动前后差绝对值合计；每个分层×方向按数量取 Top 20，分层从高到低（≥$300 在前），避免单日全量超 max_rows 截断后高付费分层不可见）。`roleitem.item_name` 实测恒为空，道具中文名由 `name_enrich.translate_dir` 查配置库 `game_item`/`game_resource` 补进"道具名称"列。

口径：金额 USD；活动参与来自 `gameeco_raw.v_presto_log_rolepromo`（其 `item_spend`/`item_get` 源码硬编码恒空，不可用）；道具产销来自 `gameeco_raw.v_presto_log_roleitem`（`change_type` '1'=产出 / '2'=消耗，varchar 数值列必须显式 `CAST(... AS BIGINT)`）；全部活动纳入不过滤。
触发词：`付费构成`、`活动付费分析`、`付费活动分析`、`付费分层`。

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
4. **列别名必须使用英文**：数仓 SQL 解析器不支持中文列别名（如 `AS 测试` 会报错），因此 SELECT / GROUP BY / ORDER BY 中的列名/别名统一用英文。
5. 每个 Sheet 提供 `columns` 映射（`英文别名 → 中文表头`），`run_report` 会在写 CSV 前自动转换，确保 Excel 输出仍为中文。
6. 在 `config.json` 的 `report_triggers.player_segment` 中保留触发词。
7. 在对应 `schema_*.md` 中补充模板口径说明。

## 开发注意事项

- 模板渲染使用标准库，不引入新依赖。
- SQL 占位符必须是 `{key}` 形式，渲染时只替换已知参数。
- 每条 SQL 必须包含对应游戏的 `game_id` / `gameid` 过滤，避免跨游戏扫描。
- 312 使用 `gamelog_raw.v_presto_log_bhbehavior`（`b_type`）；160 使用 `gamelog_raw.v_presto_log_bhbehavior`（`b_id`）；39 使用 `raw_scribe_log.prop` 作为玩法/消费代理。
- 为提升查询性能，312/160 的等级/VIP 使用 `max_by(column, ds)` 从 `rolelogin` 获取，不再使用窗口函数；160 概览的免费玩家直接通过“窗口内活跃且窗口+沉默窗口无付费”推导。
