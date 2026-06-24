from __future__ import annotations

import pytest

from src.entrypoints.http.cors import cors_headers


def test_no_env_returns_wildcard(monkeypatch):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    h = cors_headers(None)
    assert h["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Methods" in h
    assert "Access-Control-Allow-Headers" in h


def test_star_env_returns_wildcard(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    h = cors_headers(None)
    assert h["Access-Control-Allow-Origin"] == "*"


def test_matching_origin_echoes_and_sets_credentials(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com,https://local.dev")
    event = {"headers": {"origin": "https://app.example.com"}}
    h = cors_headers(event)
    assert h["Access-Control-Allow-Origin"] == "https://app.example.com"
    assert h.get("Access-Control-Allow-Credentials") == "true"
    assert h.get("Vary") == "Origin"


def test_non_matching_origin_falls_back_to_wildcard(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")
    event = {"headers": {"origin": "https://evil.com"}}
    h = cors_headers(event)
    assert h["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Credentials" not in h


def test_no_request_origin_in_restricted_list(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")
    h = cors_headers({"headers": {}})
    assert h["Access-Control-Allow-Origin"] == "*"


def test_uppercase_origin_header_key_is_matched(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")
    event = {"headers": {"Origin": "https://app.example.com"}}
    h = cors_headers(event)
    assert h["Access-Control-Allow-Origin"] == "https://app.example.com"
