# 查询结果图表化展示 — 设计文档

日期：2026-07-14
状态：已批准，待实现

## 背景

飞书数仓机器人目前的查询结果由两部分组成：

1. **文字结论**：Claude CLI 子进程生成的中文总结，以纯文本消息发送到飞书。
2. **结果文件**：每次查询的 `query_N.csv` 由 `dquery.combine_to_excel` 合并为 `result.xlsx`（每个 sheet 含数据表 + 底部 SQL），以文件消息发送。

问题：数据部分只有表格，没有可视化；文字结论只存在于飞书消息里，没有沉淀到结果文件中。

## 目标

1. 查询结果的数据部分自动生成饼图 / 柱状图 / 折线图等可视化图表。
2. 图表展示在两个位置：**飞书聊天**（PNG 图片消息）和 **result.xlsx**（原生可编辑图表）。
3. 每个图表/表格下方附文字版结论；结论文字同时写入 result.xlsx。
4. 对所有查询生效：简单 LLM 查询、分步复杂查询、固定报表（KPI / LTV / 月榜 / 玩家分层）。

## 关键决策（已与用户确认）

| 决策点 | 选择 |
|---|---|
| 图表展示位置 | 飞书聊天 + result.xlsx 都要 |
| 渲染技术 | 飞书侧 matplotlib PNG；xlsx 侧 openpyxl 原生图表（方案 A，双引擎） |
| 图表类型选择 | 程序按数据形态自动判断，不增加 LLM 调用 |
| 适用范围 | 所有查询（简单 / 分步 / 固定报表） |
| xlsx 布局 | 图表+结论随每个数据 sheet；多步查询额外在最前面加"总结"sheet |
| 新依赖 | matplotlib（用户已批准） |

## 架构

### 新增模块 `app/charts.py`

所有图表逻辑集中在该模块：

| 函数 | 职责 |
|---|---|
| `detect_chart_type(rows)` | 输入查询结果行（list[dict]），返回 `'line'` / `'pie'` / `'bar'` / `None` |
| `render_png(rows, chart_type, title, out_path)` | matplotlib 渲染 PNG 供飞书发送；返回路径或 None |
| `add_native_chart(ws, rows, chart_type, anchor)` | openpyxl 在 sheet 内嵌入原生图表 |
| `render_pngs_for_dir(result_dir)` | 遍历 `query_N.csv`，为每个可画图的查询生成 `query_N.png`，返回路径列表 |

matplotlib 导入失败时模块级置 `CHARTS_AVAILABLE=False`，所有渲染函数直接返回 None，保证主链路不受影响。

### 改动点

#### 1. `dquery.combine_to_excel(result_dir, conclusions=None, final_summary=None)`

新增两个可选参数（都有默认值，现有调用方行为不变）：

- `conclusions`：list[str]，第 i 个元素是 `query_i` 对应的文字结论。
- `final_summary`：str，多步查询的最终总结；非空时在最前面插入"总结"sheet。

每个数据 sheet 布局：

```
A1:      表头（蓝底白字，现状保留）
A2~An:   数据行
J2:      原生图表锚点（数据区右侧，不压数据）
An+2:    【结论】（加粗灰字）
An+3:    结论文字（自动换行，行高按文字长度估算，上限 200）
An+5:    【SQL】（现状保留，位置随结论下移）
An+6:    SQL 文本
```

结论来源：

- 简单查询：`conclusions=[answer]`（LLM 完整回答）。
- 分步查询：每个 sheet 的结论是 `execute_step` 返回的中文总结；`final_summary` 进"总结"sheet（标题"最终结论" + 全文自动换行）。
- 固定报表：`conclusions=[summary]`（报表函数返回的摘要）。

#### 2. `bot.py`

- 新增 `_send_image(client, chat_id, image_path)`：`im.v1.image.create` 上传 PNG → 发 `image` 消息。
- `_send_results` 签名扩展为 `_send_results(client, chat_id, ws, conclusions=None, final_summary=None)`，流程：
  1. 调用 `charts.render_pngs_for_dir(result_dir)` 生成 PNG；
  2. 逐个发送图表图片消息；
  3. 调 `combine_to_excel` 时透传结论参数；
  4. 发送 result.xlsx（现状逻辑保留）。

调用方传入结论：

- `_handle_simple`：`conclusions=[answer]`。
- `_planned_handler`：`conclusions=summaries`，`final_summary=final_summary`（需要把 `_run_planned*_body` 的返回值从拼接字符串改为结构化数据 `(summaries, final_summary)`，answer 文本在 `_planned_handler` 内组装）。
- `_handle_report`：KPI/LTV/月榜返回的是临时 CSV 路径。在 `dquery` 新增 `rows_to_xlsx(rows, summary, title)`：读回 CSV 行数据，构造单 sheet xlsx（数据+图表+结论，与 `combine_to_excel` 共用布局代码），`_handle_report` 改为发送该 xlsx 并用 `charts.render_png` 从行数据生成飞书图片；读回或构造失败时降级为发送原 CSV。player_segment 返回 result_dir，自动获得图表能力。

#### 3. 飞书消息时序（分步查询示例）

```
1. "🔎 该问题较复杂，正在分步查询…"（现状）
2. query_1.png、query_2.png … 逐个图表图片消息（新）
3. 文字总结消息（现状）
4. result.xlsx 文件消息（现状，内容升级）
5. 📊 执行详情（现状）
```

图表先于文字结论出现，与 xlsx 内"图表在上、结论在下"的结构一致。简单查询和固定报表时序相同（通常一张图）。

#### 4. 依赖管理

仓库当前没有 requirements.txt（未纳入版本控制）。新建 `requirements.txt`，写入现有运行依赖（lark_oapi、openpyxl、fastmcp 等，按实际 import 梳理）+ matplotlib。

## 图表类型自动判断规则

`detect_chart_type(rows)` 按优先级判定：

| 条件（按优先级） | 图表类型 |
|---|---|
| 无行、或没有任何数值列 | `None`（不画图） |
| 首列是日期形态（`yyyymmdd` / `yyyy-mm-dd` / 列名含"日期/月/ds"）且有数值列 | 折线图（x=日期，y=数值列，最多 3 条线） |
| 行数 ≤ 8 且恰好 1 个数值列 | 饼图（类别=首列） |
| 其余情况（类别+数值） | 柱状图（类别=首列，多数值列则分组柱状） |

数值列判定：该列超过一半的非空值能 `float()` 转换（兼容 Presto 返回的 VARCHAR 数值，如游戏 39 的 `custom_pra3`）。

渲染上限：

- 饼图：≤ 8 个类别（判断条件已保证）。
- 柱状图 PNG：取前 20 行；xlsx 原生图表引用全部行。
- 折线图 PNG：取前 60 个点；xlsx 引用全部行。

中文显示：`font.sans-serif = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']`，`axes.unicode_minus = False`；字体缺失时 matplotlib 自动回退，记 warning 不崩。

图表标题：用 sheet 名（如"查询1_payrecharge"），PNG 与 xlsx 图表标题一致。

## 错误处理

核心原则：**图表是增强，绝不能影响查询主链路**。所有图表相关调用包在 try/except 里，失败只记日志、跳过图表，文字结论和 xlsx 文件照发。

| 场景 | 处理 |
|---|---|
| matplotlib 未安装/中文字体缺失 | `CHARTS_AVAILABLE=False`，渲染函数返回 None；字体缺失自动回退默认字体 |
| 某次查询无数值列 / 空结果 | `detect_chart_type` 返回 None → 不发图、xlsx 不嵌图表，只写结论文字 |
| PNG 渲染失败 / 飞书图片上传失败 | 跳过该图，继续发后续图和文字 |
| xlsx 原生图表嵌入失败 | 跳过图表，保留数据+结论+SQL（现状行为） |
| 行数超大 | PNG 按上限截断；xlsx 原生图表引用全量 |
| 结论文字为空 | 不写【结论】块 |
| `(no data)` 占位 CSV | 跳过图表和结论，只写占位（现状） |
| 报表 CSV 读回失败 | 降级为现状：直接发原 CSV 文件 |

## 测试计划

### 新增 `tests/test_charts.py`

- `detect_chart_type`：日期首列→line、少类别单数值→pie、多类别→bar、空数据/无数值列→None、VARCHAR 数值列识别（游戏 39 场景）。
- `render_png`：三种类型各生成 PNG 到 tmp_path，断言文件存在且非空；matplotlib 不可用时返回 None 不抛异常。
- `add_native_chart`：写入 worksheet 后断言 `ws._charts` 非空。
- 渲染上限：100 行柱状数据 → PNG 只画前 20。

### 修改 `tests/test_dquery.py`

- `combine_to_excel` 传 `conclusions` → 对应 sheet 数据下方出现【结论】文字。
- 传 `final_summary` → 首个 sheet 是"总结"。
- 不传新参数 → 与现状输出一致（回归保护）。
- 结论存在时【SQL】块位置正确下移。
- `rows_to_xlsx`：单 sheet 含数据+图表+【结论】，空行数据时不崩。

### 修改 `tests/test_bot.py`

- `_send_image`：mock lark client，断言走 `im.v1.image.create` + `image` 消息。
- `_send_results`：mock charts 模块，断言先图后文件的发送顺序、图片失败时降级不崩。

### 手动验证

- `debug/test_charts_render.py`：用构造数据生成 PNG + xlsx，人工打开检查中文显示和图表效果。
- 真实查询一次（如"39 昨天充值情况"），确认飞书收到图+文字+xlsx，xlsx 内图表可编辑、结论在表格下方。

## 验收标准

1. `python -m pytest tests/ -q` 全绿。
2. `python -m py_compile app/*.py` 通过。
3. `git diff --cached --name-only | grep -i config` 无输出（敏感配置不入库）。
4. 真实查询端到端验证通过（飞书图+文字+xlsx 三件套，xlsx 内图表原生可编辑、结论在表格下方）。

## 非目标（YAGNI）

- 不做交互式图表（如 ECharts / 飞书多维表格）。
- 不让 LLM 参与图表类型选择。
- 不支持用户指定图表类型（后续如有需求再加触发词）。
- 不改动 Claude CLI 调用链路和 SQL 生成逻辑。
