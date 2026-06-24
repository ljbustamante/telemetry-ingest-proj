from __future__ import annotations

from datetime import datetime, timezone

import src.application.alert_digest_service as service_mod
from src.application.alert_digest_service import (
    _build_html,
    _build_text,
    _html_alerts,
    _html_incidents,
    run_alert_digest,
)

_NOW = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _alert(**kwargs) -> dict:
    return {
        "device_key": "DEV-001",
        "customer_name": "Cliente A",
        "risk_level": "HIGH",
        "class_prob": "0.85",
        "predicted_at": _NOW,
        **kwargs,
    }


def _incident(**kwargs) -> dict:
    return {
        "device_key": "DEV-002",
        "customer_name": "Cliente B",
        "symptom": "CPU alta",
        "severity": "critical",
        "opened_at": _NOW,
        "days_open": 3,
        **kwargs,
    }


class _FakeConn:
    def close(self):
        pass


class _FakeSES:
    def __init__(self):
        self.sent = {}

    def send_email(self, **kwargs):
        self.sent.update(kwargs)
        return {}


# --- _html_alerts ---

def test_html_alerts_empty_shows_no_alerts_message():
    html = _html_alerts([])
    assert "Sin alertas" in html


def test_html_alerts_includes_device_and_risk():
    html = _html_alerts([_alert()])
    assert "DEV-001" in html
    assert "HIGH" in html
    assert "Cliente A" in html
    assert "85.0%" in html


def test_html_alerts_none_prob_shows_dash():
    html = _html_alerts([_alert(class_prob=None)])
    assert "—" in html


def test_html_alerts_string_timestamp():
    html = _html_alerts([_alert(predicted_at="2024-01-15 12:00 UTC")])
    assert "2024-01-15 12:00 UTC" in html


# --- _html_incidents ---

def test_html_incidents_empty_shows_no_incidents_message():
    html = _html_incidents([])
    assert "Sin incidentes" in html


def test_html_incidents_includes_relevant_fields():
    html = _html_incidents([_incident()])
    assert "DEV-002" in html
    assert "CPU alta" in html
    assert "critical" in html
    assert "3" in html


def test_html_incidents_none_symptom_shows_dash():
    html = _html_incidents([_incident(symptom=None, severity=None)])
    assert "—" in html


# --- _build_text ---

def test_build_text_includes_section_headers():
    text = _build_text([_alert()], [_incident()], "2024-01-15 12:00 UTC")
    assert "EQUIPOS EN RIESGO" in text
    assert "INCIDENTES ABIERTOS" in text


def test_build_text_includes_device_keys():
    text = _build_text([_alert()], [_incident()], "2024-01-15 12:00 UTC")
    assert "DEV-001" in text
    assert "DEV-002" in text


def test_build_text_empty_alerts_shows_no_alerts():
    text = _build_text([], [], "2024-01-15")
    assert "Sin alertas activas" in text
    assert "Sin incidentes abiertos" in text


# --- _build_html ---

def test_build_html_contains_counts():
    html = _build_html([_alert(), _alert()], [_incident()], "2024-01-15")
    assert "2" in html
    assert "1" in html


# --- run_alert_digest ---

def test_run_skips_when_email_not_configured(monkeypatch):
    monkeypatch.delenv("ALERT_EMAIL_FROM", raising=False)
    monkeypatch.delenv("ALERT_EMAIL_TO", raising=False)
    result = run_alert_digest()
    assert result["skipped"] is True
    assert result["reason"] == "email_not_configured"


def test_run_skips_when_to_address_is_blank(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("ALERT_EMAIL_TO", "  ")
    result = run_alert_digest()
    assert result["skipped"] is True


def test_run_skips_when_no_alerts_or_incidents(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("ALERT_EMAIL_TO", "to@example.com")
    monkeypatch.setattr(service_mod, "get_connection", lambda: _FakeConn())
    monkeypatch.setattr(service_mod, "fetch_active_alerts", lambda conn: [])
    monkeypatch.setattr(service_mod, "fetch_open_incidents", lambda conn: [])

    result = run_alert_digest()
    assert result["skipped"] is True
    assert result["reason"] == "no_alerts"


def test_run_sends_email_and_returns_counts(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("ALERT_EMAIL_TO", "to@example.com,ops@example.com")
    monkeypatch.setattr(service_mod, "get_connection", lambda: _FakeConn())
    monkeypatch.setattr(service_mod, "fetch_active_alerts", lambda conn: [_alert()])
    monkeypatch.setattr(service_mod, "fetch_open_incidents", lambda conn: [_incident()])

    ses = _FakeSES()
    monkeypatch.setattr(service_mod.boto3, "client", lambda name, region_name=None: ses)

    result = run_alert_digest()
    assert result["skipped"] is False
    assert result["sent"] is True
    assert result["alerts_count"] == 1
    assert result["incidents_count"] == 1
    assert "to@example.com" in result["recipients"]
    assert "ops@example.com" in result["recipients"]
    assert ses.sent["Source"] == "from@example.com"
