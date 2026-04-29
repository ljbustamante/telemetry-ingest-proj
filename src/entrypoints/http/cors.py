"""CORS headers for any Lambda behind API Gateway HTTP API (shared by front + internal HTTP)."""

from __future__ import annotations

import os
from typing import Any

_BASE_CORS = {
    "Access-Control-Allow-Headers": (
        "Content-Type,Authorization,Accept,Origin,X-Requested-With,X-Internal-Key"
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
    If CORS_ALLOWED_ORIGINS is unset or '*', use Access-Control-Allow-Origin: *.
    If set to a comma-separated list and the request Origin matches, echo that
    origin and set Access-Control-Allow-Credentials: true.
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
