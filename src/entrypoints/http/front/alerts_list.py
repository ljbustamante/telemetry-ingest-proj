"""GET /alerts — docs/GUIA_LAMBDAS_AWS.txt (incl. Spanish class_label)."""

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
        p.id,
        p.device_id,
        d.device_key,
        c.name AS customer_name,
        CASE p.class_label
            WHEN 'Alto' THEN 'HIGH'
            WHEN 'Medio' THEN 'MEDIUM'
            WHEN 'Bajo' THEN 'LOW'
            ELSE p.class_label
        END AS risk_level,
        p.class_prob,
        p.eta_minutes,
        p.predicted_at,
        p.features_ref
    FROM ml_predictions p
    JOIN devices d ON d.id = p.device_id
    JOIN customers c ON c.code = d.customer_code
    WHERE p.class_label IN ('HIGH', 'MEDIUM', 'FAILURE', 'Alto', 'Medio')
      AND p.predicted_at > NOW() - INTERVAL '24 hours'
    ORDER BY p.class_prob DESC
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
        logger.exception("list_alerts: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        if conn is not None:
            conn.close()
