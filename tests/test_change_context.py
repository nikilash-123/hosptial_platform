"""
test_change_context.py
======================
Unit tests for Phase 6 Change Context Analysis & Correlation Layer.
Tests:
1. Index Change Detection (added, removed, modified, status changed, abandoned, missing)
2. Statistics Analysis (stale, age, row drift, missing, configurable threshold)
3. Workload Analysis (NORMAL, INCREASED, HIGH, SPIKE & causal categories A, B, C, D)
4. Schema Change Analysis (table modification, columns, index-related DDL)
5. Release History Analysis & Timeline Generation
6. Edge Case 1: Index removed + plan changed + execution time increased -> Strong evidence
7. Edge Case 2: Statistics stale but execution time stable -> Warning, not critical
8. Edge Case 3: Workload surge with unchanged plan -> Workload-induced slowdown
9. Edge Case 4: Release occurred but query performance stable -> Normal / No regression
10. Edge Case 5: Missing metadata -> Safe continuation with insufficient evidence
11. Integration with detection_engine evidence object
"""

import pytest
from src.core import (
    change_context_analyser,
    detection_engine,
    rules_loader
)


# ── 1. Index Change Analysis Tests ────────────────────────────────────────────

def test_CC01_index_change_detection():
    """Verify detection of added, removed, status-changed, and abandoned indexes."""
    # Test index removed
    res_removed = change_context_analyser.analyze_index_changes(
        before_indexes=["idx_doctor_schedule"],
        after_indexes=[],
        query_id="QRY-001"
    )
    assert len(res_removed) == 1
    assert res_removed[0]["change_type"] == "INDEX_REMOVED"
    assert res_removed[0]["impact"] == "HIGH_REGRESSION_RISK"
    assert "idx_doctor_schedule" in res_removed[0]["evidence"]

    # Test index added
    res_added = change_context_analyser.analyze_index_changes(
        before_indexes=[],
        after_indexes=["idx_new_covering"],
        query_id="QRY-001"
    )
    assert res_added[0]["change_type"] == "INDEX_ADDED"
    assert res_added[0]["impact"] == "POSITIVE"

    # Test index status changed
    res_status = change_context_analyser.analyze_index_changes(
        before_indexes=["idx_slot"],
        after_indexes=["idx_slot"],
        index_status_before="ACTIVE",
        index_status_after="DISABLED"
    )
    assert res_status[0]["change_type"] == "INDEX_STATUS_CHANGED"
    assert res_status[0]["impact"] == "HIGH_REGRESSION_RISK"

    # Test potentially missing index
    res_missing = change_context_analyser.analyze_index_changes(
        before_indexes=[],
        after_indexes=[],
        has_full_scan_after=True
    )
    assert res_missing[0]["change_type"] == "POTENTIALLY_MISSING"


# ── 2. Statistics Analysis Tests ──────────────────────────────────────────────

def test_CC02_statistics_analysis_staleness_and_config():
    """Verify statistics staleness uses configurable threshold and cautious language."""
    rules = {"change_context": {"stale_statistics_threshold_days": 10}}

    # Fresh statistics (age 5 < 10)
    fresh = change_context_analyser.analyze_statistics_changes(
        before_stats={"statistics_age": 2},
        after_stats={"statistics_age": 5},
        rules=rules,
        table_name="appointments"
    )
    assert fresh["status"] == "CURRENT"
    assert fresh["threshold"] == 10

    # Stale statistics (age 14 > 10)
    stale = change_context_analyser.analyze_statistics_changes(
        before_stats={"statistics_age": 2},
        after_stats={"statistics_age": 14},
        rules=rules,
        table_name="appointments"
    )
    assert stale["status"] == "STALE"
    assert "may contribute" in stale["evidence"].lower()  # Cautious language check

    # Missing statistics
    missing = change_context_analyser.analyze_statistics_changes(None, None)
    assert missing["status"] == "MISSING"


# ── 3. Workload Analysis Tests ────────────────────────────────────────────────

def test_CC03_workload_analysis_and_causal_distinction():
    """Verify workload classification and causal categories A, B, C, D."""
    # Category A: Plan regression under normal workload
    cat_a = change_context_analyser.analyze_workload_changes(
        before_workload="NORMAL",
        after_workload="NORMAL",
        plan_changed=True,
        index_lost=True,
        pct_latency_change=150.0
    )
    assert cat_a["cause_category"] == "A. plan/query regression"

    # Category B: Workload-induced slowdown (concurrency spike, plan intact)
    cat_b = change_context_analyser.analyze_workload_changes(
        before_workload="NORMAL",
        after_workload="PEAK",
        plan_changed=False,
        index_lost=False,
        pct_latency_change=35.0
    )
    assert cat_b["cause_category"] == "B. workload-induced slowdown"
    assert cat_b["workload_classification"] == "SPIKE"

    # Category C: Mixed cause (both workload surge and plan change)
    cat_c = change_context_analyser.analyze_workload_changes(
        before_workload="NORMAL",
        after_workload="HIGH",
        plan_changed=True,
        index_lost=True,
        pct_latency_change=200.0
    )
    assert cat_c["cause_category"] == "C. mixed cause"

    # Category D: Insufficient evidence
    cat_d = change_context_analyser.analyze_workload_changes(None, None)
    assert cat_d["cause_category"] == "D. insufficient evidence"


# ── 4. Schema Change Analysis Tests ───────────────────────────────────────────

def test_CC04_schema_change_analysis():
    """Verify schema change parsing and relevance assignment."""
    events = [
        {"change_description": "DROP INDEX idx_doctor_date", "affected_table": "appointments"},
        {"change_description": "ALTER TABLE appointments ADD COLUMN notes TEXT", "affected_table": "appointments"}
    ]
    parsed = change_context_analyser.analyze_schema_changes(events, query_id="QRY-001")
    assert len(parsed) == 2
    assert parsed[0]["relevance"] == "DIRECT"  # DROP event
    assert parsed[1]["relevance"] == "INDIRECT" # ADD event


# ── 5. Release History & Timeline Tests ────────────────────────────────────────

def test_CC05_release_history_and_timeline_generation():
    """Verify release timeline generation chronologically connects changes."""
    rel_info = {
        "release_id": "REL-104",
        "release_version": "v1.4",
        "deployment_timestamp": "2026-09-07T10:00:00"
    }
    schema_events = [{"change_description": "DROP INDEX idx_doctor_schedule", "affected_table": "appointments"}]
    index_events = [{
        "index_name": "idx_doctor_schedule",
        "change_type": "INDEX_REMOVED",
        "evidence": "Index dropped"
    }]
    stats_info = {"status": "STALE", "age": 8, "threshold": 7}
    workload_info = {"workload_classification": "NORMAL", "cause_category": "A. plan/query regression"}
    plan_diff = {
        "plan_changed": True,
        "scan_diff": {"scan_transition": "INDEX_TO_FULL_SCAN"},
        "reason": "Index scan to table scan"
    }
    timing_info = {"baseline_ms": 12.0, "current_ms": 150.0, "pct_change": 1150.0}

    timeline = change_context_analyser.build_change_timeline(
        rel_info, schema_events, index_events, stats_info, workload_info, plan_diff, timing_info
    )

    steps = [t["step"] for t in timeline]
    assert any("Release" in s for s in steps)
    assert any("Schema" in s for s in steps)
    assert any("Index" in s for s in steps)
    assert any("Statistics" in s for s in steps)
    assert any("Plan" in s for s in steps)
    assert any("Latency" in s for s in steps)


# ── 6. Five Required Edge Cases ───────────────────────────────────────────────

def test_CC06_edge_case_1_index_removed_plan_changed_time_increased():
    """
    CASE 1: Index removed + plan changed + execution time increased.
    Expected: Strong regression evidence.
    """
    before_state = {
        "query_id": "QRY-001",
        "execution_time_ms": 15.0,
        "indexes": ["idx_doctor_schedule"],
        "plan_text": "SEARCH appointments USING INDEX idx_doctor_schedule"
    }
    after_state = {
        "query_id": "QRY-001",
        "execution_time_ms": 180.0,
        "indexes": [],
        "index_status": "REMOVED",
        "plan_text": "SCAN appointments",
        "has_full_scan": True
    }
    plan_diff = {
        "plan_changed": True,
        "scan_diff": {"index_to_full_scan": True, "scan_transition": "INDEX_TO_FULL_SCAN"}
    }

    ctx = change_context_analyser.correlate_change_context("QRY-001", before_state, after_state, plan_diff=plan_diff)
    assert ctx["confidence"] == "Strong evidence"
    assert ctx["evidence_strength"] == "Strong evidence"
    assert "index removal" in ctx["possible_cause"].lower()


def test_CC07_edge_case_2_stale_statistics_stable_execution():
    """
    CASE 2: Statistics stale but execution time did not increase significantly.
    Expected: Statistics warning, but NOT automatically a critical regression.
    """
    before_state = {
        "query_id": "QRY-002",
        "execution_time_ms": 12.0,
        "indexes": ["idx_doctor_date"],
        "statistics_age": 1
    }
    after_state = {
        "query_id": "QRY-002",
        "execution_time_ms": 12.5,  # Only +4.1% increase (stable)
        "indexes": ["idx_doctor_date"],
        "statistics_age": 45,       # Stale (> 30 days)
        "statistics_status": "STALE"
    }
    plan_diff = {"plan_changed": False}

    res = detection_engine.detect_query_regression(before_state, after_state)
    # Must NOT be CRITICAL
    assert res["severity"] != "CRITICAL"
    assert res["classification"] in ("WARNING", "NORMAL")
    assert res["evidence"]["change_context"]["statistics_status"]["status"] == "STALE"


def test_CC08_edge_case_3_workload_surge_unchanged_plan():
    """
    CASE 3: Workload increased significantly but plan did not change.
    Expected: Identify workload-induced slowdown or mixed/uncertain cause.
    """
    before_state = {
        "query_id": "QRY-003",
        "execution_time_ms": 14.0,
        "workload_level": "NORMAL",
        "indexes": ["idx_appt_dept_date"],
        "plan_text": "SEARCH appointments USING INDEX idx_appt_dept_date"
    }
    after_state = {
        "query_id": "QRY-003",
        "execution_time_ms": 18.0,  # +28% increase under surge
        "workload_level": "PEAK",
        "indexes": ["idx_appt_dept_date"],
        "plan_text": "SEARCH appointments USING INDEX idx_appt_dept_date"
    }
    plan_diff = {"plan_changed": False}

    ctx = change_context_analyser.correlate_change_context("QRY-003", before_state, after_state, plan_diff=plan_diff)
    workload_analysis = ctx["workload_analysis"]
    assert workload_analysis["cause_category"] == "B. workload-induced slowdown"
    assert workload_analysis["workload_classification"] == "SPIKE"


def test_CC09_edge_case_4_release_occurred_performance_stable():
    """
    CASE 4: Release occurred but query performance remained stable.
    Expected: No regression merely because a release happened.
    """
    before_state = {
        "query_id": "QRY-004",
        "execution_time_ms": 20.0,
        "release_version": "v1.0",
        "indexes": ["idx_appt_pk"]
    }
    after_state = {
        "query_id": "QRY-004",
        "execution_time_ms": 20.2,  # +1% variance
        "release_version": "v1.1",  # New release deployed
        "release_change": "release_deployment",
        "indexes": ["idx_appt_pk"]
    }

    res = detection_engine.detect_query_regression(before_state, after_state)
    assert res["severity"] == "OK"
    assert res["classification"] == "NORMAL"
    assert res["evidence"]["change_context"]["confidence"] == "Insufficient evidence"


def test_CC10_edge_case_5_missing_metadata_safe_continuation():
    """
    CASE 5: No release/index/schema/statistics information available.
    Expected: System continues safely and reports insufficient change-context evidence.
    """
    # Empty dictionaries with only query_id and timings
    before_state = {"query_id": "QRY-005", "execution_time_ms": 10.0}
    after_state = {"query_id": "QRY-005", "execution_time_ms": 12.0}

    ctx = change_context_analyser.correlate_change_context("QRY-005", before_state, after_state)
    assert ctx["confidence"] == "Insufficient evidence"
    assert "insufficient" in ctx["workload_analysis"]["cause_category"].lower()
    assert ctx["statistics_status"]["status"] == "MISSING"


def test_CC11_detector_integration_evidence_package():
    """Verify that detection_engine embeds the complete change_context and timeline."""
    before_state = {
        "query_id": "SYNTH-Q-004",
        "query_name": "Verify whether an appointment slot is already booked",
        "execution_time_ms": 13.8,
        "indexes": ["idx_appt_doctor_date_time_status"],
        "plan_text": "SEARCH appointments USING INDEX idx_appt_doctor_date_time_status"
    }
    after_state = {
        "query_id": "SYNTH-Q-004",
        "query_name": "Verify whether an appointment slot is already booked",
        "execution_time_ms": 195.0,
        "indexes": [],
        "index_status": "REMOVED",
        "plan_text": "SCAN appointments",
        "has_full_scan": True,
        "schema_change": "DROP INDEX idx_appt_doctor_date_time_status",
        "release_version": "v1.4"
    }

    result = detection_engine.detect_query_regression(before_state, after_state)
    ev = result["evidence"]

    # Verify change context fields exist
    assert "change_context" in ev
    assert "timeline" in ev
    assert "evidence_strength" in ev
    assert ev["evidence_strength"] == "Strong evidence"
    assert len(ev["timeline"]) >= 3
