from __future__ import annotations

import json
import os

from src.entrypoints.aws import curation_handler, ml_risk_handler


def test_curation_handler_eventbridge_runs_etl(monkeypatch):
    monkeypatch.setattr(
        curation_handler,
        "process_curation_batch",
        lambda batch_limit: {"ok": True, "batch_limit": batch_limit},
        raising=True,
    )
    res = curation_handler.handle({"source": "aws.events"}, None)
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["ok"] is True


def test_ml_risk_handler_get_health(monkeypatch):
    res = ml_risk_handler.handle(
        {"requestContext": {"http": {"method": "GET", "path": "/internal/ml-risk/run"}}, "headers": {}},
        None,
    )
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["ok"] is True

