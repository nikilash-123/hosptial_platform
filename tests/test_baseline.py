"""
test_baseline.py
================
Test suite for Phase 3: Baseline Creation and Comparison Engine.

Verifies:
1. Multi-dimensional baseline generation (mean, p50, p90, p95, p99, plan_hash, indexes, stats, workload, rows).
2. Prevention of single-arbitrary-value baselines.
3. Baseline retrieval API for individual queries and entire catalog.
4. Baseline comparison against new executions across normal, warning, and regression scenarios.
5. Double-booking sensitive query protection during baseline comparison.
6. Configurable rule responsiveness without code changes.
7. Exact baseline reproducibility from synthetic dataset.
"""

import os
import sys
import pytest
from typing import Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import baseline_engine, rules_loader

@pytest.fixture(scope="module")
def initialized_baselines(tmp_path_factory):
    """Generates baseline in a clean isolated test database."""
    test_db = str(tmp_path_factory.mktemp("baseline_data") / "test_detector_store.db")
    baselines = baseline_engine.generate_baseline(
        source="dataset",
        baseline_tag="v1.0.0",
        store_path=test_db
    )
    return test_db, baselines


def test_BL01_multidimensional_baseline_fields(initialized_baselines):
    """Verify that every baseline contains all required multi-dimensional attributes, not just a single runtime value."""
    test_db, baselines = initialized_baselines
    assert len(baselines) == 9, f"Expected 9 baselines, got {len(baselines)}"

    required_attrs = [
        "query_id", "query_name", "query_type",
        "mean_exec_ms", "median_exec_ms", "p90_exec_ms", "p95_exec_ms", "p99_exec_ms",
        "plan_hash", "plan_characteristics", "indexes",
        "statistics_state", "normal_workload_level",
        "rows_examined", "rows_returned", "cpu_time_ms", "io_cost"
    ]

    for qid, b in baselines.items():
        for attr in required_attrs:
            assert attr in b, f"Query {qid} missing multi-dimensional attribute: {attr}"

        # Ensure percentile hierarchy: p50 <= p90 <= p95 <= p99
        assert b["median_exec_ms"] <= b["p95_exec_ms"], f"Query {qid}: median > p95"
        assert b["p90_exec_ms"] <= b["p99_exec_ms"], f"Query {qid}: p90 > p99"
        assert b["sample_count"] >= 5, f"Query {qid}: expected >= 5 samples"
        assert b["normal_workload_level"] in ("NORMAL", "LOW")
        assert len(b["plan_hash"]) >= 8


def test_BL02_baseline_retrieval_api(initialized_baselines):
    """Verify get_baseline API for single query and all queries."""
    test_db, _ = initialized_baselines

    # Single query retrieval
    b4 = baseline_engine.get_baseline(query_id="SYNTH-Q-004", store_path=test_db)
    assert b4 is not None
    assert b4["query_id"] == "SYNTH-Q-004"
    assert "doctor" in b4["query_name"].lower() or "slot" in b4["query_name"].lower()

    # All queries retrieval
    all_b = baseline_engine.get_baseline(store_path=test_db)
    assert isinstance(all_b, dict)
    assert len(all_b) == 9
    assert "SYNTH-Q-001" in all_b
    assert "SYNTH-Q-009" in all_b

    # Non-existent query
    missing = baseline_engine.get_baseline(query_id="NON_EXISTENT_Q", store_path=test_db)
    assert missing is None


def test_BL03_compare_normal_execution_within_noise_band(initialized_baselines):
    """Verify that execution within baseline noise band is evaluated as NORMAL / OK."""
    test_db, _ = initialized_baselines
    b = baseline_engine.get_baseline("SYNTH-Q-001", store_path=test_db)

    # Runtime within 5% of baseline p95, same plan, optimal index
    normal_run = {
        "query_id": "SYNTH-Q-001",
        "execution_time_ms": b["p95_exec_ms"] * 1.04,
        "plan_hash": b["plan_hash"],
        "index_status": "OPTIMAL",
        "workload_level": "NORMAL",
        "statistics_status": "CURRENT",
        "rows_examined": b["rows_examined"]
    }

    comp = baseline_engine.compare_against_baseline(normal_run, store_path=test_db)
    assert comp["regression_label"] == "NORMAL"
    assert comp["severity"] == "OK"
    assert comp["is_regression"] is False


def test_BL04_compare_workload_spike_grace(initialized_baselines):
    """Verify that temporary workload surge without plan or index degradation suppresses false alarms."""
    test_db, _ = initialized_baselines
    b = baseline_engine.get_baseline("SYNTH-Q-002", store_path=test_db)

    workload_surge_run = {
        "query_id": "SYNTH-Q-002",
        "execution_time_ms": b["p95_exec_ms"] * 1.25,  # +25% delay under peak queueing
        "plan_hash": b["plan_hash"],
        "index_status": "OPTIMAL",
        "workload_level": "PEAK",
        "statistics_status": "CURRENT",
        "rows_examined": b["rows_examined"]
    }

    comp = baseline_engine.compare_against_baseline(workload_surge_run, store_path=test_db)
    assert comp["regression_label"] == "NORMAL"
    assert comp["severity"] == "OK"
    assert comp["flags"]["is_workload_grace"] is True


def test_BL05_compare_double_booking_critical_regression(initialized_baselines):
    """Verify that dropped index on double-booking query triggers CRITICAL_REGRESSION with double_booking_risk flag."""
    test_db, _ = initialized_baselines
    b = baseline_engine.get_baseline("SYNTH-Q-004", store_path=test_db)

    dropped_idx_run = {
        "query_id": "SYNTH-Q-004",
        "execution_time_ms": b["p95_exec_ms"] * 15.0,  # 15x slowdown
        "plan_hash": "SCAN_FULL_TABLE_HASH",
        "index_status": "REMOVED",
        "workload_level": "NORMAL",
        "rows_examined": 50000
    }

    comp = baseline_engine.compare_against_baseline(dropped_idx_run, store_path=test_db)
    assert comp["regression_label"] == "CRITICAL_REGRESSION"
    assert comp["severity"] == "CRITICAL"
    assert comp["double_booking_risk"] is True
    assert comp["flags"]["index_lost"] is True
    assert comp["flags"]["has_new_scan"] is True


def test_BL06_compare_absolute_timeout_threshold(initialized_baselines):
    """Verify that runtime exceeding absolute_critical_ms triggers CRITICAL_REGRESSION unconditionally."""
    test_db, _ = initialized_baselines
    timeout_run = {
        "query_id": "SYNTH-Q-005",
        "execution_time_ms": 2450.0,  # > 2000ms threshold
        "plan_hash": "hash",
        "index_status": "OPTIMAL"
    }

    comp = baseline_engine.compare_against_baseline(timeout_run, store_path=test_db)
    assert comp["regression_label"] == "CRITICAL_REGRESSION"
    assert comp["severity"] == "CRITICAL"


def test_BL07_compare_stale_statistics_warning(initialized_baselines):
    """Verify that aged database statistics trigger a WARNING status."""
    test_db, _ = initialized_baselines
    b = baseline_engine.get_baseline("SYNTH-Q-001", store_path=test_db)

    stale_stats_run = {
        "query_id": "SYNTH-Q-001",
        "execution_time_ms": b["p95_exec_ms"] * 1.15,
        "plan_hash": b["plan_hash"],
        "index_status": "OPTIMAL",
        "statistics_age": 45,  # > 30 days threshold
        "statistics_status": "STALE"
    }

    comp = baseline_engine.compare_against_baseline(stale_stats_run, store_path=test_db)
    assert comp["severity"] in ("MEDIUM", "HIGH")
    assert comp["flags"]["stats_stale"] is True


def test_BL08_configurable_rules_responsiveness(initialized_baselines):
    """Verify that changing thresholds in rules dict changes detection severity without modifying detection code."""
    test_db, _ = initialized_baselines
    b = baseline_engine.get_baseline("SYNTH-Q-008", store_path=test_db)

    run = {
        "query_id": "SYNTH-Q-008",
        "execution_time_ms": b["p95_exec_ms"] * 1.30,  # +30% increase
        "plan_hash": b["plan_hash"],
        "index_status": "OPTIMAL"
    }

    # Strict rules: 10% threshold -> triggers regression
    strict_rules = {
        "thresholds": {
            "time_regression_pct": 10.0,
            "time_high_pct": 25.0,
            "time_critical_pct": 50.0,
            "absolute_critical_ms": 2000.0,
            "absolute_high_ms": 500.0,
            "minimum_meaningful_ms": 1.0
        },
        "plan_rules": {"flag_index_loss": True},
        "stats_rules": {"flag_row_estimate_drift_pct": 50.0},
        "false_positive_grace": {"noise_band_pct": 5.0}
    }
    comp_strict = baseline_engine.compare_against_baseline(run, rules=strict_rules, store_path=test_db)
    assert comp_strict["is_regression"] is True

    # Lenient rules: 50% threshold -> evaluates to NORMAL
    lenient_rules = {
        "thresholds": {
            "time_regression_pct": 50.0,
            "time_high_pct": 100.0,
            "time_critical_pct": 200.0,
            "absolute_critical_ms": 5000.0,
            "absolute_high_ms": 2000.0,
            "minimum_meaningful_ms": 1.0
        },
        "plan_rules": {"flag_index_loss": True},
        "stats_rules": {"flag_row_estimate_drift_pct": 50.0},
        "false_positive_grace": {"noise_band_pct": 40.0}
    }
    comp_lenient = baseline_engine.compare_against_baseline(run, rules=lenient_rules, store_path=test_db)
    assert comp_lenient["regression_label"] == "NORMAL"
    assert comp_lenient["severity"] == "OK"


def test_BL09_baseline_reproducibility(tmp_path):
    """Verify that generating baseline twice from synthetic dataset produces identical deterministic fingerprints."""
    db1 = str(tmp_path / "baseline_run1.db")
    db2 = str(tmp_path / "baseline_run2.db")

    b1 = baseline_engine.generate_baseline(source="dataset", baseline_tag="v1.0.0", store_path=db1)
    b2 = baseline_engine.generate_baseline(source="dataset", baseline_tag="v1.0.0", store_path=db2)

    assert set(b1.keys()) == set(b2.keys())
    for qid in b1.keys():
        assert b1[qid]["median_exec_ms"] == b2[qid]["median_exec_ms"]
        assert b1[qid]["p95_exec_ms"] == b2[qid]["p95_exec_ms"]
        assert b1[qid]["plan_hash"] == b2[qid]["plan_hash"]
        assert b1[qid]["indexes"] == b2[qid]["indexes"]
        assert b1[qid]["rows_examined"] == b2[qid]["rows_examined"]
