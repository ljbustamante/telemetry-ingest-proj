"""POST /auth/login — docs/GUIA_LAMBDAS_AWS.txt."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import psycopg2

from ...infrastructure.db.connection import get_connection
from .http_utils import error_detail, json_body, parse_event, response
from .jwt_auth import make_jwt

logger = logging.getLogger(__name__)


def _verify(pwd: str, hashed: str | None) -> bool:
    digest = hashlib.sha256(pwd.encode()).hexdigest()
    return hmac.compare_digest(digest, hashed or "")


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, _path, _pp, _q, body_str = parse_event(event)
    if method == "OPTIONS":
        return response(200, {})
    if method != "POST":
        return error_detail(405, "Metodo no permitido")

    body = json_body(body_str) or {}
    email = str(body.get("email", "")).strip().lower()
    pwd = str(body.get("password", ""))

    if not email or not pwd:
        return error_detail(422, "email y password requeridos")

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, role, password_hash FROM users WHERE email = %s",
            (email,),
        )
        row = cur.fetchone()
        if not row or not _verify(pwd, row[3]):
            return error_detail(401, "Credenciales invalidas")

        token = make_jwt({"sub": str(row[0]), "email": email, "role": row[2]})
        return response(
            200,
            {
                "token": token,
                "user": {
                    "id": str(row[0]),
                    "email": email,
                    "name": row[1],
                    "role": row[2],
                },
            },
        )
    except Exception as e:
        logger.exception("login: %s", e)
        return error_detail(500, "Error interno")
    finally:
        if conn is not None:
            conn.close()
