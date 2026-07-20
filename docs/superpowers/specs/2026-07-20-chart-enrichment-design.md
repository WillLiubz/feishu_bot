# 数仓分析后处理管线设计：中文名翻译 + 跨期对比图 + 图表增强

日期：2026-07-20
状态：已获用户批准

## 背景

feishu_bot 当前已具备：数仓取数（`query_data`）、GM/静态配置库取数（`query_config`）、基础图表输出（`app/charts.py`，PNG + xlsx 原生图表）。存在三个缺口：

1. **分步查询模式下中文名翻译不可靠**：`query_planner.py` 的提示词未引导 LLM 使用 `query_config`，39 的 `raw_scribe_log` 表无名称字段，结果常输出裸 ID，图表 X 轴标签也是 ID。
2. **缺少跨期对比图**：多时间段对比被拆成独立步骤，每期一个 CSV 各出一张图，无法合成多系列对比图。
3. **图表启发式较粗**：bar 超 20 行 / pie 超 8 类直接截断，无 Top-N+"其他"归并。

## 已确认的决策

- 中文名翻译：**代码层后处理**（非提示词引导 LLM），确定性优先。
- 对比图形式：**同图多系列对比**（折线每期一条线 / 柱状分组并排）。
- 三个缺口全部实现。

## 总体架构

在"子 Claude 查询完成"与"发图/发文件"之间插入后处理阶段，三条输出路径（简单查询、分步查询、固定报表）统一受益：

```
query_N.csv 生成
   │
   ├─ A. name_enrich（新模块）  ID 列 → 追加中文名列
   ├─ B. charts（扩展）         跨期对比合成图（结构兼容时）
   └─ dquery.combine_to_excel（现有，自动吃到翻译后的中文名）
```

## 模块 A：`app/name_enrich.py`（新）

入口：`translate_dir(result_dir, game_config) -> None`

- 遍历 `query_N.csv`，识别 ID 列 → 批量翻译 → 回写 CSV，中文名列插在 ID 列右侧（如 `item_id, item_name, 数量`）。
- 若 CSV 已存在同名中文名列（如 312/160 的 `roleitem` 自带 `item_name`），跳过该列。
- **列名→配置表映射**（按 game_id 内置规则，源自 CLAUDE.md 已确认映射）：

| game_id | CSV 列名 | 库 | 表 | 额外过滤 |
|---|---|---|---|---|
| 39 | `item_id` | static_database | `static_item` | — |
| 39 | `activity_id` | database（GM 运营库） | `activity` | — |
| 160 / 312 | `item_id` / `ident` | database | `game_item` | `game_id = <X>` |
| 160 / 312 | `id_name` | database | `game_resource` | `game_id = <X>` |

- **实现要点**：
  - 复用 `configdb.query(cfg, sql, database=...)`（自带只读护栏与超时）。
  - ID 去重后单条 `SELECT ... WHERE id IN (...)` 查询；名称列从结果行按候选键（`name` / `title` / `activity_name`）自动识别，不硬编码字段名。
  - 调用方进程级 dict 缓存（key = (game_id, table, id)），避免同次查询重复访问配置库。
  - `config_db` 未配置、连接失败、SQL 报错时**静默跳过**（print 日志），绝不阻塞主流程。
- 效果：画图与 xlsx 的首列/标签列自然变成中文名。

## 模块 B：`charts.py` 扩展 — 跨期对比合成图

新增：`render_comparison_png(csv_paths, labels, out_path) -> str | None`

- **兼容判定**：≥2 个 CSV、各 CSV 列名集合相同、`series_columns` 一致、首列同为日期（`_first_col_is_date`）或同为非日期。任一不满足返回 None。
- 首列为日期 → **多线折线**：X 轴为排序后的日期并集，每期一条线，图例 = 期间标签。
- 首列为维度 → **分组柱状**：复用现有多系列 bar 逻辑，每组一个维度。
- 标签来源：planned 各步骤的 `goal`（截断 12 字）；提取不到退回"查询N"。
- 单 CSV 数据点/类目超限走模块 C 的归并/抽稀。

`bot.py` 改动：

- `_send_charts(client, chat_id, result_dir, step_labels=None)` 增加可选参数。
- `_handle_simple` 与 `_planned_handler` 都在发图/发文件前调用 `name_enrich.translate_dir`；planned 路径额外把各步 `goal` 传入 `_send_charts`；结构兼容时**只发合成对比图**，不兼容退回现有 `render_pngs_for_dir` 每期单图（纯工程兜底）。
- 固定报表（KPI/LTV/月榜）本身已是中文标签，不走翻译；其单 CSV 图表路径维持现状。
- xlsx 侧不动：每期 sheet 的原生图表维持现状。

## 模块 C：图表细节增强

- **Top-N + "其他"归并**（替代生硬截断）：
  - pie：按值降序取 Top-7，其余合并为"其他"（总类目 ≤ 8，沿用 `MAX_PIE_CATEGORIES`）。
  - bar：按值降序取 Top-15 + "其他"（PNG 场景）。
  - 归并仅影响 PNG 渲染（`_slice_for_png`），xlsx 数据与原生图表保持全量。
- line 数据点上限 60 保留，超出时按时间均匀抽稀（保留首末点）。

## 数据流（分步查询为例）

1. `query_planner` 各步执行，生成 `query_1.csv … query_N.csv`。
2. `bot._planned_handler` 调 `name_enrich.translate_dir(result_dir, game_config)`。
3. `_send_charts(..., step_labels=[step.goal, ...])`：先尝试 `render_comparison_png`，失败退回 `render_pngs_for_dir`。
4. `_send_result_file` → `dquery.combine_to_excel`（数据已是翻译后版本）。

## 错误处理

- 所有后处理步骤 try/except 包裹、绝不向上抛（与现有 `_send_charts` "Never raises" 风格一致）。
- 配置库不可达 → 跳过翻译，输出裸 ID（现状行为）。
- 合成图判定不兼容 → 退回每期单图（现状行为）。

## 测试

- `tests/test_name_enrich.py`（新）：
  - mock `configdb.query`，验证 39 / 160 / 312 各映射规则的列识别与翻译回写；
  - 已有中文名列时跳过；
  - `config_db` 缺失 / 查询抛异常时 CSV 原样保留。
- `tests/test_charts.py`（扩展）：
  - 合成图兼容判定（列不一致 → None；日期首列 → line；维度首列 → bar）；
  - Top-N+"其他"归并的正确性（数量、数值合计）。
- 全量回归：`python -m pytest tests/ -q`。

## 已知限制

- 对比图期间标签依赖 planner step goal 质量（如"查5月充值"），最佳努力提取，提取不到显示"查询N"，不出错。
- 39 的 `activity` 表名称字段以运行时候选键自动识别为准，不写死字段名。
