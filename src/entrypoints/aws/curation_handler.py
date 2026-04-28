from __future__ import annotations

import hmac
import json
import logging
import os
from typing import Any, Dict

from ...infrastructure.repositories.curation_etl_repository import process_curation_batch

logger = logging.getLogger("curation-handler")
logger.setLevel(logging.INFO)


def _json_response(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {"statusCode": status, "body": json.dumps(body, default=str)}


def _headers(event: Dict[str, Any]) -> Dict[str, str]:
    raw = event.get("headers") or {}
    return {str(k).lower(): v for k, v in raw.items() if v is not None}


def _run_etl() -> Dict[str, Any]:
    batch = int(os.environ.get("CURATION_BATCH_SIZE", "500"))
    stats = process_curation_batch(batch_limit=batch)
    logger.info("curation_etl_done %s", stats)
    return _json_response(200, stats)


def handle(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    EventBridge schedule: source == aws.events
    HTTP API: POST /internal/curation/run with header X-Internal-Key matching CURATION_HTTP_SECRET
    """
    if event.get("source") == "aws.events":
        try:
            return _run_etl()
        except Exception as e:
            logger.exception("scheduled curation failed: %s", e)
            return _json_response(500, {"error": str(e)})

    req = event.get("requestContext", {}).get("http", {})
    method = (req.get("method") or "").upper()
    path = (req.get("path") or event.get("rawPath") or "").lower()

    if method == "GET" and "curation" in path:
        return _json_response(200, {"ok": True, "service": "curation-etl"})

    if method == "POST" and "curation" in path and "run" in path:
        secret = os.environ.get("CURATION_HTTP_SECRET", "")
        if not secret:
            logger.error("CURATION_HTTP_SECRET is not set; refusing HTTP trigger")
            return _json_response(503, {"error": "curation_http_not_configured"})
        hdrs = _headers(event)
        provided = hdrs.get("x-internal-key", "")
        if len(provided) != len(secret) or not hmac.compare_digest(
            provided.encode("utf-8"), secret.encode("utf-8")
        ):
            return _json_response(403, {"error": "forbidden"})
        try:
            return _run_etl()
        except Exception as e:
            logger.exception("http curation failed: %s", e)
            return _json_response(500, {"error": str(e)})

    return _json_response(404, {"error": "not_found"})
