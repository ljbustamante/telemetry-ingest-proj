from __future__ import annotations

import json

import src.entrypoints.aws.alert_digest_handler as handler_mod
from src.entrypoints.aws.alert_digest_handler import handle

_DIGEST_RESULT = {
    "skipped": False,
    "sent": True,
    "alerts_count": 2,
    "incidents_count": 1,
    "recipients": ["ops@example.com"],
}


def _http_event(method: str, path: str, headers: dict | None = None) -> dict:
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
        "headers": headers or {},
    }


def test_eventbridge_trigger_runs_digest_and_returns_200(monkeypatch):
    monkeypatch.setattr(handler_mod, "run_alert_digest", lambda: _DIGEST_RESULT, raising=True)
    res = handle({"source": "aws.events"}, None)
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["sent"] is True
    assert body["alerts_count"] == 2


def test_eventbridge_trigger_on_error_returns_500(monkeypatch):
    def _boom():
        raise RuntimeError("db connection failed")

    monkeypatch.setattr(handler_mod, "run_alert_digest", _boom, raising=True)
    res = handle({"source": "aws.events"}, None)
    assert res["statusCode"] == 500
    body = json.loads(res["body"])
    assert "error" in body


def test_get_health_check_returns_200():
    ev = _http_event("GET", "/internal/alert-digest")
    res = handle(ev, None)
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["ok"] is True
    assert body["service"] == "alert-digest"


def test_post_run_without_secret_configured_returns_503(monkeypatch):
    monkeypatch.delenv("ALERT_DIGEST_SECRET", raising=False)
    ev = _http_event("POST", "/internal/alert-digest/run")
    res = handle(ev, None)
    assert res["statusCode"] == 503


def test_post_run_wrong_key_returns_403(monkeypatch):
    monkeypatch.setenv("ALERT_DIGEST_SECRET", "correct-secret")
    ev = _http_event("POST", "/internal/alert-digest/run", headers={"x-internal-key": "wrong"})
    res = handle(ev, None)
    assert res["statusCode"] == 403


def test_post_run_correct_key_invokes_digest(monkeypatch):
    secret = "my-secret"
    monkeypatch.setenv("ALERT_DIGEST_SECRET", secret)
    monkeypatch.setattr(handler_mod, "run_alert_digest", lambda: _DIGEST_RESULT, raising=True)
    ev = _http_event("POST", "/internal/alert-digest/run", headers={"x-internal-key": secret})
    res = handle(ev, None)
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["sent"] is True


def test_post_run_error_with_correct_key_returns_500(monkeypatch):
    secret = "my-secret"
    monkeypatch.setenv("ALERT_DIGEST_SECRET", secret)

    def _boom():
        raise RuntimeError("failure")

    monkeypatch.setattr(handler_mod, "run_alert_digest", _boom, raising=True)
    ev = _http_event("POST", "/internal/alert-digest/run", headers={"x-internal-key": secret})
    res = handle(ev, None)
    assert res["statusCode"] == 500


def test_unknown_path_returns_404():
    ev = _http_event("GET", "/internal/unknown-endpoint")
    res = handle(ev, None)
    assert res["statusCode"] == 404
