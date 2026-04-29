"""GET /dashboard/summary — docs/GUIA_LAMBDAS_AWS.txt."""

from __future__ import annotations

import logging
import os
from typing import Any

import psycopg2.extras

from ....infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import error_detail, parse_event, response

logger = logging.getLogger(__name__)


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, _path, _pp, _q, _body = parse_event(event)
    if method == "OPTIONS":
        return response(200, {}, event=event)
    if method != "GET":
        return error_detail(405, "Metodo no permitido", event=event)
    bad = require_auth(event)
    if bad:
        return bad

    threshold = float(os.environ.get("AUTO_TICKET_THRESHOLD", "0.72"))

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE d.status = 'ACTIVE') AS total_devices,
                COUNT(*) FILTER (
                    WHERE d.status = 'ACTIVE' AND r.risk_bucket = 'Alto'
                ) AS high_risk_devices,
                COUNT(*) FILTER (
                    WHERE d.status = 'ACTIVE' AND r.risk_bucket = 'Medio'
                ) AS medium_risk_devices,
                COUNT(*) FILTER (
                    WHERE d.status = 'ACTIVE' AND r.risk_bucket = 'Bajo'
                ) AS low_risk_devices
            FROM devices d
            LEFT JOIN LATERAL (
                SELECT risk_bucket FROM readings_curated_parent
                WHERE device_id = d.id ORDER BY event_ts DESC LIMIT 1
            ) r ON true
            """
        )
        counts = dict(cur.fetchone() or {})

        cur.execute(
            """
            SELECT COUNT(*) AS active_alerts FROM ml_predictions
            WHERE predicted_at > NOW() - INTERVAL '24 hours'
              AND (
                class_label IN ('FAILURE', 'HIGH')
                OR class_label = 'Alto'
                OR (class_label IN ('MEDIUM', 'Medio') AND class_prob >= %s)
              )
            """,
            (threshold,),
        )
        alerts = (cur.fetchone() or {}).get("active_alerts", 0)

        cur.execute(
            """
            SELECT COUNT(*) AS new_today FROM devices
            WHERE first_seen_at > NOW() - INTERVAL '24 hours'
            """
        )
        new_today = (cur.fetchone() or {}).get("new_today", 0)

        return response(
            200,
            {
                **counts,
                "high_risk_devices": counts.get("high_risk_devices", 0),
                "medium_risk_devices": counts.get("medium_risk_devices", 0),
                "low_risk_devices": counts.get("low_risk_devices", 0),
                "active_alerts": alerts,
                "new_today": new_today,
            },
            event=event,
        )
    except Exception as e:
        logger.exception("dashboard_summary: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        if conn is not None:
            conn.close()
