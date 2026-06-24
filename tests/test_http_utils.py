from __future__ import annotations

import base64
import json

from src.entrypoints.http.front.http_utils import error_detail, json_body, parse_event, response


def test_response_correct_structure():
    res = response(200, {"key": "value"})
    assert res["statusCode"] == 200
    assert json.loads(res["body"]) == {"key": "value"}
    assert res["headers"]["Content-Type"] == "application/json"


def test_response_passes_through_string_body():
    res = response(200, '{"raw": true}')
    assert res["body"] == '{"raw": true}'


def test_response_extra_headers_are_merged():
    res = response(200, {}, extra_headers={"X-Custom": "yes"})
    assert res["headers"]["X-Custom"] == "yes"


def test_error_detail_wraps_message():
    res = error_detail(422, "campo requerido")
    assert res["statusCode"] == 422
    assert json.loads(res["body"]) == {"detail": "campo requerido"}


def test_parse_event_extracts_method_and_path():
    event = {
        "requestContext": {"http": {"method": "POST", "path": "/foo"}},
        "rawPath": "/foo",
        "body": '{"x": 1}',
    }
    method, path, pp, q, body = parse_event(event)
    assert method == "POST"
    assert path == "/foo"
    assert body == '{"x": 1}'
    assert pp is None


def test_parse_event_handles_base64_body():
    raw = '{"hello":"world"}'
    encoded = base64.b64encode(raw.encode()).decode()
    event = {
        "requestContext": {"http": {"method": "POST", "path": "/test"}},
        "rawPath": "/test",
        "body": encoded,
        "isBase64Encoded": True,
    }
    _, _, _, _, body = parse_event(event)
    assert body == raw


def test_parse_event_query_params():
    event = {
        "requestContext": {"http": {"method": "GET", "path": "/items"}},
        "rawPath": "/items",
        "queryStringParameters": {"page": "2", "limit": "10"},
    }
    _, _, _, q, _ = parse_event(event)
    assert q == {"page": "2", "limit": "10"}


def test_parse_event_defaults_to_get():
    event = {"rawPath": "/health"}
    method, _, _, _, _ = parse_event(event)
    assert method == "GET"


def test_json_body_valid():
    assert json_body('{"a": 1}') == {"a": 1}


def test_json_body_none_input():
    assert json_body(None) is None


def test_json_body_empty_string():
    assert json_body("") is None


def test_json_body_invalid_json():
    assert json_body("not-json") is None


def test_json_body_array_returns_none():
    assert json_body("[1, 2, 3]") is None
