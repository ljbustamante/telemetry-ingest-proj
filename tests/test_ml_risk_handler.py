import json
from unittest.mock import patch

from src.entrypoints.aws.ml_risk_handler import handle


@patch("src.entrypoints.aws.ml_risk_handler.run_ml_risk_job")
def test_ml_schedule(mock_run):
    mock_run.return_value = {"devices_processed": 1}
    resp = handle({"source": "aws.events"}, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["devices_processed"] == 1


def test_ml_get_health():
    event = {
        "requestContext": {"http": {"method": "GET", "path": "/internal/ml-risk/run"}},
    }
    resp = handle(event, None)
    assert resp["statusCode"] == 200


@patch.dict("os.environ", {"ML_HTTP_SECRET": "secret-key-32bytes-long-ok!!"}, clear=False)
@patch("src.entrypoints.aws.ml_risk_handler.run_ml_risk_job")
def test_ml_post_ok(mock_run):
    mock_run.return_value = {}
    event = {
        "requestContext": {"http": {"method": "POST", "path": "/internal/ml-risk/run"}},
        "headers": {"X-Internal-Key": "secret-key-32bytes-long-ok!!"},
    }
    resp = handle(event, None)
    assert resp["statusCode"] == 200
