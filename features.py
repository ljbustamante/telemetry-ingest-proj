# features.py
import os
import json
from glob import glob
from typing import Dict, Any, List

import pandas as pd


def safe_get(d: Dict[str, Any], path: List[str], default=None):
    """Obtiene un valor anidado de un dict sin romperse si falta algo."""
    current = d
    for key in path:
        if not isinstance(current, dict):
            return default
        if key not in current:
            return default
        current = current[key]
    return current


def extract_features_from_json(data: dict) -> dict:
    """
    Extrae features relevantes del JSON de telemetría.
    SOLO usa campos que realmente existen en el snapshot que me pasaste.
    Esto alimenta al modelo de anomalías (Isolation Forest) y a las reglas
    de riesgo predictivo.
    """
    row: Dict[str, Any] = {}

    # --------------------
    # Identificación básica
    # --------------------
    row["device_id"] = safe_get(data, ["Identity", "DeviceId"])
    row["location"] = safe_get(data, ["Identity", "Location"])
    row["timestamp"] = data.get("CollectedAt")

    # -------------
    # CPU
    # -------------
    row["cpu_pct"] = safe_get(data, ["Telemetry", "Cpu", "Pct"])
    row["cpu_temp_c"] = safe_get(data, ["Telemetry", "Cpu", "TempC"])
    row["cpu_temp_avg_c"] = safe_get(data, ["Telemetry", "Cpu", "TempCAvg"])
    row["cpu_temp_max_c"] = safe_get(data, ["Telemetry", "Cpu", "TempCMax"])
    row["cpu_clock_mhz"] = safe_get(data, ["Telemetry", "Cpu", "ClockMhz"])
    row["cpu_thermal_throttling"] = 1 if safe_get(
        data, ["Telemetry", "Cpu", "ThermalThrottling"]
    ) else 0
    row["cpu_throttle_events"] = safe_get(
        data, ["Telemetry", "Cpu", "ThrottleEventsSinceBoot"]
    )
    row["cpu_temp_to_load_ratio"] = safe_get(
        data, ["Derived", "CpuTempToLoadRatio"]
    )

    # -------------
    # GPUs (tomamos hasta 2 GPUs si existen)
    # -------------
    gpus = safe_get(data, ["Telemetry", "Gpu"], default=[])
    if isinstance(gpus, list):
        for idx in range(min(2, len(gpus))):
            g = gpus[idx] or {}
            prefix = f"gpu{idx}_"
            row[prefix + "pct"] = g.get("Pct")
            row[prefix + "temp_c"] = g.get("TempC")
            row[prefix + "hotspot_c"] = g.get("HotspotC")

    # -------------
    # Memoria
    # -------------
    row["mem_used_mb"] = safe_get(data, ["Telemetry", "Memory", "UsedMb"])
    row["mem_used_pct"] = safe_get(data, ["Telemetry", "Memory", "UsedPct"])

    # -------------
    # IO / discos (latencias agregadas)
    # -------------
    row["io_window_s"] = safe_get(data, ["Telemetry", "Io", "WindowSeconds"])
    row["io_avg_ms"] = safe_get(data, ["Telemetry", "Io", "AggregateAvgMs"])
    row["io_p95_ms"] = safe_get(data, ["Telemetry", "Io", "AggregateP95Ms"])

    row["io5m_window_s"] = safe_get(data, ["Telemetry", "Io5m", "WindowSeconds"])
    row["io5m_avg_ms"] = safe_get(data, ["Telemetry", "Io5m", "AggregateAvgMs"])
    row["io5m_p95_ms"] = safe_get(data, ["Telemetry", "Io5m", "AggregateP95Ms"])

    # -------------
    # Batería
    # -------------
    row["battery_pct"] = safe_get(data, ["Telemetry", "Battery", "ChargePct"])
    row["battery_cycle_count"] = safe_get(
        data, ["Telemetry", "Battery", "CycleCount"]
    )
    row["battery_status_ac"] = 1 if safe_get(
        data, ["Telemetry", "Battery", "Status"]
    ) == "ac" else 0

    # -------------
    # Salud de disco / derivados
    # -------------
    row["disk_health_score"] = safe_get(data, ["Derived", "DiskHealthScore"])
    row["hours_since_boot"] = safe_get(data, ["Derived", "HoursSinceLastBoot"])

    # -------------
    # SMART (SATA) - señales predictivas de falla de disco
    # -------------
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

    # -------------
    # Errores WHEA (hardware)
    # -------------
    row["whea_corrected"] = safe_get(
        data, ["Events", "Whea", "CorrectedSinceBoot"]
    )
    row["whea_uncorrected"] = safe_get(
        data, ["Events", "Whea", "UncorrectedSinceBoot"]
    )

    # -------------
    # Bugcheck (BSOD) últimos 7 días
    # -------------
    row["bugcheck_7d"] = safe_get(data, ["Events", "BugcheckCount7d"])

    # -------------
    # Storage30d: eventos de disco 153 / 129 / 55
    # -------------
    storage_counts = safe_get(data, ["Telemetry", "Storage30d", "Counts"], default={})
    if isinstance(storage_counts, dict):
        for code, value in storage_counts.items():
            row[f"storage30d_count_{code}"] = value

    # -------------
    # Riesgo previo (por si el agente ya trae algo)
    # -------------
    row["risk_score"] = safe_get(data, ["Risk", "RiskScore"])

    return row


def load_snapshots(base_dir: str) -> pd.DataFrame:
    """
    Lee todos los JSON de la carpeta base:
    - Espera subcarpetas con nombre = device_id
    - Dentro de cada subcarpeta, archivos .json con timestamp en el nombre
    También soporta JSON sueltos en la carpeta base.
    """
    pattern_nested = os.path.join(base_dir, "*", "*.json")
    files_nested = glob(pattern_nested)

    pattern_root = os.path.join(base_dir, "*.json")
    files_root = glob(pattern_root)

    files = sorted(set(files_nested + files_root))

    if not files:
        raise RuntimeError(
            f"No se encontraron JSON en '{base_dir}' (ni en subcarpetas)."
        )

    rows = []
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            row = extract_features_from_json(data)

            folder_name = os.path.basename(os.path.dirname(path))
            if not row.get("device_id"):
                row["device_id"] = folder_name

            row["source_file"] = os.path.basename(path)
            row["source_folder"] = folder_name

            rows.append(row)
        except Exception as e:
            print(f"[WARN] No se pudo procesar {path}: {e}")

    if not rows:
        raise RuntimeError("No se pudo extraer ninguna fila válida de los JSON.")

    df = pd.DataFrame(rows)
    return df
