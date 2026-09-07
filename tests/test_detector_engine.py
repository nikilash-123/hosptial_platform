"""
test_detector_engine.py
=======================
Test suite for Phase 4: Query-Regression Detection Engine.

Verifies:
1. Multi-signal detection across all 9 distinct evidence signals:
   - Signal 1: Execution time percentage and absolute limit checks
   - Signal 2: Query plan hash change and full table scan detection
   - Signal 3: Increased rows examined (cardinality drift)
   - Signal 4: CPU time and I/O cost increase
   - Signal 5: Index loss, modification, or missing index
   - Signal 6: Statistics staleness (age > threshold)
   - Signal 7: Workload concurrency shift vs false-positive grace suppression
   - Signal 8: Schema change context (column added, index dropped)
   - Signal 9: Release history context
2. Configurable regression score calculation (0.0 to 100.0).
3. Accurate 4-tier classification: NORMAL, WARNING, REGRESSION, CRITICAL_REGRESSION.
4. Complete forensic evidence object containing all 16 required fields.
5. Explainability guarantee for every HIGH and CRITICAL finding.
6. Special escalation for double-booking critical workflows.
"""

import os
import sys
import pytest
from typing import Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import detection_engine, rules_loader

REQUIRED_EVIDENCE_FIELDS = [
    "query_id",
    "query_name",
    "baseline_execution_time",
    "current_execution_time",
    "percentage_change",
    "baseline_plan_hash",
    "current_plan_hash",
    "plan_changed",
    "index_difference",
    "statistics_difference",
    "workload_difference",
    "release_change_information",
    "regression_score",
    "severity",
    "reason",
    "recommended_investigation_action"
]

@pytest.fixture
def base_state() -> Dict[str, Any]:
    return {
        "query_id": "SYNTH-Q-001",
        "query_name": "Find available appointment slots",
        "query_type": "find_available_slots",
        "execution_time_ms": 14.5,
        "plan_text": "SEARCH appointment_slots USING INDEX idx_appt_dept_date_status",
        "plan_hash": "base_hash_001",
        "indexes": ["idx_appt_dept_date_status"],
        "rows_examined": 120,
        "cpu_time_ms": 9.2,
        "io_cost": 2.1,
        "statistics_age": 5,
        "statistics_status": "CURRENT",
        "workload_level": "NORMAL",
        "release_version": "v1.0.0",
        "schema_change": "NONE"
    }


def test_DT01_signal_execution_time_percentage_and_absolute(base_state):
    """Verify Signal 1: Percentage surge (50%) triggers REGRESSION, absolute surge (>=2000ms) triggers CRITICAL."""
    # Test 50% percentage surge
    after_pct = dict(base_state)
    after_pct["execution_time_ms"] = base_state["execution_time_ms"] * 1.60  # +60%
    res_pct = detection_engine.detect_query_regression(base_state, after_pct)
    assert res_pct["regression_label"] in ("REGRESSION", "CRITICAL_REGRESSION")
    assert res_pct["is_regression"] is True

    # Test absolute critical limit (>= 2000ms)
    after_abs = dict(base_state)
    after_abs["execution_time_ms"] = 2150.0
    res_abs = detection_engine.detect_query_regression(base_state, after_abs)
    assert res_abs["regression_label"] == "CRITICAL_REGRESSION"
    assert res_abs["severity"] == "CRITICAL"
    assert "critical SLA threshold" in res_abs["reason"]


def test_DT02_signal_query_plan_and_full_scan(base_state):
    """Verify Signal 2: Plan hash change and new full table scan trigger plan flags."""
    after_plan = dict(base_state)
    after_plan["execution_time_ms"] = base_state["execution_time_ms"] * 1.8
    after_plan["plan_text"] = "SCAN appointment_slots (full table scan without index)"
    after_plan["plan_hash"] = "scan_hash_999"
    after_plan["has_full_scan"] = True

    res = detection_engine.detect_query_regression(base_state, after_plan)
    assert res["plan_changed"] is True
    assert res["has_new_scan"] is True
    assert res["evidence"]["plan_changed"] == "yes"
    assert res["regression_score"] >= 50.0


def test_DT03_signal_rows_examined_drift(base_state):
    """Verify Signal 3: Large surge in rows examined triggers statistics drift flag."""
    after_rows = dict(base_state)
    after_rows["execution_time_ms"] = base_state["execution_time_ms"] * 1.3
    after_rows["rows_examined"] = base_state["rows_examined"] * 10  # 10x cardinality scan

    res = detection_engine.detect_query_regression(base_state, after_rows)
    assert res["stats_flag"] is True
    assert "row_drift_percentage" in res["evidence"]["statistics_difference"]


def test_DT04_signal_cpu_and_io_cost(base_state):
    """Verify Signal 4: CPU and IO costs are evaluated in evidence difference."""
    after_cost = dict(base_state)
    after_cost["execution_time_ms"] = base_state["execution_time_ms"] * 1.4
    after_cost["cpu_time_ms"] = base_state["cpu_time_ms"] * 2.5
    after_cost["io_cost"] = base_state["io_cost"] * 3.0

    res = detection_engine.detect_query_regression(base_state, after_cost)
    cost_diff = res["evidence"]["cost_difference"]
    assert "cpu_change_percentage" in cost_diff
    assert "io_cost_change_percentage" in cost_diff


def test_DT05_signal_index_loss_and_modification(base_state):
    """Verify Signal 5: Lost index is detected and triggers index lost flag."""
    after_idx = dict(base_state)
    after_idx["execution_time_ms"] = base_state["execution_time_ms"] * 2.0
    after_idx["indexes"] = []
    after_idx["index_status"] = "REMOVED"

    res = detection_engine.detect_query_regression(base_state, after_idx)
    assert res["index_lost"] is True
    assert len(res["evidence"]["index_difference"]["lost_indexes"]) > 0


def test_DT06_signal_statistics_staleness(base_state):
    """Verify Signal 6: Statistics older than 30 days trigger staleness flag."""
    after_stats = dict(base_state)
    after_stats["statistics_age"] = 45  # > 30 days
    after_stats["statistics_status"] = "STALE"
    after_stats["execution_time_ms"] = base_state["execution_time_ms"] * 1.15

    res = detection_engine.detect_query_regression(base_state, after_stats)
    assert res["stats_flag"] is True
    assert res["evidence"]["statistics_difference"]["stats_stale"] is True


def test_DT07_signal_workload_surge_with_grace_suppression(base_state):
    """Verify Signal 7: Peak workload surge without plan degradation is suppressed as NORMAL."""
    after_surge = dict(base_state)
    after_surge["workload_level"] = "PEAK"
    after_surge["execution_time_ms"] = base_state["execution_time_ms"] * 1.25  # +25% concurrency latency

    res = detection_engine.detect_query_regression(base_state, after_surge)
    assert res["regression_label"] == "NORMAL"
    assert res["severity"] == "OK"
    assert res["evidence"]["workload_difference"]["concurrency_grace_applied"] is True


def test_DT08_signals_schema_and_release_context(base_state):
    """Verify Signals 8 & 9: Schema changes and release change descriptions are recorded in evidence."""
    after_schema = dict(base_state)
    after_schema["schema_change"] = "COLUMN_ADDED"
    after_schema["release_change"] = "schema_change"
    after_schema["release_version"] = "v1.5.0"
    after_schema["execution_time_ms"] = base_state["execution_time_ms"] * 1.5

    res = detection_engine.detect_query_regression(base_state, after_schema)
    rel_info = res["evidence"]["release_change_information"]
    assert rel_info["schema_change_event"] == "COLUMN_ADDED"
    assert rel_info["release_change_event"] == "schema_change"


def test_DT09_evidence_object_completeness(base_state):
    """Verify that every detected regression produces an evidence object with all 16 required fields."""
    after_reg = dict(base_state)
    after_reg["execution_time_ms"] = base_state["execution_time_ms"] * 4.0
    after_reg["plan_hash"] = "degraded_plan"
    after_reg["indexes"] = []
    after_reg["index_status"] = "REMOVED"

    res = detection_engine.detect_query_regression(base_state, after_reg)
    ev = res["evidence"]

    for field in REQUIRED_EVIDENCE_FIELDS:
        assert field in ev, f"Evidence object missing required field: '{field}'"

    # Verify explainability
    assert len(ev["reason"]) > 10, "Reason must be an explainable description"
    assert len(ev["recommended_investigation_action"]) > 0, "Recommendations must not be empty"


def test_DT10_double_booking_critical_escalation():
    """Verify that regressions on double-booking critical queries escalate to CRITICAL_REGRESSION."""
    db_base = {
        "query_id": "SYNTH-Q-004",
        "query_name": "Verify whether an appointment slot is already booked",
        "query_type": "verify_slot_booked",
        "execution_time_ms": 13.8,
        "plan_hash": "base_hash",
        "indexes": ["idx_appt_doctor_date_time_status"],
        "rows_examined": 25
    }

    db_after = dict(db_base)
    db_after["execution_time_ms"] = 195.0
    db_after["indexes"] = []
    db_after["index_status"] = "REMOVED"
    db_after["plan_hash"] = "scan_hash"

    res = detection_engine.detect_query_regression(db_base, db_after)
    assert res["regression_label"] == "CRITICAL_REGRESSION"
    assert res["severity"] == "CRITICAL"
    assert res["double_booking_risk"] is True
    assert "double-booking" in res["reason"].lower()


def test_DT11_batch_regression_detection(base_state):
    """Verify batch regression detection processes query lists and sorts by regression score."""
    b_list = [base_state]
    c_list = [
        dict(base_state, execution_time_ms=base_state["execution_time_ms"] * 1.02),  # normal
    ]

    # Add a regressed query
    q2_base = dict(base_state, query_id="SYNTH-Q-002", execution_time_ms=11.2)
    q2_after = dict(q2_base, execution_time_ms=180.0, index_status="REMOVED")
    b_list.append(q2_base)
    c_list.append(q2_after)

    batch_findings = detection_engine.detect_batch_regressions(b_list, c_list)
    assert len(batch_findings) == 2
    # Highest score first
    assert batch_findings[0]["query_id"] == "SYNTH-Q-002"
    assert batch_findings[0]["regression_score"] > batch_findings[1]["regression_score"]


def test_DT12_api_detection_endpoints(base_state):
    """Verify the Flask REST API endpoints /api/detect and /api/detect-batch."""
    from src.web.app import app
    client = app.test_client()

    # Test /api/detect with normal execution
    res1 = client.post("/api/detect", json={
        "before_state": base_state,
        "after_state": dict(base_state, execution_time_ms=base_state["execution_time_ms"] * 1.02)
    })
    assert res1.status_code == 200
    data1 = res1.get_json()
    assert data1["status"] == "success"
    assert data1["result"]["classification"] == "NORMAL"

    # Test /api/detect with regressed query
    reg_after = dict(base_state, execution_time_ms=180.0, indexes=[], index_status="REMOVED")
    res2 = client.post("/api/detect", json={
        "before_state": base_state,
        "after_state": reg_after
    })
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert data2["result"]["classification"] in ("REGRESSION", "CRITICAL_REGRESSION")
    assert "evidence" in data2["result"]

    # Test /api/detect-batch
    res3 = client.post("/api/detect-batch", json={
        "baselines": [base_state],
        "currents": [reg_after]
    })
    assert res3.status_code == 200
    data3 = res3.get_json()
    assert data3["status"] == "success"
    assert data3["total_evaluated"] == 1
    assert data3["regressions_detected"] == 1

