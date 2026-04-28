from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import Json

from ..db.connection import get_connection
from ...domain.payload_curated_mapping import (
    build_hardware_snapshot,
    map_payload_to_curated_row,
    parse_payload,
)

logger = logging.getLogger("curation-etl")


class CurationEtlRepository:
    """Incremental raw -> readings_curated_parent + optional hardware snapshots."""

    PIPELINE_DEFAULT = "curation_v1"

    def __init__(self, conn: Optional[Any] = None) -> None:
        self._owns_conn = conn is None
        self._conn = conn or get_connection()

    def close(self) -> None:
        if self._owns_conn and self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __enter__(self) -> "CurationEtlRepository":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            try:
                self._conn.rollback()
            except Exception:
                pass
        self.close()

    def lock_watermark(self, pipeline: str) -> int:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO etl_curation_watermark (pipeline, last_raw_id)
            VALUES (%s, 0)
            ON CONFLICT (pipeline) DO NOTHING
            """,
            (pipeline,),
        )
        cur.execute(
            """
            SELECT last_raw_id FROM etl_curation_watermark
            WHERE pipeline = %s FOR UPDATE
            """,
            (pipeline,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def update_watermark(self, pipeline: str, last_raw_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE etl_curation_watermark
               SET last_raw_id = %s, updated_at = now()
             WHERE pipeline = %s
            """,
            (last_raw_id, pipeline),
        )

    def fetch_raw_batch(self, after_id: int, limit: int) -> List[Tuple[Any, ...]]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT r.id, r.device_id, r.event_ts, r.received_at,
                   r.agent_version, r.schema_version, r.sample_period_s, r.payload
              FROM readings_raw_parent r
             WHERE r.id > %s
             ORDER BY r.id ASC
             LIMIT %s
            """,
            (after_id, limit),
        )
        return list(cur.fetchall())

    def fetch_site_by_devices(self, device_ids: List[str]) -> Dict[str, Optional[str]]:
        if not device_ids:
            return {}
        cur = self._conn.cursor()
        uniq = list(dict.fromkeys(device_ids))
        ph = ",".join(["%s::uuid"] * len(uniq))
        cur.execute(
            f"""
            SELECT id::text, current_site_id::text
              FROM devices
             WHERE id IN ({ph})
            """,
            uniq,
        )
        out: Dict[str, Optional[str]] = {}
        for did, sid in cur.fetchall():
            out[str(did)] = str(sid) if sid else None
        return out

    def insert_curated(
        self, row: Dict[str, Any]
    ) -> bool:
        """Returns True if a new row was inserted."""
        cur = self._conn.cursor()
        extra_val = row.get("extra")
        if isinstance(extra_val, str):
            extra_param: Any = extra_val
        else:
            extra_param = Json(extra_val) if extra_val is not None else None

        cur.execute(
            """
            INSERT INTO readings_curated_parent (
              device_id, site_id, event_ts, received_at, sample_period_s,
              agent_version, schema_version,
              os_name, os_version, os_build, os_hours_since_boot,
              cpu_pct, cpu_temp_c, cpu_temp_c_avg, cpu_temp_c_max, cpu_clock_mhz,
              mem_used_mb, mem_used_pct,
              battery_charge_pct, battery_status, battery_cycle_count,
              sec_tpm_present, sec_tpm_version, sec_secure_boot, sec_virt_enabled,
              risk_score, risk_bucket, risk_top_factors,
              derived_cpu_temp_to_load, extra
            ) VALUES (
              %(device_id)s::uuid, %(site_id)s::uuid, %(event_ts)s, %(received_at)s, %(sample_period_s)s,
              %(agent_version)s, %(schema_version)s,
              %(os_name)s, %(os_version)s, %(os_build)s, %(os_hours_since_boot)s,
              %(cpu_pct)s, %(cpu_temp_c)s, %(cpu_temp_c_avg)s, %(cpu_temp_c_max)s, %(cpu_clock_mhz)s,
              %(mem_used_mb)s, %(mem_used_pct)s,
              %(battery_charge_pct)s, %(battery_status)s, %(battery_cycle_count)s,
              %(sec_tpm_present)s, %(sec_tpm_version)s, %(sec_secure_boot)s, %(sec_virt_enabled)s,
              %(risk_score)s, %(risk_bucket)s, %(risk_top_factors)s,
              %(derived_cpu_temp_to_load)s, %(extra)s::jsonb
            )
            ON CONFLICT (device_id, event_ts) DO NOTHING
            RETURNING id
            """,
            {
                **row,
                "extra": extra_param,
            },
        )
        inserted = cur.fetchone() is not None
        return inserted

    def get_latest_hardware_fingerprint(
        self, device_id: str
    ) -> Optional[Tuple[Optional[str], Optional[str], Optional[str]]]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT machine_serial_hash, cpu_model, bios_version
              FROM device_hardware_snapshot
             WHERE device_id = %s::uuid
             ORDER BY snapshot_ts DESC
             LIMIT 1
            """,
            (device_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return (row[0], row[1], row[2])

    def insert_hardware_bundle(
        self,
        device_id: str,
        snapshot: Dict[str, Any],
        gpu_rows: List[Dict[str, Any]],
        drive_rows: List[Dict[str, Any]],
    ) -> int:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO device_hardware_snapshot (
              device_id, snapshot_ts,
              machine_mfr, machine_product, machine_serial_hash,
              bios_vendor, bios_version, bios_date,
              cpu_model, cpu_cores_phys, cpu_threads_log, mem_total_mb, extra
            ) VALUES (
              %(device_id)s::uuid, %(snapshot_ts)s,
              %(machine_mfr)s, %(machine_product)s, %(machine_serial_hash)s,
              %(bios_vendor)s, %(bios_version)s, %(bios_date)s,
              %(cpu_model)s, %(cpu_cores_phys)s, %(cpu_threads_log)s, %(mem_total_mb)s, %(extra)s::jsonb
            )
            RETURNING id
            """,
            {
                **snapshot,
                "extra": Json(snapshot.get("extra")) if not isinstance(snapshot.get("extra"), str) else snapshot["extra"],
            },
        )
        hw_id_row = cur.fetchone()
        if not hw_id_row:
            raise RuntimeError("device_hardware_snapshot insert returned no id")
        hw_id = int(hw_id_row[0])

        for g in gpu_rows:
            cur.execute(
                """
                INSERT INTO device_gpu (hw_snapshot_id, vendor, model, vram_mb, driver_version)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (hw_id, g.get("vendor"), g.get("model"), g.get("vram_mb"), g.get("driver_version")),
            )
        for d in drive_rows:
            cur.execute(
                """
                INSERT INTO device_storage_drive (
                  hw_snapshot_id, drive_id, interface, model, capacity_gb, serial_hash, temperature_c
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    hw_id,
                    d.get("drive_id"),
                    d.get("interface"),
                    d.get("model"),
                    d.get("capacity_gb"),
                    d.get("serial_hash"),
                    d.get("temperature_c"),
                ),
            )
        return hw_id

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        try:
            self._conn.rollback()
        except Exception:
            pass


def process_curation_batch(
    *,
    pipeline: str = CurationEtlRepository.PIPELINE_DEFAULT,
    batch_limit: int = 500,
) -> Dict[str, Any]:
    """
    Process up to `batch_limit` readings_raw_parent rows after watermark.
    Commits on success; rolls back on outer failure.
    """
    stats: Dict[str, Any] = {
        "raw_scanned": 0,
        "curated_inserted": 0,
        "curated_skipped": 0,
        "hardware_snapshots": 0,
        "errors": [],
        "last_raw_id_before": None,
        "last_raw_id_after": None,
    }

    repo = CurationEtlRepository()
    try:
        last = repo.lock_watermark(pipeline)
        stats["last_raw_id_before"] = last
        rows = repo.fetch_raw_batch(last, batch_limit)
        stats["raw_scanned"] = len(rows)
        if not rows:
            repo.update_watermark(pipeline, last)
            repo.commit()
            stats["last_raw_id_after"] = last
            return stats

        max_raw_id = max(int(r[0]) for r in rows)
        device_ids = [str(r[1]) for r in rows]
        sites = repo.fetch_site_by_devices(device_ids)

        for r in rows:
            raw_id, dev_uuid, event_ts, received_at, agent_v, schema_v, sample_s, payload_raw = r
            try:
                payload = parse_payload(payload_raw)
                site_id = sites.get(str(dev_uuid))
                curated = map_payload_to_curated_row(
                    payload,
                    device_id=str(dev_uuid),
                    site_id=site_id,
                    event_ts=event_ts,
                    received_at=received_at,
                    agent_version=agent_v,
                    schema_version=schema_v,
                    sample_period_s=sample_s,
                    source_raw_id=int(raw_id),
                )
                if repo.insert_curated(curated):
                    stats["curated_inserted"] += 1
                else:
                    stats["curated_skipped"] += 1

                snap, gpus, drives = build_hardware_snapshot(
                    payload, device_id=str(dev_uuid), snapshot_ts=event_ts
                )
                new_fp = (
                    str(snap.get("machine_serial_hash") or ""),
                    str(snap.get("cpu_model") or ""),
                    str(snap.get("bios_version") or ""),
                )
                has_hw = bool(gpus or drives or any(new_fp))
                prev = repo.get_latest_hardware_fingerprint(str(dev_uuid))
                prev_fp = (
                    None
                    if prev is None
                    else (
                        str(prev[0] or ""),
                        str(prev[1] or ""),
                        str(prev[2] or ""),
                    )
                )
                if has_hw and (prev_fp is None or prev_fp != new_fp):
                    repo.insert_hardware_bundle(str(dev_uuid), snap, gpus, drives)
                    stats["hardware_snapshots"] += 1
            except Exception as e:
                logger.exception("curation row failed raw_id=%s: %s", raw_id, e)
                stats["errors"].append({"raw_id": int(raw_id), "error": str(e)})

        repo.update_watermark(pipeline, max_raw_id)
        repo.commit()
        stats["last_raw_id_after"] = max_raw_id
        return stats
    except Exception as e:
        logger.exception("curation batch failed: %s", e)
        repo.rollback()
        raise
    finally:
        repo.close()
