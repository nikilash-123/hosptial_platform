"""
test_pg_evidence_scenarios.py
=============================
Automated test suite validating the 8 reviewer-specified regression scenarios
specifically against the real PostgreSQL telemetry evidence model:

1. No regression (healthy query within noise threshold)
2. Execution-time regression (latency jump with unchanged plan)
3. Index -> Sequential scan regression (loss of index, Seq Scan introduced)
4. Cost regression (optimizer cost surge)
5. Multiple simultaneous regressions (latency + plan + cost + index drop)
6. Invalid telemetry handling (null/negative values handled gracefully)
7. Missing execution plan handling (null/empty plan string handled gracefully)
8. False positive suppression & false negative sensitivity
"""

import os
import sys
import copy
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import detection_engine, rules_loader
from src.pg_regression_runner import BEFORE_STATE, AFTER_STATE, RULES_PATH


@pytest.fixture
def rules():
    return rules_loader.load_rules(RULES_PATH)


# 1. No regression scenario
def test_scenario_1_no_regression(rules):
    """Query executes identically or within normal variance: No regression flagged."""
    before = copy.deepcopy(BEFORE_STATE)
    after = copy.deepcopy(BEFORE_STATE)
    after["execution_time_ms"] = 2.15  # +2.3% variance (well within 20% threshold)
    after["planning_time_ms"] = 0.42

    result = detection_engine.detect_query_regression(before, after, rules=rules)

    assert result["is_regression"] is False
    assert result["classification"] in ("NORMAL", "OK")
    assert result["regression_score"] < 25.0


# 2. Execution-time regression scenario
def test_scenario_2_execution_time_regression(rules):
    """Query plan remains unchanged, but execution time increases significantly."""
    before = copy.deepcopy(BEFORE_STATE)
    after = copy.deepcopy(BEFORE_STATE)
    # Plan is identical (Bitmap Index Scan preserved), but execution latency jumps 300%
    after["execution_time_ms"] = 8.5  # +304% increase

    result = detection_engine.detect_query_regression(before, after, rules=rules)

    assert result["is_regression"] is True
    triggered_names = [r["rule_name"] for r in result.get("triggered_rules", [])]
    assert "execution_time_regression" in triggered_names
    assert result["regression_score"] > 25.0


# 3. Index -> Sequential scan regression scenario
def test_scenario_3_index_to_seq_scan_regression(rules):
    """Index dropped, causing Bitmap Index Scan to degrade into a Sequential Scan."""
    before = copy.deepcopy(BEFORE_STATE)
    after = copy.deepcopy(AFTER_STATE)

    result = detection_engine.detect_query_regression(before, after, rules=rules)

    assert result["is_regression"] is True
    assert result["classification"] == "CRITICAL_REGRESSION"
    assert result["severity"] == "CRITICAL"
    ev = result.get("evidence", {})
    scan_tr = ev.get("scan_transition") or ev.get("plan_difference", {}).get("scan_diff", {}).get("scan_transition")
    assert scan_tr == "INDEX_TO_FULL_SCAN"
    lost_idx = ev.get("index_difference", {}).get("lost_indexes", []) or ev.get("plan_difference", {}).get("index_diff", {}).get("lost_indexes", [])
    assert "idx_appointments_doctor_date_status" in lost_idx


# 4. Cost regression scenario
def test_scenario_4_cost_regression(rules):
    """Execution time is moderate, but optimizer cost estimate surges significantly."""
    before = copy.deepcopy(BEFORE_STATE)
    after = copy.deepcopy(BEFORE_STATE)
    after["total_cost"] = 85.0
    after["io_cost"] = 8.0     # +2566% IO cost surge
    after["cpu_time_ms"] = 6.0 # +300% CPU cost surge
    after["execution_time_ms"] = 2.4

    result = detection_engine.detect_query_regression(before, after, rules=rules)

    triggered_names = [r["rule_name"] for r in result.get("triggered_rules", [])]
    assert "plan_cost_increased" in triggered_names


# 5. Multiple simultaneous regressions scenario
def test_scenario_5_multiple_simultaneous_regressions(rules):
    """Index lost, plan changed to Seq Scan, latency jumped 688%, and release tag changed."""
    before = copy.deepcopy(BEFORE_STATE)
    after = copy.deepcopy(AFTER_STATE)

    result = detection_engine.detect_query_regression(before, after, rules=rules)

    assert result["is_regression"] is True
    assert result["regression_score"] >= 90.0
    triggered = [r["rule_name"] for r in result.get("triggered_rules", [])]
    # Multiple signals triggered simultaneously
    assert "execution_time_regression" in triggered
    assert "plan_changed" in triggered
    assert "full_table_scan_detected" in triggered
    assert "index_removed" in triggered
    assert "double_booking_hazard_multiplier" in triggered


# 6. Invalid telemetry handling
def test_scenario_6_invalid_telemetry_handling(rules):
    """Missing or negative values must be handled gracefully without exceptions."""
    before = copy.deepcopy(BEFORE_STATE)
    after = copy.deepcopy(BEFORE_STATE)
    after["execution_time_ms"] = -5.0  # Invalid negative
    after["total_cost"] = None        # Missing cost
    after["estimated_rows"] = "NaN"   # Non-numeric

    result = detection_engine.detect_query_regression(before, after, rules=rules)

    assert isinstance(result, dict)
    assert "is_regression" in result
    assert "regression_score" in result


# 7. Missing execution plan handling
def test_scenario_7_missing_execution_plan(rules):
    """Empty or null execution plan string must not cause a crash."""
    before = copy.deepcopy(BEFORE_STATE)
    after = copy.deepcopy(BEFORE_STATE)
    after["plan_text"] = ""
    after["plan_hash"] = None
    after["execution_time_ms"] = 12.0

    result = detection_engine.detect_query_regression(before, after, rules=rules)

    assert isinstance(result, dict)
    assert "classification" in result
    assert "severity" in result


# 8. False positive suppression & false negative sensitivity
def test_scenario_8_false_positive_suppression(rules):
    """Minor variance below threshold (+10%) must NOT trigger a false positive alarm."""
    before = copy.deepcopy(BEFORE_STATE)
    after = copy.deepcopy(BEFORE_STATE)
    after["execution_time_ms"] = 2.3  # +9.5% increase (below default 20% threshold)

    result = detection_engine.detect_query_regression(before, after, rules=rules)

    assert result["is_regression"] is False
    assert result["classification"] == "NORMAL"


def test_scenario_8_false_negative_sensitivity(rules):
    """A critical index loss on a double-booking path must NEVER be missed (no false negative)."""
    before = copy.deepcopy(BEFORE_STATE)
    after = copy.deepcopy(BEFORE_STATE)
    # Latency increase is small (e.g. on empty test db), but index was dropped
    after["has_full_scan"] = True
    after["indexes"] = []
    after["plan_text"] = "Seq Scan on appointments (cost=0.00..16.50 rows=2 width=50)"
    after["scan_type"] = "Seq Scan"

    result = detection_engine.detect_query_regression(before, after, rules=rules)

    # Must be caught as regression due to structural access-path degradation
    assert result["is_regression"] is True
    assert result["severity"] in ("HIGH", "CRITICAL")
