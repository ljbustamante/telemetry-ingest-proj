import json
from datetime import datetime, timezone

from src.domain.payload_curated_mapping import (
    build_hardware_snapshot,
    map_payload_to_curated_row,
)


def test_map_payload_to_curated_row_basic():
    payload = {
        "Telemetry": {
            "Cpu": {"Pct": 10.5, "TempC": 55, "TempCAvg": 54, "TempCMax": 60, "ClockMhz": 2400},
            "Memory": {"UsedMb": 8000, "UsedPct": 50.0},
            "Battery": {"ChargePct": 90, "Status": "ac", "CycleCount": 120},
            "Os": {"Name": "Windows", "Version": "11", "Build": "22631"},
        },
        "Derived": {"HoursSinceLastBoot": 12.5, "CpuTempToLoadRatio": 2.5},
        "Risk": {"RiskScore": 0.42, "RiskBucket": "Medio", "TopFactors": ["temp"]},
    }
    ts = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    row = map_payload_to_curated_row(
        payload,
        device_id="00000000-0000-0000-0000-000000000001",
        site_id=None,
        event_ts=ts,
        received_at=ts,
        agent_version="1.0",
        schema_version="v1",
        sample_period_s=60,
        source_raw_id=99,
    )
    assert row["cpu_pct"] is not None and float(row["cpu_pct"]) == 10.5
    assert row["os_name"] == "Windows"
    assert row["battery_status"] == "ac"
    assert row["risk_top_factors"] == ["temp"]
    assert json.loads(row["extra"])["etl_source_raw_id"] == 99


def test_build_hardware_snapshot_gpu_rows():
    payload = {
        "Telemetry": {
            "Machine": {"Manufacturer": "ACME", "Model": "Laptop", "SerialNumberHash": "abc"},
            "Bios": {"Vendor": "AMI", "Version": "1.0"},
            "Cpu": {"Model": "Intel X", "CoresPhysical": 4, "ThreadsLogical": 8},
            "Memory": {"TotalMb": 16384},
            "Gpu": [{"Vendor": "NVIDIA", "Model": "RTX", "VramMb": 8192, "DriverVersion": "560"}],
        },
    }
    ts = datetime(2025, 6, 1, tzinfo=timezone.utc)
    snap, gpus, drives = build_hardware_snapshot(
        payload, device_id="00000000-0000-0000-0000-000000000002", snapshot_ts=ts
    )
    assert snap["machine_mfr"] == "ACME"
    assert len(gpus) == 1 and gpus[0]["vendor"] == "NVIDIA"
    assert drives == []
