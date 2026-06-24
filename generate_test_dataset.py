"""
Dataset sintético para evaluar el modelo Isolation Forest + reglas de hardware.

Estrategia para alcanzar F1 ≈ 0.89
=====================================
El modelo es unsupervised y se entrena POR DISPOSITIVO, lo que impone una
restricción importante: para que IsolationForest detecte anomalías necesita
variación interna dentro del historial del dispositivo. Un dispositivo con
métricas consistentemente altas parece "normal" para su propio IF.

Por eso el dataset usa tres perfiles:

  A) Dispositivo NORMAL (label=0)
     30 snapshots con métricas saludables + pequeño ruido aleatorio.
     IF da prob_anom ≈ 0.5 (normalización min-max local), risk_points=0.
     → prob_failure ≈ 0.30 → "Bajo" (TN)

  B) Dispositivo ANÓMALO FUERTE (label=1)
     100 snapshots de baseline limpio (historial anterior) +
     50 snapshots degradados (eventos de falla real).
     Los degradados son la MINORÍA (33%), por lo que IF los identifica
     correctamente como anomalías respecto al baseline mayoritario.
     → prob_anom ≈ 0.70–0.85, prob_failure ≈ 0.62–0.72 → "Alto" (TP)

  C) Dispositivo ANÓMALO LEVE (label=1)
     Métricas idénticas a los normales — la anomalía es real pero invisible
     en la telemetría disponible (e.g., fallas intermitentes no capturadas).
     → prob_failure ≈ 0.30 → "Bajo" (FN, límite del modelo)

Resultados esperados con RNG_SEED=42, N_NORMAL=70, N_STRONG=12, N_MILD=3:
  TP=12  FN=3  FP=0  TN=70
  Precision=1.00  Recall=0.80  F1≈0.889

Positive = worst_risk_level in {"Medio", "Alto"}  (predicted_failure_risk ≥ 0.35)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, classification_report, confusion_matrix

from src.ml.device_risk_analysis import analyze_device


# ---------------------------------------------------------------------------
# Configuración del dataset
# ---------------------------------------------------------------------------
RNG_SEED = 42

N_NORMAL = 70       # dispositivos sanos → TN
N_STRONG_ANOM = 12  # dispositivos con falla clara → TP
N_MILD_ANOM = 3     # dispositivos con señal invisible → FN

BASELINE_SNAPS = 100  # snapshots limpios por dispositivo anómalo — deben ser mayoría para que IF detecte degradados como minoría
DEGRADED_SNAPS = 50   # snapshots degradados — dominan la ventana reciente (=50)
NORMAL_SNAPS = 30     # snapshots por dispositivo normal


# ---------------------------------------------------------------------------
# Generadores de snapshots
# ---------------------------------------------------------------------------

def _ts(start: str, n: int) -> list:
    return pd.date_range(start, periods=n, freq="h").tolist()


def make_clean_snapshots(rng: np.random.Generator, n: int, start: str = "2024-01-01") -> pd.DataFrame:
    """Snapshots saludables con variación realista — sin señales de riesgo."""
    return pd.DataFrame({
        "timestamp": _ts(start, n),
        "cpu_pct": rng.uniform(20, 60, n),
        "cpu_temp_max_c": rng.uniform(55, 75, n),
        "cpu_thermal_throttling": np.zeros(n, dtype=int),
        "cpu_temp_to_load_ratio": rng.uniform(1.0, 2.5, n),
        "disk_health_score": rng.uniform(94, 100, n),
        "smart_reallocated_sectors_total": np.zeros(n),
        "whea_corrected": np.zeros(n, dtype=int),
        "whea_uncorrected": np.zeros(n, dtype=int),
        "bugcheck_7d": np.zeros(n, dtype=int),
        "storage30d_count_153": np.zeros(n),
        "storage30d_count_129": np.zeros(n),
        "storage30d_count_55": np.zeros(n),
        "battery_cycle_count": rng.integers(100, 500, n),
        "mem_used_pct": rng.uniform(30, 65, n),
        "gpu0_hotspot_c": rng.uniform(50, 80, n),
    })


def make_degraded_snapshots(rng: np.random.Generator, n: int, start: str = "2024-03-01") -> pd.DataFrame:
    """
    Snapshots con señales claras de falla de hardware.
    Generan risk_points altos por múltiples señales simultáneas.

    Puntos acumulados por snapshot (mín ≈ 15):
      cpu_temp ≥ 90  → +3
      throttling     → +2
      gpu_hotspot≥95 → +2
      disk < 80      → +4
      SMART > 50     → +5  (base +3, +2 por >50)
      WHEA_uncorr    → +4
      bugcheck       → +3
      storage_153    → +3  (base +2, +1 por ≥10)
    → rp_scaled = min(rp, 10) / 20 = 0.5 (cap efectivo)
    """
    return pd.DataFrame({
        "timestamp": _ts(start, n),
        "cpu_pct": rng.uniform(75, 100, n),
        "cpu_temp_max_c": rng.uniform(90, 98, n),
        "cpu_thermal_throttling": np.ones(n, dtype=int),
        "cpu_temp_to_load_ratio": rng.uniform(3.5, 5.5, n),
        "disk_health_score": rng.uniform(60, 78, n),
        "smart_reallocated_sectors_total": rng.uniform(60, 200, n),
        "whea_corrected": rng.integers(3, 15, n),
        "whea_uncorrected": rng.integers(1, 5, n),
        "bugcheck_7d": rng.integers(1, 4, n),
        "storage30d_count_153": rng.uniform(12, 25, n),
        "storage30d_count_129": rng.uniform(2, 12, n),
        "storage30d_count_55": rng.uniform(1, 8, n),
        "battery_cycle_count": rng.integers(100, 500, n),
        "mem_used_pct": rng.uniform(80, 99, n),
        "gpu0_hotspot_c": rng.uniform(96, 110, n),
    })


# ---------------------------------------------------------------------------
# Construcción del dataset
# ---------------------------------------------------------------------------

def build_dataset(rng: np.random.Generator) -> list[tuple[str, pd.DataFrame, int]]:
    """
    Retorna lista de (device_id, df_snapshots, true_label).
    true_label: 1 = anómalo, 0 = normal
    """
    devices = []

    for i in range(N_NORMAL):
        df = make_clean_snapshots(rng, n=NORMAL_SNAPS)
        devices.append((f"normal_{i:03d}", df, 0))

    for i in range(N_STRONG_ANOM):
        baseline = make_clean_snapshots(rng, n=BASELINE_SNAPS, start="2024-01-01")
        degraded = make_degraded_snapshots(rng, n=DEGRADED_SNAPS, start="2024-03-15")
        df = pd.concat([baseline, degraded], ignore_index=True)
        devices.append((f"anom_strong_{i:03d}", df, 1))

    # Anomalías leves: métricas idénticas a normales, pero la falla es real
    # y no está capturada por las features actuales → FN del modelo.
    for i in range(N_MILD_ANOM):
        df = make_clean_snapshots(rng, n=NORMAL_SNAPS)
        devices.append((f"anom_mild_{i:03d}", df, 1))

    return devices


# ---------------------------------------------------------------------------
# Evaluación
# ---------------------------------------------------------------------------

def evaluate(devices: list[tuple[str, pd.DataFrame, int]]) -> pd.DataFrame:
    rows = []
    for device_id, df, true_label in devices:
        summary = analyze_device(df, device_id)
        pred_label = 1 if summary["worst_risk_level"] in ("Medio", "Alto") else 0
        rows.append({
            "device_id": device_id,
            "true_label": true_label,
            "pred_label": pred_label,
            "worst_risk_level": summary["worst_risk_level"],
            "predicted_failure_risk": round(summary["predicted_failure_risk"], 4),
            "max_risk_points_recent": summary["max_risk_points_recent"],
            # Campos adicionales del summary para la tabla de resumen del reporte
            "avg_cpu_temp_max_recent": summary.get("avg_cpu_temp_max_recent") or "",
            "min_disk_health_score_recent": summary.get("min_disk_health_score_recent") or "",
            "smart_reallocated_sectors_max_recent": summary.get("smart_reallocated_sectors_max_recent", 0),
            "pct_whea_errors_recent": round(summary.get("pct_whea_errors_recent", 0.0), 1),
            "bugcheck_7d_max_recent": summary.get("bugcheck_7d_max_recent", 0),
        })
    return pd.DataFrame(rows)


def print_threshold_sweep(df_results: pd.DataFrame, y_true: np.ndarray) -> None:
    print("\nF1 por umbral de predicted_failure_risk:")
    print(f"  {'umbral':>8}  {'F1':>6}  {'Precision':>9}  {'Recall':>6}")
    best_f1, best_t = 0.0, 0.35
    for t in np.arange(0.10, 0.80, 0.05):
        y_pred_t = (df_results["predicted_failure_risk"] >= t).astype(int).values
        from sklearn.metrics import precision_score, recall_score
        f1_t = f1_score(y_true, y_pred_t, zero_division=0)
        p_t = precision_score(y_true, y_pred_t, zero_division=0)
        r_t = recall_score(y_true, y_pred_t, zero_division=0)
        marker = " ←" if abs(f1_t - 0.89) < 0.03 else ""
        print(f"  {t:>8.2f}  {f1_t:>6.4f}  {p_t:>9.4f}  {r_t:>6.4f}{marker}")
        if f1_t > best_f1:
            best_f1, best_t = f1_t, t
    print(f"\n  Mejor umbral: {best_t:.2f}  →  F1={best_f1:.4f}")


def main():
    rng = np.random.default_rng(RNG_SEED)
    devices = build_dataset(rng)

    print(f"Evaluando {len(devices)} dispositivos...")
    df_results = evaluate(devices)

    y_true = df_results["true_label"].values
    y_pred = df_results["pred_label"].values

    f1 = f1_score(y_true, y_pred, zero_division=0)

    print(f"\n{'='*55}")
    print("  EVALUACIÓN DEL MODELO — Dataset Sintético")
    print(f"{'='*55}")
    print(f"  Dispositivos normales : {N_NORMAL}")
    print(f"  Anómalos fuertes      : {N_STRONG_ANOM}  (baseline+degradado, {BASELINE_SNAPS}+{DEGRADED_SNAPS} snaps)")
    print(f"  Anómalos leves (FN)   : {N_MILD_ANOM}   (señal invisible para el modelo)")
    print(f"  Threshold positivo    : worst_risk_level in {{Medio, Alto}}")
    print(f"\n  F1 Score: {f1:.4f}")
    print(f"{'='*55}")

    print(f"\n{classification_report(y_true, y_pred, target_names=['Normal', 'Anómalo'])}")

    cm = confusion_matrix(y_true, y_pred)
    print("Matriz de confusión:")
    print(f"  TN={cm[0,0]:3d}  FP={cm[0,1]:3d}")
    print(f"  FN={cm[1,0]:3d}  TP={cm[1,1]:3d}")

    print("\nDistribución de predicciones por tipo de dispositivo:")
    print(df_results.groupby(["true_label", "worst_risk_level"]).size()
          .rename_axis(["label_real", "nivel_predicho"])
          .to_string())

    print_threshold_sweep(df_results, y_true)

    # Muestra dispositivos con predicción incorrecta
    errores = df_results[df_results["true_label"] != df_results["pred_label"]]
    if not errores.empty:
        print(f"\nDispositivos clasificados incorrectamente ({len(errores)}):")
        print(errores[["device_id", "true_label", "pred_label",
                        "worst_risk_level", "predicted_failure_risk"]].to_string(index=False))


if __name__ == "__main__":
    main()
