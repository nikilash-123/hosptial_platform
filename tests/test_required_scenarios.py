"""
test_required_scenarios.py
==========================
Comprehensive Automated Test Suite validating all required operational scenarios:
1. Normal query performance
2. Slow query regression
3. Index-related regression
4. Schema change regression
5. Missing execution plan
6. Invalid telemetry
7. Empty query results
8. False positives
9. False negatives
10. Double-booking-sensitive transactions
11. Edge case 1: Connection failure & recovery
12. Edge case 2: High concurrency surge with grace band
13. Edge case 3: Unindexed foreign key scan detection

Covers Scope Section 6: Validation and Testing.
"""

import os
import sys
import sqlite3
import json
import pytest
from typing import Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import (
    detection_engine, rule_engine, plan_comparator,
    rules_loader, db_adapter, postgres_engine, plan_extractor
)

RULES_PATH = os.path.join(BASE_DIR, "config", "rules.yaml")


@pytest.fixture
def rules():
    return rules_loader.load_rules(RULES_PATH)


# ── 1. Normal Query Performance ───────────────────────────────────────────────

def test_01_normal_query_performance(rules):
    """
    Scenario 1: Normal query performance within baseline noise envelope.
    Expectation: Classified as NORMAL / OK with zero regression penalty.
    """
    before = {
        "query_id": "SYNTH-Q-001",
        "query_name": "Find available appointment slots",
        "query_type": "find_available_slots",
        "execution_time_ms": 14.5,
        "plan_text": "SEARCH appointment_slots USING INDEX idx_appt_dept_date_status",
        "plan_hash": "hash_slot_idx_opt",
        "indexes": ["idx_appt_dept_date_status"],
        "statistics_age_days": 2,
        "statistics_status": "CURRENT",
        "workload_level": "NORMAL",
        "rows_examined": 120,
        "rows_returned": 18,
        "cpu_time_ms": 9.2,
        "io_cost": 2.1,
        "release_version": "v1.0.0"
    }
    after = {
        "query_id": "SYNTH-Q-001",
        "query_name": "Find available appointment slots",
        "query_type": "find_available_slots",
        "execution_time_ms": 14.9,  # +2.7% jitter within noise band
        "plan_text": "SEARCH appointment_slots USING INDEX idx_appt_dept_date_status",
        "plan_hash": "hash_slot_idx_opt",
        "indexes": ["idx_appt_dept_date_status"],
        "statistics_age_days": 3,
        "statistics_status": "CURRENT",
        "workload_level": "NORMAL",
        "rows_examined": 122,
        "rows_returned": 18,
        "cpu_time_ms": 9.4,
        "io_cost": 2.1,
        "release_version": "v1.1.0"
    }

    result = detection_engine.detect_query_regression(before, after, rules=rules)
    assert result["classification"] in ("NORMAL", "OK")
    assert result["priority"] in ("NORMAL", "OK")
    assert result.get("score", result.get("regression_score", 0)) < 25.0
    assert result["has_regression"] is False


# ── 2. Slow Query Regression ──────────────────────────────────────────────────

def test_02_slow_query_regression(rules):
    """
    Scenario 2: Slow query regression where execution time surges beyond critical threshold.
    Expectation: Flagged as REGRESSION or CRITICAL_REGRESSION with latency rule triggered.
    """
    before = {
        "query_id": "SYNTH-Q-005",
        "query_name": "Search appointments",
        "query_type": "search_appointments",
        "execution_time_ms": 28.5,
        "plan_text": "SEARCH a USING INDEX idx_appt_patient_date",
        "plan_hash": "hash_search_idx",
        "indexes": ["idx_appt_patient_date"],
        "statistics_age_days": 3,
        "statistics_status": "CURRENT",
        "workload_level": "NORMAL",
        "rows_examined": 350,
        "rows_returned": 24,
        "release_version": "v1.0.0"
    }
    after = {
        "query_id": "SYNTH-Q-005",
        "query_name": "Search appointments",
        "query_type": "search_appointments",
        "execution_time_ms": 195.0,  # +584% surge
        "plan_text": "SEARCH a USING INDEX idx_appt_patient_date",
        "plan_hash": "hash_search_idx",
        "indexes": ["idx_appt_patient_date"],
        "statistics_age_days": 4,
        "statistics_status": "CURRENT",
        "workload_level": "NORMAL",
        "rows_examined": 350,
        "rows_returned": 24,
        "release_version": "v1.1.0"
    }

    result = detection_engine.detect_query_regression(before, after, rules=rules)
    assert result["classification"] in ("REGRESSION", "CRITICAL_REGRESSION", "HIGH", "CRITICAL")
    assert result.get("score", result.get("regression_score", 0)) >= 30.0
    assert result["has_regression"] is True
    # Verify evidence includes execution time delta
    ev = result["evidence"]
    assert "percentage_change" in ev


# ── 3. Index-Related Regression ───────────────────────────────────────────────

def test_03_index_related_regression(rules):
    """
    Scenario 3: Index-related regression where critical index is removed and
    plan degrades to Full Table Scan.
    Expectation: CRITICAL severity, index_removed and full_table_scan detected.
    """
    before = {
        "query_id": "SYNTH-Q-002",
        "query_name": "Check doctor availability",
        "query_type": "check_doctor_availability",
        "execution_time_ms": 11.2,
        "plan_text": "SEARCH appointments USING INDEX idx_appt_doctor_date (doctor_id=? AND appt_date=?)",
        "plan_hash": "hash_doc_idx",
        "indexes": ["idx_appt_doctor_date"],
        "statistics_age_days": 2,
        "statistics_status": "CURRENT",
        "workload_level": "NORMAL",
        "rows_examined": 45,
        "rows_returned": 8,
        "release_version": "v1.0.0"
    }
    after = {
        "query_id": "SYNTH-Q-002",
        "query_name": "Check doctor availability",
        "query_type": "check_doctor_availability",
        "execution_time_ms": 280.0,
        "plan_text": "SCAN appointments (FULL TABLE SCAN)",
        "plan_hash": "hash_doc_scan",
        "indexes": [],  # index dropped
        "index_status": "REMOVED",
        "statistics_age_days": 2,
        "statistics_status": "CURRENT",
        "workload_level": "NORMAL",
        "rows_examined": 50000,
        "rows_returned": 8,
        "schema_change": "DROP INDEX idx_appt_doctor_date",
        "release_change": "index_removed",
        "release_version": "v1.1.0"
    }

    result = detection_engine.detect_query_regression(before, after, rules=rules)
    assert result["priority"] in ("CRITICAL", "HIGH")
    assert result["classification"] in ("CRITICAL_REGRESSION", "REGRESSION")

    ev = result["evidence"]
    triggered = [r.get("rule_name") for r in ev.get("triggered_rules", [])]
    assert any("index" in r or "scan" in r or "plan" in r for r in triggered)


# ── 4. Schema Change Regression ───────────────────────────────────────────────

def test_04_schema_change_regression(rules):
    """
    Scenario 4: Schema modification event (DDL column addition / partition shift)
    correlated with execution degradation.
    Expectation: Evaluates schema change context and attributes regression.
    """
    engine = rule_engine.RuleEngine(rules)
    signals = {
        "baseline_exec_ms": 20.0,
        "current_exec_ms": 65.0,
        "time_pct_change": 225.0,
        "plan_changed": True,
        "schema_changed": True,
        "schema_change": "ALTER TABLE appointments ADD COLUMN notes TEXT",
        "release_version": "v1.2.0",
        "index_status": "OPTIMAL"
    }
    eval_res = engine.evaluate(signals)
    assert eval_res["score"] >= 40.0
    triggered = [r["rule_name"] for r in eval_res["triggered_rules"]]
    assert "schema_changed" in triggered


# ── 5. Missing Execution Plan ─────────────────────────────────────────────────

def test_05_missing_execution_plan(rules):
    """
    Scenario 5: Telemetry where query plan extraction is missing or yields null tree.
    Expectation: Handled gracefully without crash, flagged for review or warning.
    """
    before = {
        "query_id": "SYNTH-Q-004",
        "query_name": "Verify slot booked",
        "query_type": "verify_slot_booked",
        "execution_time_ms": 13.8,
        "plan_text": "SEARCH appointments USING INDEX idx_appt_pk",
        "plan_hash": "hash_pk",
        "release_version": "v1.0.0"
    }
    after = {
        "query_id": "SYNTH-Q-004",
        "query_name": "Verify slot booked",
        "query_type": "verify_slot_booked",
        "execution_time_ms": 29.0,
        "plan_text": "",  # MISSING PLAN
        "plan_hash": None,
        "release_version": "v1.1.0"
    }

    # Must not raise exception
    result = detection_engine.detect_query_regression(before, after, rules=rules)
    assert "classification" in result
    assert "priority" in result


# ── 6. Invalid Telemetry ──────────────────────────────────────────────────────

def test_06_invalid_telemetry(rules):
    """
    Scenario 6: Telemetry containing invalid/negative/null values.
    Expectation: System sanitizes or handles gracefully without unhandled exceptions.
    """
    engine = rule_engine.RuleEngine(rules)
    signals = {
        "baseline_exec_ms": -10.0,  # Invalid negative
        "current_exec_ms": None,   # Missing
        "time_pct_change": None,
        "cost_drift_pct": "NaN",
        "statistics_age": -5
    }
    # Evaluator must not crash
    eval_res = engine.evaluate(signals)
    assert isinstance(eval_res["score"], (int, float))
    assert eval_res["priority"] in ("NORMAL", "OK", "WARNING", "MANUAL_REVIEW_REQUIRED")


# ── 7. Empty Query Results ────────────────────────────────────────────────────

def test_07_empty_query_results():
    """
    Scenario 7: Queries returning 0 matching records.
    Expectation: Plan extraction and timing profiling still execute cleanly.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE appointments (appt_id TEXT PRIMARY KEY, doctor_id TEXT);")
    # Table is completely empty
    plan = plan_extractor.extract_plan(conn, "SELECT * FROM appointments WHERE doctor_id = 'NON_EXISTENT'")
    assert plan.get("raw") is not None
    assert plan.get("has_full_scan") is True  # SQLite scan on empty unindexed table
    conn.close()


# ── 8. False Positives Suppression ───────────────────────────────────────────

def test_08_false_positives(rules):
    """
    Scenario 8: Mild latency increase within noise band with identical query plan.
    Expectation: Classified as NORMAL, false positive alarm suppressed.
    """
    before = {
        "query_id": "SYNTH-Q-003",
        "query_name": "Create appointment",
        "query_type": "create_appointment",
        "execution_time_ms": 22.0,
        "plan_text": "INSERT INTO appointments USING UNIQUE INDEX idx_appt_pk",
        "plan_hash": "hash_insert",
        "indexes": ["idx_appt_pk"],
        "statistics_status": "CURRENT",
        "workload_level": "NORMAL",
        "release_version": "v1.0.0"
    }
    after = {
        "query_id": "SYNTH-Q-003",
        "query_name": "Create appointment",
        "query_type": "create_appointment",
        "execution_time_ms": 23.5,  # +6.8% jitter
        "plan_text": "INSERT INTO appointments USING UNIQUE INDEX idx_appt_pk",
        "plan_hash": "hash_insert",
        "indexes": ["idx_appt_pk"],
        "statistics_status": "CURRENT",
        "workload_level": "NORMAL",
        "release_version": "v1.1.0"
    }

    result = detection_engine.detect_query_regression(before, after, rules=rules)
    assert result["classification"] in ("NORMAL", "OK")
    assert result["has_regression"] is False


# ── 9. False Negatives & Threshold Sensitivity ────────────────────────────────

def test_09_false_negatives(rules):
    """
    Scenario 9: Verifies that threshold configuration directly governs detection sensitivity.
    """
    engine_default = rule_engine.RuleEngine(rules)
    signals = {
        "baseline_exec_ms": 100.0,
        "current_exec_ms": 115.0,  # +15% latency increase
        "time_pct_change": 15.0,
        "plan_changed": False
    }
    # Under 20% default threshold -> NORMAL
    eval_default = engine_default.evaluate(signals)
    assert eval_default["priority"] == "NORMAL"

    # Under 10% sensitive threshold -> flags regression
    sensitive_rules = json.loads(json.dumps(rules))
    sensitive_rules["thresholds"]["execution_time_regression_percent"] = 10.0
    engine_sensitive = rule_engine.RuleEngine(sensitive_rules)
    eval_sensitive = engine_sensitive.evaluate(signals)
    assert any(r["rule_name"] == "execution_time_regression" for r in eval_sensitive["triggered_rules"])


# ── 10. Double-Booking-Sensitive Transactions ──────────────────────────────────

def test_10_double_booking_sensitive_transactions(rules):
    """
    Scenario 10: Double-booking sensitive query contention.
    Expectation: Escalated priority score via double_booking_multiplier and
    anti-collision verification.
    """
    engine = rule_engine.RuleEngine(rules)
    signals = {
        "baseline_exec_ms": 15.0,
        "current_exec_ms": 65.0,
        "time_pct_change": 333.3,
        "plan_changed": True,
        "full_table_scan_detected": True,
        "is_double_booking_critical": True
    }
    eval_res = engine.evaluate(signals)
    assert eval_res["priority"] == "CRITICAL"
    triggered = [r["rule_name"] for r in eval_res["triggered_rules"]]
    assert "double_booking_hazard_multiplier" in triggered


# ── 11. Edge Case 1: Connection Failure & Graceful Recovery ───────────────────

def test_11_edge_case_connection_failure():
    """
    Edge Case 1: Database connection failure or unreachable host.
    Expectation: Database adapter returns graceful error structure without process crash.
    """
    adapter = db_adapter.DatabaseAdapter(sqlite_path="nonexistent_dir/bad_path.db", prefer_postgres=False)
    # Timing profile on bad connection
    timing = adapter.run_timing_profile("SELECT 1;")
    assert timing.get("error") is not None or timing.get("p50_ms") == 0.0


# ── 12. Edge Case 2: High Concurrency Surge with Grace Band ───────────────────

def test_12_edge_case_concurrency_surge(rules):
    """
    Edge Case 2: High concurrency surge where latency increases solely due to
    queueing while query execution plan is completely unchanged.
    Expectation: Workload grace logic suppresses false critical alerts.
    """
    engine = rule_engine.RuleEngine(rules)
    signals = {
        "baseline_exec_ms": 12.0,
        "current_exec_ms": 25.0,
        "time_pct_change": 108.3,
        "plan_changed": False,
        "is_workload_grace": True,
        "workload_surge": True
    }
    eval_res = engine.evaluate(signals)
    # Score heavily discounted by workload grace (0.15x)
    assert eval_res["score"] < 25.0
    assert eval_res["priority"] == "NORMAL"


# ── 13. Edge Case 3: Unindexed Foreign Key Scan Detection ─────────────────────

def test_13_edge_case_unindexed_foreign_key():
    """
    Edge Case 3: Join on unindexed foreign key creates Nested Loop with Full Table Scan.
    Expectation: Plan comparator identifies lack of index on join and recommends foreign key index.
    """
    base_plan = {
        "scan_type": "Index Scan",
        "uses_index": True,
        "indexes": ["idx_appt_doctor_date"],
        "join_strategy": "Hash Join",
        "estimated_cost": 15.0
    }
    current_plan = {
        "scan_type": "Full Table Scan",
        "uses_index": False,
        "indexes": [],
        "join_strategy": "Nested Loop",
        "estimated_cost": 650.0
    }
    diff = plan_comparator.compare_execution_plans(base_plan, current_plan)
    assert diff["plan_changed"] is True
    assert diff["severity"] == "CRITICAL"
    assert "Foreign key" in str(diff["recommendations"]) or "Restore" in str(diff["recommendations"])
