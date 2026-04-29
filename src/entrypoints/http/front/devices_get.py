"""GET /devices/{device_id} — docs/GUIA_LAMBDAS_AWS.txt."""

from __future__ import annotations

import logging
from typing import Any

import psycopg2.extras

from ....infrastructure.db.connection import get_connection
from .common import require_auth
from .http_utils import error_detail, parse_event, response

logger = logging.getLogger(__name__)


def _map_risk_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    d = dict(row)
    rb = d.get("risk_bucket")
    if rb == "Alto":
        d["risk_bucket"] = "HIGH"
    elif rb == "Medio":
        d["risk_bucket"] = "MEDIUM"
    elif rb == "Bajo":
        d["risk_bucket"] = "LOW"
    return d


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method, _path, path_params, _q, _body = parse_event(event)
    if method == "OPTIONS":
        return response(200, {}, event=event)
    if method != "GET":
        return error_detail(405, "Metodo no permitido", event=event)
    bad = require_auth(event)
    if bad:
        return bad

    device_id = (path_params or {}).get("device_id")
    if not device_id:
        return error_detail(400, "device_id requerido", event=event)

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT d.*, c.name AS customer_name, s.name AS site_name,
                   r.risk_score, r.risk_bucket
            FROM devices d
            LEFT JOIN customers c ON c.code = d.customer_code
            LEFT JOIN sites s ON s.id = d.current_site_id
            LEFT JOIN LATERAL (
                SELECT risk_score, risk_bucket FROM readings_curated_parent
                WHERE device_id = d.id ORDER BY event_ts DESC LIMIT 1
            ) r ON true
            WHERE d.id = %s::uuid
            """,
            (device_id,),
        )
        device = cur.fetchone()
        if not device:
            return error_detail(404, "Equipo no encontrado", event=event)

        cur.execute(
            """
            SELECT h.*, ds.model AS disk_model, ds.capacity_gb,
                   ds.temperature_c AS disk_temp_c
            FROM device_hardware_snapshot h
            LEFT JOIN device_storage_drive ds ON ds.hw_snapshot_id = h.id
            WHERE h.device_id = %s::uuid ORDER BY h.snapshot_ts DESC LIMIT 1
            """,
            (device_id,),
        )
        hardware = cur.fetchone()

        cur.execute(
            """
            SELECT * FROM ml_predictions
            WHERE device_id = %s::uuid ORDER BY predicted_at DESC LIMIT 1
            """,
            (device_id,),
        )
        prediction = cur.fetchone()

        dev_dict = _map_risk_row(dict(device)) or dict(device)
        return response(
            200,
            {
                **dev_dict,
                "hardware": dict(hardware) if hardware else None,
                "active_prediction": dict(prediction) if prediction else None,
            },
            event=event,
        )
    except Exception as e:
        logger.exception("get_device: %s", e)
        return error_detail(500, "Error interno", event=event)
    finally:
        if conn is not None:
            conn.close()
