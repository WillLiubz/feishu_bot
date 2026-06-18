import re
from datetime import date, timedelta, datetime
import config
import account_cache
import dataapi
import dquery

_MAX_RANGE_DAYS = 92
_LTV_MAX_ROWS = 500000
_LTV_DAYS = [1, 3, 7, 15, 30]


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


# ---------------------------------------------------------------------------
# KPI report
# ---------------------------------------------------------------------------

def _query_kpi_day(ds_str):
    """Query single-day KPI from data warehouse. Returns dict."""
    game_id = config.GAME_ID

    dau_sql = (
        f"SELECT COUNT(DISTINCT account) as dau"
        f" FROM {config.REPORT_LOGIN_TABLE}"
        f" WHERE game_id = {game_id} AND ds = '{ds_str}'"
        f" LIMIT 1"
    )
    pay_sql = (
        f"SELECT COUNT(DISTINCT account) as payers,"
        f" COALESCE(SUM(CAST(money AS DOUBLE)), 0) as revenue"
        f" FROM {config.REPORT_PAY_TABLE}"
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


def daily_kpi(question):
    """Run KPI report. Returns (summary_text, csv_path)."""
    account_cache.refresh()
    dates = _parse_dates(question)
    if len(dates) > _MAX_RANGE_DAYS:
        dates = dates[-_MAX_RANGE_DAYS:]

    rows = [_query_kpi_day(_ds(d)) for d in dates]

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

def daily_ltv(question):
    """Run LTV report by registration cohort. Returns (summary_text, csv_path)."""
    account_cache.refresh()
    game_id = config.GAME_ID

    # Fetch all pay records since ds_start
    pay_sql = (
        f"SELECT account, ds, CAST(money AS DOUBLE) as amount"
        f" FROM {config.REPORT_PAY_TABLE}"
        f" WHERE game_id = {game_id}"
        f" AND ds >= '{config.DS_START}'"
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


def run(report_type, question):
    """Dispatch to the appropriate report function."""
    if report_type == "kpi":
        return daily_kpi(question)
    if report_type == "ltv":
        return daily_ltv(question)
    raise ValueError(f"未知报表类型: {report_type}")
