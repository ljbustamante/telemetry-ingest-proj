"""GET/POST/PUT/DELETE /customers — admin CRUD."""

from __future__ import annotations

import logging
from typing import Any

import psycopg2.extras

from ....infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import cors_headers, error_detail, json_body, parse_event, response

logger = logging.getLogger(__name__)

_LIST_SQL = """
    SELECT id, code, name, ruc, contact_email, created_at
    FROM customers
    ORDER BY name
"""

_REQUIRED_POST = {"code", "name"}


def _list_customers(event: dict[str, Any]) -> dict[str, Any]:
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(_LIST_SQL)
        rows = [dict(r) for r in cur.fetchall()]
        return response(200, rows, event=event)
    finally:
        conn.close()


def _create_customer(event: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    missing = _REQUIRED_POST - body.keys()
    if missing:
        return error_detail(422, f"Campos requeridos: {sorted(missing)}", event=event)

    code = str(body["code"]).strip()
    name = str(body["name"]).strip()
    ruc = body.get("ruc")
    contact_email = body.get("contact_email")

    if not code or not name:
        return error_detail(422, "code y name no pueden estar vacios", event=event)

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            INSERT INTO customers (code, name, ruc, contact_email)
            VALUES (%s, %s, %s, %s)
            RETURNING id, code, name, ruc, contact_email, created_at
            """,
            (code, name, ruc, contact_email),
        )
        row = dict(cur.fetchone())
        conn.commit()
        return response(201, row, event=event)
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return error_detail(409, f"Ya existe un cliente con code '{code}'", event=event)
    except Exception as e:
        conn.rollback()
        logger.exception("create_customer: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        conn.close()


def _update_customer(
    event: dict[str, Any], customer_id: str | None, body: dict[str, Any]
) -> dict[str, Any]:
    if not customer_id:
        return error_detail(400, "id requerido", event=event)

    allowed = {"code", "name", "ruc", "contact_email"}
    fields = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        return error_detail(422, f"Ningún campo actualizable; permitidos: {sorted(allowed)}", event=event)

    set_clause = ", ".join(f"{col} = %s" for col in fields)
    values = list(fields.values()) + [customer_id]

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            f"""
            UPDATE customers SET {set_clause}
            WHERE id = %s
            RETURNING id, code, name, ruc, contact_email, created_at
            """,
            values,
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return error_detail(404, "Cliente no encontrado", event=event)
        conn.commit()
        return response(200, dict(row), event=event)
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return error_detail(409, "El code ya existe en otro cliente", event=event)
    except Exception as e:
        conn.rollback()
        logger.exception("update_customer: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        conn.close()


def _delete_customer(event: dict[str, Any], customer_id: str | None) -> dict[str, Any]:
    if not customer_id:
        return error_detail(400, "id requerido", event=event)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM sites WHERE customer_id = %s LIMIT 1", (customer_id,))
        if cur.fetchone():
            return error_detail(
                409,
                "No se puede eliminar: el cliente tiene ubicaciones asociadas",
                event=event,
            )
        cur.execute("DELETE FROM customers WHERE id = %s", (customer_id,))
        if cur.rowcount == 0:
            return error_detail(404, "Cliente no encontrado", event=event)
        conn.commit()
        return {
            "statusCode": 204,
            "headers": {**cors_headers(event)},
            "body": "",
        }
    except Exception as e:
        conn.rollback()
        logger.exception("delete_customer: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        conn.close()


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, _raw_path, params, _q, body_str = parse_event(event)
    if method == "OPTIONS":
        return response(200, {}, event=event)

    bad = require_auth(event)
    if bad:
        return bad

    customer_id = (params or {}).get("id")

    try:
        if method == "GET":
            return _list_customers(event)
        if method == "POST":
            return _create_customer(event, json_body(body_str) or {})
        if method == "PUT" and customer_id:
            return _update_customer(event, customer_id, json_body(body_str) or {})
        if method == "DELETE" and customer_id:
            return _delete_customer(event, customer_id)
        return error_detail(405, "Metodo no permitido", event=event)
    except Exception as e:
        logger.exception("customers_crud: %s", e)
        return error_detail(500, "Error interno", event=event)
