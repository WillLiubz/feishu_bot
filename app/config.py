import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

# Support FEISHU_BOT_ROOT env var for testing; default to one level above app/
_ROOT = Path(os.environ.get("FEISHU_BOT_ROOT", Path(__file__).parent.parent))
_CONFIG_PATH = _ROOT / "config.json"


@dataclass(frozen=True)
class GameConfig:
    """Per-game configuration."""
    game_id: int
    ds_start: str
    schema: str
    aliases: List[str]
    reports: dict
    lock_opgame_ids: List[int]
    config_db: dict = field(default_factory=dict)


def _load():
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


_cfg = _load()


def _get(path, default=None):
    keys = path.split(".")
    val = _cfg
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k, default)
    return val


# Feishu
FEISHU_APP_ID = _get("feishu.app_id")
FEISHU_APP_SECRET = _get("feishu.app_secret")

# Games: support both legacy single-game (`game`) and multi-game (`games`) config.
_GAMES: Dict[int, GameConfig] = {}
if _get("games"):
    for g in _get("games"):
        gc = GameConfig(
            game_id=g["game_id"],
            ds_start=g.get("ds_start", "20200101"),
            schema=g.get("schema", "schema_312.md"),
            aliases=g.get("aliases", []),
            reports=g.get("reports", {}),
            lock_opgame_ids=g.get("lock_opgame_ids", []),
            config_db=g.get("config_db", {}) or {},
        )
        _GAMES[gc.game_id] = gc
    GAMES = _GAMES
    GAME_IDS = list(_GAMES.keys())
    DEFAULT_GAME = GAME_IDS[0] if GAME_IDS else None
    MULTI_GAME_MODE = True
    GAME_ID = DEFAULT_GAME
elif _get("game.game_id") is not None:
    # Legacy single-game mode
    GAMES = {}
    GAME_IDS = []
    DEFAULT_GAME = None
    MULTI_GAME_MODE = False
    GAME_ID = _get("game.game_id")
else:
    GAMES = {}
    GAME_IDS = []
    DEFAULT_GAME = None
    MULTI_GAME_MODE = False
    GAME_ID = None

DS_START = _get("game.ds_start", "20200101")


def game_config(game_id=None) -> GameConfig:
    """Return GameConfig for game_id, defaulting to GAME_ID."""
    if game_id is None:
        game_id = GAME_ID
    if game_id is None:
        raise ValueError("未配置 game_id")
    if MULTI_GAME_MODE:
        if game_id not in _GAMES:
            raise ValueError(f"未找到游戏配置: {game_id}")
        return _GAMES[game_id]
    # Legacy single-game mode: synthesize a GameConfig from top-level settings.
    return GameConfig(
        game_id=game_id,
        ds_start=DS_START,
        schema="schema_312.md",
        aliases=[],
        reports={
            "login_table": REPORT_LOGIN_TABLE,
            "pay_table": REPORT_PAY_TABLE,
            "account_login_table": REPORT_ACCOUNT_LOGIN_TABLE,
        },
        lock_opgame_ids=LOCK_OPGAME_IDS,
    )


# Source code directories for optional schema augmentation.
GAME_SOURCE_DIRS = _get("game_source_dirs", {})

# Channels
LOCK_OPGAME_IDS = _get("channels.lock_opgame_ids", [])
CHANNEL_ALIASES = _get("channels.aliases", {})

# Data API
DATA_API_CLIENT_ID = str(_get("data_api.client_id", ""))
DATA_API_KEY = _get("data_api.key", "")
DATA_API_API_NAME = _get("data_api.api_name", "mfa_data")
DATA_API_SEARCH_URL = _get("data_api.search_url", "http://data-api.dc.uuzu.com/search/")
DATA_API_DOWNLOAD_URL = _get("data_api.download_url", "http://data-api.download.dc.uuzu.com/download/")
DATA_API_MAX_ROWS = int(_get("data_api.max_rows", 10000))
DATA_API_MOCK = bool(_get("data_api.mock", False))
DATA_API_QUERY_TIMEOUT = int(_get("data_api.query_timeout", 120))
DATA_API_DOWNLOAD_TIMEOUT = int(_get("data_api.download_timeout", 30))
DATA_API_POLL_MAX_ATTEMPTS = int(_get("data_api.poll_max_attempts", 24))
DATA_API_MAX_RETRY = int(_get("data_api.max_retry", 3))

# Claude
CLAUDE_MODEL = _get("claude.model", "claude-sonnet-4-6")
CLAUDE_CLI_PATH = _get("claude.cli_path", "claude")
CLAUDE_CLI_MAX_TURNS = int(_get("claude.max_turns", 25))
CLAUDE_CLI_TIMEOUT = int(_get("claude.timeout", 600))

# Bot
MAX_CONCURRENT_QUERIES = int(_get("bot.max_concurrent", 3))
DEFAULT_SQL_LIMIT = int(_get("bot.default_sql_limit", 200))
WHITELIST = bool(_get("bot.whitelist", False))
USER_OPGAMES = _get("bot.user_opgames", {})
NAMES = _get("bot.names", {})
CHAT_GAMES = {str(k): int(v) for k, v in _get("bot.chat_games", {}).items()}

# Logview
LOGVIEW_HOST = _get("logview.host", "127.0.0.1")
LOGVIEW_PORT = int(_get("logview.port", 8900))
LOGVIEW_KEY = _get("logview.key", "")

# Help and reports
HELP_TEXT = _get("help_text", "直接用中文提问即可。")
REPORT_TRIGGERS = _get("report_triggers", {})
HELP_TRIGGERS = ["help", "帮助", "?", "？"]

# Report table names (configurable per project; legacy single-game top-level)
REPORT_LOGIN_TABLE = _get("reports.login_table", "gamelog_raw.log_rolelogin")
REPORT_PAY_TABLE = _get("reports.pay_table", "gamelog_raw.log_payrecharge")
REPORT_ACCOUNT_LOGIN_TABLE = _get("reports.account_login_table", "gamelog_raw.log_accountlogin")


def check():
    """Validate required fields at startup. Checks: feishu credentials, game_id, data_api credentials, report table names."""
    missing = []
    for field in ["feishu.app_id", "feishu.app_secret", "data_api.client_id", "data_api.key"]:
        v = _get(field)
        if not v and v != 0:
            missing.append(field)
    if GAME_ID is None:
        missing.append("game.game_id 或 games")
    if missing:
        raise ValueError(f"config.json 缺少必填项: {', '.join(missing)}")

    valid_game_ids = GAME_IDS if MULTI_GAME_MODE else ([GAME_ID] if GAME_ID is not None else [])
    for chat_id, gid in CHAT_GAMES.items():
        if gid not in valid_game_ids:
            raise ValueError(
                f"config.json bot.chat_games 绑定了未配置的游戏: chat_id={chat_id} game_id={gid}"
            )

    # config_db validation (multi-game mode)
    if MULTI_GAME_MODE:
        for gid, gc in _GAMES.items():
            cdb = gc.config_db or {}
            if not cdb:
                continue
            for field_name in ("host", "user", "database"):
                if not cdb.get(field_name):
                    raise ValueError(f"config.json game {gid} config_db 缺少必填项: {field_name}")
            port = cdb.get("port", 3306)
            if not isinstance(port, int):
                raise ValueError(f"config.json game {gid} config_db.port 必须是整数: {port!r}")
            schema_name = cdb.get("schema")
            if schema_name and not (_ROOT / schema_name).exists():
                print(f"[config] 警告: game {gid} config_db.schema 文件不存在: {schema_name}")

    import re
    _TABLE_RE = re.compile(r'^[a-zA-Z0-9_.]+$')
    if MULTI_GAME_MODE:
        for gid, gc in _GAMES.items():
            for attr in ("login_table", "pay_table", "account_login_table"):
                val = gc.reports.get(attr, "")
                if val and not _TABLE_RE.match(val):
                    raise ValueError(f"config.json 报表表名非法（只允许字母数字下划线点）: game={gid} {attr}={val!r}")
    else:
        for attr in ("REPORT_LOGIN_TABLE", "REPORT_PAY_TABLE", "REPORT_ACCOUNT_LOGIN_TABLE"):
            val = globals()[attr]
            if val and not _TABLE_RE.match(val):
                raise ValueError(f"config.json 报表表名非法（只允许字母数字下划线点）: {attr}={val!r}")
