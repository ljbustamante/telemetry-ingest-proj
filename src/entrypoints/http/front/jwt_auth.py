"""HS256 JWT matching docs/GUIA_LAMBDAS_AWS.txt login."""

from __future__ import annotations

import base64
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_jwt(payload: dict[str, Any], secret: str | None = None) -> str:
    """Same construction as GUIA: header/body b64url, HMAC-SHA256 over header.body."""
    key = secret or os.environ.get("JWT_SECRET") or ""
    payload = {**payload}
    payload["exp"] = int((datetime.now(timezone.utc) + timedelta(hours=8)).timestamp())
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
    msg = header + b"." + body
    sig = hmac.new(key.encode(), msg, hashlib.sha256).digest()
    return f"{header.decode()}.{body.decode()}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"


def verify_jwt(token: str, secret: str | None = None) -> dict[str, Any] | None:
    key = secret or os.environ.get("JWT_SECRET") or ""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header_b, body_b, sig_b = parts
    msg = f"{header_b}.{body_b}".encode("ascii")
    expected = hmac.new(key.encode(), msg, hashlib.sha256).digest()
    try:
        got = _b64url_decode(sig_b)
    except Exception:
        return None
    if not hmac.compare_digest(expected, got):
        return None
    try:
        pl = json.loads(_b64url_decode(body_b).decode("utf-8"))
    except Exception:
        return None
    exp = pl.get("exp")
    if exp is not None and int(exp) < int(datetime.now(timezone.utc).timestamp()):
        return None
    return pl


def bearer_claims(event_headers: dict[str, str] | None) -> dict[str, Any] | None:
    if not event_headers:
        return None
    auth = event_headers.get("authorization") or event_headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    return verify_jwt(token)
