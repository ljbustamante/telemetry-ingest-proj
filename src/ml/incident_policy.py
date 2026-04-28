"""
Policy for optional auto-creation of incidents from ML risk job.
Configured via environment variables (see serverless.yml / .env).
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

# Substring in incidents.notes (JSON text) for deduplication of open auto-incidents.
ML_INCIDENT_MARKER = "device_risk_v1"

_LEVEL_RANK = {"Bajo": 0, "Medio": 1, "Alto": 2}


def ml_auto_incident_enabled() -> bool:
    v = os.environ.get("ML_AUTO_INCIDENT_ENABLED", "false").lower().strip()
    return v in ("1", "true", "yes", "on")


def ml_auto_incident_min_rank() -> int:
    """Minimum risk rank (0=Bajo, 1=Medio, 2=Alto) to open an auto-incident."""
    lvl = os.environ.get("ML_AUTO_INCIDENT_MIN_LEVEL", "Alto").strip()
    return _LEVEL_RANK.get(lvl, 2)


def risk_level_rank(level: str | None) -> int:
    if not level:
        return 0
    return _LEVEL_RANK.get(str(level).strip(), 0)


def should_open_incident(summary: Dict[str, Any]) -> bool:
    if not ml_auto_incident_enabled():
        return False
    w = summary.get("worst_risk_level") or "Bajo"
    return risk_level_rank(str(w)) >= ml_auto_incident_min_rank()


def severity_for_risk_level(level: str | None) -> str:
    """DB text; keep English tokens for downstream integrations."""
    return {"Alto": "high", "Medio": "medium", "Bajo": "low"}.get(
        (level or "Bajo").strip(), "low"
    )


def incident_symptom(summary: Dict[str, Any]) -> str:
    lvl = summary.get("worst_risk_level") or "?"
    return f"[ML] Riesgo predictivo: {lvl}"


def incident_notes_json(summary: Dict[str, Any], device_key: Optional[str]) -> str:
    import json

    payload = {
        "ml_auto": ML_INCIDENT_MARKER,
        "device_key": device_key,
        "worst_risk_level": summary.get("worst_risk_level"),
        "predicted_failure_risk": summary.get("predicted_failure_risk"),
        "main_risk_factors": summary.get("main_risk_factors"),
        "total_snapshots": summary.get("total_snapshots"),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)
