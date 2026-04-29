from __future__ import annotations

import hmac
import json
import logging
import os
from typing import Any, Dict

from ..http.cors import cors_headers
from ...application.ml_risk_job_service import run_ml_risk_job

logger = logging.getLogger("ml-risk-handler")
logger.setLevel(logging.INFO)


def _json_response(
    status: int, body: Dict[str, Any], event: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {**cors_headers(event), "Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _headers(event: Dict[str, Any]) -> Dict[str, str]:
    raw = event.get("headers") or {}
    return {str(k).lower(): v for k, v in raw.items() if v is not None}


def _invoke(event: Dict[str, Any] | None = None) -> Dict[str, Any]:
    stats = run_ml_risk_job()
    logger.info("ml_risk_job_done %s", stats)
    return _json_response(200, stats, event)


def handle(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    if event.get("source") == "aws.events":
        try:
            return _invoke(event)
        except Exception as e:
            logger.exception("scheduled ml risk failed: %s", e)
            return _json_response(500, {"error": str(e)}, event)

    req = event.get("requestContext", {}).get("http", {})
    method = (req.get("method") or "").upper()
    path = (req.get("path") or event.get("rawPath") or "").lower()

    if method == "GET" and "ml-risk" in path:
        return _json_response(200, {"ok": True, "service": "ml-risk-job"}, event)

    if method == "POST" and "ml-risk" in path and "run" in path:
        secret = os.environ.get("ML_HTTP_SECRET", "")
        if not secret:
            logger.error("ML_HTTP_SECRET is not set; refusing HTTP trigger")
            return _json_response(503, {"error": "ml_http_not_configured"}, event)
        hdrs = _headers(event)
        provided = hdrs.get("x-internal-key", "")
        if len(provided) != len(secret) or not hmac.compare_digest(
            provided.encode("utf-8"), secret.encode("utf-8")
        ):
            return _json_response(403, {"error": "forbidden"}, event)
        try:
            return _invoke(event)
        except Exception as e:
            logger.exception("http ml risk failed: %s", e)
            return _json_response(500, {"error": str(e)}, event)

    return _json_response(404, {"error": "not_found"}, event)
