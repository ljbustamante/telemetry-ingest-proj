#!/usr/bin/env python3
"""Run ML risk job locally (load .env, then execute same logic as Lambda)."""
from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

# repo root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from src.application.ml_risk_job_service import run_ml_risk_job  # noqa: E402


def main() -> None:
    stats = run_ml_risk_job()
    print(json.dumps(stats, indent=2, default=str))


if __name__ == "__main__":
    main()
