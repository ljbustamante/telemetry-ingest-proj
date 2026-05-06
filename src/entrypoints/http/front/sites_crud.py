"""GET/POST /customers/{customer_id}/sites — PUT/DELETE /sites/{id} — admin CRUD."""

from __future__ import annotations

import logging
from typing import Any

import psycopg2.extras

from ....infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import cors_headers, error_detail, json_body, parse_event, response

logger = logging.getLogger(__name__)

_REQUIRED_POST = {"name"}
_ALLOWED_UPDATE = {"name", "address", "city", "region", "timezone"}


def _list_sites(event: dict[str, Any], customer_id: str | None) -> dict[str, Any]:
    if not customer_id:
        return error_detail(400, "customer_id requerido", event=event)

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, customer_id, name, address, city, region, timezone, created_at
            FROM sites
            WHERE customer_id = %s
            ORDER BY name
            """,
            (customer_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        return response(200, rows, event=event)
    finally:
        conn.close()


def _create_site(
    event: dict[str, Any], customer_id: str | None, body: dict[str, Any]
) -> dict[str, Any]:
    if not customer_id:
        return error_detail(400, "customer_id requerido", event=event)

    missing = _REQUIRED_POST - body.keys()
    if missing:
        return error_detail(422, f"Campos requeridos: {sorted(missing)}", event=event)

    name = str(body["name"]).strip()
    if not name:
        return error_detail(422, "name no puede estar vacio", event=event)

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # Verify customer exists
        cur.execute("SELECT 1 FROM customers WHERE id = %s", (customer_id,))
        if not cur.fetchone():
            return error_detail(404, "Cliente no encontrado", event=event)

        cur.execute(
            """
            INSERT INTO sites (customer_id, name, address, city, region, timezone)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, customer_id, name, address, city, region, timezone, created_at
            """,
            (
                customer_id,
                name,
                body.get("address"),
                body.get("city"),
                body.get("region"),
                body.get("timezone"),
            ),
        )
        row = dict(cur.fetchone())
        conn.commit()
        return response(201, row, event=event)
    except Exception as e:
        conn.rollback()
        logger.exception("create_site: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        conn.close()


def _update_site(
    event: dict[str, Any], site_id: str | None, body: dict[str, Any]
) -> dict[str, Any]:
    if not site_id:
        return error_detail(400, "id requerido", event=event)

    fields = {k: v for k, v in body.items() if k in _ALLOWED_UPDATE}
    if not fields:
        return error_detail(
            422,
            f"Ningún campo actualizable; permitidos: {sorted(_ALLOWED_UPDATE)}",
            event=event,
        )

    set_clause = ", ".join(f"{col} = %s" for col in fields)
    values = list(fields.values()) + [site_id]

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            f"""
            UPDATE sites SET {set_clause}
            WHERE id = %s
            RETURNING id, customer_id, name, address, city, region, timezone, created_at
            """,
            values,
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return error_detail(404, "Ubicación no encontrada", event=event)
        conn.commit()
        return response(200, dict(row), event=event)
    except Exception as e:
        conn.rollback()
        logger.exception("update_site: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        conn.close()


def _delete_site(event: dict[str, Any], site_id: str | None) -> dict[str, Any]:
    if not site_id:
        return error_detail(400, "id requerido", event=event)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM device_assignments WHERE site_id = %s AND unassigned_at IS NULL LIMIT 1",
            (site_id,),
        )
        if cur.fetchone():
            return error_detail(
                409,
                "No se puede eliminar: la ubicación tiene equipos asignados activos",
                event=event,
            )
        cur.execute("DELETE FROM sites WHERE id = %s", (site_id,))
        if cur.rowcount == 0:
            return error_detail(404, "Ubicación no encontrada", event=event)
        conn.commit()
        return {
            "statusCode": 204,
            "headers": {**cors_headers(event)},
            "body": "",
        }
    except Exception as e:
        conn.rollback()
        logger.exception("delete_site: %s", e)
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
    customer_id = p.get("customer_id")
    site_id = p.get("id")

    try:
        if method == "GET" and "/sites" in path and customer_id:
            return _list_sites(event, customer_id)
        if method == "POST" and "/sites" in path and customer_id:
            return _create_site(event, customer_id, json_body(body_str) or {})
        if method == "PUT" and site_id:
            return _update_site(event, site_id, json_body(body_str) or {})
        if method == "DELETE" and site_id:
            return _delete_site(event, site_id)
        return error_detail(405, "Metodo no permitido", event=event)
    except Exception as e:
        logger.exception("sites_crud: %s", e)
        return error_detail(500, "Error interno", event=event)
