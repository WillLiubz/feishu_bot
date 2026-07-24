# 312 付费构成与活动分析报表（pay_activity）设计

日期：2026-07-23
状态：已获用户确认（方案 C：固定模板 + LLM 经营解读）

## 背景与目标

为游戏 312 建立一个可重复使用的 KPI 分析模板：用户指定时间（默认昨日单日）后，机器人输出一份多 Sheet Excel + 中文经营解读，回答三个问题：

1. **付费构成**：当日收入由普通充值与各类直购如何构成，单笔金额档位分布如何。
2. **付费用户分层**：当日付费用户按累计充值金额（USD）分层后，各层人数/金额/占比。
3. **分层 × 付费活动**：各层玩家参与了哪些活动（精彩活动 + 活动日历中的全部活动），每个活动对应的消耗与产出。

活动范围**不过滤**：当日 rolepromo 有参与记录的活动全部列出，并带"是否精彩活动 / 是否充值活动"标记，便于与运营日历（跨服大亨、限时召唤、女神轮盘、女神悬赏、女神方舟、女神集市、女神拉霸、水果机、狂欢节、王的财宝、钻石刮刮乐、彩票、买一送一、女神通行证等）人工对照。

## 关键口径（已与用户确认）

- 金额币种：**USD**（`payrecharge.pay_money`，`pay_currency` 实测全为 USD）。
- 分层边界（按当日累计充值，互斥落一层）：
  `<$10`、`$10~20`、`$20~40`、`$40~80`、`$80~100`、`$100~150`、`$150~200`、`$200~300`、`≥$300`。
- 消耗/产出口径：**道具产销流水口径**——`gameeco_raw.v_presto_log_roleitem`（`change_type = '1'` 产出 / `'2'` 消耗，按当日累计分层归属）。⚠ 原设计采用 rolepromo 的 `item_spend`/`item_get`，2026-07-24 实测+源码确认：该两字段在唯一调用点（`module_activity.go:2293`）硬编码传 `""`，全月 170 万+ 行无一非空；`activity_special`/`activity_pay` 同处硬编码 `1`/`0`，标记无意义。rolepromo 仅用于"活动参与"（领奖记录的人数/次数）。
- **rolepromo 实测**（2026-07-24 探针）：`activity_topic` 为多语言 JSON 字符串，中文名需 `json_extract_scalar(activity_topic, '$.cn')` 提取；`game_id`/`role_id` 为 varchar；`role_type` 为 integer。
- **roleitem 实测**（2026-07-24 探针）：`change_type`/`status_before`/`status_after` 均为 **varchar**；聚合必须显式 `CAST(... AS BIGINT)`（隐式算术在 1600 万行/天上 6 分钟跑不完，显式 CAST 约 5 秒）；表自带 `item_name`。
- 付费构成维度：普通充值 vs 直购（多选结果，另含充值金额档位分布）。
- **所有出现 item ID 的地方必须补中文道具名**（用户明确要求）。
- 数值字段一律 `COALESCE(TRY_CAST(... AS DOUBLE), 0)`；312 过滤 `game_id = 312`、`SUBSTR(CAST(server_id AS VARCHAR), 5, 1) != '4'`；role_id 为 VARCHAR，过滤时加引号。

## 方案概述（方案 C）

固定报表模板（与 `player_segment` 同构）出 Excel，再由子 Claude 基于聚合结果写中文经营解读。解读失败不影响数据交付。

## 组件设计

### 1. 模板 `app/templates/pay_activity.json`（新增）

仅配置 `games.312`。复用 `templates.compute_params` 的日期解析（默认昨日单日；支持"今日"、"7月15日"、绝对日期范围）。占位符沿用 `{analysis_start}` / `{analysis_end}` / `{game_id}` / `{server_filter}`。

7 个 Sheet（顺序固定）：

| # | key | Sheet 名 | 数据源 | 内容 |
|---|---|---|---|---|
| 1 | `overview` | 付费概览 | `gamelog_raw.v_presto_log_payrecharge` + `v_presto_log_rolelogin` | DAU、付费人数、收入(USD)、付费率、ARPPU、人均付费次数 |
| 2 | `pay_composition` | 付费构成 | `payrecharge` | 普通充值（`pay_itemid='0'`）vs 直购（`strpos(pay_itemid, ':') > 0`）；直购按 actId=`split_part(pay_itemid, ':', 1)` 细分（14=新手直购、13=新月卡、9=天使通行证、7/8=商店、其余=其他直购）。各行：类型、金额、人数、次数、金额占比 |
| 3 | `pay_tiers` | 充值档位分布 | `payrecharge` | 按**单笔** `pay_money` 档位（<1 / 1~5 / 5~10 / 10~20 / 20~50 / 50~100 / ≥100 USD）：笔数、金额、人数 |
| 4 | `payer_segments` | 付费用户分层 | `payrecharge` | 按**当日累计**充值落入上述 9 层：各层人数、金额、金额占比、层内 ARPPU |
| 5 | `segment_activity` | 分层×活动参与 | `payrecharge` JOIN `gameeco_raw.v_presto_log_rolepromo` | 粒度=分层 × 活动主题（`json_extract_scalar(activity_topic,'$.cn')`）：该层该活动参与人数、参与次数（rolepromo 为领奖记录，无消耗/产出字段） |
| 6 | `activity_overview` | 活动总览 | `rolepromo` | 全量玩家：当日全部活动主题按参与人数排序（人数/次数），便于与运营日历对照 |
| 7 | `segment_item_flow` | 分层×道具产销 | `payrecharge` JOIN `gameeco_raw.v_presto_log_roleitem` | 粒度=分层 × 方向（产出/消耗） × `item_id`：参与人数、变动次数、数量合计（`SUM(ABS(CAST(status_after AS BIGINT)-CAST(status_before AS BIGINT)))`），表自带 `item_name` |

**道具名**：Sheet 7 的 `item_id` 行自带 `item_name`，无需翻译；其余 Sheet 不出现 item ID。name_enrich 的中文表头兼容与 game_resource fallback 作为通用能力保留（player_segment 等报表受益）。

### 2. 道具名补全（name_enrich 增强，`app/name_enrich.py` 改动）

现状问题：`_handle_report` 的目录型报表分支从未调用 `name_enrich.translate_dir`（player_segment 目前未翻译），且模板写 CSV 前已把列头映射成中文，`item_id` 规则匹配不到。

改动：

1. `bot._handle_report` 目录分支：发图前调用 `name_enrich.translate_dir(file_or_dir, game_config)`（player_segment 同时受益）。
2. `_COLUMN_RULES[312]` 的 `item_id` 规则 `cols` 追加中文表头候选（如 `"道具ID"`），兼容模板输出的中文列头。
3. 新增**资源名 fallback**：`item_id` 经 `game_item` 未命中（名称为空）的 ID，再按 `game_resource`（`id_name`，`game_id = 312`）补查资源名——活动消耗中会混入钻石/体力等资源 ID。实现为规则上的可选 `fallback` 节点，复用同一 `_fetch_names` 缓存机制；任何失败静默跳过，绝不阻塞主流程。

### 3. LLM 经营解读 `app/report_insight.py`（新增）

复用 `query_planner.summarize` 的模式：

```python
def interpret(question: str, result_dir: str, ws: dict, game_config) -> str
```

- 读取 result_dir 下各 `query_N.csv`（聚合表，行数小），按 Sheet 名拼接进 prompt；单 Sheet 超阈值（如 200 行 / 20KB）截断并标注。
- system prompt 声明：**只做经营解读，禁止调用任何工具/执行查询**；输出固定结构：
  1. 当日付费大盘（收入、付费人数、ARPPU、与口径说明）
  2. 付费构成亮点（普通 vs 直购、主要直购活动）
  3. 分层观察（哪层贡献最大、高价值层人数）
  4. 活动表现（参与 Top、精彩/付费活动标记对照、异常活动）
  5. 建议关注点
- 调用 `claude_cli.run_with_system_prompt(question, ws, system_prompt)`。
- **失败兜底**：任何异常/超时 → 返回空串，调用方只发数据 summary，绝不影响报表交付。
- ws 由 `bot._handle_report` 用 `workspace.prepare(chat_id, message_id, game_config=...)` 构建（复用 cwd/mcp_config/result_dir 结构；解读不依赖 MCP 工具）。

### 4. 报表注册与路由

- `reports.py` 新增：

```python
def pay_activity_report(question, game_config=None):
    summary, result_dir = templates.run_report("pay_activity", question, game_config=game_config)
    return summary, result_dir
```

  `run()` 新增 `pay_activity` 分支。LLM 解读在 `bot._handle_report` 层编排（拿得到 chat_id/message_id 构建 ws），解读文本拼在 summary 之后；解读为空则只发数据 summary。
- `config.json` `report_triggers` 新增：

```json
"pay_activity": ["付费构成", "活动付费分析", "付费活动分析", "付费分层"]
```

### 5. 数据流

```
用户提问（含触发词+日期）
  → reports.match → pay_activity
  → bot._handle_report
      → templates.run_report("pay_activity")     # 6 条 SQL 顺序执行，写 query_N.csv
      → name_enrich.translate_dir(result_dir)    # item_id → 道具名/资源名
      → report_insight.interpret(...)            # LLM 经营解读（失败→空串）
      → _send_charts → _send_text(summary+解读) → _send_result_file(Excel)
```

### 6. 错误处理

- 单 Sheet SQL 失败：`templates.run_report` 当前无逐步容错（`dataapi.run_sql_rows` 抛错即整体失败）。本期**不改动**该行为，与 player_segment 保持一致；Excel 缺失通过"报表生成失败，请稍后重试"兜底文案反馈。
- name_enrich / report_insight 全部 `Never raises`。
- LLM 解读超时沿用 `claude.timeout`（600s）；解读失败只丢文字不丢数据。

### 7. 测试

- `tests/test_pay_activity_template.py`：模板加载、占位符渲染（日期/server_filter/game_id）、分层 CASE 边界（9.99→`<$10`、10→`$10~20`、300→`≥$300`）、`reports.match` 触发词命中。
- `tests/test_report_insight.py`：prompt 组装含全部 Sheet、超长 CSV 截断、interpret 异常返回空串（mock claude_cli）。
- `tests/test_name_enrich.py` 增补：中文表头 `道具ID` 命中规则、`game_item` 未命中时 fallback `game_resource`、fallback 失败静默。
- `debug/test_pay_activity_live.py`：真实库冒烟脚本——先探 `item_spend`/`item_get` 格式与 `activity_topic` 取值，再整跑 6 个 Sheet 验证行数与道具名补全。

### 8. 文档更新

- `app/templates/README.md`：新增 pay_activity 模板说明（口径、Sheet 列表、触发词）。
- `CLAUDE.md`：报表清单与触发词补充。
- `schema_312.md`：补充 rolepromo 实测口径（item_spend/item_get 格式、activity_topic 取值示例）。

## 非目标（YAGNI）

- 不做道具级消耗/产出的跨天趋势、不做活动 ROI 归因到收入。
- 不支持 160/39/255 的 pay_activity 模板（模板结构预留 games 节点，后续可复制 312 适配）。
- 不改动 `templates.run_report` 的单 Sheet 容错行为。
- 不做 Sheet 内图表自动化（沿用 `_send_charts` 现有检测）。
