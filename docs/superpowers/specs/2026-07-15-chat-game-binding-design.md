# 聊天群绑定固定游戏 ID — 设计文档

日期：2026-07-15
状态：已批准，待实现

## 背景

一个飞书机器人实例（数仓-312-女3页游）同时服务多个聊天群。当前游戏路由
（`bot._resolve_game`）按以下顺序解析游戏 ID：

1. 消息开头数字前缀（如 `312 xxx`）
2. 别名子串匹配（按配置顺序 39 → 312 → 160 → 255，如文本含"女1"即命中 39）
3. 兜底默认 = `games` 列表第一个 = 39

两种典型出错方式：

- 用户在 312 群直接问"分析昨日付费"（无前缀无别名）→ 落到默认 39，查错库。
- 312 群里文本无意包含别名子串（如"女1玩法…"）→ 被别名匹配抢走。

另外发现一个现存 bug：`_on_message` 中 `_resolve_game` 抛 `ValueError` 时直接
`return`，未释放 `_query_sem` 与 `_active_chats`，导致该群之后永远回复
"上一条查询还未完成"（信号量泄漏）。

## 目标

1. 管理员可在 `config.json` 中把某个聊天群绑定到固定游戏 ID。
2. 已绑定的群只查该游戏：跳过前缀/别名解析；显式输入其他游戏前缀时拒绝并提示。
3. 未绑定的群行为完全不变。
4. 修复游戏解析失败时的信号量泄漏。
5. 提供 `chatid` 即时命令，方便管理员获取群 ID。

## 关键决策（已与用户确认）

| 决策点 | 选择 |
|---|---|
| 绑定关系维护方式 | 配置文件绑定（`bot.chat_games`），重启生效；不做运行时命令绑定 |
| 绑定群遇到其他游戏显式前缀 | 拒绝并提示，不处理查询 |
| 绑定群文本含其他游戏别名 | 静默用绑定游戏（绑定群内禁用别名匹配） |
| 未绑定群 | 保持现状（前缀 → 别名 → 默认） |

## 设计

### 1. 配置结构

`config.json` 的 `bot` 节新增 `chat_games`（chat_id → game_id）：

```json
"bot": {
  "chat_games": {
    "oc_41497c8fa167192a69572d00c1a632c4": 39,
    "oc_另一个群chat_id": 312
  }
}
```

- `config.py` 读取为 `CHAT_GAMES: dict[str, int]`（缺省 `{}`）。JSON 对象的 key
  天然是字符串，value 用 `int()` 归一化。
- `config.check()` 启动校验：`CHAT_GAMES` 每个 value 必须是已配置的 game_id
  （多游戏模式：`config.GAME_IDS`；单游戏遗留模式：等于 `config.GAME_ID`），
  非法值抛 `ValueError` 拒绝启动。

### 2. 路由逻辑

`bot.py` 新增 `_resolve_game_for_chat(chat_id, text)`：

```python
def _resolve_game_for_chat(chat_id, text):
    """Bound chats are pinned to their game; unbound chats use legacy resolution."""
    bound_gid = config.CHAT_GAMES.get(chat_id)
    if bound_gid is None:
        return _resolve_game(text, raise_on_missing=True)
    gc = config.game_config(bound_gid)
    m = _game_id_pattern.match(text or "")
    if m and int(m.group(1)) != bound_gid:
        aliases = "/".join(gc.aliases) if gc.aliases else str(bound_gid)
        raise ValueError(
            f"本群仅支持查询游戏 {bound_gid}（{aliases}），"
            f"如需查询游戏 {int(m.group(1))} 请到对应群。"
        )
    return gc
```

| 场景 | 行为 |
|---|---|
| 群未绑定 | `_resolve_game(text, raise_on_missing=True)`，现状不变 |
| 群已绑定 G，文本无显式前缀 | 返回 G 的 GameConfig，跳过别名匹配 |
| 群已绑定 G，文本前缀就是 G | 返回 G |
| 群已绑定 G，文本前缀是其他游戏 | 抛 `ValueError`，bot 回复提示文案 |
| 群已绑定 G，文本含其他游戏别名 | 静默返回 G |

`_on_message` 中把 `game_config = _resolve_game(text, raise_on_missing=True)`
替换为 `game_config = _resolve_game_for_chat(chat_id, text)`。

### 3. 信号量泄漏修复

`_on_message` 当前顺序：加 `_active_chats` → 获取 `_query_sem` → 解析游戏
（抛错时 return，锁与信号量均未释放）。

修复：把游戏解析移到获取信号量**之前**（解析失败时还没有占用任何资源，
直接回复并 return）。`_active_chats` 与 `_query_sem` 的获取顺序不变，
仍在解析成功后执行。

### 4. `chatid` 即时命令

`_on_message` 中与 `whoami` 并列新增：

```python
if text.strip().lower() == "chatid":
    _send_text(client, chat_id, f"chat_id: {chat_id}")
    return
```

### 5. 生效方式

`config.json` 静态加载，改绑定后重启 bot 生效。`config.check()` 在启动时
拦截非法绑定（未配置的 game_id），避免带病运行。

### 6. 文档

CLAUDE.md"查询路由"一节末尾补充群绑定说明：配置字段、严格拒绝行为、
`chatid` 命令、重启生效。

## 测试计划

扩展 `tests/test_bot.py` 与 `tests/test_config.py`：

- `test_resolve_game_for_chat_unbound_keeps_legacy`：未绑定群，前缀/别名/默认
  三种现状回归（直接复用 `_resolve_game` 既有用例的断言）。
- `test_resolve_game_for_chat_bound_no_prefix`：绑定 312，文本"昨日付费"→ 312。
- `test_resolve_game_for_chat_bound_same_prefix`：绑定 39，文本"39 昨日充值"→ 39。
- `test_resolve_game_for_chat_bound_other_prefix`：绑定 312，文本"39 昨日充值"
  → `ValueError`，文案含"本群仅支持查询游戏 312"。
- `test_resolve_game_for_chat_bound_ignores_alias`：绑定 312，文本含"女1"→ 312。
- `test_on_message_game_resolve_failure_releases_locks`：模拟 `_resolve_game_for_chat`
  抛错，断言 `_query_sem` 与 `_active_chats` 状态复原，群不会被卡死。
- `test_chatid_command`：回复内容含完整 chat_id。
- `test_config_check_rejects_unknown_chat_game`：`chat_games` 含未配置 game_id
  时 `check()` 抛 `ValueError`。

## 验收标准

1. `python -m pytest tests/ -q` 全绿。
2. `python -m py_compile app/*.py` 通过。
3. `git diff --cached --name-only | grep -i config` 无输出（config.json 不入库）。
4. 真实验证：在一个群配置绑定后，分别发无前缀问题、同游戏前缀问题、
   其他游戏前缀问题，确认行为符合第 2 节表格。

## 非目标（YAGNI）

- 不做运行时命令绑定/解绑（不改 bot.db，不加绑定权限体系）。
- 不做配置热加载（重启生效即可）。
- 不改动未绑定群的解析优先级与别名列表。
- 不处理"一个群绑多个游戏"——一个群只绑一个游戏。
