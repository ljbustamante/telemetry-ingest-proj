"""GET /devices/{device_id}/metrics?hours=24 — docs/GUIA_LAMBDAS_AWS.txt."""

from __future__ import annotations

import logging
from typing import Any

import psycopg2.extras

from ...infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import error_detail, parse_event, response

logger = logging.getLogger(__name__)


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, _path, path_params, query, _body = parse_event(event)
    if method == "OPTIONS":
        return response(200, {})
    if method != "GET":
        return error_detail(405, "Metodo no permitido")
    bad = require_auth(event)
    if bad:
        return bad

    device_id = (path_params or {}).get("device_id")
    if not device_id:
        return error_detail(400, "device_id requerido")

    hours = int((query or {}).get("hours", 24))
    hours = min(max(hours, 1), 168)

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                date_trunc('hour', event_ts) AS event_ts,
                AVG(cpu_pct) AS cpu_pct,
                AVG(cpu_temp_c) AS cpu_temp_c,
                MAX(cpu_temp_c_max) AS cpu_temp_c_max,
                AVG(mem_used_pct) AS mem_used_pct,
                AVG(battery_charge_pct) AS battery_charge_pct,
                AVG(risk_score) AS risk_score
            FROM readings_curated_parent
            WHERE device_id = %s::uuid
              AND event_ts > NOW() - (%s || ' hours')::interval
            GROUP BY date_trunc('hour', event_ts)
            ORDER BY event_ts ASC
            """,
            (device_id, str(hours)),
        )
        rows = [dict(r) for r in cur.fetchall()]
        return response(200, rows)
    except Exception as e:
        logger.exception("device_metrics: %s", e)
        return error_detail(500, "Error interno")
    finally:
        if conn is not None:
            conn.close()
