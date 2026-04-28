from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from pydantic import ValidationError

from ...domain.models import TelemetryIngest
from ...infrastructure.repositories.postgres_raw_repository import PostgresRawWriter

logger = logging.getLogger("telemetry-sqs")
logger.setLevel(logging.INFO)

writer = PostgresRawWriter()


def handle(event: Dict[str, Any], context: Any) -> Dict[str, int]:
    """
    Consumer SQS sin dependencias de Powertools:
    - Valida cada record con Pydantic
    - Inserta en lotes en readings_raw_parent (dedupe por ON CONFLICT)
    - Devuelve contadores para observabilidad en CloudWatch/logs locales
    """
    records: List[Dict[str, Any]] = event.get("Records", []) or []
    valid_items: List[TelemetryIngest] = []
    ok, bad = 0, 0

    for rec in records:
        try:
            body = rec.get("body") or "{}"
            data = json.loads(body)
            t = TelemetryIngest.model_validate(data)
            valid_items.append(t)
            ok += 1
        except ValidationError as ve:
            bad += 1
            logger.warning("Record inválido: %s", ve.errors())
        except Exception as e:
            bad += 1
            logger.exception("Error parseando record: %s", e)

    if valid_items:
        try:
            writer.upsert_raw_batch(valid_items)
        except Exception as e:
            # Si falla el batch, deja trazas claras (el caller SQS reenviará si aplica)
            logger.exception("Fallo al persistir batch en PostgreSQL: %s", e)
            raise

    logger.info("Procesados ok=%s, bad=%s", ok, bad)
    return {"ok": ok, "bad": bad}
