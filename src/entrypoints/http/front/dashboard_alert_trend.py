"""GET /dashboard/alert-trend — serie 6h agregada (devices ACTIVE, readings_curated_parent)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras

from ....infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import error_detail, parse_event, response

logger = logging.getLogger(__name__)

# Defaults cuando un bucket no tiene lecturas (mismo espíritu que el mock del front).
_DEFAULT_CPU = 55.0
_DEFAULT_TEMP = 70.0
_DEFAULT_BATTERY = 65.0

_SQL = """
WITH bounds AS (
    SELECT
        (NOW() - (%s::integer * INTERVAL '1 day'))::timestamptz AS start_ts,
        NOW()::timestamptz AS end_ts
),
series AS (
    SELECT
        (b.start_ts + (seq * INTERVAL '6 hours'))::timestamptz AS bucket_ts
    FROM bounds b
    CROSS JOIN LATERAL generate_series(
        0,
        GREATEST(
            0,
            CEIL(EXTRACT(EPOCH FROM (b.end_ts - b.start_ts)) / 21600.0)::bigint - 1
        )
    ) AS seq
),
agg AS (
    SELECT
        b.start_ts
        + (FLOOR(EXTRACT(EPOCH FROM (r.event_ts - b.start_ts)) / 21600.0) * 21600)
            * INTERVAL '1 second' AS bucket_ts,
        AVG(r.cpu_pct) AS cpu_pct,
        AVG(r.cpu_temp_c) AS temp_c,
        AVG(r.battery_charge_pct) AS battery
    FROM readings_curated_parent r
    INNER JOIN devices d ON d.id = r.device_id AND d.status = 'ACTIVE'
    CROSS JOIN bounds b
    WHERE r.event_ts >= b.start_ts
      AND r.event_ts <= b.end_ts
    GROUP BY 1
)
SELECT
    b.start_ts,
    s.bucket_ts,
    COALESCE(ROUND(a.cpu_pct::numeric, 1), %s)::double precision AS cpu_pct,
    COALESCE(ROUND(a.temp_c::numeric, 1), %s)::double precision AS temp_c,
    COALESCE(ROUND(a.battery::numeric, 1), %s)::double precision AS battery
FROM series s
CROSS JOIN bounds b
LEFT JOIN agg a ON a.bucket_ts = s.bucket_ts
ORDER BY s.bucket_ts ASC
"""


def _hour_label(start_ts: datetime, bucket_ts: datetime) -> str:
    if start_ts.tzinfo is None:
        start_ts = start_ts.replace(tzinfo=timezone.utc)
    if bucket_ts.tzinfo is None:
        bucket_ts = bucket_ts.replace(tzinfo=timezone.utc)
    delta = bucket_ts - start_ts
    hrs = int(delta.total_seconds() // 3600)
    if hrs < 0:
        hrs = 0
    return f"{hrs // 24}d {hrs % 24}h"


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, _path, _pp, query, _body = parse_event(event)
    if method == "OPTIONS":
        return response(200, {}, event=event)
    if method != "GET":
        return error_detail(405, "Metodo no permitido", event=event)
    bad = require_auth(event)
    if bad:
        return bad

    raw_days = (query or {}).get("days", 7)
    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        days = 7
    days = min(max(days, 1), 90)

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            _SQL,
            (
                days,
                _DEFAULT_CPU,
                _DEFAULT_TEMP,
                _DEFAULT_BATTERY,
            ),
        )
        rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            start_ts = d.pop("start_ts")
            bucket_ts = d.pop("bucket_ts")
            out.append(
                {
                    "hour": _hour_label(start_ts, bucket_ts),
                    "cpu_pct": float(d["cpu_pct"]),
                    "temp_c": float(d["temp_c"]),
                    "battery": float(d["battery"]),
                }
            )
        return response(200, out, event=event)
    except Exception as e:
        logger.exception("dashboard_alert_trend: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        if conn is not None:
            conn.close()
