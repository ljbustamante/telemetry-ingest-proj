"""
Isolation Forest + reglas de riesgo por dispositivo (mismo algoritmo que train_model.py).
Parámetros vía entorno: ML_MIN_SNAPSHOTS, ML_RECENT_WINDOW, ML_SKLEARN_N_JOBS.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


def _min_snapshots() -> int:
    return int(os.environ.get("ML_MIN_SNAPSHOTS", "5"))


def _recent_window() -> int:
    return int(os.environ.get("ML_RECENT_WINDOW", "50"))


def _sklearn_n_jobs() -> int:
    return int(os.environ.get("ML_SKLEARN_N_JOBS", "1"))


def compute_risk_points(row):
    rp = 0
    score = row.get("anomaly_score", 0)

    if score < -0.30:
        rp += 4
    elif score < -0.15:
        rp += 2
    elif score < -0.05:
        rp += 1

    cpu_temp_max = row.get("cpu_temp_max_c", None)
    if cpu_temp_max is not None:
        try:
            val = float(cpu_temp_max)
            if val >= 90:
                rp += 3
            elif val >= 85:
                rp += 2
        except Exception:
            pass

    if row.get("cpu_thermal_throttling", 0) == 1:
        rp += 2

    cpu_ratio = row.get("cpu_temp_to_load_ratio", None)
    if cpu_ratio is not None:
        try:
            val = float(cpu_ratio)
            if val > 4.0:
                rp += 1
        except Exception:
            pass

    gpu_hotspot = row.get("gpu0_hotspot_c", None)
    if gpu_hotspot is not None:
        try:
            val = float(gpu_hotspot)
            if val >= 100:
                rp += 3
            elif val >= 95:
                rp += 2
        except Exception:
            pass

    disk_health = row.get("disk_health_score", None)
    if disk_health is not None:
        try:
            val = float(disk_health)
            if val < 80:
                rp += 4
            elif val < 90:
                rp += 2
        except Exception:
            pass

    smart_reall = row.get("smart_reallocated_sectors_total", 0) or 0
    try:
        smart_reall = float(smart_reall)
    except Exception:
        smart_reall = 0.0
    if smart_reall > 0:
        rp += 3
        if smart_reall > 50:
            rp += 2

    for code, base_points in [("153", 2), ("129", 2), ("55", 3)]:
        val = row.get(f"storage30d_count_{code}", 0) or 0
        try:
            val = float(val)
        except Exception:
            val = 0.0
        if val > 0:
            rp += base_points
            if val >= 10:
                rp += 1

    whea_corr = row.get("whea_corrected", 0) or 0
    whea_uncorr = row.get("whea_uncorrected", 0) or 0
    try:
        whea_corr = int(whea_corr)
        whea_uncorr = int(whea_uncorr)
    except Exception:
        whea_corr = 0
        whea_uncorr = 0

    if whea_corr > 0:
        rp += 2
    if whea_uncorr > 0:
        rp += 4

    bug7d = row.get("bugcheck_7d", 0) or 0
    try:
        bug7d = int(bug7d)
    except Exception:
        bug7d = 0
    if bug7d > 0:
        rp += 3

    batt_cycles = row.get("battery_cycle_count", None)
    if batt_cycles is not None:
        try:
            val = float(batt_cycles)
            if val > 1000:
                rp += 2
            elif val > 800:
                rp += 1
        except Exception:
            pass

    return rp


def compute_prob_failure_snapshot(row):
    rp = row.get("risk_points", 0) or 0
    try:
        rp = float(rp)
    except Exception:
        rp = 0.0

    rp_scaled = min(rp, 10.0) / 20.0

    p_anom = row.get("prob_anom_snapshot", 0) or 0.0
    try:
        p_anom = float(p_anom)
    except Exception:
        p_anom = 0.0
    p_anom = max(0.0, min(p_anom, 1.0))

    prob = 0.6 * p_anom + 0.4 * rp_scaled
    return max(0.0, min(prob, 1.0))


def device_risk_level_from_prob(p: float) -> str:
    if p < 0.35:
        return "Bajo"
    elif p < 0.60:
        return "Medio"
    else:
        return "Alto"


def pct(mask: pd.Series) -> float:
    if mask is None or len(mask) == 0:
        return 0.0
    return float(mask.mean() * 100.0)


def analyze_device(df_device_in: pd.DataFrame, device_id: str) -> dict:
    df = df_device_in.copy()
    total_snapshots = len(df)

    df["ts"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.sort_values("ts")

    feature_df = df.select_dtypes(include=[np.number]).copy()
    medians = feature_df.median(numeric_only=True)
    feature_df = feature_df.fillna(medians)

    if total_snapshots >= _min_snapshots():
        model = IsolationForest(
            n_estimators=100,
            contamination="auto",
            random_state=42,
            n_jobs=_sklearn_n_jobs(),
        )
        model.fit(feature_df)
        scores = model.decision_function(feature_df)
        preds = model.predict(feature_df)
        df["anomaly_score"] = scores
        df["is_anomaly"] = (preds == -1).astype(int)
    else:
        df["anomaly_score"] = 0.0
        df["is_anomaly"] = 0

    raw = -df["anomaly_score"]
    min_raw = raw.min()
    max_raw = raw.max()
    if max_raw > min_raw:
        df["prob_anom_snapshot"] = (raw - min_raw) / (max_raw - min_raw)
    else:
        df["prob_anom_snapshot"] = 0.0

    df["risk_points"] = df.apply(compute_risk_points, axis=1)
    df["prob_failure_snapshot"] = df.apply(compute_prob_failure_snapshot, axis=1)

    pct_anomalos_all = df["is_anomaly"].mean() * 100.0
    failure_risk_historical = df["prob_failure_snapshot"].mean()
    avg_risk_points_all = df["risk_points"].mean()

    n_recent = min(_recent_window(), total_snapshots)
    df_recent = df.tail(n_recent)

    cpu_temp_recent = pd.to_numeric(df_recent["cpu_temp_max_c"], errors="coerce")
    avg_cpu_temp_max_recent = (
        float(cpu_temp_recent.mean()) if cpu_temp_recent.notna().any() else None
    )
    max_cpu_temp_max_recent = (
        float(cpu_temp_recent.max()) if cpu_temp_recent.notna().any() else None
    )
    high_cpu_mask_recent = cpu_temp_recent >= 85
    pct_high_cpu_temp_recent = pct(high_cpu_mask_recent)

    throttling_mask_recent = df_recent.get("cpu_thermal_throttling", 0) == 1
    pct_throttling_recent = pct(throttling_mask_recent)

    disk_health_recent = pd.to_numeric(
        df_recent["disk_health_score"], errors="coerce"
    )
    min_disk_health_recent = (
        float(disk_health_recent.min())
        if disk_health_recent.notna().any()
        else None
    )
    avg_disk_health_recent = (
        float(disk_health_recent.mean())
        if disk_health_recent.notna().any()
        else None
    )
    low_disk_mask_recent = disk_health_recent < 90
    pct_low_disk_health_recent = pct(low_disk_mask_recent)

    smart_reall_recent = pd.to_numeric(
        df_recent.get("smart_reallocated_sectors_total", pd.Series(dtype=float)),
        errors="coerce",
    )
    max_smart_reall_recent = (
        float(smart_reall_recent.max())
        if len(smart_reall_recent) > 0 and smart_reall_recent.notna().any()
        else 0.0
    )

    def max_storage_code(code: str) -> float:
        col = f"storage30d_count_{code}"
        if col in df_recent.columns:
            s = pd.to_numeric(df_recent[col].fillna(0), errors="coerce")
            if s.notna().any():
                return float(s.max())
        return 0.0

    disk_event_153_30d_max_recent = max_storage_code("153")
    disk_event_129_30d_max_recent = max_storage_code("129")
    disk_event_55_30d_max_recent = max_storage_code("55")

    whea_corr_recent = pd.to_numeric(
        df_recent.get("whea_corrected", pd.Series(dtype=float)).fillna(0),
        errors="coerce",
    )
    whea_uncorr_recent = pd.to_numeric(
        df_recent.get("whea_uncorrected", pd.Series(dtype=float)).fillna(0),
        errors="coerce",
    )
    whea_mask_recent = (whea_corr_recent > 0) | (whea_uncorr_recent > 0)
    pct_whea_errors_recent = pct(whea_mask_recent)

    bug7d_recent = pd.to_numeric(
        df_recent.get("bugcheck_7d", pd.Series(dtype=float)).fillna(0),
        errors="coerce",
    )
    bugcheck_7d_max_recent = (
        int(bug7d_recent.max())
        if len(bug7d_recent) > 0 and bug7d_recent.notna().any()
        else 0
    )

    pct_anomalos_recent = df_recent["is_anomaly"].mean() * 100.0
    predicted_failure_risk = df_recent["prob_failure_snapshot"].mean()
    if predicted_failure_risk is None or np.isnan(predicted_failure_risk):
        predicted_failure_risk = 0.0

    max_risk_points_recent = (
        float(df_recent["risk_points"].max()) if len(df_recent) > 0 else 0.0
    )

    worst_risk_level = device_risk_level_from_prob(predicted_failure_risk)

    factors = []

    if avg_cpu_temp_max_recent is not None:
        if avg_cpu_temp_max_recent >= 70 or pct_high_cpu_temp_recent >= 20:
            factors.append(
                f"CPU reciente alta: media ≈ {avg_cpu_temp_max_recent:.1f}°C, "
                f"≥85°C en ~{pct_high_cpu_temp_recent:.0f}% de snapshots recientes"
            )

    if pct_throttling_recent >= 5:
        factors.append(
            f"Throttling de CPU en ~{pct_throttling_recent:.0f}% de snapshots recientes"
        )

    if min_disk_health_recent is not None:
        if min_disk_health_recent < 80:
            factors.append(
                f"Salud de disco baja reciente (mín ≈ {min_disk_health_recent:.0f})"
            )
        elif min_disk_health_recent < 90:
            factors.append(
                f"Salud de disco moderada reciente (mín ≈ {min_disk_health_recent:.0f})"
            )

    if max_smart_reall_recent > 0:
        factors.append(
            f"Sectores reasignados en SMART (máx ≈ {max_smart_reall_recent:.0f})"
        )

    if disk_event_153_30d_max_recent > 0:
        factors.append(
            f"Eventos de I/O con timeout (ID 153) en los últimos 30 días: máx ≈ {disk_event_153_30d_max_recent:.0f}"
        )
    if disk_event_129_30d_max_recent > 0:
        factors.append(
            f"Resets de controlador de disco (ID 129) en los últimos 30 días: máx ≈ {disk_event_129_30d_max_recent:.0f}"
        )
    if disk_event_55_30d_max_recent > 0:
        factors.append(
            f"Errores/corrupción de sistema de archivos (ID 55) en los últimos 30 días: máx ≈ {disk_event_55_30d_max_recent:.0f}"
        )

    if pct_whea_errors_recent > 0:
        factors.append(
            f"Errores WHEA recientes en ~{pct_whea_errors_recent:.1f}% de snapshots"
        )

    if bugcheck_7d_max_recent > 0:
        factors.append(
            f"Pantallazos azules (bugcheck) en los últimos 7 días: máx ≈ {bugcheck_7d_max_recent}"
        )

    if not factors:
        if worst_risk_level == "Alto":
            factors.append(
                f"Riesgo alto principalmente por patrón de telemetría inusual: "
                f"~{pct_anomalos_recent:.1f}% de snapshots recientes detectados como anómalos"
            )
        elif worst_risk_level == "Medio":
            factors.append(
                f"Riesgo medio por patrón de telemetría inusual: "
                f"~{pct_anomalos_recent:.1f}% de snapshots recientes detectados como anómalos"
            )
        else:
            factors.append("Sin factores de riesgo claros en los datos recientes")

    main_risk_factors = "; ".join(factors)

    return {
        "device_id": device_id,
        "total_snapshots": int(total_snapshots),
        "num_recent_snapshots": int(n_recent),
        "pct_anomalos": float(pct_anomalos_all),
        "pct_anomalos_recent": float(pct_anomalos_recent),
        "failure_risk_historical": float(failure_risk_historical)
        if failure_risk_historical is not None
        else 0.0,
        "predicted_failure_risk": float(predicted_failure_risk),
        "avg_risk_points_all": float(avg_risk_points_all),
        "max_risk_points_recent": float(max_risk_points_recent),
        "worst_risk_level": worst_risk_level,
        "avg_cpu_temp_max_recent": float(avg_cpu_temp_max_recent)
        if avg_cpu_temp_max_recent is not None
        else "",
        "max_cpu_temp_max_recent": float(max_cpu_temp_max_recent)
        if max_cpu_temp_max_recent is not None
        else "",
        "pct_high_cpu_temp_recent": float(pct_high_cpu_temp_recent),
        "pct_throttling_recent": float(pct_throttling_recent),
        "min_disk_health_score_recent": float(min_disk_health_recent)
        if min_disk_health_recent is not None
        else "",
        "avg_disk_health_score_recent": float(avg_disk_health_recent)
        if avg_disk_health_recent is not None
        else "",
        "pct_low_disk_health_recent": float(pct_low_disk_health_recent),
        "smart_reallocated_sectors_max_recent": float(max_smart_reall_recent),
        "disk_event_153_30d_max_recent": float(disk_event_153_30d_max_recent),
        "disk_event_129_30d_max_recent": float(disk_event_129_30d_max_recent),
        "disk_event_55_30d_max_recent": float(disk_event_55_30d_max_recent),
        "pct_whea_errors_recent": float(pct_whea_errors_recent),
        "bugcheck_7d_max_recent": int(bugcheck_7d_max_recent),
        "main_risk_factors": main_risk_factors,
    }
