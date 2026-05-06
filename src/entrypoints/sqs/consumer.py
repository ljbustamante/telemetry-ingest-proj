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
    # #region agent log
    import time as _time, os as _os, json as _json3
    def _dbg3(msg, data, hyp):
        entry = _json3.dumps({"sessionId":"69d890","timestamp":int(_time.time()*1000),"location":"consumer.py:handle","message":msg,"data":data,"hypothesisId":hyp,"runId":"run1"})
        try:
            _p = "/home/ljbustamante/upc/telemetry-ingest-proj/.cursor/debug-69d890.log"
            _os.makedirs(_os.path.dirname(_p), exist_ok=True)
            open(_p,"a").write(entry+"\n")
        except Exception: pass
        logger.info("debug_agent: %s | %s", msg, _json3.dumps(data))
    _dbg3("consumer.handle: INVOKED", {"record_count": len(records)}, "H2-H3-H4")
    # #endregion
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
            # #region agent log
            _dbg3("consumer.handle: VALIDATION FAILED", {"errors": ve.errors()[:2]}, "H3")
            # #endregion
        except Exception as e:
            bad += 1
            logger.exception("Error parseando record: %s", e)

    # #region agent log
    _dbg3("consumer.handle: after parsing", {"ok": ok, "bad": bad, "valid_items": len(valid_items)}, "H3-H4")
    # #endregion
    if valid_items:
        try:
            writer.upsert_raw_batch(valid_items)
            # #region agent log
            _dbg3("consumer.handle: upsert_raw_batch SUCCESS", {"count": len(valid_items)}, "H4")
            # #endregion
        except Exception as e:
            # Si falla el batch, deja trazas claras (el caller SQS reenviará si aplica)
            logger.exception("Fallo al persistir batch en PostgreSQL: %s", e)
            # #region agent log
            _dbg3("consumer.handle: upsert_raw_batch FAILED", {"error": str(e)}, "H4")
            # #endregion
            raise

    logger.info("Procesados ok=%s, bad=%s", ok, bad)
    return {"ok": ok, "bad": bad}
