import json
import os
from pathlib import Path

# Support FEISHU_BOT_ROOT env var for testing; default to one level above app/
_ROOT = Path(os.environ.get("FEISHU_BOT_ROOT", Path(__file__).parent.parent))
_CONFIG_PATH = _ROOT / "config.json"


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


def check():
    """Validate required fields at startup. Checks: feishu credentials, game_id, data_api credentials."""
    missing = []
    for field in ["feishu.app_id", "feishu.app_secret", "game.game_id",
                  "data_api.client_id", "data_api.key"]:
        v = _get(field)
        if not v and v != 0:
            missing.append(field)
    if missing:
        raise ValueError(f"config.json 缺少必填项: {', '.join(missing)}")


# Feishu
FEISHU_APP_ID = _get("feishu.app_id")
FEISHU_APP_SECRET = _get("feishu.app_secret")

# Game
GAME_ID = _get("game.game_id")
DS_START = _get("game.ds_start", "20200101")

# Channels
LOCK_OPGAME_IDS = _get("channels.lock_opgame_ids", [])
CHANNEL_ALIASES = _get("channels.aliases", {})

# Data API
DATA_API_CLIENT_ID = str(_get("data_api.client_id", ""))
DATA_API_KEY = _get("data_api.key", "")
DATA_API_SEARCH_URL = _get("data_api.search_url", "http://data-api.dc.uuzu.com/search/")
DATA_API_DOWNLOAD_URL = _get("data_api.download_url", "http://data-api.download.dc.uuzu.com/download/")
DATA_API_MAX_ROWS = int(_get("data_api.max_rows", 10000))
DATA_API_MOCK = bool(_get("data_api.mock", False))
DATA_API_MAX_RETRY = 10

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

# Logview
LOGVIEW_HOST = _get("logview.host", "127.0.0.1")
LOGVIEW_PORT = int(_get("logview.port", 8900))
LOGVIEW_KEY = _get("logview.key", "")

# Help and reports
HELP_TEXT = _get("help_text", "直接用中文提问即可。")
REPORT_TRIGGERS = _get("report_triggers", {})
HELP_TRIGGERS = ["help", "帮助", "?", "？"]

# Report table names (configurable per project)
REPORT_LOGIN_TABLE = _get("reports.login_table", "gamelog_raw.log_rolelogin")
REPORT_PAY_TABLE = _get("reports.pay_table", "gamelog_raw.log_payrecharge")
REPORT_ACCOUNT_LOGIN_TABLE = _get("reports.account_login_table", "gamelog_raw.log_accountlogin")
