import os
import json
import boto3
from aws_lambda_powertools import Logger
from ..config import Settings

logger = Logger(service="telemetry-http")

def _resolve_sqs_client():
    """
    Usa LocalStack si:
    - ENV=local, o
    - TELEMETRY_QUEUE_URL contiene 'localhost' o '.localstack.cloud', o
    - se definió LOCALSTACK_URL explícitamente
    """
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    ls_url = os.getenv("LOCALSTACK_URL")

    use_local = (
        os.getenv("ENV") == "local"
        or "localhost" in Settings.TELEMETRY_QUEUE_URL
        or ".localstack.cloud" in Settings.TELEMETRY_QUEUE_URL
        or bool(ls_url)
    )

    endpoint = ls_url if ls_url else ("http://localhost:4566" if use_local else None)

    if use_local:
        # Credenciales dummy para LocalStack (si no existen)
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
        os.environ.setdefault("AWS_SESSION_TOKEN", "test")  # algunos setups lo requieren

    client = boto3.client("sqs", endpoint_url=endpoint, region_name=region)
    logger.debug({
        "env": os.getenv("ENV"),
        "bool(ls_url)": bool(ls_url),
        "use_local": use_local,
        "sqs_endpoint": endpoint or "aws",
        "region": region,
        "queue_url": Settings.TELEMETRY_QUEUE_URL
    })
    return client

_sqs = _resolve_sqs_client()

def publish_telemetry(message: dict, message_group_id: str) -> None:
    # #region agent log
    import time as _time, os as _os, json as _json2
    def _dbg2(msg, data, hyp):
        entry = _json2.dumps({"sessionId":"69d890","timestamp":int(_time.time()*1000),"location":"sqs_publisher.py:publish_telemetry","message":msg,"data":data,"hypothesisId":hyp,"runId":"run1"})
        try:
            _p = "/home/ljbustamante/upc/telemetry-ingest-proj/.cursor/debug-69d890.log"
            _os.makedirs(_os.path.dirname(_p), exist_ok=True)
            open(_p,"a").write(entry+"\n")
        except Exception: pass
        logger.info({"debug_agent": msg, **data})
    _dbg2("publish_telemetry: called", {"queue_url": Settings.TELEMETRY_QUEUE_URL, "group_id": message_group_id}, "H1-H2")
    # #endregion
    resp = _sqs.send_message(
        QueueUrl=Settings.TELEMETRY_QUEUE_URL,
        MessageBody=json.dumps(message, separators=(",", ":")),
        MessageGroupId=message_group_id,
    )
    # #region agent log
    _dbg2("publish_telemetry: send_message OK", {"MessageId": resp.get("MessageId"), "SequenceNumber": resp.get("SequenceNumber")}, "H1-H2")
    # #endregion
    logger.debug({"sqs_message_id": resp.get("MessageId")})
