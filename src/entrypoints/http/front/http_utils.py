"""HTTP API Gateway v2 helpers and CORS (docs/GUIA_LAMBDAS_AWS.txt)."""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Mapping

# Browsers sending Authorization / JSON trigger preflight; include common request headers.
_BASE_CORS = {
    "Access-Control-Allow-Headers": (
        "Content-Type,Authorization,Accept,Origin,X-Requested-With"
    ),
    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
}


def _origin_from_event(event: dict[str, Any] | None) -> str | None:
    if not event:
        return None
    raw = event.get("headers") or {}
    for k, v in raw.items():
        if str(k).lower() == "origin" and v is not None:
            if isinstance(v, list):
                return str(v[0]) if v else None
            return str(v)
    return None


def cors_headers(event: dict[str, Any] | None = None) -> dict[str, str]:
    """
    CORS headers for Lambda proxy responses.

    If CORS_ALLOWED_ORIGINS is unset or '*', use Access-Control-Allow-Origin: *.
    If set to a comma-separated list and the request Origin matches, echo that
    origin and set Access-Control-Allow-Credentials: true (needed when the
    browser uses fetch/axios with credentials and * is not allowed).
    """
    out: dict[str, str] = dict(_BASE_CORS)
    allowed_env = (os.environ.get("CORS_ALLOWED_ORIGINS") or "*").strip()
    origin_req = _origin_from_event(event)
    if allowed_env == "*" or not allowed_env:
        out["Access-Control-Allow-Origin"] = "*"
        return out
    allow_list = [x.strip() for x in allowed_env.split(",") if x.strip()]
    if origin_req and origin_req in allow_list:
        out["Access-Control-Allow-Origin"] = origin_req
        out["Access-Control-Allow-Credentials"] = "true"
        out["Vary"] = "Origin"
        return out
    out["Access-Control-Allow-Origin"] = "*"
    return out


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
