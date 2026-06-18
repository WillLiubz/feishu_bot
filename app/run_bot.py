import io
import sys
from pathlib import Path

# Ensure app/ is on sys.path regardless of working directory
sys.path.insert(0, str(Path(__file__).parent))

# Force UTF-8 output to avoid emoji/Chinese mojibake on GBK consoles
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import account_cache
import bot
import config
import store


def main():
    config.check()
    store.init()
    account_cache.init()
    ws = bot.build_ws_client()
    print(f"[bot] 启动中，game_id={config.GAME_ID}，模型={config.CLAUDE_MODEL}")
    ws.start()


if __name__ == "__main__":
    main()
