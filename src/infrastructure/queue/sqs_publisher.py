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
    resp = _sqs.send_message(
        QueueUrl=Settings.TELEMETRY_QUEUE_URL,
        MessageBody=json.dumps(message, separators=(",", ":")),
        MessageGroupId=message_group_id,
    )
    logger.debug({"sqs_message_id": resp.get("MessageId")})
