"""
Feature extraction from full telemetry payload (same paths as root features.py).
Used by the ML risk job; lives under src/ for Lambda packaging.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .json_paths import safe_get


def extract_features_from_json(data: dict) -> Dict[str, Any]:
    row: Dict[str, Any] = {}

    row["device_id"] = safe_get(data, ["Identity", "DeviceId"])
    row["location"] = safe_get(data, ["Identity", "Location"])
    row["timestamp"] = data.get("CollectedAt")

    row["cpu_pct"] = safe_get(data, ["Telemetry", "Cpu", "Pct"])
    row["cpu_temp_c"] = safe_get(data, ["Telemetry", "Cpu", "TempC"])
    row["cpu_temp_avg_c"] = safe_get(data, ["Telemetry", "Cpu", "TempCAvg"])
    row["cpu_temp_max_c"] = safe_get(data, ["Telemetry", "Cpu", "TempCMax"])
    row["cpu_clock_mhz"] = safe_get(data, ["Telemetry", "Cpu", "ClockMhz"])
    row["cpu_thermal_throttling"] = (
        1 if safe_get(data, ["Telemetry", "Cpu", "ThermalThrottling"]) else 0
    )
    row["cpu_throttle_events"] = safe_get(
        data, ["Telemetry", "Cpu", "ThrottleEventsSinceBoot"]
    )
    row["cpu_temp_to_load_ratio"] = safe_get(data, ["Derived", "CpuTempToLoadRatio"])

    gpus = safe_get(data, ["Telemetry", "Gpu"], default=[])
    if isinstance(gpus, list):
        for idx in range(min(2, len(gpus))):
            g = gpus[idx] or {}
            prefix = f"gpu{idx}_"
            row[prefix + "pct"] = g.get("Pct")
            row[prefix + "temp_c"] = g.get("TempC")
            row[prefix + "hotspot_c"] = g.get("HotspotC")

    row["mem_used_mb"] = safe_get(data, ["Telemetry", "Memory", "UsedMb"])
    row["mem_used_pct"] = safe_get(data, ["Telemetry", "Memory", "UsedPct"])

    row["io_window_s"] = safe_get(data, ["Telemetry", "Io", "WindowSeconds"])
    row["io_avg_ms"] = safe_get(data, ["Telemetry", "Io", "AggregateAvgMs"])
    row["io_p95_ms"] = safe_get(data, ["Telemetry", "Io", "AggregateP95Ms"])

    row["io5m_window_s"] = safe_get(data, ["Telemetry", "Io5m", "WindowSeconds"])
    row["io5m_avg_ms"] = safe_get(data, ["Telemetry", "Io5m", "AggregateAvgMs"])
    row["io5m_p95_ms"] = safe_get(data, ["Telemetry", "Io5m", "AggregateP95Ms"])

    row["battery_pct"] = safe_get(data, ["Telemetry", "Battery", "ChargePct"])
    row["battery_cycle_count"] = safe_get(data, ["Telemetry", "Battery", "CycleCount"])
    row["battery_status_ac"] = (
        1 if safe_get(data, ["Telemetry", "Battery", "Status"]) == "ac" else 0
    )

    row["disk_health_score"] = safe_get(data, ["Derived", "DiskHealthScore"])
    row["hours_since_boot"] = safe_get(data, ["Derived", "HoursSinceLastBoot"])

    smart_sata = safe_get(data, ["Telemetry", "Smart", "Sata"], default=[])
    total_reallocated = 0
    max_reallocated = 0
    max_power_on_hours = 0
    if isinstance(smart_sata, list):
        for e in smart_sata:
            try:
                reall = int(e.get("ReallocatedSectors", 0) or 0)
                poh = int(e.get("PowerOnHours", 0) or 0)
            except Exception:
                reall = 0
                poh = 0
            total_reallocated += reall
            max_reallocated = max(max_reallocated, reall)
            max_power_on_hours = max(max_power_on_hours, poh)

    row["smart_reallocated_sectors_total"] = total_reallocated
    row["smart_reallocated_sectors_max"] = max_reallocated
    row["smart_power_on_hours_max"] = max_power_on_hours

    row["whea_corrected"] = safe_get(data, ["Events", "Whea", "CorrectedSinceBoot"])
    row["whea_uncorrected"] = safe_get(data, ["Events", "Whea", "UncorrectedSinceBoot"])

    row["bugcheck_7d"] = safe_get(data, ["Events", "BugcheckCount7d"])

    storage_counts = safe_get(data, ["Telemetry", "Storage30d", "Counts"], default={})
    if isinstance(storage_counts, dict):
        for code, value in storage_counts.items():
            row[f"storage30d_count_{code}"] = value

    row["risk_score"] = safe_get(data, ["Risk", "RiskScore"])

    return row
