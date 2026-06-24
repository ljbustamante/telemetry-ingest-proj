from __future__ import annotations

import src.application.ml_risk_job_service as service_mod
from src.application.ml_risk_job_service import run_ml_risk_job


def test_run_ml_risk_job_delegates_to_process_ml_risk_job(monkeypatch):
    calls = {}

    def _fake_process(trigger_source="schedule"):
        calls["trigger_source"] = trigger_source
        return {"ok": True, "devices_processed": 3}

    monkeypatch.setattr(service_mod, "process_ml_risk_job", _fake_process, raising=True)
    result = run_ml_risk_job(trigger_source="http")
    assert calls["trigger_source"] == "http"
    assert result["ok"] is True
    assert result["devices_processed"] == 3


def test_run_ml_risk_job_default_trigger_source(monkeypatch):
    calls = {}

    def _fake_process(trigger_source="schedule"):
        calls["trigger_source"] = trigger_source
        return {}

    monkeypatch.setattr(service_mod, "process_ml_risk_job", _fake_process, raising=True)
    run_ml_risk_job()
    assert calls["trigger_source"] == "schedule"
