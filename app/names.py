import lark_oapi as lark
import config

_cache = {}


def _client():
    return lark.Client.builder() \
        .app_id(config.FEISHU_APP_ID) \
        .app_secret(config.FEISHU_APP_SECRET) \
        .build()


def user_name(open_id):
    """Resolve open_id to display name. Falls back to last-6-chars of ID."""
    if open_id in config.NAMES:
        return config.NAMES[open_id]
    if open_id in _cache:
        return _cache[open_id]
    try:
        from lark_oapi.api.contact.v3 import GetUserRequest
        req = GetUserRequest.builder() \
            .user_id(open_id) \
            .user_id_type("open_id") \
            .build()
        resp = _client().contact.v3.user.get(req)
        if resp.success():
            name = resp.data.user.name
            _cache[open_id] = name
            return name
    except Exception:
        pass
    return f"用户_{open_id[-6:]}"


def chat_name(chat_id, chat_type="p2p"):
    """Resolve chat_id to display name."""
    if chat_id in config.NAMES:
        return config.NAMES[chat_id]
    if chat_type == "p2p":
        return f"私聊_{chat_id[-6:]}"
    return f"群_{chat_id[-6:]}"
