"""
test_dataset.py
===============
Test suite for Phase 2: Synthetic Dataset Generation.

Verifies:
1. File generation parity across CSV, JSON, and SQLite.
2. Complete schema compliance across all 27 required fields.
3. Accurate representation of all 9 hospital appointment query types.
4. Inclusion of critical double-booking sensitive workflows.
5. Representation of all 11 required system change types.
6. Representation of all 4 required edge / failure scenarios.
7. Deterministic, measurable rule-derived regression labels (no random assignment).
8. Strict zero-PII guarantee.
9. Successful consumption by the regression detector engine.
"""

import os
import sys
import json
import csv
import sqlite3
import pytest
from typing import Dict, List, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.dataset_generator import (
    generate_synthetic_dataset,
    CSV_PATH,
    JSON_PATH,
    SQLITE_PATH,
    evaluate_record_label
)
from src.dataset_importer import load_synthetic_records, import_dataset_to_detector

REQUIRED_FIELDS = [
    "query_id", "query_name", "query_type", "release_id", "release_version",
    "timestamp", "execution_time_ms", "baseline_execution_time_ms",
    "rows_examined", "rows_returned", "cpu_time_ms", "io_cost",
    "plan_hash", "baseline_plan_hash", "plan_changed", "index_name",
    "index_status", "statistics_age", "statistics_status", "workload_level",
    "schema_change", "release_change", "regression_label", "regression_severity",
    "expected_impact", "user_impact", "evidence"
]

REQUIRED_QUERY_TYPES = [
    "find_available_slots",
    "check_doctor_availability",
    "create_appointment",
    "verify_slot_booked",
    "search_appointments",
    "update_appointment_status",
    "cancel_appointment",
    "retrieve_doctor_schedule",
    "retrieve_department_schedule"
]

REQUIRED_CHANGE_TYPES = [
    "index_added",
    "index_removed",
    "index_changed",
    "statistics_stale",
    "schema_change",
    "workload_increase",
    "query_plan_change",
    "table_growth",
    "bad_query_plan",
    "missing_index",
    "release_deployment"
]

REQUIRED_LABELS = ["NORMAL", "WARNING", "REGRESSION", "CRITICAL_REGRESSION"]

@pytest.fixture(scope="module")
def dataset_records():
    """Loads records from SQLite for testing."""
    if not os.path.exists(SQLITE_PATH):
        # Generate if not existing
        dataset = generate_synthetic_dataset(10)
        from src.dataset_generator import export_to_csv, export_to_json, export_to_sqlite
        export_to_csv(dataset, CSV_PATH)
        export_to_json(dataset, JSON_PATH)
        export_to_sqlite(dataset, SQLITE_PATH)
    return load_synthetic_records(SQLITE_PATH)


def test_DST01_file_existence_and_parity(dataset_records):
    """Verify all 3 output formats exist and have identical record counts (> 500 records)."""
    assert os.path.exists(CSV_PATH), "CSV file does not exist"
    assert os.path.exists(JSON_PATH), "JSON file does not exist"
    assert os.path.exists(SQLITE_PATH), "SQLite file does not exist"

    # Check JSON count
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        json_data = json.load(f)
    assert len(json_data) >= 500, f"Expected >= 500 records, got {len(json_data)}"

    # Check CSV count
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)
    assert len(csv_rows) == len(json_data), "CSV and JSON record counts mismatch"

    # Check SQLite count
    assert len(dataset_records) == len(json_data), "SQLite and JSON record counts mismatch"


def test_DST02_all_27_fields_present(dataset_records):
    """Verify that every record contains all 27 required fields without unexpected missing keys."""
    assert len(dataset_records) > 0
    sample = dataset_records[0]
    for field in REQUIRED_FIELDS:
        assert field in sample, f"Missing required field: {field}"

    # Also verify in CSV
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        csv_fields = reader.fieldnames
        for field in REQUIRED_FIELDS:
            assert field in csv_fields, f"Missing field in CSV: {field}"


def test_DST03_all_9_query_types_represented(dataset_records):
    """Verify all 9 hospital appointment query types are represented."""
    present_types = set(r["query_type"] for r in dataset_records)
    for qt in REQUIRED_QUERY_TYPES:
        assert qt in present_types, f"Query type {qt} is not represented in dataset"


def test_DST04_double_booking_workflows_represented(dataset_records):
    """Verify that double-booking sensitive workflows (slot verification, availability) are present with critical severity."""
    db_records = [r for r in dataset_records if r["query_type"] == "verify_slot_booked"]
    assert len(db_records) > 0, "No verify_slot_booked records found"

    # Verify at least one severe regression specifically highlighting double-booking risk
    critical_db = [
        r for r in db_records
        if r["regression_label"] == "CRITICAL_REGRESSION" and "DOUBLE-BOOKING" in r["user_impact"].upper()
    ]
    assert len(critical_db) > 0, "Expected at least one CRITICAL double-booking regression record"


def test_DST05_all_11_change_types_represented(dataset_records):
    """Verify all 11 required system change types are present."""
    present_changes = set(r["release_change"] for r in dataset_records)
    for ch in REQUIRED_CHANGE_TYPES:
        assert ch in present_changes, f"Change type {ch} missing from dataset"


def test_DST06_all_4_edge_scenarios_represented(dataset_records):
    """
    Verify all 4 edge/failure scenarios:
    1. Missing execution plan
    2. Stale statistics
    3. Query with increased execution time but no actual regression (FP suppression)
    4. Missing index / plan parsing failure
    """
    # 1. Missing execution plan
    missing_plan = [r for r in dataset_records if r["plan_hash"] is None or r["plan_hash"] == ""]
    assert len(missing_plan) > 0, "Edge case 1 (Missing execution plan) not found"

    # 2. Stale statistics
    stale_stats = [r for r in dataset_records if r["statistics_status"] == "STALE" and r["statistics_age"] > 30]
    assert len(stale_stats) > 0, "Edge case 2 (Stale statistics) not found"

    # 3. Increased execution time without regression (False positive grace suppression)
    fp_grace = [
        r for r in dataset_records
        if r["workload_level"] == "PEAK"
        and r["execution_time_ms"] > r["baseline_execution_time_ms"]
        and r["regression_label"] == "NORMAL"
    ]
    assert len(fp_grace) > 0, "Edge case 3 (Increased execution time but no regression) not found"

    # 4. Missing index / plan parsing degradation
    missing_idx = [
        r for r in dataset_records
        if r["index_status"] == "MISSING" or "PARSE_ERROR" in str(r.get("plan_hash"))
    ]
    assert len(missing_idx) > 0, "Edge case 4 (Missing index / parse degradation) not found"


def test_DST07_rule_based_label_determinism():
    """Verify that evaluate_record_label follows deterministic thresholds and is not random."""
    # Test absolute critical threshold (>= 2000ms)
    label, sev, _, _, _ = evaluate_record_label(
        exec_ms=2500.0,
        baseline_exec_ms=15.0,
        plan_changed=False,
        index_status="OPTIMAL",
        stats_status="CURRENT",
        workload_level="NORMAL",
        double_booking_critical=False
    )
    assert label == "CRITICAL_REGRESSION"
    assert sev == "CRITICAL"

    # Test baseline noise band (<10% change, no plan change)
    label_noise, sev_noise, _, _, _ = evaluate_record_label(
        exec_ms=15.5,
        baseline_exec_ms=15.0,
        plan_changed=False,
        index_status="OPTIMAL",
        stats_status="CURRENT",
        workload_level="NORMAL",
        double_booking_critical=False
    )
    assert label_noise == "NORMAL"
    assert sev_noise == "OK"

    # Test double-booking critical query with dropped index
    label_db, sev_db, _, _, _ = evaluate_record_label(
        exec_ms=80.0,
        baseline_exec_ms=13.8,
        plan_changed=True,
        index_status="REMOVED",
        stats_status="CURRENT",
        workload_level="NORMAL",
        double_booking_critical=True
    )
    assert label_db == "CRITICAL_REGRESSION"
    assert sev_db == "CRITICAL"


def test_DST08_zero_pii_guarantee(dataset_records):
    """Verify no real patient names, NHS numbers, or identifiable addresses are present."""
    forbidden_terms = ["nhs", "social security", "dr. john", "patient name", "@hospital.nhs.uk"]
    for r in dataset_records:
        evidence_str = str(r["evidence"]).lower()
        impact_str = str(r["user_impact"]).lower()
        for term in forbidden_terms:
            assert term not in evidence_str, f"Found sensitive term '{term}' in evidence"
            assert term not in impact_str, f"Found sensitive term '{term}' in user_impact"

        # Ensure no real clinical or real name fixtures
        assert "SMITH" not in str(r.values())
        assert "JOHNSON" not in str(r.values())


def test_DST09_detector_consumption(tmp_path):
    """Verify that detector_store and regression_analyser can consume the synthetic dataset cleanly."""
    temp_store = str(tmp_path / "temp_detector.db")
    sample_records = [
        # Baseline
        {
            "query_id": "SYNTH-Q-001",
            "query_name": "Find available slots",
            "query_type": "find_available_slots",
            "release_id": "REL-101",
            "release_version": "v1.0.0",
            "timestamp": "2026-07-01 08:00:00",
            "execution_time_ms": 14.5,
            "baseline_execution_time_ms": 14.5,
            "rows_examined": 120,
            "rows_returned": 18,
            "cpu_time_ms": 9.2,
            "io_cost": 2.1,
            "plan_hash": "hash_base_001",
            "baseline_plan_hash": "hash_base_001",
            "plan_changed": 0,
            "index_name": "idx_appt_dept_date_status",
            "index_status": "OPTIMAL",
            "statistics_age": 5,
            "statistics_status": "CURRENT",
            "workload_level": "NORMAL",
            "schema_change": "NONE",
            "release_change": "release_deployment",
            "regression_label": "NORMAL",
            "regression_severity": "OK",
            "expected_impact": "None",
            "user_impact": "None",
            "evidence": json.dumps({"rule": "BASELINE"})
        },
        # Run with regression
        {
            "query_id": "SYNTH-Q-001",
            "query_name": "Find available slots",
            "query_type": "find_available_slots",
            "release_id": "REL-102",
            "release_version": "v1.1.0",
            "timestamp": "2026-07-15 08:00:00",
            "execution_time_ms": 185.0,
            "baseline_execution_time_ms": 14.5,
            "rows_examined": 50000,
            "rows_returned": 18,
            "cpu_time_ms": 150.0,
            "io_cost": 32.0,
            "plan_hash": "hash_scan_001",
            "baseline_plan_hash": "hash_base_001",
            "plan_changed": 1,
            "index_name": "None",
            "index_status": "REMOVED",
            "statistics_age": 19,
            "statistics_status": "CURRENT",
            "workload_level": "NORMAL",
            "schema_change": "INDEX_DROPPED",
            "release_change": "index_removed",
            "regression_label": "CRITICAL_REGRESSION",
            "regression_severity": "CRITICAL",
            "expected_impact": "Full table scan",
            "user_impact": "Timeout",
            "evidence": json.dumps({"rule": "INDEX_LOST"})
        }
    ]

    res = import_dataset_to_detector(sample_records, store_path=temp_store)
    assert res["imported_snapshots"] == 2
    assert len(res["verification_results"]) == 1
    vr = res["verification_results"][0]
    assert vr["release"] == "v1.1.0"
    assert vr["regressions_detected"] >= 1
