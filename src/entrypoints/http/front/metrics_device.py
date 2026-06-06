"""GET /devices/{device_id}/metrics?hours=24 — docs/GUIA_LAMBDAS_AWS.txt."""

from __future__ import annotations

import logging
from typing import Any

import psycopg2.extras

from ....infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import error_detail, parse_event, response

logger = logging.getLogger(__name__)


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, _path, path_params, query, _body = parse_event(event)
    if method == "OPTIONS":
        return response(200, {}, event=event)
    if method != "GET":
        return error_detail(405, "Metodo no permitido", event=event)
    bad = require_auth(event)
    if bad:
        return bad

    device_id = (path_params or {}).get("device_id")
    if not device_id:
        return error_detail(400, "device_id requerido", event=event)

    hours = int((query or {}).get("hours", 24))
    hours = min(max(hours, 1), 168)

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Snapshot: lectura más reciente con todos los campos para el resumen
        cur.execute(
            """
            SELECT
                r.event_ts,
                r.cpu_pct,
                r.cpu_temp_c,
                r.cpu_temp_c_max,
                r.mem_used_pct,
                r.battery_charge_pct,
                r.battery_status,
                r.battery_cycle_count,
                (
                    SELECT (payload->'Derived'->>'DiskHealthScore')::numeric
                    FROM readings_raw_parent
                    WHERE device_id = %s::uuid
                    ORDER BY event_ts DESC LIMIT 1
                ) AS disk_health_score
            FROM readings_curated_parent r
            WHERE r.device_id = %s::uuid
            ORDER BY r.event_ts DESC
            LIMIT 1
            """,
            (device_id, device_id),
        )
        snapshot_row = cur.fetchone()
        snapshot = dict(snapshot_row) if snapshot_row else None

        # Series: promedio horario para la gráfica de tendencias (últimas N horas)
        cur.execute(
            """
            SELECT
                date_trunc('hour', event_ts) AS event_ts,
                AVG(cpu_pct)            AS cpu_pct,
                AVG(cpu_temp_c)         AS cpu_temp_c,
                MAX(cpu_temp_c_max)     AS cpu_temp_c_max,
                AVG(mem_used_pct)       AS mem_used_pct,
                AVG(battery_charge_pct) AS battery_charge_pct,
                AVG(risk_score)         AS risk_score
            FROM readings_curated_parent
            WHERE device_id = %s::uuid
              AND event_ts > NOW() - (%s || ' hours')::interval
            GROUP BY date_trunc('hour', event_ts)
            ORDER BY event_ts ASC
            """,
            (device_id, str(hours)),
        )
        series = [dict(r) for r in cur.fetchall()]

        return response(200, {"snapshot": snapshot, "series": series}, event=event)
    except Exception as e:
        logger.exception("device_metrics: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        if conn is not None:
            conn.close()
