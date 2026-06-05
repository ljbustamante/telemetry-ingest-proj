from __future__ import annotations

import logging
import os
import traceback
from datetime import datetime, timezone
from typing import Optional

import boto3

logger = logging.getLogger("job-failure-notifier")


def notify_job_failure(job_name: str, error: Exception) -> None:
    """Send a failure alert email via SES. Never raises — logs warning on any issue."""
    try:
        email_from = os.environ.get("ALERT_EMAIL_FROM", "").strip()
        email_to_raw = os.environ.get("JOB_FAILURE_EMAIL_TO", "").strip()

        if not email_from or not email_to_raw:
            logger.warning(
                "job_failure_notify skipped: ALERT_EMAIL_FROM or JOB_FAILURE_EMAIL_TO not set"
            )
            return

        recipients = [e.strip() for e in email_to_raw.split(",") if e.strip()]
        if not recipients:
            return

        tb = traceback.format_exc()
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        error_msg = str(error)

        subject = f"[CN Telemetry] Job fallido: {job_name}"
        text_body = (
            f"FALLO EN JOB: {job_name}\n"
            f"Timestamp: {ts}\n\n"
            f"Error: {error_msg}\n\n"
            f"Traceback:\n{tb}"
        )
        html_body = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>Job fallido</title></head>
<body style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px;color:#333">
  <h2 style="color:#c62828;border-bottom:2px solid #c62828;padding-bottom:8px">
    &#10060; Job fallido: {job_name}
  </h2>
  <p><strong>Timestamp:</strong> {ts}</p>
  <p><strong>Error:</strong></p>
  <pre style="background:#fef2f2;border:1px solid #fecaca;padding:12px;border-radius:4px;white-space:pre-wrap">{error_msg}</pre>
  <p><strong>Traceback:</strong></p>
  <pre style="background:#f8f8f8;border:1px solid #e0e0e0;padding:12px;border-radius:4px;font-size:12px;white-space:pre-wrap">{tb}</pre>
  <hr style="margin-top:32px">
  <p style="color:#999;font-size:12px">Enviado automáticamente por CN Telemetry.</p>
</body>
</html>"""

        ses = boto3.client("ses", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        ses.send_email(
            Source=email_from,
            Destination={"ToAddresses": recipients},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            },
        )
        logger.info("job_failure_notified job=%s recipients=%s", job_name, recipients)
    except Exception:
        logger.warning("job_failure_notify send failed", exc_info=True)
