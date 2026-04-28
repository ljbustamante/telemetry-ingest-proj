
import os, json
from moto import mock_aws
import boto3
from src.entrypoints.http.handlers import http_ingest

@mock_aws
def test_http_ingest_ok_sends_to_sqs():
    sqs = boto3.client("sqs", region_name="us-east-1")
    q = sqs.create_queue(
        QueueName="telemetry-test.fifo",
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "true"},
    )
    os.environ["TELEMETRY_QUEUE_URL"] = q["QueueUrl"]

    payload = {
        "device_key": "DEV-ABC-1",
        "event_ts_ms": 1730070000000,
        "payload": {"x": 1}
    }
    event = {"requestContext": {"http": {"method": "POST"}}, "body": json.dumps(payload)}
    resp = http_ingest(event, None)
    assert resp["statusCode"] == 202

    msgs = sqs.receive_message(QueueUrl=q["QueueUrl"], MaxNumberOfMessages=10)
    assert "Messages" in msgs and len(msgs["Messages"]) == 1

def test_http_ingest_validation_error():
    event = {"requestContext": {"http": {"method": "POST"}}, "body": json.dumps({"payload": {}})}
    resp = http_ingest(event, None)
    assert resp["statusCode"] == 400
