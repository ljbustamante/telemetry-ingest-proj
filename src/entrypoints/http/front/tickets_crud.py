"""GET/PATCH/DELETE /tickets — docs/GUIA_LAMBDAS_AWS.txt (+ HTTP API v2 routing)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras

from ....infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import cors_headers, error_detail, json_body, parse_event, response

logger = logging.getLogger(__name__)

VALID_OUTCOMES = {"confirmed_failure", "false_positive"}
VALID_FAILURE_TYPES = {
    "cpu_thermal",
    "disk_io",
    "disk_filesystem",
    "bsod_disk",
    "battery",
    "other",
}

_LIST_SQL = """
    SELECT i.id,
           i.device_id,
           d.device_key,
           c.name AS customer_name,
           i.opened_at,
           i.closed_at,
           i.symptom AS issue_description,
           i.severity,
           i.notes,
           f.outcome,
           f.notes AS failure_type,
           CASE
             WHEN i.notes::text LIKE '%device_risk_v1%'
               OR i.notes::text LIKE '%"ml_auto"%' THEN 'sistema'
             ELSE 'manual'
           END AS technician,
           CASE COALESCE(mp.class_label, mp2.class_label)
             WHEN 'Alto' THEN 'HIGH'
             WHEN 'Medio' THEN 'MEDIUM'
             WHEN 'Bajo' THEN 'LOW'
             ELSE COALESCE(mp.class_label, mp2.class_label)
           END AS risk_bucket,
           COALESCE(mp.class_prob, mp2.class_prob) AS class_prob
    FROM incidents i
    JOIN devices d ON d.id = i.device_id
    JOIN customers c ON c.code = d.customer_code
    LEFT JOIN ml_feedback f ON f.incident_id = i.id
    LEFT JOIN ml_predictions mp ON mp.id = i.source_ml_prediction_id
    LEFT JOIN LATERAL (
        SELECT class_label, class_prob FROM ml_predictions
        WHERE device_id = i.device_id
        ORDER BY predicted_at DESC LIMIT 1
    ) mp2 ON true
    ORDER BY i.opened_at DESC
"""


def _list_tickets(event: dict[str, Any]) -> dict[str, Any]:
    query = event.get("queryStringParameters") or {}
    device_id = query.get("device_id") or None

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if device_id:
            sql = _LIST_SQL.replace(
                "ORDER BY i.opened_at DESC",
                "WHERE i.device_id = %s::uuid ORDER BY i.opened_at DESC",
            )
            cur.execute(sql, (device_id,))
        else:
            cur.execute(_LIST_SQL)
        rows = [dict(r) for r in cur.fetchall()]
        return response(200, rows, event=event)
    finally:
        conn.close()


def _close_ticket(
    event: dict[str, Any], ticket_id: str | None, body: dict[str, Any]
) -> dict[str, Any]:
    if not ticket_id:
        return error_detail(400, "ticket_id requerido", event=event)

    outcome = body.get("outcome")
    failure_type = body.get("failure_type")
    notes = body.get("notes", "")

    if outcome not in VALID_OUTCOMES:
        return error_detail(422, f"outcome debe ser: {VALID_OUTCOMES}", event=event)
    if failure_type and failure_type not in VALID_FAILURE_TYPES:
        return error_detail(422, f"failure_type debe ser: {VALID_FAILURE_TYPES}", event=event)

    fb_notes = failure_type if failure_type else (notes or "")

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE incidents SET closed_at = NOW(), notes = %s WHERE id = %s",
            (notes, ticket_id),
        )
        cur.execute("SELECT id FROM ml_feedback WHERE incident_id = %s", (ticket_id,))
        existing = cur.fetchone()
        if existing:
            cur.execute(
                """
                UPDATE ml_feedback
                SET outcome = %s, notes = %s
                WHERE incident_id = %s
                """,
                (outcome, fb_notes, ticket_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO ml_feedback (incident_id, outcome, notes)
                VALUES (%s, %s, %s)
                """,
                (ticket_id, outcome, fb_notes),
            )
        conn.commit()
        closed_at = datetime.now(timezone.utc).isoformat()
        return response(
            200, {"id": ticket_id, "outcome": outcome, "closed_at": closed_at}, event=event
        )
    except Exception as e:
        conn.rollback()
        logger.exception("close_ticket: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        conn.close()


def _delete_ticket(event: dict[str, Any], ticket_id: str | None) -> dict[str, Any]:
    if not ticket_id:
        return error_detail(400, "ticket_id requerido", event=event)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM ml_feedback WHERE incident_id = %s", (ticket_id,))
        if cur.fetchone():
            return error_detail(
                409,
                "No se puede eliminar un ticket cerrado — es Ground Truth del modelo ML",
                event=event,
            )
        cur.execute("DELETE FROM incidents WHERE id = %s", (ticket_id,))
        if cur.rowcount == 0:
            return error_detail(404, "Ticket no encontrado", event=event)
        conn.commit()
        return {
            "statusCode": 204,
            "headers": {**cors_headers(event)},
            "body": "",
        }
    except Exception as e:
        conn.rollback()
        logger.exception("delete_ticket: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        conn.close()


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, raw_path, params, _q, body_str = parse_event(event)
    if method == "OPTIONS":
        return response(200, {}, event=event)

    bad = require_auth(event)
    if bad:
        return bad

    # Normalize path (HTTP API v2 has no stage prefix on rawPath).
    path = (raw_path or "/").rstrip("/") or "/"
    ticket_id = (params or {}).get("ticket_id")

    try:
        if method == "GET" and path.endswith("/tickets") and "export" not in path:
            return _list_tickets(event)
        if method == "PATCH" and "/close" in path:
            body = json_body(body_str) or {}
            return _close_ticket(event, ticket_id, body)
        if method == "DELETE" and ticket_id and "/tickets/" in path:
            return _delete_ticket(event, ticket_id)
        return error_detail(405, "Metodo no permitido", event=event)
    except Exception as e:
        logger.exception("tickets_crud: %s", e)
        return error_detail(500, "Error interno", event=event)
