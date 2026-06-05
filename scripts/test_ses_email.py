#!/usr/bin/env python3
"""Test SES email sending locally.

Usage:
  python scripts/test_ses_email.py                     # minimal test to JOB_FAILURE_EMAIL_TO
  python scripts/test_ses_email.py --digest            # full alert digest to ALERT_EMAIL_TO
  python scripts/test_ses_email.py --to me@example.com # minimal test to a specific address
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# .env usa credenciales ficticias de LocalStack ("test"). Las descartamos para que
# boto3 use el perfil real de ~/.aws/credentials.
if os.environ.get("AWS_ACCESS_KEY_ID") == "test":
    os.environ.pop("AWS_ACCESS_KEY_ID", None)
    os.environ.pop("AWS_SECRET_ACCESS_KEY", None)

import boto3  # noqa: E402


def _send_minimal(to: str) -> None:
    email_from = os.environ.get("ALERT_EMAIL_FROM", "").strip()
    if not email_from:
        print("ERROR: ALERT_EMAIL_FROM no está configurado en .env")
        sys.exit(1)
    if not to:
        print("ERROR: destinatario vacío. Usa --to o configura JOB_FAILURE_EMAIL_TO en .env")
        sys.exit(1)

    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    print(f"  Región  : {region}")
    print(f"  From    : {email_from}")
    print(f"  To      : {to}")
    print()

    ses = boto3.client("ses", region_name=region)
    response = ses.send_email(
        Source=email_from,
        Destination={"ToAddresses": [to]},
        Message={
            "Subject": {"Data": "[CN Telemetry] Prueba de envío SES", "Charset": "UTF-8"},
            "Body": {
                "Text": {
                    "Data": f"Este es un email de prueba enviado a las {ts}.\n\nSi recibes esto, SES está funcionando correctamente.",
                    "Charset": "UTF-8",
                },
                "Html": {
                    "Data": f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;padding:20px;color:#333">
  <h2 style="color:#1565c0">&#9989; Prueba SES — CN Telemetry</h2>
  <p>Este email fue enviado a las <strong>{ts}</strong>.</p>
  <p>Si lo recibes, SES está configurado correctamente.</p>
</body>
</html>""",
                    "Charset": "UTF-8",
                },
            },
        },
    )
    print(f"OK — MessageId: {response['MessageId']}")


def _send_digest_forced() -> None:
    from src.application.alert_digest_service import (
        _build_html,
        _build_text,
        _html_alerts,
        _html_incidents,
    )
    from src.infrastructure.db.connection import get_connection
    from src.infrastructure.repositories.alert_digest_repository import (
        fetch_active_alerts,
        fetch_open_incidents,
    )

    email_from = os.environ.get("ALERT_EMAIL_FROM", "").strip()
    email_to_raw = os.environ.get("ALERT_EMAIL_TO", "").strip()

    if not email_from or not email_to_raw:
        print("ERROR: ALERT_EMAIL_FROM o ALERT_EMAIL_TO no configurados en .env")
        sys.exit(1)

    recipients = [e.strip() for e in email_to_raw.split(",") if e.strip()]
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    print(f"  Región  : {region}")
    print(f"  From    : {email_from}")
    print(f"  To      : {recipients}")
    print()

    conn = get_connection()
    try:
        alerts = fetch_active_alerts(conn)
        incidents = fetch_open_incidents(conn)
    finally:
        conn.close()

    print(f"  Alertas encontradas  : {len(alerts)}")
    print(f"  Incidentes abiertos  : {len(incidents)}")
    print()

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"[CN Telemetry TEST] Digest: {len(alerts)} alertas, {len(incidents)} incidentes"
    html_body = _build_html(alerts, incidents, generated_at)
    text_body = _build_text(alerts, incidents, generated_at)

    ses = boto3.client("ses", region_name=region)
    response = ses.send_email(
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
    print(f"OK — MessageId: {response['MessageId']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test SES email sending")
    parser.add_argument("--digest", action="store_true", help="Send full alert digest")
    parser.add_argument("--to", default="", help="Override recipient for minimal test")
    args = parser.parse_args()

    if args.digest:
        print("=== Modo: digest real (alertas + incidentes actuales) ===")
        _send_digest_forced()
    else:
        to = args.to or os.environ.get("JOB_FAILURE_EMAIL_TO", "").split(",")[0].strip()
        print("=== Modo: email de prueba mínimo ===")
        _send_minimal(to)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}")
        sys.exit(1)
