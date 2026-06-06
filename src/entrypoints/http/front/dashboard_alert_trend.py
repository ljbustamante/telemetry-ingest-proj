"""GET /dashboard/alert-trend — conteo de devices ACTIVE por nivel de riesgo por ejecución de mlRiskJob."""

from __future__ import annotations

import logging
from typing import Any

import psycopg2.extras

from ....infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import error_detail, parse_event, response

logger = logging.getLogger(__name__)

_SQL = """
SELECT
    jr.started_at                                                          AS run_ts,
    COUNT(*) FILTER (WHERE p.class_label IN ('Alto',  'HIGH'))            AS high,
    COUNT(*) FILTER (WHERE p.class_label IN ('Medio', 'MEDIUM'))          AS medium,
    COUNT(*) FILTER (WHERE p.class_label IN ('Bajo',  'LOW'))             AS low
FROM ml_job_runs jr
JOIN ml_predictions p  ON p.job_run_id = jr.id
JOIN devices d         ON d.id = p.device_id AND d.status = 'ACTIVE'
WHERE jr.status      = 'completed'
  AND jr.started_at >= NOW() - (%s * INTERVAL '1 day')
GROUP BY jr.id, jr.started_at
ORDER BY jr.started_at ASC
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
                "date": dict(r)["run_ts"].strftime("%d %b %H:%M"),
                "high":   int(dict(r)["high"]   or 0),
                "medium": int(dict(r)["medium"] or 0),
                "low":    int(dict(r)["low"]    or 0),
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
