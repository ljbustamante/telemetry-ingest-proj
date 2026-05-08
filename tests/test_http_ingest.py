from __future__ import annotations

import json

from src.entrypoints.http import handlers

from .conftest import make_http_event


def test_http_ingest_health_get_returns_ok(monkeypatch):
    ev = make_http_event("GET", "/health")
    res = handlers.http_ingest(ev, None)
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["ok"] is True


def test_http_ingest_post_publishes_to_sqs(monkeypatch):
    called = {}

    def _fake_publish(payload, group_id):
        called["payload"] = payload
        called["group_id"] = group_id

    monkeypatch.setattr(handlers, "publish_telemetry", _fake_publish, raising=True)

    ev = make_http_event(
        "POST",
        "/telemetry",
        body={
            "device_key": "dev-1",
            "event_ts_ms": 1700000000000,
            "payload": {"x": 1},
        },
    )
    res = handlers.http_ingest(ev, None)
    assert res["statusCode"] == 202
    assert called["group_id"] == "dev-1"
    assert called["payload"]["device_key"] == "dev-1"
    assert "idemKey" in called["payload"]

