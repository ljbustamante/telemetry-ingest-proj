from __future__ import annotations

from datetime import datetime, timezone

from src.infrastructure.repositories.alert_digest_repository import (
    fetch_active_alerts,
    fetch_open_incidents,
)

_TS = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, columns: list[str], rows: list[tuple]):
        self._rows = rows
        self.description = [(col,) for col in columns]

    def execute(self, sql: str, params=None):
        pass

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, cursor: _Cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


_ALERT_COLS = ["id", "device_key", "customer_name", "risk_level", "class_prob", "predicted_at"]
_INCIDENT_COLS = ["id", "device_key", "customer_name", "symptom", "severity", "opened_at", "days_open"]


def test_fetch_active_alerts_returns_list_of_dicts():
    rows = [(1, "DEV-001", "Cliente A", "HIGH", 0.85, _TS)]
    conn = _Conn(_Cursor(_ALERT_COLS, rows))
    result = fetch_active_alerts(conn)
    assert len(result) == 1
    assert result[0]["device_key"] == "DEV-001"
    assert result[0]["risk_level"] == "HIGH"
    assert result[0]["class_prob"] == 0.85
    assert result[0]["customer_name"] == "Cliente A"


def test_fetch_active_alerts_empty_result():
    conn = _Conn(_Cursor(_ALERT_COLS, []))
    assert fetch_active_alerts(conn) == []


def test_fetch_active_alerts_multiple_rows():
    rows = [
        (1, "DEV-001", "C A", "HIGH", 0.90, _TS),
        (2, "DEV-002", "C B", "MEDIUM", 0.55, _TS),
    ]
    conn = _Conn(_Cursor(_ALERT_COLS, rows))
    result = fetch_active_alerts(conn)
    assert len(result) == 2
    assert result[1]["device_key"] == "DEV-002"


def test_fetch_open_incidents_returns_list_of_dicts():
    rows = [(1, "DEV-002", "Cliente B", "CPU alta", "critical", _TS, 3)]
    conn = _Conn(_Cursor(_INCIDENT_COLS, rows))
    result = fetch_open_incidents(conn)
    assert len(result) == 1
    assert result[0]["device_key"] == "DEV-002"
    assert result[0]["symptom"] == "CPU alta"
    assert result[0]["days_open"] == 3


def test_fetch_open_incidents_empty_result():
    conn = _Conn(_Cursor(_INCIDENT_COLS, []))
    assert fetch_open_incidents(conn) == []


def test_fetch_open_incidents_multiple_rows():
    rows = [
        (1, "DEV-A", "C A", "disk", "high", _TS, 1),
        (2, "DEV-B", "C B", "memory", "medium", _TS, 5),
    ]
    conn = _Conn(_Cursor(_INCIDENT_COLS, rows))
    result = fetch_open_incidents(conn)
    assert len(result) == 2
    assert result[0]["device_key"] == "DEV-A"
    assert result[1]["days_open"] == 5
