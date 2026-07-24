import calendar
import re
from datetime import date, timedelta, datetime
import config
import account_cache
import dataapi
import dquery
import role_ranking_cache
import templates

_MAX_RANGE_DAYS = 92
_LTV_MAX_ROWS = 500000
_LTV_DAYS = [1, 3, 7, 15, 30]
_MONTH_RANK_PAY_TOP_N = 200
_IN_BATCH_SIZE = 1000


# ---------------------------------------------------------------------------
# Trigger matching
# ---------------------------------------------------------------------------

def match(text):
    """Return report type string if text matches a trigger, else None."""
    triggers = config.REPORT_TRIGGERS
    for report_type, keywords in triggers.items():
        for kw in keywords:
            if kw.lower() in text.lower():
                return report_type
    return None


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

def _today():
    return date.today()


def _ds(d):
    return d.strftime("%Y%m%d")


def _parse_dates(text):
    """
    Parse date or date range from text.
    Returns list of date objects (single day or range).
    """
    today = _today()

    # Relative keywords
    if re.search(r'今日|今天', text):
        return [today]
    if re.search(r'昨日|昨天', text):
        return [today - timedelta(days=1)]
    if re.search(r'近\s*3\s*[天日]', text):
        return [today - timedelta(days=i) for i in range(2, -1, -1)]
    if re.search(r'近\s*7\s*[天日]', text):
        return [today - timedelta(days=i) for i in range(6, -1, -1)]
    if re.search(r'近\s*30\s*[天日]', text):
        return [today - timedelta(days=i) for i in range(29, -1, -1)]
    if re.search(r'本周', text):
        start = today - timedelta(days=today.weekday())
        return [start + timedelta(days=i) for i in range((today - start).days + 1)]
    if re.search(r'上周', text):
        start = today - timedelta(days=today.weekday() + 7)
        return [start + timedelta(days=i) for i in range(7)]
    if re.search(r'本月', text):
        start = today.replace(day=1)
        return [start + timedelta(days=i) for i in range((today - start).days + 1)]

    # Absolute date: 20260601, 2026-06-01, 6月1日
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', text)
    if m:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return [d]
    m = re.search(r'(\d{8})', text)
    if m:
        s = m.group(1)
        d = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return [d]
    m = re.search(r'(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]', text)
    if m:
        d = date(today.year, int(m.group(1)), int(m.group(2)))
        return [d]

    # Default: yesterday (data for today may be incomplete)
    return [today - timedelta(days=1)]


def _parse_year_month(text):
    """Parse YYYYMM from text. Defaults to last month."""
    # 2026年6月, 2026-06, 202606, 6月
    m = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月', text)
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}"
    m = re.search(r'(\d{4})[/-](\d{1,2})', text)
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}"
    m = re.search(r'(\d{6})', text)
    if m:
        return m.group(1)
    m = re.search(r'(\d{1,2})\s*月', text)
    if m:
        return f"{date.today().year}{int(m.group(1)):02d}"
    # Default to last month
    d = date.today().replace(day=1) - timedelta(days=1)
    return d.strftime("%Y%m")


# ---------------------------------------------------------------------------
# KPI report
# ---------------------------------------------------------------------------

def _query_kpi_day(ds_str, game_config):
    """Query single-day KPI from data warehouse. Returns dict."""
    game_id = game_config.game_id
    login_table = game_config.reports.get("login_table", config.REPORT_LOGIN_TABLE)
    pay_table = game_config.reports.get("pay_table", config.REPORT_PAY_TABLE)

    dau_sql = (
        f"SELECT COUNT(DISTINCT account) as dau"
        f" FROM {login_table}"
        f" WHERE game_id = {game_id} AND ds = '{ds_str}'"
        f" LIMIT 1"
    )
    pay_sql = (
        f"SELECT COUNT(DISTINCT account) as payers,"
        f" COALESCE(SUM(CAST(money AS DOUBLE)), 0) as revenue"
        f" FROM {pay_table}"
        f" WHERE game_id = {game_id} AND ds = '{ds_str}'"
        f" LIMIT 1"
    )

    dau_rows = dataapi.run_sql_rows(dau_sql, max_rows=1)
    pay_rows = dataapi.run_sql_rows(pay_sql, max_rows=1)

    dau = int(dau_rows[0].get("dau", 0)) if dau_rows else 0
    payers = int(pay_rows[0].get("payers", 0)) if pay_rows else 0
    revenue = float(pay_rows[0].get("revenue", 0)) if pay_rows else 0.0
    new_accs = account_cache.new_accounts_on(ds_str)

    return {
        "日期": ds_str,
        "日活(DAU)": dau,
        "新增账号": new_accs,
        "付费人数": payers,
        "收入(元)": f"{revenue:.2f}",
    }


def daily_kpi(question, game_config=None):
    """Run KPI report. Returns (summary_text, csv_path)."""
    if game_config is None:
        game_config = config.game_config()
    account_cache.refresh()
    dates = _parse_dates(question)
    if len(dates) > _MAX_RANGE_DAYS:
        dates = dates[-_MAX_RANGE_DAYS:]

    rows = [_query_kpi_day(_ds(d), game_config) for d in dates]

    if len(rows) == 1:
        r = rows[0]
        summary = (
            f"【{r['日期']} KPI】\n"
            f"日活(DAU)：{r['日活(DAU)']}\n"
            f"新增账号：{r['新增账号']}\n"
            f"付费人数：{r['付费人数']}\n"
            f"收入：{r['收入(元)']} 元"
        )
    else:
        total_dau = sum(int(r["日活(DAU)"]) for r in rows)
        total_rev = sum(float(r["收入(元)"]) for r in rows)
        avg_dau = total_dau // len(rows)
        summary = (
            f"【KPI 汇总 {_ds(dates[0])}~{_ds(dates[-1])}，共 {len(rows)} 天】\n"
            f"日均DAU：{avg_dau}\n"
            f"总收入：{total_rev:.2f} 元"
        )

    csv_path = dquery.write_csv(rows)
    return summary, csv_path


# ---------------------------------------------------------------------------
# LTV report
# ---------------------------------------------------------------------------

def daily_ltv(question, game_config=None):
    """Run LTV report by registration cohort. Returns (summary_text, csv_path)."""
    if game_config is None:
        game_config = config.game_config()
    account_cache.refresh()
    game_id = game_config.game_id
    pay_table = game_config.reports.get("pay_table", config.REPORT_PAY_TABLE)

    # Fetch all pay records since ds_start
    pay_sql = (
        f"SELECT account, ds, CAST(money AS DOUBLE) as amount"
        f" FROM {pay_table}"
        f" WHERE game_id = {game_id}"
        f" AND ds >= '{game_config.ds_start}'"
        f" LIMIT {_LTV_MAX_ROWS}"
    )
    pay_rows = dataapi.run_sql_rows(pay_sql, max_rows=_LTV_MAX_ROWS)
    truncated = len(pay_rows) >= _LTV_MAX_ROWS

    # Build account -> reg_date mapping
    all_accounts = list({r["account"] for r in pay_rows})
    rdmap = account_cache.reg_date_map(all_accounts)

    # Group pay by cohort
    cohort_rev = {}  # {(reg_date, days_since_reg): total}
    cohort_counts = account_cache.cohort_sizes()

    for r in pay_rows:
        acc = r["account"]
        reg = rdmap.get(acc)
        if not reg:
            continue
        try:
            reg_d = datetime.strptime(reg, "%Y%m%d").date()
            pay_d = datetime.strptime(r["ds"], "%Y%m%d").date()
        except ValueError:
            continue
        delta = (pay_d - reg_d).days
        key = (reg, delta)
        cohort_rev[key] = cohort_rev.get(key, 0.0) + float(r.get("amount", 0))

    # Compute LTV rows per cohort date
    cohort_dates = sorted(cohort_counts.keys())
    ltv_rows = []
    for reg_date in cohort_dates:
        n = cohort_counts[reg_date]
        if n == 0:
            continue
        row = {"注册日": reg_date, "新增人数": n}
        for ltv_day in _LTV_DAYS:
            total = sum(
                cohort_rev.get((reg_date, d), 0.0) for d in range(ltv_day)
            )
            row[f"LTV{ltv_day}"] = f"{total / n:.4f}"
        ltv_rows.append(row)

    note = "（数据量过大，结果可能不完整）" if truncated else ""
    summary = f"【LTV 报表，共 {len(ltv_rows)} 个注册日队列】{note}"
    csv_path = dquery.write_csv(ltv_rows)
    return summary, csv_path


# ---------------------------------------------------------------------------
# Month ranking pay report
# ---------------------------------------------------------------------------

def _last_day_of_month(year_month: str) -> str:
    y = int(year_month[:4])
    m = int(year_month[4:6])
    _, last_day = calendar.monthrange(y, m)
    return f"{year_month}{last_day:02d}"


def month_rank_pay(question, game_config=None, top_n=_MONTH_RANK_PAY_TOP_N):
    """Query recharge for top ranking players of a month. Returns (summary, csv_path)."""
    if game_config is None:
        game_config = config.game_config()

    year_month = _parse_year_month(question)
    start_ds = f"{year_month}01"
    end_ds = _last_day_of_month(year_month)

    role_ranking_cache.init(game_config)
    rank_map = role_ranking_cache.get_rank_map(
        year_month=year_month, rank_type="MonthRank", top_n=top_n, game_config=game_config
    )
    role_ids = list(rank_map.keys())
    if not role_ids:
        return f"【{year_month} 月度排行榜充值】未找到上榜玩家", None

    pay_table = game_config.reports.get("pay_table", config.REPORT_PAY_TABLE)
    game_id = game_config.game_id

    rows = []
    # Batch IN clause to avoid oversized SQL
    for i in range(0, len(role_ids), _IN_BATCH_SIZE):
        batch = role_ids[i:i + _IN_BATCH_SIZE]
        in_list = ",".join(f"'{rid}'" for rid in batch)
        sql = (
            f"SELECT CAST(role_id AS VARCHAR) AS role_id,"
            f" COUNT(*) AS pay_times,"
            f" COALESCE(SUM(CAST(money AS DOUBLE)), 0) AS total_money"
            f" FROM {pay_table}"
            f" WHERE game_id = {game_id}"
            f" AND ds >= '{start_ds}' AND ds <= '{end_ds}'"
            f" AND CAST(role_id AS VARCHAR) IN ({in_list})"
            f" GROUP BY CAST(role_id AS VARCHAR)"
        )
        rows.extend(dataapi.run_sql_rows(sql, max_rows=len(batch)))

    # Merge with rank
    merged = []
    for rid in role_ids:
        found = next((r for r in rows if str(r.get("role_id")) == rid), None)
        merged.append({
            "排名": rank_map[rid],
            "role_id": rid,
            "充值次数": int(found.get("pay_times", 0)) if found else 0,
            "充值金额": float(found.get("total_money", 0)) if found else 0.0,
        })

    total_money = sum(r["充值金额"] for r in merged)
    payers = sum(1 for r in merged if r["充值金额"] > 0)
    summary = (
        f"【{year_month} 月度排行榜玩家充值 TOP {len(merged)}】\n"
        f"上榜玩家数：{len(merged)}\n"
        f"有充值人数：{payers}\n"
        f"总充值金额：{total_money:.2f} 元"
    )
    csv_path = dquery.write_csv(merged)
    return summary, csv_path


# ---------------------------------------------------------------------------
# Player segment analysis report
# ---------------------------------------------------------------------------

def player_segment_report(question, game_config=None):
    """Run player segmentation analytics report. Returns (summary, result_dir)."""
    if game_config is None:
        game_config = config.game_config()
    summary, result_dir = templates.run_report(
        "player_segment", question, game_config=game_config
    )
    return summary, result_dir


# ---------------------------------------------------------------------------
# Pay composition & activity analysis report
# ---------------------------------------------------------------------------

def pay_activity_report(question, game_config=None):
    """Run pay composition & activity analysis report. Returns (summary, result_dir)."""
    if game_config is None:
        game_config = config.game_config()
    return templates.run_report("pay_activity", question, game_config=game_config)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def run(report_type, question, game_config=None):
    """Dispatch to the appropriate report function."""
    if game_config is None:
        game_config = config.game_config()
    if report_type == "kpi":
        return daily_kpi(question, game_config=game_config)
    if report_type == "ltv":
        return daily_ltv(question, game_config=game_config)
    if report_type == "month_rank_pay":
        return month_rank_pay(question, game_config=game_config)
    if report_type == "player_segment":
        return player_segment_report(question, game_config=game_config)
    if report_type == "pay_activity":
        return pay_activity_report(question, game_config=game_config)
    raise ValueError(f"未知报表类型: {report_type}")
