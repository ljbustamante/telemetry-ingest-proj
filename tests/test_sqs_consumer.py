from __future__ import annotations

import json

from src.entrypoints.sqs import consumer


def test_sqs_consumer_valid_record_calls_upsert(monkeypatch):
    calls = {"count": 0}

    def _fake_upsert(items):
        calls["count"] = len(items)

    monkeypatch.setattr(consumer.writer, "upsert_raw_batch", _fake_upsert, raising=True)

    payload = {
        "device_key": "dev-1",
        "event_ts_ms": 1700000000000,
        "payload": {"x": 1},
    }
    event = {"Records": [{"body": json.dumps(payload)}]}
    res = consumer.handle(event, None)
    assert res == {"ok": 1, "bad": 0}
    assert calls["count"] == 1

