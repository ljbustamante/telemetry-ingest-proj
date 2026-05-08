from __future__ import annotations

import json

import pytest

from src.entrypoints.http.front import (
    alerts_list,
    auth_login,
    customers_crud,
    dashboard_alert_trend,
    device_assignments_crud,
    devices_get,
    devices_list,
    metrics_dashboard,
    metrics_device,
    sites_crud,
    tickets_crud,
    tickets_export,
    users_crud,
)

from .conftest import make_http_event


def test_front_auth_login_missing_fields_returns_422():
    ev = make_http_event("POST", "/auth/login", body={"email": "a@b.com"})
    res = auth_login.handle(ev, None)
    assert res["statusCode"] == 422


@pytest.mark.parametrize(
    "mod,path",
    [
        (devices_list, "/devices"),
        (alerts_list, "/alerts"),
        (metrics_dashboard, "/dashboard/summary"),
        (dashboard_alert_trend, "/dashboard/alert-trend"),
    ],
)
def test_front_get_endpoints_return_200_with_mock_db_and_auth(monkeypatch, fake_db, mod, path):
    # bypass JWT validation
    monkeypatch.setattr(mod, "require_auth", lambda event: None, raising=True)
    fake_db.patch(mod, rows=[])

    ev = make_http_event("GET", path, headers={"authorization": "Bearer x"})
    res = mod.handle(ev, None)
    assert res["statusCode"] == 200


def test_front_devices_get_options_is_200():
    ev = make_http_event("OPTIONS", "/devices/123")
    res = devices_get.handle(ev, None)
    assert res["statusCode"] == 200


def test_front_metrics_device_options_is_200():
    ev = make_http_event("OPTIONS", "/devices/123/metrics")
    res = metrics_device.handle(ev, None)
    assert res["statusCode"] == 200


def test_front_tickets_crud_options_is_200():
    ev = make_http_event("OPTIONS", "/tickets")
    res = tickets_crud.handle(ev, None)
    assert res["statusCode"] == 200


def test_front_customers_crud_options_is_200():
    ev = make_http_event("OPTIONS", "/customers")
    res = customers_crud.handle(ev, None)
    assert res["statusCode"] == 200


def test_front_sites_crud_options_is_200():
    ev = make_http_event("OPTIONS", "/customers/1/sites")
    res = sites_crud.handle(ev, None)
    assert res["statusCode"] == 200


def test_front_device_assignments_crud_options_is_200():
    ev = make_http_event("OPTIONS", "/sites/1/device-assignments")
    res = device_assignments_crud.handle(ev, None)
    assert res["statusCode"] == 200


def test_front_users_crud_options_is_200():
    ev = make_http_event("OPTIONS", "/users")
    res = users_crud.handle(ev, None)
    assert res["statusCode"] == 200


def test_front_tickets_export_puts_object_and_returns_csv(monkeypatch, fake_db):
    # bypass auth
    monkeypatch.setattr(tickets_export, "require_auth", lambda event: None, raising=True)
    fake_db.patch(tickets_export, rows=[])

    put_calls = {}

    class _FakeS3:
        def put_object(self, **kwargs):
            put_calls.update(kwargs)
            return {}

    monkeypatch.setattr(tickets_export.boto3, "client", lambda name: _FakeS3(), raising=True)

    ev = make_http_event("GET", "/tickets/export", headers={"authorization": "Bearer x"})
    res = tickets_export.handle(ev, None)
    assert res["statusCode"] == 200
    assert res["headers"]["Content-Type"] == "text/csv"
    assert "Bucket" in put_calls and "Key" in put_calls

