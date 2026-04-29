"""HTTP API Gateway v2 helpers and CORS (docs/GUIA_LAMBDAS_AWS.txt)."""

from __future__ import annotations

import base64
import json
from typing import Any, Mapping

from ..cors import cors_headers

__all__ = [
    "cors_headers",
    "response",
    "error_detail",
    "parse_event",
    "json_body",
]


def response(
    status: int,
    body: Any,
    *,
    event: dict[str, Any] | None = None,
    json_default: Any = str,
    extra_headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    headers = {**cors_headers(event), "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    payload = body if isinstance(body, str) else json.dumps(body, default=json_default)
    return {"statusCode": status, "headers": headers, "body": payload}


def error_detail(
    status: int, message: str, *, event: dict[str, Any] | None = None
) -> dict[str, Any]:
    return response(status, {"detail": message}, event=event)


def parse_event(
    event: dict[str, Any],
) -> tuple[str, str, dict[str, str] | None, dict[str, str] | None, str | None]:
    """Return (method, raw_path, path_params, query_params, body_str)."""
    ctx = event.get("requestContext") or {}
    http = ctx.get("http") or {}
    method = (http.get("method") or event.get("httpMethod") or "GET").upper()
    raw_path = event.get("rawPath") or event.get("path") or "/"
    path_params = event.get("pathParameters") or None
    query = event.get("queryStringParameters") or None
    body = event.get("body")
    if event.get("isBase64Encoded") and isinstance(body, str):
        body = base64.b64decode(body).decode("utf-8", errors="replace")
    return method, raw_path, path_params, query, body


def json_body(body_str: str | None) -> dict[str, Any] | None:
    if not body_str:
        return None
    try:
        o = json.loads(body_str)
        return o if isinstance(o, dict) else None
    except json.JSONDecodeError:
        return None
