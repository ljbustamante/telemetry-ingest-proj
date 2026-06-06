"""Entry point for the scheduled / HTTP ML risk job."""
from __future__ import annotations

from typing import Any, Dict

from ..infrastructure.repositories.ml_risk_job_repository import process_ml_risk_job


def run_ml_risk_job(trigger_source: str = "schedule") -> Dict[str, Any]:
    return process_ml_risk_job(trigger_source=trigger_source)
