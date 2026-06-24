from __future__ import annotations

from src.domain.telemetry_features import extract_features_from_json


def _base_payload() -> dict:
    return {
        "CollectedAt": "2024-01-01T00:00:00Z",
        "Identity": {"DeviceId": "dev-abc", "Location": "rack-1"},
        "Telemetry": {
            "Cpu": {
                "Pct": 45.0,
                "TempC": 72.0,
                "TempCAvg": 70.0,
                "TempCMax": 75.0,
                "ClockMhz": 3200,
                "ThermalThrottling": False,
                "ThrottleEventsSinceBoot": 0,
            },
            "Gpu": [{"Pct": 80.0, "TempC": 70.0, "HotspotC": 85.0}],
            "Memory": {"UsedMb": 8192, "UsedPct": 50.0},
            "Io": {"WindowSeconds": 60, "AggregateAvgMs": 5.0, "AggregateP95Ms": 20.0},
            "Io5m": {"WindowSeconds": 300, "AggregateAvgMs": 4.0, "AggregateP95Ms": 18.0},
            "Battery": {"ChargePct": 95, "CycleCount": 100, "Status": "ac"},
            "Smart": {"Sata": [{"ReallocatedSectors": 2, "PowerOnHours": 5000}]},
            "Storage30d": {"Counts": {"153": 2, "129": 1}},
        },
        "Events": {
            "Whea": {"CorrectedSinceBoot": 0, "UncorrectedSinceBoot": 0},
            "BugcheckCount7d": 0,
        },
        "Derived": {
            "DiskHealthScore": 98.0,
            "HoursSinceLastBoot": 24.0,
            "CpuTempToLoadRatio": 1.6,
        },
    }


def test_extract_identity_fields():
    feat = extract_features_from_json(_base_payload())
    assert feat["device_id"] == "dev-abc"
    assert feat["location"] == "rack-1"
    assert feat["timestamp"] == "2024-01-01T00:00:00Z"


def test_extract_cpu_fields():
    feat = extract_features_from_json(_base_payload())
    assert feat["cpu_pct"] == 45.0
    assert feat["cpu_temp_max_c"] == 75.0
    assert feat["cpu_thermal_throttling"] == 0


def test_extract_cpu_thermal_throttling_true():
    p = _base_payload()
    p["Telemetry"]["Cpu"]["ThermalThrottling"] = True
    feat = extract_features_from_json(p)
    assert feat["cpu_thermal_throttling"] == 1


def test_extract_gpu_fields():
    feat = extract_features_from_json(_base_payload())
    assert feat["gpu0_pct"] == 80.0
    assert feat["gpu0_hotspot_c"] == 85.0


def test_extract_battery_ac_status():
    feat = extract_features_from_json(_base_payload())
    assert feat["battery_status_ac"] == 1


def test_extract_battery_non_ac_status():
    p = _base_payload()
    p["Telemetry"]["Battery"]["Status"] = "battery"
    feat = extract_features_from_json(p)
    assert feat["battery_status_ac"] == 0


def test_extract_smart_reallocated_aggregates():
    p = _base_payload()
    p["Telemetry"]["Smart"]["Sata"] = [
        {"ReallocatedSectors": 3, "PowerOnHours": 1000},
        {"ReallocatedSectors": 7, "PowerOnHours": 2000},
    ]
    feat = extract_features_from_json(p)
    assert feat["smart_reallocated_sectors_total"] == 10
    assert feat["smart_reallocated_sectors_max"] == 7
    assert feat["smart_power_on_hours_max"] == 2000


def test_extract_storage30d_counts():
    feat = extract_features_from_json(_base_payload())
    assert feat["storage30d_count_153"] == 2
    assert feat["storage30d_count_129"] == 1


def test_extract_missing_sections_return_none():
    feat = extract_features_from_json({})
    assert feat["device_id"] is None
    assert feat["cpu_pct"] is None
    assert feat["timestamp"] is None
    assert feat["disk_health_score"] is None


def test_extract_empty_gpu_list():
    p = _base_payload()
    p["Telemetry"]["Gpu"] = []
    feat = extract_features_from_json(p)
    assert "gpu0_pct" not in feat


def test_extract_whea_events():
    p = _base_payload()
    p["Events"]["Whea"]["CorrectedSinceBoot"] = 3
    p["Events"]["Whea"]["UncorrectedSinceBoot"] = 1
    feat = extract_features_from_json(p)
    assert feat["whea_corrected"] == 3
    assert feat["whea_uncorrected"] == 1
