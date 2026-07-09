import csv
import hashlib
import io
import json
import time
import urllib.parse
import requests
import config

_MOCK_ROWS = [{"game_id": str(config.GAME_ID), "ds": "20260617", "col": "mock_value"}]


def generate_sign(params):
    """Sort params by key, join as k=v&..., return MD5 hex."""
    s = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.md5(s.encode()).hexdigest()


def _submit(sql):
    """Submit SQL to search endpoint, return task_id. Retries up to DATA_API_MAX_RETRY times."""
    api_params = urllib.parse.quote(json.dumps({"sql": sql}))
    last_err = None
    for attempt in range(config.DATA_API_MAX_RETRY):
        ts = str(int(time.time()))
        sign = generate_sign({
            "_key": config.DATA_API_KEY,
            "api_name": config.DATA_API_API_NAME,
            "api_params": api_params,
            "client_id": config.DATA_API_CLIENT_ID,
            "timestamp": ts,
        })
        payload = {
            "api_name": config.DATA_API_API_NAME,
            "api_params": api_params,
            "client_id": config.DATA_API_CLIENT_ID,
            "timestamp": ts,
            "sign": sign,
        }
        try:
            resp = requests.post(config.DATA_API_SEARCH_URL, json=payload, timeout=30)
            data = resp.json()
            comment = data.get("return_comment") or ""
            if "失败" not in comment and data.get("return_code") == 0:
                return data["data"]["task_id"]
            last_err = comment
        except Exception as e:
            last_err = str(e)
        if attempt < config.DATA_API_MAX_RETRY - 1:
            time.sleep(3)
    raise RuntimeError(f"数仓提交失败（重试 {config.DATA_API_MAX_RETRY} 次）: {last_err}")


_POLL_INTERVAL = 5
_POLL_MAX_ATTEMPTS = 108  # ~9 minutes total


def _download_rows(task_id, max_rows):
    """Download TSV result, poll until ready, parse into list[dict]."""
    api_params = urllib.parse.quote(json.dumps({"task_id": task_id}))
    t0 = time.time()

    for attempt in range(_POLL_MAX_ATTEMPTS):
        ts = str(int(time.time()))
        sign = generate_sign({
            "_key": config.DATA_API_KEY,
            "api_params": api_params,
            "client_id": config.DATA_API_CLIENT_ID,
            "timestamp": ts,
        })
        payload = {
            "client_id": config.DATA_API_CLIENT_ID,
            "api_params": api_params,
            "timestamp": ts,
            "sign": sign,
        }
        resp = requests.post(config.DATA_API_DOWNLOAD_URL, json=payload, timeout=120)
        content_type = resp.headers.get("content-type", "")

        if "multipart/form-data" in content_type:
            # Data is ready — parse TSV
            rows = []
            headers = None
            reader = csv.reader(io.StringIO(resp.text), delimiter="\t")
            for line in reader:
                if headers is None:
                    headers = line
                    continue
                if len(rows) >= max_rows:
                    break
                rows.append(dict(zip(headers, line)))
            elapsed_ms = int((time.time() - t0) * 1000)
            print(f"[dataapi] download ready rows={len(rows)} latency={elapsed_ms}ms", flush=True)
            return rows

        if "text/html" in content_type or resp.text.strip().startswith("<"):
            # Task not ready yet, wait and retry
            if attempt < _POLL_MAX_ATTEMPTS - 1:
                time.sleep(_POLL_INTERVAL)
                continue
        elapsed_sec = int(time.time() - t0)
        raise RuntimeError(f"数仓任务超时未完成 (task_id={task_id}，已等待 {elapsed_sec} 秒)")

    elapsed_sec = int(time.time() - t0)
    raise RuntimeError(f"数仓下载重试耗尽 (task_id={task_id}，已等待 {elapsed_sec} 秒)")



def run_sql_rows(sql, max_rows=None):
    """Execute SQL, return list[dict]. Uses mock data if DATA_API_MOCK is True."""
    if max_rows is None:
        max_rows = config.DATA_API_MAX_ROWS
    if config.DATA_API_MOCK:
        return list(_MOCK_ROWS)
    task_id = _submit(sql)
    return _download_rows(task_id, max_rows)


if __name__ == "__main__":
    params = {"_key": config.DATA_API_KEY, "api_name": "mfa_data",
              "api_params": "test", "client_id": config.DATA_API_CLIENT_ID,
              "timestamp": "1234567890"}
    print(f"Example sign: {generate_sign(params)}")
