import json
from unittest.mock import patch

from src.entrypoints.aws.curation_handler import handle


@patch("src.entrypoints.aws.curation_handler.process_curation_batch")
def test_handle_eventbridge_schedule(mock_batch):
    mock_batch.return_value = {"raw_scanned": 0, "curated_inserted": 0}
    resp = handle({"source": "aws.events", "detail-type": "Scheduled Event"}, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["raw_scanned"] == 0
    mock_batch.assert_called_once()


def test_handle_http_get_health():
    event = {
        "requestContext": {"http": {"method": "GET", "path": "/internal/curation/run"}},
    }
    resp = handle(event, None)
    assert resp["statusCode"] == 200


@patch.dict("os.environ", {"CURATION_HTTP_SECRET": "secret-key-32bytes-long-ok!!"}, clear=False)
@patch("src.entrypoints.aws.curation_handler.process_curation_batch")
def test_handle_http_post_ok(mock_batch):
    mock_batch.return_value = {"raw_scanned": 1}
    event = {
        "requestContext": {"http": {"method": "POST", "path": "/internal/curation/run"}},
        "headers": {"X-Internal-Key": "secret-key-32bytes-long-ok!!"},
    }
    resp = handle(event, None)
    assert resp["statusCode"] == 200


@patch.dict("os.environ", {"CURATION_HTTP_SECRET": "secret"}, clear=False)
def test_handle_http_post_forbidden():
    event = {
        "requestContext": {"http": {"method": "POST", "path": "/internal/curation/run"}},
        "headers": {"X-Internal-Key": "wrong"},
    }
    resp = handle(event, None)
    assert resp["statusCode"] == 403
