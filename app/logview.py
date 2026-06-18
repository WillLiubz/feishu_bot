"""
Local read-only web log viewer.
Usage: python app/logview.py
Open: http://127.0.0.1:8900
"""
import io
import json
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
import config

_DB_PATH = Path(config._ROOT) / "data" / "bot.db"


def _get_conn():
    return sqlite3.connect(str(_DB_PATH), check_same_thread=False)


def _check_auth(handler):
    if not config.LOGVIEW_KEY:
        return True
    import base64
    auth = handler.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode()
        return decoded.split(":", 1)[1] == config.LOGVIEW_KEY
    except Exception:
        return False


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>飞书 Bot 日志</title>
<style>
body{{font-family:sans-serif;margin:0;display:flex;height:100vh}}
#sidebar{{width:260px;overflow-y:auto;border-right:1px solid #ddd;padding:8px}}
#main{{flex:1;overflow-y:auto;padding:12px}}
.chat-item{{padding:6px 8px;cursor:pointer;border-radius:4px;margin-bottom:2px}}
.chat-item:hover,.chat-item.active{{background:#e8f0fe}}
.msg{{margin:8px 0;max-width:75%}}
.msg.in{{margin-left:auto;background:#dcf8c6;padding:8px;border-radius:8px}}
.msg.out{{background:#fff;border:1px solid #ddd;padding:8px;border-radius:8px}}
.sql{{font-family:monospace;font-size:12px;background:#f5f5f5;padding:6px;border-left:3px solid #aaa;margin:4px 0}}
.ts{{font-size:11px;color:#999}}
h3{{margin:0 0 8px}}
</style>
<script>
function loadChat(chatId){{
  fetch('/chat?id='+encodeURIComponent(chatId))
    .then(r=>r.json()).then(data=>{{
      document.querySelectorAll('.chat-item').forEach(el=>el.classList.remove('active'));
      document.querySelector('[data-id="'+chatId+'"]').classList.add('active');
      let html='<h3>'+data.name+'</h3>';
      data.messages.forEach(m=>{{
        html+='<div class="msg '+m.dir+'">';
        html+='<div class="ts">'+m.time+'</div>';
        html+='<div>'+m.text.replace(/\\n/g,'<br>')+'</div>';
        if(m.sqls&&m.sqls.length){{
          m.sqls.forEach(s=>{{html+='<div class="sql">'+s+'</div>';}});
        }}
        html+='</div>';
      }});
      document.getElementById('main').innerHTML=html;
    }});
}}
setInterval(()=>{{if(window._activeChatId)loadChat(window._activeChatId);}},3000);
function pickChat(id){{window._activeChatId=id;loadChat(id);}}
</script>
</head>
<body>
<div id="sidebar"><h3>会话列表</h3>{chats}</div>
<div id="main"><p>选择左侧会话查看记录</p></div>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Silence default access log

    def do_GET(self):
        if not _check_auth(self):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="logview"')
            self.end_headers()
            return

        parsed = urlparse(self.path)
        if parsed.path == "/chat":
            self._serve_chat(parse_qs(parsed.query).get("id", [""])[0])
        else:
            self._serve_index()

    def _serve_index(self):
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT chat_id FROM messages ORDER BY MAX(created_at) DESC LIMIT 100"
            ).fetchall()
        finally:
            conn.close()
        items = ""
        for (cid,) in rows:
            items += f'<div class="chat-item" data-id="{cid}" onclick="pickChat(\'{cid}\')">{cid[-12:]}</div>\n'
        html = _HTML_TEMPLATE.format(chats=items).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html)

    def _serve_chat(self, chat_id):
        conn = _get_conn()
        try:
            msgs = conn.execute(
                "SELECT direction, text, created_at, message_id, status FROM messages"
                " WHERE chat_id=? ORDER BY created_at",
                (chat_id,)
            ).fetchall()
            sqls = conn.execute(
                "SELECT message_id, sql, row_count, status, error FROM query_log"
                " WHERE chat_id=? ORDER BY id",
                (chat_id,)
            ).fetchall()
        finally:
            conn.close()

        sql_by_msg = {}
        for (mid, sql, rc, st, err) in sqls:
            label = f"[{st}] rows={rc} | {sql}"
            if err:
                label += f" | ERROR: {err}"
            sql_by_msg.setdefault(mid, []).append(label)

        import datetime
        result_msgs = []
        for (direction, text, ts, mid, status) in msgs:
            t = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else ""
            result_msgs.append({
                "dir": direction,
                "text": text or status or "",
                "time": t,
                "sqls": sql_by_msg.get(mid, []),
            })

        data = {"name": chat_id[-12:], "messages": result_msgs}
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def main():
    server = HTTPServer((config.LOGVIEW_HOST, config.LOGVIEW_PORT), Handler)
    print(f"[logview] http://{config.LOGVIEW_HOST}:{config.LOGVIEW_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
