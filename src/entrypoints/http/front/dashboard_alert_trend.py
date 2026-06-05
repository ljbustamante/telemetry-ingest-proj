"""GET /dashboard/alert-trend — conteo diario de devices ACTIVE por nivel de riesgo."""

from __future__ import annotations

import logging
from typing import Any

import psycopg2.extras

from ....infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import error_detail, parse_event, response

logger = logging.getLogger(__name__)

_SQL = """
WITH bounds AS (
    SELECT
        (NOW() - (%s::integer * INTERVAL '1 day'))::date AS start_day,
        NOW()::date AS end_day
),
days AS (
    SELECT gs.day::date
    FROM bounds b,
    LATERAL generate_series(
        b.start_day::timestamptz,
        b.end_day::timestamptz,
        INTERVAL '1 day'
    ) AS gs(day)
),
device_daily AS (
    SELECT DISTINCT ON (r.device_id, DATE(r.event_ts))
        DATE(r.event_ts) AS day,
        r.risk_bucket
    FROM readings_curated_parent r
    JOIN devices d ON d.id = r.device_id AND d.status = 'ACTIVE'
    WHERE r.event_ts >= (SELECT start_day::timestamptz FROM bounds)
      AND r.risk_bucket IS NOT NULL
    ORDER BY r.device_id, DATE(r.event_ts), r.event_ts DESC
)
SELECT
    days.day,
    COUNT(dd.*) FILTER (WHERE dd.risk_bucket = 'Alto')  AS high,
    COUNT(dd.*) FILTER (WHERE dd.risk_bucket = 'Medio') AS medium,
    COUNT(dd.*) FILTER (WHERE dd.risk_bucket = 'Bajo')  AS low
FROM days
LEFT JOIN device_daily dd ON dd.day = days.day
GROUP BY days.day
ORDER BY days.day ASC
"""


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, _path, _pp, query, _body = parse_event(event)
    if method == "OPTIONS":
        return response(200, {}, event=event)
    if method != "GET":
        return error_detail(405, "Metodo no permitido", event=event)
    bad = require_auth(event)
    if bad:
        return bad

    raw_days = (query or {}).get("days", 7)
    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        days = 7
    days = min(max(days, 1), 90)

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(_SQL, (days,))
        out = [
            {
                "date": dict(r)["day"].strftime("%d %b"),
                "high": int(dict(r)["high"] or 0),
                "medium": int(dict(r)["medium"] or 0),
                "low": int(dict(r)["low"] or 0),
            }
            for r in cur.fetchall()
        ]
        return response(200, out, event=event)
    except Exception as e:
        logger.exception("dashboard_alert_trend: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        if conn is not None:
            conn.close()
