from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3

from ..infrastructure.db.connection import get_connection
from ..infrastructure.repositories.alert_digest_repository import (
    fetch_active_alerts,
    fetch_open_incidents,
)

logger = logging.getLogger("alert-digest")

_RISK_COLOR = {"HIGH": "#d32f2f", "MEDIUM": "#f57c00", "FAILURE": "#b71c1c"}


def _html_alerts(alerts: list[dict]) -> str:
    if not alerts:
        return "<p>Sin alertas activas en las últimas 24 horas.</p>"
    rows = ""
    for a in alerts:
        color = _RISK_COLOR.get(a["risk_level"], "#333")
        prob = f"{float(a['class_prob']) * 100:.1f}%" if a["class_prob"] is not None else "—"
        ts = a["predicted_at"]
        ts_str = ts.strftime("%Y-%m-%d %H:%M UTC") if hasattr(ts, "strftime") else str(ts)
        rows += (
            f"<tr>"
            f"<td>{a['device_key']}</td>"
            f"<td>{a['customer_name']}</td>"
            f"<td style='color:{color};font-weight:bold'>{a['risk_level']}</td>"
            f"<td>{prob}</td>"
            f"<td>{ts_str}</td>"
            f"</tr>"
        )
    return (
        "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%'>"
        "<thead style='background:#f5f5f5'>"
        "<tr><th>Equipo</th><th>Cliente</th><th>Riesgo</th><th>Probabilidad</th><th>Predicción</th></tr>"
        "</thead><tbody>" + rows + "</tbody></table>"
    )


def _html_incidents(incidents: list[dict]) -> str:
    if not incidents:
        return "<p>Sin incidentes abiertos.</p>"
    rows = ""
    for i in incidents:
        ts = i["opened_at"]
        ts_str = ts.strftime("%Y-%m-%d %H:%M UTC") if hasattr(ts, "strftime") else str(ts)
        days = i.get("days_open", "—")
        rows += (
            f"<tr>"
            f"<td>{i['device_key']}</td>"
            f"<td>{i['customer_name']}</td>"
            f"<td>{i['symptom'] or '—'}</td>"
            f"<td>{i['severity'] or '—'}</td>"
            f"<td>{ts_str}</td>"
            f"<td>{days}</td>"
            f"</tr>"
        )
    return (
        "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%'>"
        "<thead style='background:#f5f5f5'>"
        "<tr><th>Equipo</th><th>Cliente</th><th>Síntoma</th><th>Severidad</th><th>Apertura</th><th>Días abierto</th></tr>"
        "</thead><tbody>" + rows + "</tbody></table>"
    )


def _build_html(alerts: list[dict], incidents: list[dict], generated_at: str) -> str:
    return f"""
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>Resumen diario de alertas</title></head>
<body style="font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px;color:#333">
  <h2 style="border-bottom:2px solid #1565c0;padding-bottom:8px;color:#1565c0">
    Resumen diario de alertas de equipos
  </h2>
  <p style="color:#666">Generado: {generated_at}</p>

  <h3>⚠️ Equipos en riesgo — últimas 24 horas ({len(alerts)})</h3>
  {_html_alerts(alerts)}

  <h3 style="margin-top:32px">🎫 Incidentes abiertos ({len(incidents)})</h3>
  {_html_incidents(incidents)}

  <hr style="margin-top:40px">
  <p style="color:#999;font-size:12px">Enviado automáticamente por el sistema de monitoreo CN Telemetry.</p>
</body>
</html>
"""


def _build_text(alerts: list[dict], incidents: list[dict], generated_at: str) -> str:
    lines = [
        "RESUMEN DIARIO DE ALERTAS DE EQUIPOS",
        f"Generado: {generated_at}",
        "",
        f"EQUIPOS EN RIESGO - ÚLTIMAS 24 HORAS ({len(alerts)})",
        "-" * 60,
    ]
    if alerts:
        for a in alerts:
            prob = f"{float(a['class_prob']) * 100:.1f}%" if a["class_prob"] is not None else "—"
            lines.append(f"  {a['device_key']} | {a['customer_name']} | {a['risk_level']} | {prob}")
    else:
        lines.append("  Sin alertas activas.")

    lines += ["", f"INCIDENTES ABIERTOS ({len(incidents)})", "-" * 60]
    if incidents:
        for i in incidents:
            lines.append(
                f"  {i['device_key']} | {i['customer_name']} | {i['symptom'] or '—'} | {i['severity'] or '—'} | {i.get('days_open', '—')} días"
            )
    else:
        lines.append("  Sin incidentes abiertos.")

    return "\n".join(lines)


def run_alert_digest() -> dict[str, Any]:
    email_from = os.environ.get("ALERT_EMAIL_FROM", "").strip()
    email_to_raw = os.environ.get("ALERT_EMAIL_TO", "").strip()

    if not email_from or not email_to_raw:
        logger.warning("ALERT_EMAIL_FROM o ALERT_EMAIL_TO no configurados — omitiendo envío")
        return {"skipped": True, "reason": "email_not_configured"}

    recipients = [e.strip() for e in email_to_raw.split(",") if e.strip()]
    if not recipients:
        return {"skipped": True, "reason": "no_recipients"}

    conn = get_connection()
    try:
        alerts = fetch_active_alerts(conn)
        incidents = fetch_open_incidents(conn)
    finally:
        conn.close()

    if not alerts and not incidents:
        logger.info("Sin alertas ni incidentes — omitiendo envío")
        return {"skipped": True, "reason": "no_alerts", "alerts_count": 0, "incidents_count": 0}

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"[CN Telemetry] Resumen diario: {len(alerts)} alertas, {len(incidents)} incidentes abiertos"

    html_body = _build_html(alerts, incidents, generated_at)
    text_body = _build_text(alerts, incidents, generated_at)

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
    logger.info("alert_digest_sent recipients=%s alerts=%d incidents=%d", recipients, len(alerts), len(incidents))
    return {
        "skipped": False,
        "sent": True,
        "alerts_count": len(alerts),
        "incidents_count": len(incidents),
        "recipients": recipients,
    }
