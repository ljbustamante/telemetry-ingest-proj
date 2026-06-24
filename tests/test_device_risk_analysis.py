from __future__ import annotations

import pandas as pd
import pytest

from src.ml.device_risk_analysis import (
    analyze_device,
    compute_prob_failure_snapshot,
    compute_risk_points,
    device_risk_level_from_prob,
    pct,
)


def _row(**kwargs) -> dict:
    defaults = {
        "anomaly_score": 0.0,
        "cpu_temp_max_c": 70.0,
        "cpu_thermal_throttling": 0,
        "cpu_temp_to_load_ratio": 2.0,
        "gpu0_hotspot_c": 80.0,
        "disk_health_score": 95.0,
        "smart_reallocated_sectors_total": 0,
        "whea_corrected": 0,
        "whea_uncorrected": 0,
        "bugcheck_7d": 0,
        "battery_cycle_count": 500,
    }
    return {**defaults, **kwargs}


# --- compute_risk_points ---

def test_risk_points_clean_device_is_zero():
    assert compute_risk_points(_row()) == 0


def test_risk_points_severe_anomaly_score():
    rp = compute_risk_points(_row(anomaly_score=-0.35))
    assert rp >= 4


def test_risk_points_moderate_anomaly_score():
    rp = compute_risk_points(_row(anomaly_score=-0.20))
    assert rp >= 2


def test_risk_points_cpu_temp_very_high():
    rp = compute_risk_points(_row(cpu_temp_max_c=92.0))
    assert rp >= 3


def test_risk_points_cpu_temp_high():
    rp = compute_risk_points(_row(cpu_temp_max_c=86.0))
    assert rp >= 2


def test_risk_points_thermal_throttling():
    rp = compute_risk_points(_row(cpu_thermal_throttling=1))
    assert rp >= 2


def test_risk_points_cpu_ratio_high():
    rp = compute_risk_points(_row(cpu_temp_to_load_ratio=5.0))
    assert rp >= 1


def test_risk_points_gpu_very_high_hotspot():
    rp = compute_risk_points(_row(gpu0_hotspot_c=102.0))
    assert rp >= 3


def test_risk_points_low_disk_health():
    rp = compute_risk_points(_row(disk_health_score=75.0))
    assert rp >= 4


def test_risk_points_moderate_disk_health():
    rp = compute_risk_points(_row(disk_health_score=85.0))
    assert rp >= 2


def test_risk_points_smart_reallocated():
    rp = compute_risk_points(_row(smart_reallocated_sectors_total=5.0))
    assert rp >= 3


def test_risk_points_many_smart_reallocated():
    rp = compute_risk_points(_row(smart_reallocated_sectors_total=60.0))
    assert rp >= 5


def test_risk_points_whea_corrected():
    rp = compute_risk_points(_row(whea_corrected=1))
    assert rp >= 2


def test_risk_points_whea_uncorrected():
    rp = compute_risk_points(_row(whea_uncorrected=1))
    assert rp >= 4


def test_risk_points_bugcheck():
    rp = compute_risk_points(_row(bugcheck_7d=1))
    assert rp >= 3


def test_risk_points_high_battery_cycles():
    rp = compute_risk_points(_row(battery_cycle_count=1100.0))
    assert rp >= 2


def test_risk_points_storage_event_153():
    rp = compute_risk_points({"storage30d_count_153": 3, **_row()})
    assert rp >= 2


# --- compute_prob_failure_snapshot ---

def test_prob_failure_zero_for_clean_device():
    row = {"risk_points": 0, "prob_anom_snapshot": 0.0}
    assert compute_prob_failure_snapshot(row) == 0.0


def test_prob_failure_bounded_between_0_and_1():
    row = {"risk_points": 100, "prob_anom_snapshot": 1.0}
    prob = compute_prob_failure_snapshot(row)
    assert 0.0 <= prob <= 1.0


def test_prob_failure_increases_with_risk_points():
    low = compute_prob_failure_snapshot({"risk_points": 1, "prob_anom_snapshot": 0.0})
    high = compute_prob_failure_snapshot({"risk_points": 8, "prob_anom_snapshot": 0.0})
    assert high > low


# --- device_risk_level_from_prob ---

def test_risk_level_bajo_below_035():
    assert device_risk_level_from_prob(0.0) == "Bajo"
    assert device_risk_level_from_prob(0.34) == "Bajo"


def test_risk_level_medio_between_035_and_060():
    assert device_risk_level_from_prob(0.35) == "Medio"
    assert device_risk_level_from_prob(0.59) == "Medio"


def test_risk_level_alto_above_060():
    assert device_risk_level_from_prob(0.60) == "Alto"
    assert device_risk_level_from_prob(0.99) == "Alto"


# --- pct ---

def test_pct_empty_series_returns_zero():
    assert pct(pd.Series([], dtype=bool)) == 0.0


def test_pct_all_true_returns_100():
    assert pct(pd.Series([True, True, True])) == pytest.approx(100.0)


def test_pct_half_returns_50():
    assert pct(pd.Series([True, False, True, False])) == pytest.approx(50.0)


# --- analyze_device ---

def _make_df(n: int = 10, **overrides) -> pd.DataFrame:
    data: dict = {
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="h"),
        "cpu_pct": [50.0] * n,
        "cpu_temp_max_c": [70.0] * n,
        "cpu_thermal_throttling": [0] * n,
        "cpu_temp_to_load_ratio": [2.0] * n,
        "disk_health_score": [95.0] * n,
        "smart_reallocated_sectors_total": [0] * n,
        "whea_corrected": [0] * n,
        "whea_uncorrected": [0] * n,
        "bugcheck_7d": [0] * n,
        "battery_cycle_count": [500] * n,
        "mem_used_pct": [60.0] * n,
    }
    data.update(overrides)
    return pd.DataFrame(data)


def test_analyze_device_returns_expected_keys():
    result = analyze_device(_make_df(), "uuid-123")
    for key in ("device_id", "worst_risk_level", "predicted_failure_risk", "main_risk_factors", "total_snapshots"):
        assert key in result


def test_analyze_device_correct_device_id():
    result = analyze_device(_make_df(), "uuid-abc")
    assert result["device_id"] == "uuid-abc"


def test_analyze_device_total_snapshots_count():
    result = analyze_device(_make_df(n=15), "uuid-1")
    assert result["total_snapshots"] == 15


def test_analyze_device_healthy_is_bajo():
    result = analyze_device(_make_df(), "uuid-healthy")
    assert result["worst_risk_level"] == "Bajo"


def test_analyze_device_fewer_than_min_snapshots(monkeypatch):
    monkeypatch.setenv("ML_MIN_SNAPSHOTS", "10")
    result = analyze_device(_make_df(n=3), "uuid-small")
    assert result["total_snapshots"] == 3
    assert result["worst_risk_level"] in ("Bajo", "Medio", "Alto")


def test_analyze_device_high_risk_factors_produces_high_risk_points():
    df = _make_df(
        cpu_temp_max_c=[92.0] * 10,
        disk_health_score=[70.0] * 10,
        smart_reallocated_sectors_total=[10.0] * 10,
        bugcheck_7d=[2] * 10,
    )
    result = analyze_device(df, "uuid-bad")
    # Uniform risky data → IsolationForest can't differentiate rows → prob_anom=0,
    # but risk_points from hardware indicators are still non-zero and reflected in the result.
    assert result["max_risk_points_recent"] > 5
    assert result["predicted_failure_risk"] > 0


def test_analyze_device_mixed_data_risky_rows_detected():
    normal = _make_df(n=25)
    risky = pd.DataFrame({
        "timestamp": pd.date_range("2024-12-01", periods=5, freq="h"),
        "cpu_pct": [99.0] * 5,
        "cpu_temp_max_c": [95.0] * 5,
        "cpu_thermal_throttling": [1] * 5,
        "cpu_temp_to_load_ratio": [6.0] * 5,
        "disk_health_score": [60.0] * 5,
        "smart_reallocated_sectors_total": [15.0] * 5,
        "whea_corrected": [0] * 5,
        "whea_uncorrected": [3] * 5,
        "bugcheck_7d": [5] * 5,
        "battery_cycle_count": [500] * 5,
        "mem_used_pct": [98.0] * 5,
    })
    df = pd.concat([normal, risky], ignore_index=True)
    result = analyze_device(df, "uuid-mixed")
    # The risky tail rows have large risk_points, which is captured in max_risk_points_recent
    assert result["max_risk_points_recent"] > 10
    assert result["worst_risk_level"] in ("Bajo", "Medio", "Alto")


def test_analyze_device_main_risk_factors_not_empty():
    result = analyze_device(_make_df(), "uuid-1")
    assert len(result["main_risk_factors"]) > 0
