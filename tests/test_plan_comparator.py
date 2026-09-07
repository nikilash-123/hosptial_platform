"""
test_plan_comparator.py
=======================
Unit tests for the Phase 5 Execution Plan Comparison Module (plan_comparator.py).
Tests:
- Index Scan to Full Table Scan regression
- Exact prompt scenario (idx_doctor_schedule cost 20 -> Full Table Scan cost 450)
- Cost, CPU, and IO drift tracking
- Join strategy transitions (Hash Join vs Nested Loop)
- Sort operations (Temporary B-tree sort injection)
- Raw text vs structured JSON input parsing
- Explanations rooted in input data
- Integration with detection_engine
"""

import pytest
from src.core import plan_comparator, detection_engine


def test_PC01_exact_user_scenario_index_to_full_scan():
    """
    Test the exact scenario specified by the user:
    BEFORE: Index Scan, Index: idx_doctor_schedule, Estimated Cost: 20
    AFTER: Full Table Scan, Index: none, Estimated Cost: 450
    """
    before_plan = {
        "scan_type": "Index Scan",
        "indexes": ["idx_doctor_schedule"],
        "estimated_cost": 20.0
    }
    after_plan = {
        "scan_type": "Full Table Scan",
        "indexes": [],
        "estimated_cost": 450.0
    }

    diff = plan_comparator.compare_execution_plans(before_plan, after_plan)

    assert diff["plan_changed"] is True
    assert diff["scan_diff"]["index_to_full_scan"] is True
    assert diff["scan_diff"]["scan_transition"] == "INDEX_TO_FULL_SCAN"
    assert "idx_doctor_schedule" in diff["index_diff"]["lost_indexes"]
    assert diff["cost_diff"]["baseline_estimated_cost"] == 20.0
    assert diff["cost_diff"]["current_estimated_cost"] == 450.0
    assert diff["cost_diff"]["cost_pct_change"] == 2150.0
    assert diff["severity"] == "CRITICAL"

    # Verify explainable WHY narrative
    explanation = diff["explanation"]
    assert "index scan" in explanation.lower()
    assert "full table scan" in explanation.lower()
    assert "estimated cost increased" in explanation.lower()
    assert "450" in explanation
    assert len(diff["recommendations"]) > 0
    assert "idx_doctor_schedule" in diff["recommendations"][0]


def test_PC02_cost_and_resource_drift():
    """Verify CPU, IO, and estimated cost drift calculations."""
    before_plan = {
        "scan_type": "Index Scan",
        "indexes": ["idx_appt_slot"],
        "estimated_cost": 15.0,
        "cpu_cost": 5.0,
        "io_cost": 10.0
    }
    after_plan = {
        "scan_type": "Index Scan",
        "indexes": ["idx_appt_slot"],
        "estimated_cost": 30.0,
        "cpu_cost": 12.0,
        "io_cost": 18.0
    }

    diff = plan_comparator.compare_execution_plans(before_plan, after_plan)
    assert diff["plan_changed"] is True
    assert diff["cost_diff"]["cost_delta"] == 15.0
    assert diff["cost_diff"]["cost_pct_change"] == 100.0
    assert diff["cost_diff"]["cpu_pct_change"] == 140.0
    assert diff["cost_diff"]["io_pct_change"] == 80.0
    assert "cost" in diff["explanation"].lower()


def test_PC03_estimated_and_actual_rows_drift():
    """Verify rows examined drift detection."""
    before_plan = {
        "scan_type": "Index Scan",
        "indexes": ["idx_test"],
        "estimated_rows": 25,
        "actual_rows": 24
    }
    after_plan = {
        "scan_type": "Index Scan",
        "indexes": ["idx_test"],
        "estimated_rows": 25000,
        "actual_rows": 24950
    }

    diff = plan_comparator.compare_execution_plans(before_plan, after_plan)
    assert diff["plan_changed"] is True
    assert diff["rows_diff"]["rows_examined_delta"] == 24975
    assert diff["rows_diff"]["rows_pct_change"] >= 90000.0
    assert "rows" in diff["explanation"].lower()


def test_PC04_join_strategy_regression():
    """Verify detection when join strategy shifts from Hash Join to Nested Loop."""
    before_plan = {
        "scan_type": "Index Scan",
        "join_strategy": "Hash Join"
    }
    after_plan = {
        "scan_type": "Index Scan",
        "join_strategy": "Nested Loop"
    }

    diff = plan_comparator.compare_execution_plans(before_plan, after_plan)
    assert diff["plan_changed"] is True
    assert diff["join_diff"]["strategy_changed"] is True
    assert diff["join_diff"]["baseline_strategy"] == "Hash Join"
    assert diff["join_diff"]["current_strategy"] == "Nested Loop"
    assert "nested loop" in diff["explanation"].lower()


def test_PC05_sort_operations_injection():
    """Verify detection when a query introduces an expensive temporary B-Tree sort."""
    before_plan = {
        "scan_type": "Index Scan",
        "sort_operations": []
    }
    after_plan = {
        "scan_type": "Index Scan",
        "sort_operations": ["Temporary B-Tree Sort (ORDER BY)"]
    }

    diff = plan_comparator.compare_execution_plans(before_plan, after_plan)
    assert diff["plan_changed"] is True
    assert len(diff["operations_diff"]["added_sort_operations"]) == 1
    assert "temporary b-tree sort" in diff["explanation"].lower()


def test_PC06_identical_plans_produce_normal_explanation():
    """Verify identical plans result in no plan change and OK status."""
    plan = {
        "plan_hash": "62c759822b393c31",
        "scan_type": "Index Scan",
        "indexes": ["idx_appt_doctor_date"],
        "estimated_cost": 25.0
    }

    diff = plan_comparator.compare_execution_plans(plan, plan)
    assert diff["plan_changed"] is False
    assert diff["severity"] == "OK"
    assert diff["scan_diff"]["scan_transition"] == "UNCHANGED"
    assert "conforms to baseline" in diff["reason"].lower()


def test_PC07_raw_sqlite_explain_text_parsing():
    """Verify raw EXPLAIN QUERY PLAN text strings are parsed and compared correctly."""
    b_text = "SEARCH appointments USING INDEX idx_appt_dept_date (department_id=?)"
    a_text = "SCAN appointments"

    diff = plan_comparator.compare_execution_plans(b_text, a_text)
    assert diff["plan_changed"] is True
    assert diff["scan_diff"]["index_to_full_scan"] is True
    assert "idx_appt_dept_date" in diff["index_diff"]["lost_indexes"]
    assert diff["severity"] == "CRITICAL"


def test_PC08_plan_improvement_detection():
    """Verify changing from full scan to index scan is recognized as improvement."""
    before_plan = {
        "scan_type": "Full Table Scan",
        "indexes": []
    }
    after_plan = {
        "scan_type": "Index Scan",
        "indexes": ["idx_new_covering"],
        "is_full_scan": False
    }

    diff = plan_comparator.compare_execution_plans(before_plan, after_plan)
    assert diff["scan_diff"]["full_to_index_scan"] is True
    assert diff["severity"] == "OK"
    assert "improved" in diff["reason"].lower()


def test_PC09_none_and_malformed_inputs():
    """Verify graceful handling when plans are None or empty."""
    diff = plan_comparator.compare_execution_plans(None, None)
    assert diff["plan_changed"] is False
    assert diff["severity"] == "OK"

    diff2 = plan_comparator.compare_execution_plans(None, {"scan_type": "Full Table Scan", "is_full_scan": True})
    assert diff2["plan_changed"] is True


def test_PC10_integration_with_detection_engine():
    """Verify that detection_engine embeds plan_difference and plan_explanation in evidence."""
    base_state = {
        "query_id": "SYNTH-Q-002",
        "query_name": "Check doctor availability",
        "query_type": "check_doctor_availability",
        "execution_time_ms": 11.2,
        "plan_text": "SEARCH appointments USING INDEX idx_appt_doctor_date",
        "indexes": ["idx_appt_doctor_date"],
        "estimated_cost": 20.0
    }

    after_state = {
        "query_id": "SYNTH-Q-002",
        "query_name": "Check doctor availability",
        "query_type": "check_doctor_availability",
        "execution_time_ms": 195.0,
        "plan_text": "SCAN appointments",
        "indexes": [],
        "index_status": "REMOVED",
        "estimated_cost": 450.0
    }

    res = detection_engine.detect_query_regression(base_state, after_state)
    ev = res["evidence"]

    assert "plan_difference" in ev
    assert "plan_explanation" in ev
    plan_diff = ev["plan_difference"]
    assert plan_diff["scan_diff"]["index_to_full_scan"] is True
    assert "idx_appt_doctor_date" in plan_diff["index_diff"]["lost_indexes"]
    assert "index scan" in ev["plan_explanation"].lower()
    assert "full table scan" in ev["plan_explanation"].lower()
