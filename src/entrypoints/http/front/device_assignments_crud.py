"""GET/POST /sites/{site_id}/device-assignments — PATCH /device-assignments/{id}/unassign."""

from __future__ import annotations

import logging
from typing import Any

import psycopg2.extras

from ....infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import cors_headers, error_detail, json_body, parse_event, response

logger = logging.getLogger(__name__)


def _list_assignments(event: dict[str, Any], site_id: str | None) -> dict[str, Any]:
    if not site_id:
        return error_detail(400, "site_id requerido", event=event)

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                da.id,
                da.device_id,
                da.site_id,
                da.assigned_at,
                da.unassigned_at,
                d.device_key,
                d.status AS device_status
            FROM device_assignments da
            JOIN devices d ON d.id = da.device_id
            WHERE da.site_id = %s
              AND da.unassigned_at IS NULL
            ORDER BY da.assigned_at DESC
            """,
            (site_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        return response(200, rows, event=event)
    finally:
        conn.close()


def _create_assignment(
    event: dict[str, Any], site_id: str | None, body: dict[str, Any]
) -> dict[str, Any]:
    if not site_id:
        return error_detail(400, "site_id requerido", event=event)

    device_id = body.get("device_id")
    if not device_id:
        return error_detail(422, "device_id requerido", event=event)

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Verify site and device exist
        cur.execute("SELECT 1 FROM sites WHERE id = %s", (site_id,))
        if not cur.fetchone():
            return error_detail(404, "Ubicación no encontrada", event=event)

        cur.execute("SELECT 1 FROM devices WHERE id = %s", (device_id,))
        if not cur.fetchone():
            return error_detail(404, "Equipo no encontrado", event=event)

        # Check device is not already assigned elsewhere
        cur.execute(
            "SELECT 1 FROM device_assignments WHERE device_id = %s AND unassigned_at IS NULL LIMIT 1",
            (device_id,),
        )
        if cur.fetchone():
            return error_detail(
                409,
                "El equipo ya tiene una asignación activa; desasígnalo primero",
                event=event,
            )

        # Insert assignment and update device's current site
        cur.execute(
            """
            INSERT INTO device_assignments (device_id, site_id, assigned_at)
            VALUES (%s, %s, NOW())
            RETURNING id, device_id, site_id, assigned_at, unassigned_at
            """,
            (device_id, site_id),
        )
        assignment = dict(cur.fetchone())

        cur.execute(
            "UPDATE devices SET current_site_id = %s WHERE id = %s",
            (site_id, device_id),
        )
        conn.commit()
        return response(201, assignment, event=event)
    except Exception as e:
        conn.rollback()
        logger.exception("create_assignment: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        conn.close()


def _unassign(event: dict[str, Any], assignment_id: str | None) -> dict[str, Any]:
    if not assignment_id:
        return error_detail(400, "id requerido", event=event)

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            UPDATE device_assignments
            SET unassigned_at = NOW()
            WHERE id = %s AND unassigned_at IS NULL
            RETURNING id, device_id, site_id, assigned_at, unassigned_at
            """,
            (assignment_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return error_detail(
                404,
                "Asignación no encontrada o ya desasignada",
                event=event,
            )
        conn.commit()
        return response(200, dict(row), event=event)
    except Exception as e:
        conn.rollback()
        logger.exception("unassign: %s", e)
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

    path = (raw_path or "/").rstrip("/") or "/"
    p = params or {}
    site_id = p.get("site_id")
    assignment_id = p.get("id")

    try:
        if method == "GET" and site_id:
            return _list_assignments(event, site_id)
        if method == "POST" and site_id:
            return _create_assignment(event, site_id, json_body(body_str) or {})
        if method == "PATCH" and assignment_id and "unassign" in path:
            return _unassign(event, assignment_id)
        return error_detail(405, "Metodo no permitido", event=event)
    except Exception as e:
        logger.exception("device_assignments_crud: %s", e)
        return error_detail(500, "Error interno", event=event)
