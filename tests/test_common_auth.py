from __future__ import annotations

import json

from src.entrypoints.http.front.common import lower_headers, require_auth, require_superadmin
from src.entrypoints.http.front.jwt_auth import make_jwt

_SECRET = "test-secret"


def _auth_event(role: str = "admin") -> dict:
    token = make_jwt({"sub": "user-1", "role": role}, secret=_SECRET)
    return {"headers": {"Authorization": f"Bearer {token}"}}


def test_lower_headers_lowercases_all_keys():
    result = lower_headers({"headers": {"Content-Type": "application/json", "Authorization": "Bearer x"}})
    assert "content-type" in result
    assert "authorization" in result


def test_lower_headers_empty_event():
    assert lower_headers({}) == {}


def test_lower_headers_skips_none_values():
    result = lower_headers({"headers": {"X-Foo": None, "X-Bar": "val"}})
    assert "x-foo" not in result
    assert result["x-bar"] == "val"


def test_require_auth_valid_jwt_returns_none(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    assert require_auth(_auth_event()) is None


def test_require_auth_no_token_returns_401(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    result = require_auth({"headers": {}})
    assert result is not None
    assert result["statusCode"] == 401


def test_require_auth_invalid_token_returns_401(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    result = require_auth({"headers": {"Authorization": "Bearer bad.token.here"}})
    assert result is not None
    assert result["statusCode"] == 401


def test_require_superadmin_superadmin_returns_none(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    assert require_superadmin(_auth_event(role="superadmin")) is None


def test_require_superadmin_regular_admin_returns_403(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    result = require_superadmin(_auth_event(role="admin"))
    assert result is not None
    assert result["statusCode"] == 403


def test_require_superadmin_no_token_returns_401(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    result = require_superadmin({"headers": {}})
    assert result is not None
    assert result["statusCode"] == 401
