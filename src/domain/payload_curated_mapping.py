from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .json_paths import safe_get


def _num(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _pct(v: Any) -> Optional[Decimal]:
    """Parse a percentage value and clamp to [0, 100]."""
    d = _num(v)
    if d is None:
        return None
    if d < 0:
        return Decimal("0")
    if d > 100:
        return Decimal("100")
    return d


def _int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def _bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "on")
    return None


def _battery_status_text(payload: Dict[str, Any]) -> Optional[str]:
    st = safe_get(payload, ["Telemetry", "Battery", "Status"])
    if st is None:
        return None
    return str(st)


def _risk_factors(payload: Dict[str, Any]) -> Optional[List[str]]:
    raw = safe_get(payload, ["Risk", "TopFactors"])
    if raw is None:
        return None
    if isinstance(raw, list):
        return [str(x) for x in raw if x is not None]
    if isinstance(raw, str):
        return [raw]
    return None


def _os_block(payload: Dict[str, Any]) -> Dict[str, Any]:
    for path in (["Telemetry", "Os"], ["Os"]):
        block = safe_get(payload, path, None)
        if isinstance(block, dict):
            return block
    return {}


def _sec_block(payload: Dict[str, Any]) -> Dict[str, Any]:
    for path in (
        ["Telemetry", "Security"],
        ["Security"],
        ["SecurityPosture"],
    ):
        block = safe_get(payload, path, None)
        if isinstance(block, dict):
            return block
    return {}


def map_payload_to_curated_row(
    payload: Dict[str, Any],
    *,
    device_id: str,
    site_id: Optional[str],
    event_ts: datetime,
    received_at: datetime,
    agent_version: Optional[str],
    schema_version: Optional[str],
    sample_period_s: Optional[int],
    source_raw_id: int,
) -> Dict[str, Any]:
    """Build column dict for readings_curated_parent INSERT."""
    osb = _os_block(payload)
    sec = _sec_block(payload)

    extra: Dict[str, Any] = {
        "etl_source_raw_id": source_raw_id,
        "cpu_thermal_throttling": bool(
            safe_get(payload, ["Telemetry", "Cpu", "ThermalThrottling"])
        ),
        "io_window_s": safe_get(payload, ["Telemetry", "Io", "WindowSeconds"]),
        "io_avg_ms": safe_get(payload, ["Telemetry", "Io", "AggregateAvgMs"]),
        "io_p95_ms": safe_get(payload, ["Telemetry", "Io", "AggregateP95Ms"]),
    }
    # Optional GPU extras for ML / debugging
    gpus = safe_get(payload, ["Telemetry", "Gpu"], default=[])
    if isinstance(gpus, list):
        extra["gpu_preview"] = gpus[:2]

    return {
        "device_id": device_id,
        "site_id": site_id,
        "event_ts": event_ts,
        "received_at": received_at,
        "sample_period_s": sample_period_s,
        "agent_version": agent_version,
        "schema_version": schema_version,
        "os_name": osb.get("Name") or osb.get("name"),
        "os_version": osb.get("Version") or osb.get("version"),
        "os_build": osb.get("Build") or osb.get("build"),
        "os_hours_since_boot": _num(
            safe_get(payload, ["Derived", "HoursSinceLastBoot"])
        )
        if safe_get(payload, ["Derived", "HoursSinceLastBoot"]) is not None
        else _num(osb.get("HoursSinceLastBoot")),
        "cpu_pct": _pct(safe_get(payload, ["Telemetry", "Cpu", "Pct"])),
        "cpu_temp_c": _num(safe_get(payload, ["Telemetry", "Cpu", "TempC"])),
        "cpu_temp_c_avg": _num(safe_get(payload, ["Telemetry", "Cpu", "TempCAvg"])),
        "cpu_temp_c_max": _num(safe_get(payload, ["Telemetry", "Cpu", "TempCMax"])),
        "cpu_clock_mhz": _num(safe_get(payload, ["Telemetry", "Cpu", "ClockMhz"])),
        "mem_used_mb": _int(safe_get(payload, ["Telemetry", "Memory", "UsedMb"])),
        "mem_used_pct": _pct(safe_get(payload, ["Telemetry", "Memory", "UsedPct"])),
        "battery_charge_pct": _pct(safe_get(payload, ["Telemetry", "Battery", "ChargePct"])),
        "battery_status": _battery_status_text(payload),
        "battery_cycle_count": _int(safe_get(payload, ["Telemetry", "Battery", "CycleCount"])),
        "sec_tpm_present": _bool(sec.get("TpmPresent") or sec.get("tpm_present")),
        "sec_tpm_version": sec.get("TpmVersion") or sec.get("tpm_version"),
        "sec_secure_boot": _bool(
            sec.get("SecureBoot")
            or sec.get("secure_boot")
            or sec.get("SecureBootEnabled")
        ),
        "sec_virt_enabled": _bool(
            sec.get("VirtualizationEnabled")
            or sec.get("virt_enabled")
            or sec.get("VirtEnabled")
        ),
        "risk_score": _pct(safe_get(payload, ["Risk", "RiskScore"])),
        "risk_bucket": safe_get(payload, ["Risk", "RiskBucket"]) or safe_get(payload, ["Risk", "Bucket"]),
        "risk_top_factors": _risk_factors(payload),
        "derived_cpu_temp_to_load": _num(safe_get(payload, ["Derived", "CpuTempToLoadRatio"])),
        "extra": json.dumps(extra),
    }


def _machine_block(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Static machine identity: agent may use Hardware.Machine (inventory) or Telemetry.Machine."""
    for path in (
        ["Hardware", "Machine"],
        ["Telemetry", "Machine"],
        ["Machine"],
    ):
        b = safe_get(payload, path, None)
        if isinstance(b, dict) and b:
            return b
    return {}


def _bios_block(payload: Dict[str, Any]) -> Dict[str, Any]:
    for path in (
        ["Hardware", "Baseboard", "BiosUefi"],
        ["Telemetry", "Bios"],
        ["Bios"],
    ):
        b = safe_get(payload, path, None)
        if isinstance(b, dict) and b:
            return b
    return {}


def _cpu_inventory_block(payload: Dict[str, Any]) -> Dict[str, Any]:
    """CPU static info is often at root Cpu, while Telemetry.Cpu holds live counters."""
    root = safe_get(payload, ["Cpu"], None)
    if isinstance(root, dict) and (root.get("Model") or root.get("model")):
        return root
    tel = safe_get(payload, ["Telemetry", "Cpu"], default={}) or {}
    return tel if isinstance(tel, dict) else {}


def build_hardware_snapshot(
    payload: Dict[str, Any], *, device_id: str, snapshot_ts: datetime
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (snapshot_row, gpu_rows, storage_rows) for device_hardware_snapshot / gpu / storage.
    snapshot_ts should align with telemetry event_ts.
    """
    m = _machine_block(payload)
    bios = _bios_block(payload)
    cpu = _cpu_inventory_block(payload)
    mem_total = safe_get(payload, ["Memory", "TotalMb"])
    if mem_total is None:
        mem_total = safe_get(payload, ["Memory", "TotalMB"])
    if mem_total is None:
        mem_total = safe_get(payload, ["Telemetry", "Memory", "TotalMb"])
    if mem_total is None:
        mem_total = safe_get(payload, ["Telemetry", "Memory", "TotalMB"])

    bios_date_raw = (
        bios.get("Date")
        or bios.get("date")
        or bios.get("ReleaseDate")
        or bios.get("release_date")
    )
    bios_date: Optional[datetime] = None
    if isinstance(bios_date_raw, str):
        try:
            bios_date = datetime.fromisoformat(bios_date_raw.replace("Z", "+00:00"))
        except Exception:
            bios_date = None

    snapshot = {
        "device_id": device_id,
        "snapshot_ts": snapshot_ts,
        "machine_mfr": m.get("Manufacturer") or m.get("manufacturer"),
        "machine_product": m.get("ProductName")
        or m.get("product_name")
        or m.get("Model")
        or m.get("model"),
        "machine_serial_hash": m.get("SerialHash")
        or m.get("serial_hash")
        or m.get("SerialNumberHash")
        or m.get("serial_number_hash"),
        "bios_vendor": bios.get("Vendor") or bios.get("vendor"),
        "bios_version": bios.get("Version") or bios.get("version"),
        "bios_date": bios_date,
        "cpu_model": cpu.get("Model") or cpu.get("model"),
        "cpu_cores_phys": _int(cpu.get("CoresPhysical") or cpu.get("cores_physical")),
        "cpu_threads_log": _int(cpu.get("ThreadsLogical") or cpu.get("threads_logical")),
        "mem_total_mb": _int(mem_total),
        "extra": json.dumps({"source": "curation_etl"}),
    }

    gpu_rows: List[Dict[str, Any]] = []

    def _append_gpu_row(g: Dict[str, Any]) -> None:
        vendor = g.get("Vendor") or g.get("vendor")
        model = (
            g.get("Model")
            or g.get("model")
            or g.get("Name")
            or g.get("name")
        )
        if not vendor and not model:
            return
        gpu_rows.append(
            {
                "vendor": vendor,
                "model": model,
                "vram_mb": _int(g.get("VramMb") or g.get("VRAMMb") or g.get("vram_mb")),
                "driver_version": g.get("DriverVersion") or g.get("driver_version"),
            }
        )

    # Inventario en raíz (Vendor, VramMb, DriverVersion). Telemetry.Gpu suele ser solo Name/TempC/Pct.
    inventory_gpus: List[Any] = []
    for path_key in ("Gpus", "gpus"):
        gpus = payload.get(path_key)
        if isinstance(gpus, list) and gpus:
            inventory_gpus = gpus
            break
    if inventory_gpus:
        for g in inventory_gpus:
            if isinstance(g, dict):
                _append_gpu_row(g)
    else:
        tel_gpus = safe_get(payload, ["Telemetry", "Gpu"], default=[])
        if isinstance(tel_gpus, list):
            for g in tel_gpus:
                if isinstance(g, dict):
                    _append_gpu_row(g)

    # Discos: Storage (raíz) trae modelo/capacidad/serial; Telemetry.Disks suele ser solo DriveId + TempC.
    drives_by_id: Dict[str, Dict[str, Any]] = {}

    def _merge_disk_entry(e: Dict[str, Any], idx_fallback: int) -> None:
        did_raw = e.get("DriveId") or e.get("drive_id")
        if not did_raw:
            return
        did = str(did_raw)
        row = drives_by_id.setdefault(
            did,
            {
                "drive_id": did,
                "interface": None,
                "model": None,
                "capacity_gb": None,
                "serial_hash": None,
                "temperature_c": None,
            },
        )
        iface = e.get("Interface") or e.get("interface")
        if iface is not None:
            row["interface"] = iface
        model = e.get("Model") or e.get("model")
        if model is not None:
            row["model"] = model
        cap = e.get("CapacityGb") or e.get("capacity_gb")
        if cap is not None:
            row["capacity_gb"] = _int(cap)
        sh = e.get("SerialHash") or e.get("serial_hash")
        if sh is not None:
            row["serial_hash"] = sh
        temp = e.get("TemperatureC") or e.get("temperature_c") or e.get("TempC") or e.get("temp_c")
        if temp is not None:
            row["temperature_c"] = _num(temp)

    storage = payload.get("Storage")
    if isinstance(storage, list):
        for idx, e in enumerate(storage):
            if isinstance(e, dict):
                _merge_disk_entry(e, idx)

    tel_disks = safe_get(payload, ["Telemetry", "Disks"], default=[])
    if isinstance(tel_disks, list):
        for idx, e in enumerate(tel_disks):
            if isinstance(e, dict):
                _merge_disk_entry(e, idx + 1000)

    sata = safe_get(payload, ["Telemetry", "Smart", "Sata"], default=[])
    if isinstance(sata, list):
        for idx, e in enumerate(sata):
            if isinstance(e, dict):
                did_raw = e.get("DriveId") or e.get("drive_id") or f"sata{idx}"
                _merge_disk_entry({**e, "DriveId": did_raw}, idx)

    drive_rows = list(drives_by_id.values())

    return snapshot, gpu_rows, drive_rows


def parse_payload(data: Any) -> Dict[str, Any]:
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        try:
            o = json.loads(data)
            return o if isinstance(o, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
