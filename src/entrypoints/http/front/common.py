"""Shared auth and header normalization for dashboard Lambdas."""

from __future__ import annotations

from typing import Any

from .http_utils import error_detail, parse_event
from .jwt_auth import bearer_claims


def lower_headers(event: dict[str, Any]) -> dict[str, str]:
    raw = event.get("headers") or {}
    return {str(k).lower(): str(v) for k, v in raw.items() if v is not None}


def require_auth(event: dict[str, Any]) -> dict[str, Any] | None:
    """Return None if OK; otherwise a Lambda response dict (401)."""
    claims = bearer_claims(lower_headers(event))
    if not claims or not claims.get("sub"):
        return error_detail(401, "No autorizado", event=event)
    return None
