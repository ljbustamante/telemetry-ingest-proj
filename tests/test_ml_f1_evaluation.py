"""
Regresión de F1 para el modelo Isolation Forest + reglas de hardware.

Usa un dataset sintético controlado (semilla fija) donde la etiqueta de
verdad es conocida en el momento de generación. Garantiza que el pipeline
completo (analyze_device) siga discriminando correctamente.

Threshold óptimo = 0.40 → F1 ≈ 0.889 (Precision=1.0, Recall=0.80).
"""
from __future__ import annotations

import sys
import os

import numpy as np
import pytest
from sklearn.metrics import f1_score, precision_score, recall_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generate_test_dataset import build_dataset, evaluate

F1_THRESHOLD = 0.40   # umbral óptimo sobre predicted_failure_risk
F1_MIN = 0.85         # límite inferior aceptable


@pytest.fixture(scope="module")
def evaluation_results():
    rng = np.random.default_rng(42)
    devices = build_dataset(rng)
    df = evaluate(devices)
    return df


def test_f1_meets_target(evaluation_results):
    df = evaluation_results
    y_true = df["true_label"].values
    y_pred = (df["predicted_failure_risk"] >= F1_THRESHOLD).astype(int).values
    f1 = f1_score(y_true, y_pred, zero_division=0)
    assert f1 >= F1_MIN, (
        f"F1={f1:.4f} con umbral={F1_THRESHOLD} está por debajo del mínimo={F1_MIN}. "
        "El modelo puede haber degradado — revisar cambios en device_risk_analysis.py."
    )


def test_no_false_positives_at_optimal_threshold(evaluation_results):
    df = evaluation_results
    normal_devices = df[df["true_label"] == 0]
    false_positives = normal_devices[normal_devices["predicted_failure_risk"] >= F1_THRESHOLD]
    assert len(false_positives) == 0, (
        f"Se encontraron {len(false_positives)} falsos positivos con umbral={F1_THRESHOLD}: "
        f"{false_positives['device_id'].tolist()}"
    )


def test_strong_anomalous_all_detected(evaluation_results):
    df = evaluation_results
    strong = df[df["device_id"].str.startswith("anom_strong_")]
    detected = strong[strong["predicted_failure_risk"] >= F1_THRESHOLD]
    assert len(detected) == len(strong), (
        f"Solo {len(detected)}/{len(strong)} dispositivos anómalos fuertes detectados. "
        "Verificar que el contraste baseline→degradado se mantiene en make_degraded_snapshots()."
    )


def test_precision_at_optimal_threshold(evaluation_results):
    df = evaluation_results
    y_true = df["true_label"].values
    y_pred = (df["predicted_failure_risk"] >= F1_THRESHOLD).astype(int).values
    precision = precision_score(y_true, y_pred, zero_division=0)
    assert precision >= 0.90, f"Precision={precision:.4f} por debajo de 0.90"


def test_recall_at_optimal_threshold(evaluation_results):
    df = evaluation_results
    y_true = df["true_label"].values
    y_pred = (df["predicted_failure_risk"] >= F1_THRESHOLD).astype(int).values
    recall = recall_score(y_true, y_pred, zero_division=0)
    assert recall >= 0.75, f"Recall={recall:.4f} por debajo de 0.75"


def test_strong_anomalous_reach_alto(evaluation_results):
    strong = evaluation_results[evaluation_results["device_id"].str.startswith("anom_strong_")]
    alto = strong[strong["worst_risk_level"] == "Alto"]
    assert len(alto) >= 5, (
        f"Solo {len(alto)}/{len(strong)} dispositivos anómalos fuertes alcanzan nivel Alto. "
        "Verificar que BASELINE_SNAPS > DEGRADED_SNAPS para que IF detecte correctamente."
    )
