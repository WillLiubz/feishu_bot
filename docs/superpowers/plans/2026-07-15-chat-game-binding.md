# 聊天群绑定固定游戏 ID Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员在 config.json 中把飞书聊天群绑定到固定游戏 ID，绑定的群只查该游戏，并修复游戏解析失败导致的信号量泄漏。

**Architecture:** 在 `config.py` 新增 `CHAT_GAMES` 配置与启动校验；`bot.py` 新增纯函数 `_resolve_game_for_chat` 封装"绑定群严格、未绑定群走现状"的路由；`_on_message` 把游戏解析移到获取锁之前（修泄漏）并新增 `chatid` 即时命令。

**Tech Stack:** Python 3.12+，pytest，无新增依赖。

**Spec:** `docs/superpowers/specs/2026-07-15-chat-game-binding-design.md`

## Global Constraints

- 工作分支：`fix-game39-raw-scribe-tables`（不要提交 master/main，不要 push）。
- 提交信息：中文，格式 `<type>: <简短描述>`，结尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`。
- 不新增依赖；所有文件 UTF-8。
- 每个任务提交前必须通过：`python -m py_compile app/*.py` 与 `python -m pytest tests/ -q`。
- `config.json` 不得进入暂存区（提交前 `git diff --cached --name-only | grep -i config` 应无输出；注意 tests/test_config.py 文件名也含 config，它**应该**被提交，grep 命中它时人工确认即可，真正禁止的是根目录 `config.json`）。
- 行为契约（spec 决策表，逐字遵守）：绑定群遇到**其他游戏显式数字前缀**→ 拒绝并提示"本群仅支持查询游戏 G（别名），如需查询游戏 X 请到对应群。"；绑定群文本含其他游戏**别名**→ 静默用绑定游戏；未绑定群保持"前缀 → 别名 → 默认"现状。

---

### Task 1: config.CHAT_GAMES 解析与启动校验

**Files:**
- Modify: `app/config.py`（Bot 节 ~line 136 `NAMES` 之后；`check()` ~line 164 缺字段检查之后）
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.CHAT_GAMES: dict[str, int]`（chat_id → game_id，value 用 `int()` 归一化，缺省 `{}`）。Task 2 的 `_resolve_game_for_chat` 消费它。

- [ ] **Step 1: Write the failing tests**

追加到 `tests/test_config.py` 末尾（文件已有 `_write_config` helper 与 reload 模式，直接复用）：

```python
def test_chat_games_default_empty(tmp_path, monkeypatch):
    root = _write_config(tmp_path)
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    assert config.CHAT_GAMES == {}


def test_chat_games_parsed_as_int(tmp_path, monkeypatch):
    root = _write_config(tmp_path, {"bot": {"chat_games": {"oc_a": "312"}}})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    assert config.CHAT_GAMES == {"oc_a": 312}


def test_check_rejects_unknown_chat_game(tmp_path, monkeypatch):
    root = _write_config(tmp_path, {"bot": {"chat_games": {"oc_a": 999}}})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    with pytest.raises(ValueError, match="chat_games"):
        config.check()


def test_check_accepts_valid_chat_game(tmp_path, monkeypatch):
    root = _write_config(tmp_path, {"bot": {"chat_games": {"oc_a": 312}}})
    monkeypatch.setenv("FEISHU_BOT_ROOT", root)
    import importlib
    import config
    importlib.reload(config)
    config.check()  # 不应抛错
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL — `AttributeError: module 'config' has no attribute 'CHAT_GAMES'`（前两个用例）。

- [ ] **Step 3: Implement**

`app/config.py` 在 Bot 节 `NAMES = _get("bot.names", {})` 之后新增一行：

```python
CHAT_GAMES = {str(k): int(v) for k, v in _get("bot.chat_games", {}).items()}
```

`app/config.py` 的 `check()` 中，在缺字段检查的 `raise` 之后、`import re` 之前插入：

```python
    valid_game_ids = GAME_IDS if MULTI_GAME_MODE else ([GAME_ID] if GAME_ID is not None else [])
    for chat_id, gid in CHAT_GAMES.items():
        if gid not in valid_game_ids:
            raise ValueError(
                f"config.json bot.chat_games 绑定了未配置的游戏: chat_id={chat_id} game_id={gid}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS（含既有用例共 11 个）。

- [ ] **Step 5: Commit**

```bash
python -m py_compile app/*.py && python -m pytest tests/ -q
git add app/config.py tests/test_config.py
git commit -m "feat: config 支持 bot.chat_games 群绑定配置与启动校验

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: bot._resolve_game_for_chat 绑定群路由

**Files:**
- Modify: `app/bot.py`（在 `_resolve_game` 之后、`_send_query_summary` 之前插入新函数，~line 150）
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: `config.CHAT_GAMES`（Task 1）、`bot._resolve_game`、`config.game_config`、`bot._game_id_pattern`
- Produces: `bot._resolve_game_for_chat(chat_id: str, text: str) -> GameConfig`，其他游戏显式前缀时抛 `ValueError`。Task 3 的 `_on_message` 消费它。

- [ ] **Step 1: Write the failing tests**

`tests/test_bot.py` 顶部 import 区补充 `import pytest`，然后追加：

```python
def _gc(gid, aliases=()):
    gc = MagicMock()
    gc.game_id = gid
    gc.aliases = list(aliases)
    return gc


def test_resolve_game_for_chat_unbound_uses_legacy():
    with patch.object(bot.config, "CHAT_GAMES", {}), \
         patch.object(bot, "_resolve_game", return_value="LEGACY") as m:
        assert bot._resolve_game_for_chat("oc_x", "昨日付费") == "LEGACY"
    m.assert_called_once_with("昨日付费", raise_on_missing=True)


def test_resolve_game_for_chat_bound_no_prefix():
    with patch.object(bot.config, "CHAT_GAMES", {"oc_a": 312}), \
         patch.object(bot.config, "game_config", return_value=_gc(312, ["女3"])) as mg:
        assert bot._resolve_game_for_chat("oc_a", "昨日付费").game_id == 312
    mg.assert_called_once_with(312)


def test_resolve_game_for_chat_bound_same_prefix():
    with patch.object(bot.config, "CHAT_GAMES", {"oc_a": 39}), \
         patch.object(bot.config, "game_config", return_value=_gc(39, ["女1"])):
        assert bot._resolve_game_for_chat("oc_a", "39 昨日充值").game_id == 39


def test_resolve_game_for_chat_bound_other_prefix_rejected():
    with patch.object(bot.config, "CHAT_GAMES", {"oc_a": 312}), \
         patch.object(bot.config, "game_config", return_value=_gc(312, ["女3"])):
        with pytest.raises(ValueError, match="本群仅支持查询游戏 312"):
            bot._resolve_game_for_chat("oc_a", "39 昨日充值")


def test_resolve_game_for_chat_bound_ignores_alias():
    with patch.object(bot.config, "CHAT_GAMES", {"oc_a": 312}), \
         patch.object(bot.config, "game_config", return_value=_gc(312, ["女3"])):
        assert bot._resolve_game_for_chat("oc_a", "女1玩法参与率").game_id == 312
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bot.py -q`
Expected: FAIL — `AttributeError: module 'bot' has no attribute '_resolve_game_for_chat'`（patch.object 找不到属性）。

- [ ] **Step 3: Implement**

`app/bot.py` 在 `_resolve_game` 函数结束之后插入：

```python
def _resolve_game_for_chat(chat_id, text):
    """Resolve game for a chat: bound chats are pinned to their game.

    Unbound chats keep the legacy resolution (prefix -> alias -> default).
    Bound chats skip prefix/alias matching entirely; an explicit numeric
    prefix for a DIFFERENT game is rejected with ValueError.
    """
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bot.py -q`
Expected: PASS（6 个用例）。

- [ ] **Step 5: Commit**

```bash
python -m py_compile app/*.py && python -m pytest tests/ -q
git add app/bot.py tests/test_bot.py
git commit -m "feat: 新增 _resolve_game_for_chat 绑定群游戏路由

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: _on_message 接线 + 信号量泄漏修复 + chatid 命令 + CLAUDE.md

**Files:**
- Modify: `app/bot.py`（`_on_message` 中并发控制与游戏解析块，~line 456-474；whoami 块之后，~line 444）
- Modify: `CLAUDE.md`（"查询路由"一节末尾）
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: `bot._resolve_game_for_chat`（Task 2）
- Produces: `_on_message` 的新行为契约：游戏解析失败不占用 `_active_chats`/`_query_sem`；`chatid` 命令回复完整 chat_id。

- [ ] **Step 1: Write the failing tests**

`tests/test_bot.py` 顶部 import 区补充 `import json`，然后追加：

```python
def _make_event(chat_id="oc_chat1", text="hello"):
    from types import SimpleNamespace
    msg = SimpleNamespace(
        chat_id=chat_id,
        message_id="om_m1",
        message_type="text",
        content=json.dumps({"text": text}, ensure_ascii=False),
    )
    sender = SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_u1"))
    return SimpleNamespace(event=SimpleNamespace(message=msg, sender=sender))


def test_on_message_game_resolve_failure_releases_locks():
    chat_id = "oc_leak_test"
    event = _make_event(chat_id=chat_id, text="999 昨日充值")
    with patch.object(bot, "_lark_client", return_value=MagicMock()), \
         patch.object(bot.store, "log_in"), \
         patch.object(bot, "_send_text") as mock_send, \
         patch.object(bot.reports, "match", return_value=None), \
         patch.object(bot, "_resolve_game_for_chat", side_effect=ValueError("未配置游戏 999")):
        bot._active_chats.discard(chat_id)
        bot._on_message(event)
    # 错误提示已发送
    assert any("未配置游戏 999" in str(c.args[2]) for c in mock_send.call_args_list)
    # 解析失败不得占用资源：群不在活跃集合，信号量可获取
    assert chat_id not in bot._active_chats
    assert bot._query_sem.acquire(blocking=False)
    bot._query_sem.release()


def test_chatid_command():
    chat_id = "oc_chatid_test"
    event = _make_event(chat_id=chat_id, text="chatid")
    with patch.object(bot, "_lark_client", return_value=MagicMock()), \
         patch.object(bot.store, "log_in"), \
         patch.object(bot, "_send_text") as mock_send:
        bot._on_message(event)
    assert mock_send.call_count == 1
    assert mock_send.call_args.args[2] == f"chat_id: {chat_id}"
```

注意：`test_chatid_command` 对现状代码也会失败（旧代码没有 chatid 分支，`_send_text` 不会被调用或回复别的内容），符合 TDD"先失败"。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bot.py -q`
Expected: 两个新用例 FAIL（泄漏用例断言 `chat_id not in bot._active_chats` 失败；chatid 用例 `call_count == 1` 失败）。

- [ ] **Step 3: Implement**

`app/bot.py` 的 `_on_message` 中，在 whoami 块之后新增 chatid 分支：

```python
        if text.strip().lower() == "chatid":
            _send_text(client, chat_id, f"chat_id: {chat_id}")
            return
```

然后把"并发控制 + 游戏解析"块（现状：先 `_active_chats`、再 `_query_sem`、最后 `_resolve_game`）改为**先解析游戏再占锁**。删除原 try/except 解析块，在白名单检查之后、并发控制之前插入：

```python
        # Resolve game BEFORE acquiring locks: a failed resolution must not
        # leak the semaphore / active-chat slot (that wedged the chat).
        try:
            game_config = _resolve_game_for_chat(chat_id, text)
        except ValueError as e:
            _send_text(client, chat_id, str(e))
            return
```

并发控制两块（`_active_chats` 与 `_query_sem` 获取）保持原样，仅位于解析之后。

`CLAUDE.md` 在"查询路由"一节末尾（"默认所有查询仍走 RAW 库……"段之后）追加：

```markdown
## 聊天群游戏绑定

- `config.json` 的 `bot.chat_games` 可把聊天群绑定到固定游戏：`"bot": {"chat_games": {"oc_群ID": 312}}`，重启生效；绑定的 game_id 必须在 `games` 中已配置，否则启动时报错。
- 已绑定的群只查该游戏：跳过数字前缀与别名匹配；显式输入其他游戏前缀会被拒绝并提示。未绑定的群保持原有解析（前缀 → 别名 → 默认）。
- 群里发 `chatid` 可获取该群的 chat_id，用于填写 `chat_games`。
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bot.py -q`
Expected: PASS（8 个用例）。

- [ ] **Step 5: Commit**

```bash
python -m py_compile app/*.py && python -m pytest tests/ -q
git diff --cached --name-only | grep -i config   # 只允许出现 tests/test_config.py（本任务应无输出）
git add app/bot.py tests/test_bot.py CLAUDE.md
git commit -m "feat: 群绑定接入消息路由并修复游戏解析失败的信号量泄漏

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review 记录

- Spec 覆盖：配置结构→Task 1；路由决策表→Task 2；信号量泄漏修复/chatid/文档→Task 3；测试计划 8 条全部映射到具体 step。
- 类型一致：`config.CHAT_GAMES` 为 `dict[str, int]`；`_resolve_game_for_chat` 返回 `GameConfig`、抛 `ValueError`，与 Task 3 的 `_on_message` 捕获一致。
- 测试隔离：bot 用例全部 patch `bot.config.CHAT_GAMES`/`bot.config.game_config`，不依赖 pytest 进程中 config 模块的全局状态（test_config.py 会 reload config）。
