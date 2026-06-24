from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from src.entrypoints.http.front.jwt_auth import bearer_claims, make_jwt, verify_jwt

_SECRET = "test-secret-key"


def test_make_and_verify_roundtrip():
    token = make_jwt({"sub": "user-1", "role": "admin"}, secret=_SECRET)
    claims = verify_jwt(token, secret=_SECRET)
    assert claims is not None
    assert claims["sub"] == "user-1"
    assert claims["role"] == "admin"


def test_verify_wrong_secret_returns_none():
    token = make_jwt({"sub": "user-1"}, secret=_SECRET)
    assert verify_jwt(token, secret="wrong-secret") is None


def test_verify_malformed_token_returns_none():
    assert verify_jwt("not.valid", secret=_SECRET) is None
    assert verify_jwt("", secret=_SECRET) is None


def test_verify_expired_token_returns_none():
    payload = {"sub": "user-1", "exp": int(time.time()) - 10}
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
    msg = header + b"." + body
    sig = hmac.new(_SECRET.encode(), msg, hashlib.sha256).digest()
    token = f"{header.decode()}.{body.decode()}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"
    assert verify_jwt(token, secret=_SECRET) is None


def test_verify_token_has_exp_field():
    token = make_jwt({"sub": "user-1"}, secret=_SECRET)
    claims = verify_jwt(token, secret=_SECRET)
    assert "exp" in claims
    assert claims["exp"] > int(time.time())


def test_bearer_claims_extracts_from_authorization_header(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    token = make_jwt({"sub": "user-1"}, secret=_SECRET)
    claims = bearer_claims({"Authorization": f"Bearer {token}"})
    assert claims is not None
    assert claims["sub"] == "user-1"


def test_bearer_claims_lowercase_header_key(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    token = make_jwt({"sub": "user-2"}, secret=_SECRET)
    claims = bearer_claims({"authorization": f"Bearer {token}"})
    assert claims is not None
    assert claims["sub"] == "user-2"


def test_bearer_claims_missing_header_returns_none():
    assert bearer_claims({}) is None
    assert bearer_claims(None) is None


def test_bearer_claims_non_bearer_scheme_returns_none():
    assert bearer_claims({"Authorization": "Basic dXNlcjpwYXNz"}) is None
