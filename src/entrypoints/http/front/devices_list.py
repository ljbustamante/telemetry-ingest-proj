"""GET /devices — docs/GUIA_LAMBDAS_AWS.txt (risk_bucket HIGH/MEDIUM/LOW for front)."""

from __future__ import annotations

import logging
from typing import Any

import psycopg2.extras

from ...infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import error_detail, parse_event, response

logger = logging.getLogger(__name__)

_SQL = """
    SELECT
        d.id,
        d.device_key,
        d.customer_code,
        d.status,
        d.last_seen_at,
        d.first_seen_at,
        d.tags,
        c.name AS customer_name,
        s.name AS site_name,
        r.cpu_pct,
        r.cpu_temp_c,
        r.battery_charge_pct,
        r.risk_score,
        CASE r.risk_bucket
            WHEN 'Alto' THEN 'HIGH'
            WHEN 'Medio' THEN 'MEDIUM'
            WHEN 'Bajo' THEN 'LOW'
            ELSE r.risk_bucket
        END AS risk_bucket,
        r.mem_used_pct,
        da.id IS NOT NULL AS assigned
    FROM devices d
    LEFT JOIN customers c ON c.code = d.customer_code
    LEFT JOIN sites s ON s.id = d.current_site_id
    LEFT JOIN LATERAL (
        SELECT cpu_pct, cpu_temp_c, battery_charge_pct,
               risk_score, risk_bucket, mem_used_pct
        FROM readings_curated_parent
        WHERE device_id = d.id
        ORDER BY event_ts DESC LIMIT 1
    ) r ON true
    LEFT JOIN LATERAL (
        SELECT id FROM device_assignments
        WHERE device_id = d.id AND unassigned_at IS NULL
        LIMIT 1
    ) da ON true
    WHERE d.status != 'RETIRED'
    ORDER BY r.risk_score DESC NULLS LAST
"""


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, _path, _pp, _q, _body = parse_event(event)
    if method == "OPTIONS":
        return response(200, {}, event=event)
    if method != "GET":
        return error_detail(405, "Metodo no permitido", event=event)
    bad = require_auth(event)
    if bad:
        return bad

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(_SQL)
        rows = [dict(r) for r in cur.fetchall()]
        return response(200, rows, event=event)
    except Exception as e:
        logger.exception("list_devices: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        if conn is not None:
            conn.close()
