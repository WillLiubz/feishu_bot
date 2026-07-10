"""Patch player_segment.json to fix timeouts and table references."""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
TEMPLATE_PATH = ROOT / "app" / "templates" / "player_segment.json"


def load():
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save(t):
    with open(TEMPLATE_PATH, "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Game 160
# ---------------------------------------------------------------------------

OVERVIEW_160 = """WITH active AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
paid AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
silent AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{silent_start}' AND '{silent_end}'
    {server_filter}
),
pay_analysis AS (
  SELECT role_id,
         SUM(CAST(pay_money AS DOUBLE)) AS pay_amount,
         COUNT(*) AS pay_times
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
  GROUP BY role_id
)
SELECT
  CASE
    WHEN p.role_id IS NOT NULL THEN '付费玩家'
    WHEN s.role_id IS NOT NULL THEN '沉默玩家'
    ELSE '免费玩家'
  END AS segment,
  COUNT(DISTINCT a.role_id) AS user_count,
  COUNT(DISTINCT pa.role_id) AS payer_count,
  COALESCE(CAST(SUM(pa.pay_amount) AS DECIMAL(18,2)), 0) AS pay_amount,
  COALESCE(SUM(pa.pay_times), 0) AS pay_times,
  CASE WHEN COUNT(DISTINCT a.role_id) > 0
       THEN ROUND(COALESCE(CAST(SUM(pa.pay_amount) AS DOUBLE), 0) / COUNT(DISTINCT a.role_id), 2)
       ELSE 0 END AS arpu,
  CASE WHEN COUNT(DISTINCT pa.role_id) > 0
       THEN ROUND(COALESCE(CAST(SUM(pa.pay_amount) AS DOUBLE), 0) / COUNT(DISTINCT pa.role_id), 2)
       ELSE 0 END AS arppu
FROM active a
LEFT JOIN paid p ON a.role_id = p.role_id
LEFT JOIN silent s ON a.role_id = s.role_id
LEFT JOIN pay_analysis pa ON a.role_id = pa.role_id
GROUP BY CASE
    WHEN p.role_id IS NOT NULL THEN '付费玩家'
    WHEN s.role_id IS NOT NULL THEN '沉默玩家'
    ELSE '免费玩家'
  END
ORDER BY CASE segment WHEN '付费玩家' THEN 1 WHEN '沉默玩家' THEN 2 WHEN '免费玩家' THEN 3 ELSE 4 END"""


SILENT_BEHAVIOR_160 = """WITH paid AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
silent AS (
  SELECT role_id, MAX(ds) AS last_pay_ds,
         SUM(CAST(pay_money AS DOUBLE)) AS silent_pay_amount,
         COUNT(*) AS silent_pay_times
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{silent_start}' AND '{silent_end}'
    {server_filter}
  GROUP BY role_id
),
behavior AS (
  SELECT role_id, b_id, COUNT(*) AS events
  FROM gamelog_raw.v_presto_log_bhbehavior
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
  GROUP BY role_id, b_id
),
silent_active AS (
  SELECT s.role_id,
         s.last_pay_ds,
         s.silent_pay_amount,
         s.silent_pay_times
  FROM silent s
  LEFT JOIN paid p ON s.role_id = p.role_id
  WHERE p.role_id IS NULL
)
SELECT
  b.b_id AS b_id,
  COUNT(DISTINCT sa.role_id) AS silent_users,
  SUM(b.events) AS total_events,
  ROUND(CAST(SUM(b.events) AS DOUBLE) / NULLIF(COUNT(DISTINCT sa.role_id), 0), 1) AS avg_per_user,
  ROUND(CAST(COUNT(DISTINCT sa.role_id) AS DOUBLE) / NULLIF((SELECT COUNT(DISTINCT role_id) FROM silent_active), 0) * 100, 2) AS participation_rate
FROM silent_active sa
LEFT JOIN behavior b ON sa.role_id = b.role_id
GROUP BY b.b_id
ORDER BY silent_users DESC NULLS LAST
LIMIT 50"""


FREE_BEHAVIOR_160 = """WITH paid AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
silent AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{silent_start}' AND '{silent_end}'
    {server_filter}
),
active AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
login_info AS (
  SELECT role_id,
         max_by(role_level, ds) AS role_level,
         max_by(role_vip, ds) AS role_vip
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
  GROUP BY role_id
),
free_roles AS (
  SELECT a.role_id
  FROM active a
  LEFT JOIN paid p ON a.role_id = p.role_id
  LEFT JOIN silent s ON a.role_id = s.role_id
  WHERE p.role_id IS NULL AND s.role_id IS NULL
),
behavior AS (
  SELECT role_id, b_id, COUNT(*) AS events
  FROM gamelog_raw.v_presto_log_bhbehavior
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
  GROUP BY role_id, b_id
),
login_days AS (
  SELECT role_id, COUNT(DISTINCT ds) AS active_days
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
    AND role_id IN (SELECT role_id FROM free_roles)
  GROUP BY role_id
)
SELECT
  b.b_id AS b_id,
  COUNT(DISTINCT fr.role_id) AS users,
  SUM(b.events) AS total_events,
  ROUND(CAST(SUM(b.events) AS DOUBLE) / NULLIF(COUNT(DISTINCT fr.role_id), 0), 1) AS avg_per_user,
  ROUND(CAST(COUNT(DISTINCT fr.role_id) AS DOUBLE) / NULLIF((SELECT COUNT(DISTINCT role_id) FROM free_roles), 0) * 100, 2) AS participation_rate,
  COALESCE(CAST(AVG(ld.active_days) AS DECIMAL(18,1)), 0) AS avg_active_days,
  COALESCE(CAST(AVG(li.role_level) AS DECIMAL(18,0)), 0) AS avg_level,
  COALESCE(CAST(AVG(li.role_vip) AS DECIMAL(18,0)), 0) AS avg_vip
FROM free_roles fr
LEFT JOIN behavior b ON fr.role_id = b.role_id
LEFT JOIN login_days ld ON fr.role_id = ld.role_id
LEFT JOIN login_info li ON fr.role_id = li.role_id
GROUP BY b.b_id
ORDER BY users DESC NULLS LAST
LIMIT 50"""


PAID_RECHARGE_160 = """SELECT
  pay_itemid AS item_id,
  pay_type AS pay_type_name,
  COUNT(DISTINCT role_id) AS payer_count,
  COUNT(*) AS pay_times,
  ROUND(SUM(CAST(pay_money AS DOUBLE)), 2) AS pay_amount,
  ROUND(SUM(CAST(pay_money AS DOUBLE)) / COUNT(*), 2) AS avg_price
FROM gamelog_raw.v_presto_log_payrecharge
WHERE game_id = {game_id}
  AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
  {server_filter}
GROUP BY pay_itemid, pay_type
ORDER BY pay_amount DESC
LIMIT 50"""


PAID_RECHARGE_312 = """SELECT
  pay_itemid AS item_id,
  pay_type AS pay_type_name,
  COUNT(DISTINCT role_id) AS payer_count,
  COUNT(*) AS pay_times,
  ROUND(SUM(CAST(pay_money AS DOUBLE)), 2) AS pay_amount,
  ROUND(SUM(CAST(pay_money AS DOUBLE)) / COUNT(*), 2) AS avg_price
FROM gamelog_raw.v_presto_log_payrecharge
WHERE game_id = {game_id}
  AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
  {server_filter}
GROUP BY pay_itemid, pay_type
ORDER BY pay_amount DESC
LIMIT 50"""


TOP_DETAIL_160 = """WITH paid AS (
  SELECT role_id, SUM(CAST(pay_money AS DOUBLE)) AS pay_amount, COUNT(*) AS pay_times
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
  GROUP BY role_id
),
silent AS (
  SELECT role_id, SUM(CAST(pay_money AS DOUBLE)) AS silent_pay_amount,
         COUNT(*) AS silent_pay_times, MAX(ds) AS last_pay_ds
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{silent_start}' AND '{silent_end}'
    {server_filter}
  GROUP BY role_id
),
login_info AS (
  SELECT role_id,
         max_by(role_level, ds) AS role_level,
         max_by(role_vip, ds) AS role_vip
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
  GROUP BY role_id
),
login_days AS (
  SELECT role_id, COUNT(DISTINCT ds) AS active_days
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
  GROUP BY role_id
),
paid_top AS (
  SELECT '付费玩家' AS segment, p.role_id,
         li.role_level, li.role_vip,
         COALESCE(CAST(p.pay_amount AS DECIMAL(18,2)), 0) AS window_pay_amount,
         p.pay_times,
         ld.active_days,
         ROW_NUMBER() OVER (ORDER BY p.pay_amount DESC) AS rk
  FROM paid p
  LEFT JOIN login_info li ON p.role_id = li.role_id
  LEFT JOIN login_days ld ON p.role_id = ld.role_id
),
silent_top AS (
  SELECT '沉默玩家' AS segment, s.role_id,
         li.role_level, li.role_vip,
         COALESCE(CAST(s.silent_pay_amount AS DECIMAL(18,2)), 0) AS window_pay_amount,
         s.silent_pay_times AS pay_times,
         ld.active_days,
         ROW_NUMBER() OVER (ORDER BY s.silent_pay_amount DESC, s.last_pay_ds ASC) AS rk
  FROM silent s
  LEFT JOIN paid p ON s.role_id = p.role_id
  LEFT JOIN login_info li ON s.role_id = li.role_id
  LEFT JOIN login_days ld ON s.role_id = ld.role_id
  WHERE p.role_id IS NULL
),
free_top AS (
  SELECT '免费玩家' AS segment, fr.role_id,
         li.role_level, li.role_vip,
         0 AS window_pay_amount,
         0 AS pay_times,
         ld.active_days,
         ROW_NUMBER() OVER (ORDER BY ld.active_days DESC, li.role_level DESC NULLS LAST) AS rk
  FROM (
    SELECT DISTINCT role_id
    FROM gamelog_raw.v_presto_log_rolelogin
    WHERE game_id = {game_id}
      AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
      {server_filter}
  ) fr
  LEFT JOIN paid p ON fr.role_id = p.role_id
  LEFT JOIN silent s ON fr.role_id = s.role_id
  LEFT JOIN login_info li ON fr.role_id = li.role_id
  LEFT JOIN login_days ld ON fr.role_id = ld.role_id
  WHERE p.role_id IS NULL AND s.role_id IS NULL
)
SELECT segment, role_id, role_level, role_vip, window_pay_amount, pay_times, active_days
FROM paid_top WHERE rk <= {top_n}
UNION ALL
SELECT segment, role_id, role_level, role_vip, window_pay_amount, pay_times, active_days
FROM silent_top WHERE rk <= {top_n}
UNION ALL
SELECT segment, role_id, role_level, role_vip, window_pay_amount, pay_times, active_days
FROM free_top WHERE rk <= {top_n}
ORDER BY segment, window_pay_amount DESC"""


# ---------------------------------------------------------------------------
# Game 312
# ---------------------------------------------------------------------------

PAID_ENGAGEMENT_312 = """WITH paid AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
behavior AS (
  SELECT b_type, role_id
  FROM gamelog_raw.v_presto_log_bhbehavior
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
)
SELECT
  b.b_type AS module_id,
  COUNT(DISTINCT b.role_id) AS active_users,
  COUNT(*) AS active_events,
  ROUND(CAST(COUNT(*) AS DOUBLE) / NULLIF(COUNT(DISTINCT b.role_id), 0), 1) AS active_avg,
  COUNT(DISTINCT p.role_id) AS paid_users,
  COUNT(*) FILTER (WHERE p.role_id IS NOT NULL) AS paid_events,
  ROUND(CAST(COUNT(*) FILTER (WHERE p.role_id IS NOT NULL) AS DOUBLE) / NULLIF(COUNT(DISTINCT p.role_id), 0), 1) AS paid_avg,
  ROUND(CAST(COUNT(DISTINCT p.role_id) AS DOUBLE) / NULLIF(COUNT(DISTINCT b.role_id), 0) * 100, 2) AS paid_rate
FROM behavior b
LEFT JOIN paid p ON b.role_id = p.role_id
GROUP BY b.b_type
ORDER BY active_events DESC
LIMIT 50"""


PAID_ENGAGEMENT_160 = """WITH paid AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
behavior AS (
  SELECT b_id, role_id
  FROM gamelog_raw.v_presto_log_bhbehavior
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
)
SELECT
  b.b_id AS b_id,
  COUNT(DISTINCT b.role_id) AS active_users,
  COUNT(*) AS active_events,
  ROUND(CAST(COUNT(*) AS DOUBLE) / NULLIF(COUNT(DISTINCT b.role_id), 0), 1) AS active_avg,
  COUNT(DISTINCT p.role_id) AS paid_users,
  COUNT(*) FILTER (WHERE p.role_id IS NOT NULL) AS paid_events,
  ROUND(CAST(COUNT(*) FILTER (WHERE p.role_id IS NOT NULL) AS DOUBLE) / NULLIF(COUNT(DISTINCT p.role_id), 0), 1) AS paid_avg,
  ROUND(CAST(COUNT(DISTINCT p.role_id) AS DOUBLE) / NULLIF(COUNT(DISTINCT b.role_id), 0) * 100, 2) AS paid_rate
FROM behavior b
LEFT JOIN paid p ON b.role_id = p.role_id
GROUP BY b.b_id
ORDER BY active_events DESC
LIMIT 50"""


SILENT_BEHAVIOR_312 = """WITH paid AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
silent AS (
  SELECT role_id, MAX(ds) AS last_pay_ds, SUM(CAST(pay_money AS DOUBLE)) AS silent_pay_amount, COUNT(*) AS silent_pay_times
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{silent_start}' AND '{silent_end}'
    {server_filter}
  GROUP BY role_id
),
silent_active AS (
  SELECT s.role_id,
         s.silent_pay_amount
  FROM silent s
  LEFT JOIN paid p ON s.role_id = p.role_id
  WHERE p.role_id IS NULL
),
behavior AS (
  SELECT b_type, role_id
  FROM gamelog_raw.v_presto_log_bhbehavior
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
)
SELECT
  b.b_type AS module_id,
  COUNT(DISTINCT sa.role_id) AS silent_users,
  COUNT(b.role_id) AS total_events,
  ROUND(CAST(COUNT(b.role_id) AS DOUBLE) / NULLIF(COUNT(DISTINCT sa.role_id), 0), 1) AS avg_per_user,
  ROUND(CAST(COUNT(DISTINCT sa.role_id) AS DOUBLE) / NULLIF((SELECT COUNT(DISTINCT role_id) FROM silent_active), 0) * 100, 2) AS participation_rate,
  COALESCE(CAST(AVG(sa.silent_pay_amount) AS DECIMAL(18,2)), 0) AS avg_silent_pay
FROM silent_active sa
LEFT JOIN behavior b ON sa.role_id = b.role_id
GROUP BY b.b_type
ORDER BY silent_users DESC NULLS LAST
LIMIT 50"""


SILENT_BEHAVIOR_160 = """WITH paid AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
silent AS (
  SELECT role_id, MAX(ds) AS last_pay_ds, SUM(CAST(pay_money AS DOUBLE)) AS silent_pay_amount, COUNT(*) AS silent_pay_times
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{silent_start}' AND '{silent_end}'
    {server_filter}
  GROUP BY role_id
),
silent_active AS (
  SELECT s.role_id,
         s.silent_pay_amount
  FROM silent s
  LEFT JOIN paid p ON s.role_id = p.role_id
  WHERE p.role_id IS NULL
),
behavior AS (
  SELECT b_id, role_id
  FROM gamelog_raw.v_presto_log_bhbehavior
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
)
SELECT
  b.b_id AS b_id,
  COUNT(DISTINCT sa.role_id) AS silent_users,
  COUNT(b.role_id) AS total_events,
  ROUND(CAST(COUNT(b.role_id) AS DOUBLE) / NULLIF(COUNT(DISTINCT sa.role_id), 0), 1) AS avg_per_user,
  ROUND(CAST(COUNT(DISTINCT sa.role_id) AS DOUBLE) / NULLIF((SELECT COUNT(DISTINCT role_id) FROM silent_active), 0) * 100, 2) AS participation_rate
FROM silent_active sa
LEFT JOIN behavior b ON sa.role_id = b.role_id
GROUP BY b.b_id
ORDER BY silent_users DESC NULLS LAST
LIMIT 50"""


FREE_BEHAVIOR_312 = """WITH paid AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
silent AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{silent_start}' AND '{silent_end}'
    {server_filter}
),
active AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
login_info AS (
  SELECT role_id,
         max_by(role_paid, ds) AS role_paid,
         max_by(role_level, ds) AS role_level,
         max_by(role_vip, ds) AS role_vip
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
  GROUP BY role_id
),
free_roles AS (
  SELECT a.role_id
  FROM active a
  LEFT JOIN paid p ON a.role_id = p.role_id
  LEFT JOIN silent s ON a.role_id = s.role_id
  LEFT JOIN login_info li ON a.role_id = li.role_id
  WHERE p.role_id IS NULL AND s.role_id IS NULL
    AND (li.role_paid = 0 OR li.role_id IS NULL)
),
behavior AS (
  SELECT b_type, role_id
  FROM gamelog_raw.v_presto_log_bhbehavior
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
login_days AS (
  SELECT role_id, COUNT(DISTINCT ds) AS active_days
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
    AND role_id IN (SELECT role_id FROM free_roles)
  GROUP BY role_id
)
SELECT
  b.b_type AS module_id,
  COUNT(DISTINCT fr.role_id) AS users,
  COUNT(b.role_id) AS total_events,
  ROUND(CAST(COUNT(b.role_id) AS DOUBLE) / NULLIF(COUNT(DISTINCT fr.role_id), 0), 1) AS avg_per_user,
  ROUND(CAST(COUNT(DISTINCT fr.role_id) AS DOUBLE) / NULLIF((SELECT COUNT(DISTINCT role_id) FROM free_roles), 0) * 100, 2) AS participation_rate,
  COALESCE(CAST(AVG(ld.active_days) AS DECIMAL(18,1)), 0) AS avg_active_days,
  COALESCE(CAST(AVG(li.role_level) AS DECIMAL(18,0)), 0) AS avg_level,
  COALESCE(CAST(AVG(li.role_vip) AS DECIMAL(18,0)), 0) AS avg_vip
FROM free_roles fr
LEFT JOIN behavior b ON fr.role_id = b.role_id
LEFT JOIN login_days ld ON fr.role_id = ld.role_id
LEFT JOIN login_info li ON fr.role_id = li.role_id
GROUP BY b.b_type
ORDER BY users DESC NULLS LAST
LIMIT 50"""


FREE_BEHAVIOR_160 = """WITH paid AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
silent AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{silent_start}' AND '{silent_end}'
    {server_filter}
),
active AS (
  SELECT DISTINCT role_id
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
login_info AS (
  SELECT role_id,
         max_by(role_level, ds) AS role_level,
         max_by(role_vip, ds) AS role_vip
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
  GROUP BY role_id
),
free_roles AS (
  SELECT a.role_id
  FROM active a
  LEFT JOIN paid p ON a.role_id = p.role_id
  LEFT JOIN silent s ON a.role_id = s.role_id
  WHERE p.role_id IS NULL AND s.role_id IS NULL
),
behavior AS (
  SELECT b_id, role_id
  FROM gamelog_raw.v_presto_log_bhbehavior
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
),
login_days AS (
  SELECT role_id, COUNT(DISTINCT ds) AS active_days
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
    AND role_id IN (SELECT role_id FROM free_roles)
  GROUP BY role_id
)
SELECT
  b.b_id AS b_id,
  COUNT(DISTINCT fr.role_id) AS users,
  COUNT(b.role_id) AS total_events,
  ROUND(CAST(COUNT(b.role_id) AS DOUBLE) / NULLIF(COUNT(DISTINCT fr.role_id), 0), 1) AS avg_per_user,
  ROUND(CAST(COUNT(DISTINCT fr.role_id) AS DOUBLE) / NULLIF((SELECT COUNT(DISTINCT role_id) FROM free_roles), 0) * 100, 2) AS participation_rate,
  COALESCE(CAST(AVG(ld.active_days) AS DECIMAL(18,1)), 0) AS avg_active_days,
  COALESCE(CAST(AVG(li.role_level) AS DECIMAL(18,0)), 0) AS avg_level,
  COALESCE(CAST(AVG(li.role_vip) AS DECIMAL(18,0)), 0) AS avg_vip
FROM free_roles fr
LEFT JOIN behavior b ON fr.role_id = b.role_id
LEFT JOIN login_days ld ON fr.role_id = ld.role_id
LEFT JOIN login_info li ON fr.role_id = li.role_id
GROUP BY b.b_id
ORDER BY users DESC NULLS LAST
LIMIT 50"""


TOP_DETAIL_312 = """WITH paid AS (
  SELECT role_id, SUM(CAST(pay_money AS DOUBLE)) AS pay_amount, COUNT(*) AS pay_times
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
  GROUP BY role_id
),
silent AS (
  SELECT role_id, SUM(CAST(pay_money AS DOUBLE)) AS silent_pay_amount, COUNT(*) AS silent_pay_times, MAX(ds) AS last_pay_ds
  FROM gamelog_raw.v_presto_log_payrecharge
  WHERE game_id = {game_id}
    AND ds BETWEEN '{silent_start}' AND '{silent_end}'
    {server_filter}
  GROUP BY role_id
),
login_info AS (
  SELECT role_id,
         max_by(role_level, ds) AS role_level,
         max_by(role_vip, ds) AS role_vip
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
  GROUP BY role_id
),
login_days AS (
  SELECT role_id, COUNT(DISTINCT ds) AS active_days
  FROM gamelog_raw.v_presto_log_rolelogin
  WHERE game_id = {game_id}
    AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
    {server_filter}
  GROUP BY role_id
),
paid_top AS (
  SELECT '付费玩家' AS segment, CAST(p.role_id AS VARCHAR) AS role_id,
         li.role_level, li.role_vip,
         COALESCE(CAST(p.pay_amount AS DECIMAL(18,2)), 0) AS window_pay_amount,
         p.pay_times,
         ld.active_days,
         ROW_NUMBER() OVER (ORDER BY p.pay_amount DESC) AS rk
  FROM paid p
  LEFT JOIN login_info li ON p.role_id = li.role_id
  LEFT JOIN login_days ld ON p.role_id = ld.role_id
),
silent_top AS (
  SELECT '沉默玩家' AS segment, CAST(s.role_id AS VARCHAR) AS role_id,
         li.role_level, li.role_vip,
         COALESCE(CAST(s.silent_pay_amount AS DECIMAL(18,2)), 0) AS window_pay_amount,
         s.silent_pay_times AS pay_times,
         ld.active_days,
         ROW_NUMBER() OVER (ORDER BY s.silent_pay_amount DESC, s.last_pay_ds ASC) AS rk
  FROM silent s
  LEFT JOIN paid p ON s.role_id = p.role_id
  LEFT JOIN login_info li ON s.role_id = li.role_id
  LEFT JOIN login_days ld ON s.role_id = ld.role_id
  WHERE p.role_id IS NULL
),
free_top AS (
  SELECT '免费玩家' AS segment, CAST(fr.role_id AS VARCHAR) AS role_id,
         li.role_level, li.role_vip,
         0 AS window_pay_amount,
         0 AS pay_times,
         ld.active_days,
         ROW_NUMBER() OVER (ORDER BY ld.active_days DESC, li.role_level DESC NULLS LAST) AS rk
  FROM (
    SELECT DISTINCT role_id
    FROM gamelog_raw.v_presto_log_rolelogin
    WHERE game_id = {game_id}
      AND ds BETWEEN '{analysis_start}' AND '{analysis_end}'
      {server_filter}
  ) fr
  LEFT JOIN paid p ON fr.role_id = p.role_id
  LEFT JOIN silent s ON fr.role_id = s.role_id
  LEFT JOIN login_info li ON fr.role_id = li.role_id
  LEFT JOIN login_days ld ON fr.role_id = ld.role_id
  WHERE p.role_id IS NULL AND s.role_id IS NULL
)
SELECT segment, role_id, role_level, role_vip, window_pay_amount, pay_times, active_days
FROM paid_top WHERE rk <= {top_n}
UNION ALL
SELECT segment, role_id, role_level, role_vip, window_pay_amount, pay_times, active_days
FROM silent_top WHERE rk <= {top_n}
UNION ALL
SELECT segment, role_id, role_level, role_vip, window_pay_amount, pay_times, active_days
FROM free_top WHERE rk <= {top_n}
ORDER BY segment, window_pay_amount DESC"""


def main():
    t = load()
    g160 = t["games"]["160"]
    g312 = t["games"]["312"]

    g160["overview"]["sql"] = OVERVIEW_160
    g160["paid_recharge"]["sql"] = PAID_RECHARGE_160
    g160["paid_recharge"]["value_map"] = {"pay_type_name": {"1": "购买钻石", "2": "购买商品"}}
    g160["paid_engagement"]["sql"] = PAID_ENGAGEMENT_160
    g160["silent_behavior"]["sql"] = SILENT_BEHAVIOR_160
    g160["free_behavior"]["sql"] = FREE_BEHAVIOR_160
    g160["top_detail"]["sql"] = TOP_DETAIL_160

    g312["paid_recharge"]["sql"] = PAID_RECHARGE_312
    g312["paid_recharge"]["value_map"] = {"pay_type_name": {"1": "购买钻石", "2": "购买商品"}}
    g312["paid_engagement"]["sql"] = PAID_ENGAGEMENT_312
    g312["silent_behavior"]["sql"] = SILENT_BEHAVIOR_312
    g312["free_behavior"]["sql"] = FREE_BEHAVIOR_312
    g312["top_detail"]["sql"] = TOP_DETAIL_312

    save(t)
    print("patched player_segment.json")


if __name__ == "__main__":
    main()
