"""GET /tickets/export — docs/GUIA_LAMBDAS_AWS.txt."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
import psycopg2.extras

from ....infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import cors_headers, error_detail, parse_event, response

logger = logging.getLogger(__name__)

_S3_KEY = "tickets/tickets_history.csv"


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, _path, _pp, _q, _body = parse_event(event)
    if method == "OPTIONS":
        return response(200, {}, event=event)
    if method != "GET":
        return error_detail(405, "Metodo no permitido", event=event)
    bad = require_auth(event)
    if bad:
        return bad

    bucket = os.environ.get("S3_BUCKET", "cnagent-ml-data")

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                i.id AS ticket_id,
                d.device_key AS device_id,
                i.opened_at,
                i.closed_at,
                COALESCE(i.notes::text, 'sistema') AS technician,
                i.symptom AS issue_description,
                f.outcome,
                f.notes AS failure_type
            FROM incidents i
            JOIN devices d ON d.id = i.device_id
            JOIN ml_feedback f ON f.incident_id = i.id
            WHERE i.closed_at IS NOT NULL
              AND f.outcome IS NOT NULL
            ORDER BY i.opened_at ASC
            """
        )
        rows = cur.fetchall()
    except Exception as e:
        logger.exception("export_tickets_csv query: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        if conn is not None:
            conn.close()

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "ticket_id",
            "device_id",
            "opened_at",
            "closed_at",
            "technician",
            "issue_description",
            "outcome",
            "failure_type",
        ],
    )
    writer.writeheader()
    for r in rows:
        d = dict(r)
        writer.writerow(
            {
                k: (v.isoformat() if hasattr(v, "isoformat") else v or "")
                for k, v in d.items()
            }
        )

    csv_text = output.getvalue()
    csv_bytes = csv_text.encode("utf-8")

    try:
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=bucket,
            Key=_S3_KEY,
            Body=csv_bytes,
            ContentType="text/csv",
        )
    except Exception as e:
        logger.exception("export_tickets_csv s3: %s", e)
        return {
            "statusCode": 500,
            "headers": {
                **cors_headers(event),
                "Content-Type": "application/json",
            },
            "body": json.dumps({"detail": "Error interno"}),
        }

    fname = f"tickets_history_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return {
        "statusCode": 200,
        "headers": {
            **cors_headers(event),
            "Content-Type": "text/csv",
            "Content-Disposition": f"attachment; filename={fname}",
        },
        "body": csv_text,
        "isBase64Encoded": False,
    }
