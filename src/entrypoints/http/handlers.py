import json, hashlib, datetime
from aws_lambda_powertools import Logger
from pydantic import ValidationError
from ...domain.models import TelemetryIngest
from ...infrastructure.queue.sqs_publisher import publish_telemetry
from .cors import cors_headers

logger = Logger(service="telemetry-http")


def _http_json(status: int, body: dict, event: dict | None) -> dict:
    return {
        "statusCode": status,
        "headers": {**cors_headers(event), "Content-Type": "application/json"},
        "body": json.dumps(body),
    }

def _hash_payload(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def _iso_to_epoch_ms(s: str) -> int:
    # soporta 'Z' y offset (+00:00)
    dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)

def _normalize_snapshot(body: dict) -> dict | None:
    # Detecta el snapshot como el tuyo y normaliza
    try:
        return {
            "device_key": body["Identity"]["DeviceId"],
            "event_ts_ms": _iso_to_epoch_ms(body["CollectedAt"]),
            "agent_version": body.get("AgentVersion"),
            "schema_version": body.get("SchemaVersion"),
            "sample_period_s": body.get("SamplePeriodSec"),
            "payload": body,  # guardamos el snapshot completo
            # pasamos hints para enriquecer 'devices' (opcionales)
            "_device_hostname_hash": body.get("Identity", {}).get("HostnameHash"),
            "_device_customer_code": body.get("Identity", {}).get("CustomerId"),
        }
    except Exception:
        return None

def http_ingest(event, context):
    if event.get("requestContext", {}).get("http", {}).get("method") == "GET":
        return _http_json(200, {"ok": True}, event)

    try:
        body_str = event.get("body") or "{}"
        raw = json.loads(body_str)

        # 1) si ya viene en el formato normalizado (device_key, event_ts_ms, payload...)
        try:
            telemetry = TelemetryIngest.model_validate(raw)
        except ValidationError:
            # 2) intenta normalizar el snapshot y validar nuevamente
            norm = _normalize_snapshot(raw)
            if not norm:
                raise
            telemetry = TelemetryIngest.model_validate(norm)

    except ValidationError as ve:
        logger.warning({"validation": ve.errors()})
        return _http_json(
            400, {"error": "invalid payload", "details": ve.errors()}, event
        )
    except Exception as e:
        return _http_json(400, {"error": str(e)}, event)

    payload = telemetry.model_dump()
    payload["idemKey"] = _hash_payload(payload)
    publish_telemetry(payload, telemetry.device_key)
    return _http_json(202, {"status": "accepted"}, event)
