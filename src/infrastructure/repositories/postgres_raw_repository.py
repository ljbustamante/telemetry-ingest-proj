from __future__ import annotations

import json
import hashlib
from typing import List, Dict, Any

from aws_lambda_powertools import Logger

from ...domain.models import TelemetryIngest
from ..db.connection import get_connection

logger = Logger(service="telemetry-sqs")


def _json_c14n(d: Dict[str, Any]) -> str:
    """
    Canonical JSON (ordenado y sin espacios) para que el hash sea estable
    independientemente del formateo.
    """
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


class PostgresRawWriter:
    """
    Repositorio para insertar lecturas RAW en readings_raw_parent.

    - Asegura existencia de devices(device_key)
    - Enriquecimiento opcional de devices.hostname_hash / customer_code
      leyendo de payload.Identity.HostnameHash / payload.Identity.CustomerId
    - Inserta lote en readings_raw_parent con deduplicación:
      ON CONFLICT (device_id, event_ts, payload_hash) DO NOTHING
    """

    def upsert_raw_batch(self, items: List[TelemetryIngest]) -> None:
        if not items:
            return

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                # 1) Resolver IDs de device para todos los device_key en el lote
                keys: List[str] = [i.device_key for i in items]
                cur.execute(
                    "SELECT device_key, id FROM devices WHERE device_key = ANY(%s)",
                    (keys,),
                )
                found: Dict[str, str] = dict(cur.fetchall()) if cur.rowcount else {}

                # 2) Insertar los device_key faltantes
                missing = [k for k in keys if k not in found]
                if missing:
                    args = [(k,) for k in sorted(set(missing))]
                    cur.executemany(
                        """
                        INSERT INTO devices (device_key)
                        VALUES (%s)
                        ON CONFLICT (device_key) DO NOTHING
                        """,
                        args,
                    )
                    # Reconsultar el mapping completo
                    cur.execute(
                        "SELECT device_key, id FROM devices WHERE device_key = ANY(%s)",
                        (keys,),
                    )
                    found = dict(cur.fetchall())

                # 3) Enriquecer opcionalmente devices con hostname_hash / customer_code
                #    (solo si vienen en el snapshot dentro de payload.Identity.*)
                enrich_args = []
                for t in items:
                    identity = (t.payload or {}).get("Identity", {})
                    hh = identity.get("HostnameHash")
                    cc = identity.get("CustomerId")
                    if hh is not None or cc is not None:
                        enrich_args.append((hh, cc, t.device_key))

                if enrich_args:
                    cur.executemany(
                        """
                        UPDATE devices
                           SET hostname_hash = COALESCE(%s, hostname_hash),
                               customer_code  = COALESCE(customer_code, %s)
                         WHERE device_key = %s
                        """,
                        enrich_args,
                    )

                # 4) Insertar el lote en readings_raw_parent con deduplicación
                values_sql_parts: List[str] = []
                params: List[Any] = []

                for t in items:
                    dev_id = found[t.device_key]

                    # hash del snapshot completo (payload) canonicalizado
                    payload_c14n = _json_c14n(t.payload)
                    payload_hash = hashlib.sha256(payload_c14n.encode("utf-8")).digest()

                    # Construir fila
                    values_sql_parts.append(
                        "(%s, to_timestamp(%s/1000.0), now(), %s, %s, %s, %s, %s)"
                    )
                    params.extend(
                        [
                            dev_id,                  # device_id (uuid)
                            t.event_ts_ms,           # event_ts (ms → to_timestamp)
                            t.agent_version,         # agent_version
                            t.schema_version,        # schema_version
                            t.sample_period_s,       # sample_period_s
                            payload_hash,            # payload_hash (bytea)
                            json.dumps(t.payload),   # payload (jsonb)
                        ]
                    )

                if values_sql_parts:
                    sql = (
                        "INSERT INTO readings_raw_parent "
                        "(device_id, event_ts, received_at, agent_version, schema_version, "
                        " sample_period_s, payload_hash, payload) "
                        f"VALUES {', '.join(values_sql_parts)} "
                        "ON CONFLICT (device_id, event_ts, payload_hash) DO NOTHING"
                    )
                    cur.execute(sql, params)

            conn.commit()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error({"raw_upsert_error": str(e)})
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass
