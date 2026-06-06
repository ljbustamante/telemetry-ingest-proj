from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

import pandas as pd

from ...domain.payload_curated_mapping import parse_payload
from ...domain.telemetry_features import extract_features_from_json
from ...ml.device_risk_analysis import analyze_device
from ...ml.incident_policy import (
    ML_INCIDENT_MARKER,
    incident_notes_json,
    incident_symptom,
    severity_for_risk_level,
    should_open_incident,
)
from ..db.connection import get_connection

logger = logging.getLogger("ml-risk-job")


def _round_prob(p: float) -> Decimal:
    d = Decimal(str(min(max(p, 0.0), 0.99999)))
    return d.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)


def fetch_snapshots_for_ml(
    conn: Any, *, lookback_days: int, max_snapshots_per_device: int
) -> List[Tuple[str, str, Dict[str, Any], datetime]]:
    """Rows: (device_uuid, device_key, payload_dict, event_ts)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT x.dev_id::text, x.device_key, x.payload, x.event_ts
        FROM (
          SELECT d.id AS dev_id, d.device_key, r.payload, r.event_ts,
            ROW_NUMBER() OVER (
              PARTITION BY r.device_id ORDER BY r.event_ts ASC
            ) AS rn
            FROM readings_raw_parent r
            JOIN devices d ON d.id = r.device_id
           WHERE r.event_ts >= (now() AT TIME ZONE 'utc')
                              - make_interval(days => %s)
        ) x
       WHERE x.rn <= %s
       ORDER BY x.dev_id, x.event_ts ASC
        """,
        (lookback_days, max_snapshots_per_device),
    )
    out: List[Tuple[str, str, Dict[str, Any], datetime]] = []
    for dev_id, device_key, payload, event_ts in cur.fetchall():
        pl = parse_payload(payload)
        out.append((str(dev_id), str(device_key or ""), pl, event_ts))
    return out


def fetch_site_id_for_device(conn: Any, device_uuid: str) -> Optional[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT current_site_id::text FROM devices WHERE id = %s::uuid",
        (device_uuid,),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return str(row[0])


def has_open_ml_auto_incident(conn: Any, device_uuid: str) -> bool:
    cur = conn.cursor()
    pat = f"%{ML_INCIDENT_MARKER}%"
    cur.execute(
        """
        SELECT 1 FROM incidents
         WHERE device_id = %s::uuid
           AND closed_at IS NULL
           AND notes::text LIKE %s
         LIMIT 1
        """,
        (device_uuid, pat),
    )
    return cur.fetchone() is not None


def _create_job_run(trigger_source: str, config: Dict[str, Any]) -> int:
    """Inserta una fila en ml_job_runs con status='running' y retorna su id.
    Usa una conexión separada con autocommit para que el registro persista
    incluso si el job falla y hace rollback de la transacción principal."""
    conn = get_connection()
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO ml_job_runs (status, trigger_source, config)
            VALUES ('running', %s, %s::jsonb)
            RETURNING id
            """,
            (trigger_source, json.dumps(config)),
        )
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def _finish_job_run(job_run_id: int, stats: Dict[str, Any]) -> None:
    conn = get_connection()
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE ml_job_runs SET
                status               = 'completed',
                completed_at         = now(),
                devices_processed    = %s,
                predictions_inserted = %s,
                incidents_inserted   = %s,
                devices_deactivated  = %s,
                skipped_no_rows      = %s,
                errors               = %s::jsonb
            WHERE id = %s
            """,
            (
                stats.get("devices_processed", 0),
                stats.get("predictions_inserted", 0),
                stats.get("incidents_inserted", 0),
                stats.get("devices_deactivated", 0),
                stats.get("skipped_no_rows", 0),
                json.dumps(stats.get("errors", []), default=str),
                job_run_id,
            ),
        )
    finally:
        conn.close()


def _fail_job_run(job_run_id: int, error: Exception) -> None:
    conn = get_connection()
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE ml_job_runs SET
                status        = 'failed',
                completed_at  = now(),
                error_summary = %s
            WHERE id = %s
            """,
            (str(error), job_run_id),
        )
    except Exception:
        logger.exception("Could not mark job_run %d as failed", job_run_id)
    finally:
        conn.close()


def insert_ml_prediction(
    cur: Any,
    *,
    device_uuid: str,
    site_id: Optional[str],
    summary: Dict[str, Any],
    model_name: str,
    model_version: str,
    horizon_minutes: Optional[int],
    feature_ts: Optional[datetime],
    job_run_id: Optional[int] = None,
) -> int:
    predicted_at = datetime.now(timezone.utc)
    class_prob = _round_prob(float(summary.get("predicted_failure_risk") or 0.0))
    ref = {
        "worst_risk_level": summary.get("worst_risk_level"),
        "predicted_failure_risk": summary.get("predicted_failure_risk"),
        "pct_anomalos_recent": summary.get("pct_anomalos_recent"),
        "main_risk_factors": summary.get("main_risk_factors"),
        "total_snapshots": summary.get("total_snapshots"),
    }
    cur.execute(
        """
        INSERT INTO ml_predictions (
          model_name, model_version, predicted_at, device_id, site_id,
          horizon_minutes, class_label, class_prob, eta_minutes, feature_ts,
          features_ref, job_run_id
        ) VALUES (
          %s, %s, %s, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s
        )
        RETURNING id
        """,
        (
            model_name,
            model_version,
            predicted_at,
            device_uuid,
            site_id,
            horizon_minutes,
            str(summary.get("worst_risk_level") or "Bajo"),
            class_prob,
            None,
            feature_ts,
            json.dumps(ref, default=str),
            job_run_id,
        ),
    )
    rid = cur.fetchone()
    if not rid:
        raise RuntimeError("ml_predictions insert returned no id")
    return int(rid[0])


def insert_ml_auto_incident(
    cur: Any,
    *,
    device_uuid: str,
    site_id: Optional[str],
    summary: Dict[str, Any],
    device_key: str,
    source_ml_prediction_id: int,
) -> None:
    opened_at = datetime.now(timezone.utc)
    symptom = incident_symptom(summary)
    severity = severity_for_risk_level(str(summary.get("worst_risk_level")))
    notes = incident_notes_json(summary, device_key or None)
    cur.execute(
        """
        INSERT INTO incidents (
          device_id, site_id, opened_at, symptom, root_cause, severity, notes,
          source_ml_prediction_id
        ) VALUES (
          %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s
        )
        """,
        (
            device_uuid,
            site_id,
            opened_at,
            symptom,
            "predictivo_ml",
            severity,
            notes,
            source_ml_prediction_id,
        ),
    )


def process_ml_risk_job(trigger_source: str = "schedule") -> Dict[str, Any]:
    lookback = int(os.environ.get("ML_RISK_LOOKBACK_DAYS", "30"))
    max_per = int(os.environ.get("ML_MAX_SNAPSHOTS_PER_DEVICE", "5000"))
    model_name = os.environ.get("ML_MODEL_NAME", "device_risk_if")
    model_version = os.environ.get("ML_MODEL_VERSION", "1")
    horizon = int(os.environ.get("ML_HORIZON_MINUTES", "60"))

    config = {
        "lookback_days": lookback,
        "max_snapshots_per_device": max_per,
        "model_name": model_name,
        "model_version": model_version,
        "horizon_minutes": horizon,
    }
    job_run_id = _create_job_run(trigger_source, config)
    logger.info("ml_risk_job started job_run_id=%d trigger=%s", job_run_id, trigger_source)

    stats: Dict[str, Any] = {
        "job_run_id": job_run_id,
        "devices_processed": 0,
        "predictions_inserted": 0,
        "incidents_inserted": 0,
        "skipped_no_rows": 0,
        "errors": [],
    }

    conn = get_connection()
    try:
        rows = fetch_snapshots_for_ml(conn, lookback_days=lookback, max_snapshots_per_device=max_per)
        by_dev: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        keys: Dict[str, str] = {}
        ts_max: Dict[str, datetime] = {}
        for dev_id, device_key, payload, event_ts in rows:
            feat = extract_features_from_json(payload)
            by_dev[dev_id].append(feat)
            keys[dev_id] = device_key
            ts_max[dev_id] = event_ts

        cur = conn.cursor()
        for dev_uuid, feats in by_dev.items():
            try:
                if not feats:
                    stats["skipped_no_rows"] += 1
                    continue
                df = pd.DataFrame(feats)
                if "timestamp" not in df.columns or df["timestamp"].isna().all():
                    stats["skipped_no_rows"] += 1
                    continue
                summary = analyze_device(df, dev_uuid)
                site_id = fetch_site_id_for_device(conn, dev_uuid)
                fts = ts_max.get(dev_uuid)
                pred_id = insert_ml_prediction(
                    cur,
                    device_uuid=dev_uuid,
                    site_id=site_id,
                    summary=summary,
                    model_name=model_name,
                    model_version=model_version,
                    horizon_minutes=horizon,
                    feature_ts=fts,
                    job_run_id=job_run_id,
                )
                stats["predictions_inserted"] += 1
                stats["devices_processed"] += 1

                if should_open_incident(summary) and not has_open_ml_auto_incident(
                    conn, dev_uuid
                ):
                    try:
                        insert_ml_auto_incident(
                            cur,
                            device_uuid=dev_uuid,
                            site_id=site_id,
                            summary=summary,
                            device_key=keys.get(dev_uuid, ""),
                            source_ml_prediction_id=pred_id,
                        )
                        stats["incidents_inserted"] += 1
                    except Exception as inc_err:
                        logger.warning(
                            "ml_auto_incident skipped device=%s: %s "
                            "(apply migrations/003_incidents_source_ml_prediction.sql if missing column)",
                            dev_uuid,
                            inc_err,
                        )
            except Exception as e:
                logger.exception("ml job device=%s: %s", dev_uuid, e)
                stats["errors"].append({"device_id": dev_uuid, "error": str(e)})

        # Sync device status: devices with readings in the lookback window → ACTIVE,
        # devices with no readings at all → INACTIVE (they've stopped reporting).
        found_ids = list(by_dev.keys())
        if found_ids:
            cur.execute(
                """
                UPDATE devices SET status = 'ACTIVE'
                WHERE id = ANY(%s::uuid[])
                  AND status = 'INACTIVE'
                """,
                (found_ids,),
            )
            reactivated = cur.rowcount
            if reactivated:
                logger.info("ml_risk_job: reactivated %d device(s)", reactivated)

        cur.execute(
            """
            UPDATE devices SET status = 'INACTIVE'
            WHERE status = 'ACTIVE'
              AND id NOT IN (
                SELECT device_id FROM readings_raw_parent
                WHERE event_ts >= (now() AT TIME ZONE 'utc') - make_interval(days => %s)
              )
            """,
            (lookback,),
        )
        deactivated = cur.rowcount
        if deactivated:
            logger.info("ml_risk_job: marked %d device(s) INACTIVE (no readings in %d days)", deactivated, lookback)
        stats["devices_deactivated"] = deactivated

        conn.commit()
        _finish_job_run(job_run_id, stats)
        logger.info("ml_risk_job completed job_run_id=%d stats=%s", job_run_id, stats)
        return stats
    except Exception as exc:
        conn.rollback()
        _fail_job_run(job_run_id, exc)
        raise
    finally:
        conn.close()
