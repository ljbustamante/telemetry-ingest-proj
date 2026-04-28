from src.ml.incident_policy import (
    ML_INCIDENT_MARKER,
    incident_notes_json,
    should_open_incident,
)


def test_should_open_incident_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ML_AUTO_INCIDENT_ENABLED", raising=False)
    assert should_open_incident({"worst_risk_level": "Alto"}) is False


def test_should_open_when_enabled_and_alto(monkeypatch):
    monkeypatch.setenv("ML_AUTO_INCIDENT_ENABLED", "true")
    monkeypatch.setenv("ML_AUTO_INCIDENT_MIN_LEVEL", "Alto")
    assert should_open_incident({"worst_risk_level": "Alto"}) is True
    assert should_open_incident({"worst_risk_level": "Medio"}) is False


def test_should_open_medio_when_min_medio(monkeypatch):
    monkeypatch.setenv("ML_AUTO_INCIDENT_ENABLED", "1")
    monkeypatch.setenv("ML_AUTO_INCIDENT_MIN_LEVEL", "Medio")
    assert should_open_incident({"worst_risk_level": "Medio"}) is True
    assert should_open_incident({"worst_risk_level": "Bajo"}) is False


def test_incident_notes_contains_marker():
    s = incident_notes_json({"worst_risk_level": "Alto"}, "dev-key-1")
    assert ML_INCIDENT_MARKER in s
    assert "dev-key-1" in s
