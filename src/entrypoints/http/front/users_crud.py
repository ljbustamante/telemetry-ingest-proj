"""GET/POST/PUT/PATCH/DELETE /users — solo superadmin."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import psycopg2.extras

from ....infrastructure.db.connection import get_connection
from .common import require_superadmin
from .http_utils import cors_headers, error_detail, json_body, parse_event, response

logger = logging.getLogger(__name__)

VALID_ROLES = {"tecnico", "analista", "admin", "superadmin"}

_SELECT_COLS = "id, name, email, role, active, created_at"


def _hash_password(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


def _list_users(event: dict[str, Any]) -> dict[str, Any]:
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(f"SELECT {_SELECT_COLS} FROM users ORDER BY name")
        rows = [dict(r) for r in cur.fetchall()]
        return response(200, rows, event=event)
    finally:
        conn.close()


def _create_user(event: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    name = str(body.get("name", "")).strip()
    email = str(body.get("email", "")).strip().lower()
    role = str(body.get("role", "")).strip()
    password = str(body.get("password", "")).strip()

    missing = [f for f, v in [("name", name), ("email", email), ("role", role), ("password", password)] if not v]
    if missing:
        return error_detail(422, f"Campos requeridos faltantes: {missing}", event=event)
    if role not in VALID_ROLES:
        return error_detail(422, f"role debe ser uno de: {sorted(VALID_ROLES)}", event=event)
    if "@" not in email:
        return error_detail(422, "email inválido", event=event)

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            f"""
            INSERT INTO users (name, email, role, password_hash)
            VALUES (%s, %s, %s, %s)
            RETURNING {_SELECT_COLS}
            """,
            (name, email, role, _hash_password(password)),
        )
        row = dict(cur.fetchone())
        conn.commit()
        return response(201, row, event=event)
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return error_detail(409, f"Ya existe un usuario con email '{email}'", event=event)
    except Exception as e:
        conn.rollback()
        logger.exception("create_user: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        conn.close()


def _update_user(
    event: dict[str, Any], user_id: str | None, body: dict[str, Any]
) -> dict[str, Any]:
    if not user_id:
        return error_detail(400, "id requerido", event=event)

    fields: dict[str, Any] = {}

    if "name" in body and str(body["name"]).strip():
        fields["name"] = str(body["name"]).strip()
    if "email" in body and str(body["email"]).strip():
        email = str(body["email"]).strip().lower()
        if "@" not in email:
            return error_detail(422, "email inválido", event=event)
        fields["email"] = email
    if "role" in body:
        role = str(body["role"]).strip()
        if role not in VALID_ROLES:
            return error_detail(422, f"role debe ser uno de: {sorted(VALID_ROLES)}", event=event)
        fields["role"] = role
    pwd = str(body.get("password", "")).strip()
    if pwd:
        fields["password_hash"] = _hash_password(pwd)

    if not fields:
        return error_detail(422, "No se proporcionó ningún campo actualizable", event=event)

    set_clause = ", ".join(f"{col} = %s" for col in fields)
    values = list(fields.values()) + [user_id]

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            f"UPDATE users SET {set_clause} WHERE id = %s RETURNING {_SELECT_COLS}",
            values,
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return error_detail(404, "Usuario no encontrado", event=event)
        conn.commit()
        return response(200, dict(row), event=event)
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return error_detail(409, "El email ya está en uso por otro usuario", event=event)
    except Exception as e:
        conn.rollback()
        logger.exception("update_user: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        conn.close()


def _set_active(
    event: dict[str, Any], user_id: str | None, body: dict[str, Any]
) -> dict[str, Any]:
    if not user_id:
        return error_detail(400, "id requerido", event=event)
    if "active" not in body:
        return error_detail(422, "Campo 'active' requerido", event=event)

    active = bool(body["active"])

    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            f"UPDATE users SET active = %s WHERE id = %s RETURNING {_SELECT_COLS}",
            (active, user_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return error_detail(404, "Usuario no encontrado", event=event)
        conn.commit()
        return response(200, dict(row), event=event)
    except Exception as e:
        conn.rollback()
        logger.exception("set_active: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        conn.close()


def _delete_user(event: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    if not user_id:
        return error_detail(400, "id requerido", event=event)

    conn = get_connection()
    try:
        cur = conn.cursor()
        # Guard: do not delete the last active superadmin
        cur.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'superadmin' AND active = true",
        )
        superadmin_count = cur.fetchone()[0]

        cur.execute("SELECT role, active FROM users WHERE id = %s", (user_id,))
        target = cur.fetchone()
        if not target:
            return error_detail(404, "Usuario no encontrado", event=event)

        if target[0] == "superadmin" and target[1] and superadmin_count <= 1:
            return error_detail(
                409,
                "No se puede eliminar el único superadmin activo",
                event=event,
            )

        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        return {
            "statusCode": 204,
            "headers": {**cors_headers(event)},
            "body": "",
        }
    except Exception as e:
        conn.rollback()
        logger.exception("delete_user: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        conn.close()


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, raw_path, params, _q, body_str = parse_event(event)
    if method == "OPTIONS":
        return response(200, {}, event=event)

    bad = require_superadmin(event)
    if bad:
        return bad

    path = (raw_path or "/").rstrip("/") or "/"
    p = params or {}
    user_id = p.get("id")

    try:
        if method == "GET" and path.endswith("/users"):
            return _list_users(event)
        if method == "POST" and path.endswith("/users"):
            return _create_user(event, json_body(body_str) or {})
        if method == "PUT" and user_id:
            return _update_user(event, user_id, json_body(body_str) or {})
        if method == "PATCH" and user_id and "active" in path:
            return _set_active(event, user_id, json_body(body_str) or {})
        if method == "DELETE" and user_id:
            return _delete_user(event, user_id)
        return error_detail(405, "Metodo no permitido", event=event)
    except Exception as e:
        logger.exception("users_crud: %s", e)
        return error_detail(500, "Error interno", event=event)
