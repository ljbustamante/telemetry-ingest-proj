"""Hardware paths as sent by the real agent (root Hardware / Cpu / Gpus / Storage)."""

from datetime import datetime, timezone

from src.domain.payload_curated_mapping import build_hardware_snapshot


def test_build_hardware_snapshot_agent_inventory_shape():
    payload = {
        "Hardware": {
            "Machine": {
                "Manufacturer": "Dell Inc.",
                "ProductName": "Inspiron 15 5510",
                "SerialHash": "4c3e97815de00010",
            },
            "Baseboard": {
                "BiosUefi": {
                    "Vendor": "Dell Inc.",
                    "Version": "2.18.0",
                    "Date": "2023-03-12T19:00:00-05:00",
                }
            },
        },
        "Cpu": {
            "Vendor": "GenuineIntel",
            "Model": "11th Gen Intel(R) Core(TM) i7-11390H @ 3.40GHz",
            "CoresPhysical": 4,
            "ThreadsLogical": 8,
        },
        "Memory": {"TotalMb": 32510},
        "Gpus": [
            {
                "Vendor": "Intel Corporation",
                "Model": "Intel(R) Iris(R) Xe Graphics",
                "VramMb": 128,
                "DriverVersion": "31.0.101.5333",
            }
        ],
        "Storage": [
            {
                "DriveId": "\\\\.\\PHYSICALDRIVE0",
                "Interface": "SCSI",
                "Model": "KBG40ZNS512G NVMe KIOXIA 512GB",
                "CapacityGb": 476,
                "SerialHash": "fedcf2c6c2f7d617",
                "TemperatureC": 49,
            }
        ],
    }
    ts = datetime(2025, 10, 29, tzinfo=timezone.utc)
    snap, gpus, drives = build_hardware_snapshot(
        payload, device_id="00000000-0000-0000-0000-000000000099", snapshot_ts=ts
    )
    assert snap["machine_mfr"] == "Dell Inc."
    assert snap["machine_product"] == "Inspiron 15 5510"
    assert snap["machine_serial_hash"] == "4c3e97815de00010"
    assert snap["bios_vendor"] == "Dell Inc."
    assert snap["bios_version"] == "2.18.0"
    assert snap["cpu_model"] and "Intel" in snap["cpu_model"]
    assert snap["mem_total_mb"] == 32510
    assert len(gpus) >= 1
    assert len(drives) == 1
    assert drives[0]["model"] == "KBG40ZNS512G NVMe KIOXIA 512GB"


def test_gpu_inventory_preferred_over_telemetry_only_names():
    """Root Gpus has vendor/VRAM; Telemetry.Gpu is metrics-only — do not duplicate partial rows."""
    payload = {
        "Gpus": [
            {
                "Vendor": "NVIDIA",
                "Model": "NVIDIA GeForce MX450",
                "VramMb": 2048,
                "DriverVersion": "32.0.15",
            }
        ],
        "Telemetry": {
            "Gpu": [
                {"Name": "NVIDIA GeForce MX450", "TempC": 70},
                {"Name": "Intel(R) Iris(R) Xe Graphics", "Pct": 0},
            ]
        },
    }
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    _, gpus, _ = build_hardware_snapshot(
        payload, device_id="00000000-0000-0000-0000-000000000001", snapshot_ts=ts
    )
    assert len(gpus) == 1
    assert gpus[0]["vendor"] == "NVIDIA"
    assert gpus[0]["vram_mb"] == 2048


def test_storage_merged_with_telemetry_disks():
    payload = {
        "Storage": [
            {
                "DriveId": "\\\\.\\PHYSICALDRIVE0",
                "Interface": "SCSI",
                "Model": "KIOXIA NVMe",
                "CapacityGb": 476,
                "SerialHash": "abc",
            }
        ],
        "Telemetry": {
            "Disks": [{"DriveId": "\\\\.\\PHYSICALDRIVE0", "TempC": 49}]
        },
    }
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    _, _, drives = build_hardware_snapshot(
        payload, device_id="00000000-0000-0000-0000-000000000001", snapshot_ts=ts
    )
    assert len(drives) == 1
    assert drives[0]["model"] == "KIOXIA NVMe"
    assert drives[0]["temperature_c"] is not None
    assert float(drives[0]["temperature_c"]) == 49
