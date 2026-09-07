"""
dataset_generator.py
====================
Phase 2: Synthetic Dataset Generator for Hospital Appointment Platform.

Generates a realistic, completely anonymised synthetic dataset representing:
1. Query execution records
2. Query plans & hashes
3. Execution times & baseline comparisons
4. Index health & states
5. Database statistics & staleness
6. Release/change history
7. Workload conditions
8. Measurable rule-derived regression labels (NORMAL, WARNING, REGRESSION, CRITICAL_REGRESSION)
9. Structured detection evidence & impact analysis

Includes 9 hospital appointment query types, 11 change events, and 4 failure/edge scenarios.
All patient data and identifiers are 100% synthetic (zero PII).

Outputs:
  - data/synthetic_dataset.csv
  - data/synthetic_dataset.json
  - data/synthetic_dataset.db (SQLite)
"""

import os
import sys
import json
import csv
import sqlite3
import hashlib
import random
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple, Optional

# Ensure reproducibility
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

CSV_PATH = os.path.join(DATA_DIR, "synthetic_dataset.csv")
JSON_PATH = os.path.join(DATA_DIR, "synthetic_dataset.json")
SQLITE_PATH = os.path.join(DATA_DIR, "synthetic_dataset.db")

# ── Query Catalog (9 Hospital Appointment Query Types) ─────────────────────────

QUERY_CATALOG = [
    {
        "query_id": "SYNTH-Q-001",
        "query_name": "Find available appointment slots",
        "query_type": "find_available_slots",
        "base_exec_ms": 14.5,
        "base_rows_examined": 120,
        "base_rows_returned": 18,
        "base_cpu_ms": 9.2,
        "base_io_cost": 2.1,
        "primary_index": "idx_appt_dept_date_status",
        "double_booking_critical": False,
        "sql_template": "SELECT slot_time, doctor_id, dept_id FROM appointment_slots WHERE dept_id = 'SYNTH-DEPT-01' AND slot_date = '2026-09-15' AND is_available = 1 ORDER BY slot_time;",
        "base_plan_text": "SEARCH appointment_slots USING INDEX idx_appt_dept_date_status (dept_id=? AND slot_date=? AND is_available=?)"
    },
    {
        "query_id": "SYNTH-Q-002",
        "query_name": "Check doctor availability",
        "query_type": "check_doctor_availability",
        "base_exec_ms": 11.2,
        "base_rows_examined": 45,
        "base_rows_returned": 8,
        "base_cpu_ms": 7.0,
        "base_io_cost": 1.4,
        "primary_index": "idx_appt_doctor_date",
        "double_booking_critical": True,
        "sql_template": "SELECT appt_id, appt_time, duration_mins, status FROM appointments WHERE doctor_id = 'SYNTH-D-012' AND appt_date = '2026-09-15' AND status = 'SCHEDULED';",
        "base_plan_text": "SEARCH appointments USING INDEX idx_appt_doctor_date (doctor_id=? AND appt_date=?)"
    },
    {
        "query_id": "SYNTH-Q-003",
        "query_name": "Create appointment",
        "query_type": "create_appointment",
        "base_exec_ms": 22.0,
        "base_rows_examined": 15,
        "base_rows_returned": 1,
        "base_cpu_ms": 14.5,
        "base_io_cost": 4.2,
        "primary_index": "idx_appt_doctor_date_time",
        "double_booking_critical": True,
        "sql_template": "INSERT INTO appointments (appt_id, patient_id, doctor_id, dept_id, appt_date, appt_time, duration_mins, status) VALUES ('SYNTH-A-999999', 'SYNTH-P-004312', 'SYNTH-D-012', 'SYNTH-DEPT-01', '2026-09-15', '10:30', 30, 'SCHEDULED');",
        "base_plan_text": "INSERT INTO appointments USING UNIQUE INDEX idx_appt_pk"
    },
    {
        "query_id": "SYNTH-Q-004",
        "query_name": "Verify whether an appointment slot is already booked",
        "query_type": "verify_slot_booked",
        "base_exec_ms": 13.8,
        "base_rows_examined": 25,
        "base_rows_returned": 1,
        "base_cpu_ms": 8.5,
        "base_io_cost": 1.8,
        "primary_index": "idx_appt_doctor_date_time_status",
        "double_booking_critical": True,
        "sql_template": "SELECT COUNT(*) as is_booked FROM appointments WHERE doctor_id = 'SYNTH-D-012' AND appt_date = '2026-09-15' AND appt_time = '10:30' AND status = 'SCHEDULED';",
        "base_plan_text": "SEARCH appointments USING COVERING INDEX idx_appt_doctor_date_time_status (doctor_id=? AND appt_date=? AND appt_time=?)"
    },
    {
        "query_id": "SYNTH-Q-005",
        "query_name": "Search appointments",
        "query_type": "search_appointments",
        "base_exec_ms": 28.5,
        "base_rows_examined": 350,
        "base_rows_returned": 24,
        "base_cpu_ms": 19.0,
        "base_io_cost": 5.8,
        "primary_index": "idx_appt_patient_date",
        "double_booking_critical": False,
        "sql_template": "SELECT a.appt_id, a.appt_date, a.appt_time, a.status, d.specialty FROM appointments a JOIN doctors d ON a.doctor_id = d.doctor_id WHERE a.patient_id = 'SYNTH-P-001200' AND a.appt_date >= '2026-09-01' ORDER BY a.appt_date DESC;",
        "base_plan_text": "SEARCH a USING INDEX idx_appt_patient_date (patient_id=? AND appt_date>=?); SEARCH d USING INDEX idx_doctor_pk (doctor_id=?)"
    },
    {
        "query_id": "SYNTH-Q-006",
        "query_name": "Update appointment status",
        "query_type": "update_appointment_status",
        "base_exec_ms": 16.4,
        "base_rows_examined": 1,
        "base_rows_returned": 1,
        "base_cpu_ms": 10.2,
        "base_io_cost": 3.1,
        "primary_index": "idx_appt_pk",
        "double_booking_critical": False,
        "sql_template": "UPDATE appointments SET status = 'COMPLETED', updated_at = '2026-09-15T11:00:00' WHERE appt_id = 'SYNTH-A-102941';",
        "base_plan_text": "SEARCH appointments USING INDEX idx_appt_pk (appt_id=?)"
    },
    {
        "query_id": "SYNTH-Q-007",
        "query_name": "Cancel appointment",
        "query_type": "cancel_appointment",
        "base_exec_ms": 15.1,
        "base_rows_examined": 1,
        "base_rows_returned": 1,
        "base_cpu_ms": 9.5,
        "base_io_cost": 2.9,
        "primary_index": "idx_appt_pk",
        "double_booking_critical": True,
        "sql_template": "UPDATE appointments SET status = 'CANCELLED', updated_at = '2026-09-15T09:15:00' WHERE appt_id = 'SYNTH-A-102942' AND status = 'SCHEDULED';",
        "base_plan_text": "SEARCH appointments USING INDEX idx_appt_pk (appt_id=?)"
    },
    {
        "query_id": "SYNTH-Q-008",
        "query_name": "Retrieve doctor schedule",
        "query_type": "retrieve_doctor_schedule",
        "base_exec_ms": 18.2,
        "base_rows_examined": 90,
        "base_rows_returned": 16,
        "base_cpu_ms": 11.4,
        "base_io_cost": 2.6,
        "primary_index": "idx_appt_doctor_date",
        "double_booking_critical": True,
        "sql_template": "SELECT appt_id, patient_id, appt_time, duration_mins, status FROM appointments WHERE doctor_id = 'SYNTH-D-012' AND appt_date = '2026-09-15' ORDER BY appt_time ASC;",
        "base_plan_text": "SEARCH appointments USING INDEX idx_appt_doctor_date (doctor_id=? AND appt_date=?)"
    },
    {
        "query_id": "SYNTH-Q-009",
        "query_name": "Retrieve department schedule",
        "query_type": "retrieve_department_schedule",
        "base_exec_ms": 35.0,
        "base_rows_examined": 480,
        "base_rows_returned": 65,
        "base_cpu_ms": 23.5,
        "base_io_cost": 6.8,
        "primary_index": "idx_appt_dept_date",
        "double_booking_critical": False,
        "sql_template": "SELECT appt_date, COUNT(*) as scheduled_count FROM appointments WHERE dept_id = 'SYNTH-DEPT-01' AND appt_date BETWEEN '2026-09-01' AND '2026-09-30' AND status = 'SCHEDULED' GROUP BY appt_date ORDER BY appt_date;",
        "base_plan_text": "SEARCH appointments USING INDEX idx_appt_dept_date (dept_id=? AND appt_date BETWEEN ? AND ?) USE TEMP B-TREE FOR GROUP BY"
    }
]

# ── Releases and Deployment Context ────────────────────────────────────────────

RELEASES = [
    {
        "release_id": "REL-101",
        "release_version": "v1.0.0",
        "stage": "BASELINE",
        "change_type": "release_deployment",
        "schema_change": "NONE",
        "date_offset_days": -60,
        "description": "Initial stable platform release. All optimal composite indexes installed."
    },
    {
        "release_id": "REL-102",
        "release_version": "v1.1.0",
        "stage": "INDEX_REGRESSION",
        "change_type": "index_removed",
        "schema_change": "INDEX_DROPPED",
        "date_offset_days": -45,
        "description": "Faulty migration script dropped composite index idx_appt_doctor_date_time_status."
    },
    {
        "release_id": "REL-103",
        "release_version": "v1.2.0",
        "stage": "OPTIMIZATION",
        "change_type": "index_added",
        "schema_change": "INDEX_ADDED",
        "date_offset_days": -30,
        "description": "Added covering index idx_appt_doctor_date_time_status and optimized dept queries."
    },
    {
        "release_id": "REL-104",
        "release_version": "v1.3.0",
        "stage": "STALE_STATS",
        "change_type": "statistics_stale",
        "schema_change": "NONE",
        "date_offset_days": -22,
        "description": "Vacuum maintenance paused; SQLite statistics grew stale over 45 days of bulk slot loads."
    },
    {
        "release_id": "REL-105",
        "release_version": "v1.4.0",
        "stage": "DATA_EXPLOSION",
        "change_type": "table_growth",
        "schema_change": "NONE",
        "date_offset_days": -15,
        "description": "Annual flu vaccination campaign increased active appointment records 4.5x."
    },
    {
        "release_id": "REL-106",
        "release_version": "v1.5.0",
        "stage": "SCHEMA_ALTER",
        "change_type": "schema_change",
        "schema_change": "COLUMN_ADDED",
        "date_offset_days": -10,
        "description": "Added triage_priority column to appointments without re-indexing compound filter."
    },
    {
        "release_id": "REL-107",
        "release_version": "v2.0.0",
        "stage": "WORKLOAD_SURGE",
        "change_type": "workload_increase",
        "schema_change": "NONE",
        "date_offset_days": -5,
        "description": "Peak morning booking window (08:00-09:30) with 8x concurrent transactions."
    },
    {
        "release_id": "REL-108",
        "release_version": "v2.1.0",
        "stage": "BAD_QUERY_PLAN",
        "change_type": "bad_query_plan",
        "schema_change": "NONE",
        "date_offset_days": -4,
        "description": "Query planner regressed on join ordering following optimizer parameter tuning."
    },
    {
        "release_id": "REL-109",
        "release_version": "v2.2.0",
        "stage": "INDEX_CHANGED",
        "change_type": "index_changed",
        "schema_change": "INDEX_MODIFIED",
        "date_offset_days": -1,
        "description": "Composite index idx_appt_dept_date had column ordering swapped, degrading prefix search."
    }
]

# ── Plan Hash Helper ──────────────────────────────────────────────────────────

def compute_plan_hash(plan_text: Optional[str]) -> Optional[str]:
    if not plan_text:
        return None
    return hashlib.sha256(plan_text.encode("utf-8")).hexdigest()[:16]

# ── Measurable Rule Engine ────────────────────────────────────────────────────

def evaluate_record_label(
    exec_ms: float,
    baseline_exec_ms: float,
    plan_changed: bool,
    index_status: str,
    stats_status: str,
    workload_level: str,
    double_booking_critical: bool,
    is_edge_fp: bool = False
) -> Tuple[str, str, str, str, Dict[str, Any]]:
    """
    Deterministically computes:
      regression_label, regression_severity, expected_impact, user_impact, evidence
    using measurable thresholds defined in config/rules.yaml.
    """
    delta_ms = exec_ms - baseline_exec_ms
    pct_change = (delta_ms / baseline_exec_ms * 100.0) if baseline_exec_ms > 0 else 0.0

    # Measurable thresholds from config/rules.yaml
    TIME_REGRESSION_PCT = 20.0
    TIME_HIGH_PCT = 50.0
    TIME_CRITICAL_PCT = 100.0
    ABSOLUTE_CRITICAL_MS = 2000.0
    NOISE_BAND_PCT = 10.0

    # Edge Case 3: False Positive Grace Period (increased execution time due to workload only)
    if is_edge_fp or (workload_level in ("HIGH", "PEAK") and not plan_changed and index_status == "OPTIMAL" and stats_status == "CURRENT"):
        if pct_change < 45.0 and exec_ms < 100.0:
            evidence = {
                "rule_triggered": "FALSE_POSITIVE_GRACE_BAND",
                "delta_pct": round(pct_change, 2),
                "delta_ms": round(delta_ms, 2),
                "plan_diff": "NONE - Query plan remains optimal index search",
                "index_impact": f"{index_status} (no index drop)",
                "workload_effect": f"Queue delay during {workload_level} workload",
                "recommendation": "Maintain baseline. No schema or query regression detected; transient queue latency."
            }
            return (
                "NORMAL",
                "OK",
                "Slight concurrency queueing without plan degradation.",
                "Imperceptible patient UI latency (<50ms shift); no booking hazard.",
                evidence
            )

    # Within noise band
    if abs(pct_change) <= NOISE_BAND_PCT and not plan_changed and index_status in ("OPTIMAL", "ADDED"):
        evidence = {
            "rule_triggered": "WITHIN_NOISE_BAND",
            "delta_pct": round(pct_change, 2),
            "delta_ms": round(delta_ms, 2),
            "plan_diff": "NONE",
            "index_impact": index_status,
            "recommendation": "Performance within normal operational variance."
        }
        return (
            "NORMAL",
            "OK",
            "System performance within acceptable noise band.",
            "Normal patient scheduling experience with zero delay.",
            evidence
        )

    # CRITICAL REGRESSION CONDITIONS
    # 1. Absolute runtime >= 2000ms
    # 2. Time increase >= 100% AND plan changed / index lost
    # 3. Double-booking sensitive query where index is removed or full scan introduced
    if (
        exec_ms >= ABSOLUTE_CRITICAL_MS or
        (pct_change >= TIME_CRITICAL_PCT and (plan_changed or index_status in ("REMOVED", "MISSING"))) or
        (double_booking_critical and index_status in ("REMOVED", "MISSING") and pct_change >= 40.0)
    ):
        label = "CRITICAL_REGRESSION"
        severity = "CRITICAL"
        expected_impact = "Severe database CPU exhaustion, lock contention, and full table scans."
        if double_booking_critical:
            user_impact = "CRITICAL DOUBLE-BOOKING HAZARD: Slot check latency creates concurrent race window where two patients book same slot."
        else:
            user_impact = "Patient booking portal timeout; department schedule unavailable."

        evidence = {
            "rule_triggered": "ABSOLUTE_CRITICAL_MS" if exec_ms >= ABSOLUTE_CRITICAL_MS else "TIME_CRITICAL_PLAN_SCAN_REGRESSION",
            "delta_pct": round(pct_change, 2),
            "delta_ms": round(delta_ms, 2),
            "plan_diff": "Index search converted to full table SCAN or Cartesian product",
            "index_impact": f"Index status: {index_status}",
            "double_booking_risk": "HIGH" if double_booking_critical else "LOW",
            "recommendation": "BLOCK RELEASE. Immediately restore dropped/missing index or revert bad query plan."
        }
        return (label, severity, expected_impact, user_impact, evidence)

    # REGRESSION CONDITIONS
    # Time increase >= 50% OR plan changed to full scan
    if pct_change >= TIME_HIGH_PCT or (plan_changed and pct_change >= TIME_REGRESSION_PCT):
        label = "REGRESSION"
        severity = "HIGH"
        expected_impact = "Significant latency degradation across booking transactions."
        user_impact = "Noticeable scheduling UI lag; increased booking abandonment rate."
        evidence = {
            "rule_triggered": "TIME_HIGH_PCT_REGRESSION",
            "delta_pct": round(pct_change, 2),
            "delta_ms": round(delta_ms, 2),
            "plan_diff": "Sub-optimal plan selection or extra temporary B-Tree sorting",
            "index_impact": f"Index status: {index_status}",
            "recommendation": "Analyze index selectivity and query predicates before deployment."
        }
        return (label, severity, expected_impact, user_impact, evidence)

    # WARNING CONDITIONS
    # Time increase >= 20% OR statistics stale OR mild drift
    if pct_change >= TIME_REGRESSION_PCT or stats_status == "STALE":
        label = "WARNING"
        severity = "MEDIUM"
        expected_impact = "Moderate query slowdown; planner row estimates drifting."
        user_impact = "Minor booking delay under load; warning flag raised for DBA review."
        evidence = {
            "rule_triggered": "STATS_STALE_OR_MILD_TIME_INCREASE",
            "delta_pct": round(pct_change, 2),
            "delta_ms": round(delta_ms, 2),
            "plan_diff": "Planner estimate mismatch due to stale stats",
            "index_impact": f"Index status: {index_status}",
            "statistics_status": stats_status,
            "recommendation": "Execute ANALYZE on appointments table to refresh statistics."
        }
        return (label, severity, expected_impact, user_impact, evidence)

    # Performance improved or negligible shift
    evidence = {
        "rule_triggered": "NORMAL_STABLE_OR_IMPROVED",
        "delta_pct": round(pct_change, 2),
        "delta_ms": round(delta_ms, 2),
        "plan_diff": "NONE",
        "index_impact": index_status,
        "recommendation": "Release is safe for deployment."
    }
    return (
        "NORMAL",
        "OK",
        "Stable execution profile.",
        "Smooth booking workflow.",
        evidence
    )

# ── Dataset Generation Core ───────────────────────────────────────────────────

def generate_synthetic_dataset(records_per_query_per_release: int = 10) -> List[Dict[str, Any]]:
    """
    Generates synthetic query execution records spanning baseline and multiple releases,
    including normal workloads, regressions, and 4 failure/edge scenarios.
    """
    dataset: List[Dict[str, Any]] = []
    base_timestamp = datetime(2026, 7, 1, 8, 0, 0)

    for rel_idx, rel in enumerate(RELEASES):
        rel_id = rel["release_id"]
        rel_version = rel["release_version"]
        stage = rel["stage"]
        primary_change = rel["change_type"]
        schema_change = rel["schema_change"]
        rel_time_base = base_timestamp + timedelta(days=rel["date_offset_days"] + 60)

        for q in QUERY_CATALOG:
            qid = q["query_id"]
            qname = q["query_name"]
            qtype = q["query_type"]
            base_ms = q["base_exec_ms"]
            base_plan = q["base_plan_text"]
            base_plan_hash = compute_plan_hash(base_plan)
            base_rows_ex = q["base_rows_examined"]
            base_rows_ret = q["base_rows_returned"]
            base_cpu = q["base_cpu_ms"]
            base_io = q["base_io_cost"]
            is_double_booking = q["double_booking_critical"]

            for rep in range(records_per_query_per_release):
                record_time = rel_time_base + timedelta(hours=rep * 2, minutes=random.randint(0, 50))
                timestamp_str = record_time.strftime("%Y-%m-%d %H:%M:%S")

                # Default states
                workload = random.choice(["LOW", "NORMAL", "NORMAL", "HIGH"])
                stats_age = random.randint(1, 14)
                stats_status = "CURRENT"
                idx_status = "OPTIMAL"
                idx_name = q["primary_index"]
                curr_plan = base_plan
                curr_plan_hash = base_plan_hash
                plan_changed = 0
                rel_change = primary_change
                is_edge_fp = False

                # Baseline Release: REL-101
                if stage == "BASELINE":
                    jitter = random.uniform(-0.08, 0.08)
                    exec_ms = round(base_ms * (1.0 + jitter), 2)
                    cpu_ms = round(base_cpu * (1.0 + jitter), 2)
                    io_cost = round(base_io * (1.0 + jitter), 2)
                    rows_examined = int(base_rows_ex * (1.0 + jitter * 0.5))
                    rows_returned = base_rows_ret

                # Index Dropped Regression: REL-102
                elif stage == "INDEX_REGRESSION":
                    # Affects double-booking checks heavily (SYNTH-Q-002, SYNTH-Q-004, SYNTH-Q-008)
                    if qid in ("SYNTH-Q-002", "SYNTH-Q-004", "SYNTH-Q-008"):
                        idx_status = "REMOVED"
                        idx_name = "None"
                        curr_plan = "SCAN appointments (full table scan without index)"
                        curr_plan_hash = compute_plan_hash(curr_plan)
                        plan_changed = 1
                        # Extreme slowdown: 8x to 25x slower
                        multiplier = random.uniform(12.0, 24.0)
                        exec_ms = round(base_ms * multiplier, 2)
                        cpu_ms = round(base_cpu * multiplier * 0.9, 2)
                        io_cost = round(base_io * multiplier * 1.5, 2)
                        rows_examined = 50000 + random.randint(100, 2000)
                        rows_returned = base_rows_ret
                    else:
                        # Non-affected queries remain normal
                        jitter = random.uniform(-0.05, 0.10)
                        exec_ms = round(base_ms * (1.0 + jitter), 2)
                        cpu_ms = round(base_cpu * (1.0 + jitter), 2)
                        io_cost = round(base_io * (1.0 + jitter), 2)
                        rows_examined = base_rows_ex
                        rows_returned = base_rows_ret

                # Optimization: REL-103
                elif stage == "OPTIMIZATION":
                    idx_status = "ADDED"
                    rel_change = "index_added"
                    curr_plan = base_plan + " (enhanced covering)"
                    curr_plan_hash = compute_plan_hash(curr_plan)
                    plan_changed = 1
                    # 10% to 30% faster
                    exec_ms = round(base_ms * random.uniform(0.70, 0.90), 2)
                    cpu_ms = round(base_cpu * random.uniform(0.70, 0.90), 2)
                    io_cost = round(base_io * random.uniform(0.60, 0.85), 2)
                    rows_examined = max(1, int(base_rows_ex * 0.7))
                    rows_returned = base_rows_ret

                # Stale Statistics: REL-104 (EDGE CASE 2)
                elif stage == "STALE_STATS":
                    stats_age = random.randint(35, 60)
                    stats_status = "STALE"
                    rel_change = "statistics_stale"
                    if qid in ("SYNTH-Q-001", "SYNTH-Q-005", "SYNTH-Q-009"):
                        # Planner misestimates row count
                        curr_plan = base_plan + " (planner suboptimal scan order due to stale stats)"
                        curr_plan_hash = compute_plan_hash(curr_plan)
                        plan_changed = 1
                        multiplier = random.uniform(1.35, 1.80)
                        exec_ms = round(base_ms * multiplier, 2)
                        cpu_ms = round(base_cpu * multiplier, 2)
                        io_cost = round(base_io * (multiplier * 1.2), 2)
                        rows_examined = int(base_rows_ex * multiplier * 2.0)
                        rows_returned = base_rows_ret
                    else:
                        jitter = random.uniform(0.05, 0.15)
                        exec_ms = round(base_ms * (1.0 + jitter), 2)
                        cpu_ms = round(base_cpu * (1.0 + jitter), 2)
                        io_cost = round(base_io * (1.0 + jitter), 2)
                        rows_examined = base_rows_ex
                        rows_returned = base_rows_ret

                # Table Growth: REL-105
                elif stage == "DATA_EXPLOSION":
                    rel_change = "table_growth"
                    multiplier = random.uniform(1.8, 3.2)
                    rows_examined = int(base_rows_ex * multiplier * 1.5)
                    rows_returned = int(base_rows_ret * random.uniform(1.5, 2.5))
                    exec_ms = round(base_ms * multiplier, 2)
                    cpu_ms = round(base_cpu * multiplier, 2)
                    io_cost = round(base_io * (multiplier * 1.3), 2)

                # Schema Alter: REL-106
                elif stage == "SCHEMA_ALTER":
                    rel_change = "schema_change"
                    if qid in ("SYNTH-Q-003", "SYNTH-Q-006"):
                        # Column added caused row width expansion
                        idx_status = "CHANGED"
                        multiplier = random.uniform(1.4, 2.2)
                        exec_ms = round(base_ms * multiplier, 2)
                        cpu_ms = round(base_cpu * multiplier, 2)
                        io_cost = round(base_io * (multiplier * 1.4), 2)
                        rows_examined = base_rows_ex
                        rows_returned = base_rows_ret
                    else:
                        jitter = random.uniform(-0.05, 0.12)
                        exec_ms = round(base_ms * (1.0 + jitter), 2)
                        cpu_ms = round(base_cpu * (1.0 + jitter), 2)
                        io_cost = round(base_io * (1.0 + jitter), 2)
                        rows_examined = base_rows_ex
                        rows_returned = base_rows_ret

                # Workload Surge: REL-107 (EDGE CASE 3 - Transient spike / False positive suppression)
                elif stage == "WORKLOAD_SURGE":
                    workload = "PEAK"
                    rel_change = "workload_increase"
                    # Execution time increases moderately due to connection queueing, but NO plan change
                    is_edge_fp = (rep % 2 == 0)  # half are pure FP scenarios
                    multiplier = random.uniform(1.22, 1.40)
                    exec_ms = round(base_ms * multiplier, 2)
                    cpu_ms = round(base_cpu * (1.0 + random.uniform(0.05, 0.12)), 2)
                    io_cost = round(base_io * (1.0 + random.uniform(0.05, 0.15)), 2)
                    rows_examined = base_rows_ex
                    rows_returned = base_rows_ret
                    plan_changed = 0

                # Bad Query Plan: REL-108
                elif stage == "BAD_QUERY_PLAN":
                    rel_change = "bad_query_plan"
                    if qid in ("SYNTH-Q-004", "SYNTH-Q-005", "SYNTH-Q-009"):
                        curr_plan = "SCAN appointments USE TEMP B-TREE (planner chose unindexed nested loop)"
                        curr_plan_hash = compute_plan_hash(curr_plan)
                        plan_changed = 1
                        idx_status = "UNUSED"
                        multiplier = random.uniform(3.5, 7.5)
                        exec_ms = round(base_ms * multiplier, 2)
                        cpu_ms = round(base_cpu * multiplier, 2)
                        io_cost = round(base_io * (multiplier * 2.0), 2)
                        rows_examined = 25000 + random.randint(100, 5000)
                        rows_returned = base_rows_ret
                    else:
                        jitter = random.uniform(-0.05, 0.10)
                        exec_ms = round(base_ms * (1.0 + jitter), 2)
                        cpu_ms = round(base_cpu * (1.0 + jitter), 2)
                        io_cost = round(base_io * (1.0 + jitter), 2)
                        rows_examined = base_rows_ex
                        rows_returned = base_rows_ret

                # Index Changed / Modified: REL-109
                elif stage == "INDEX_CHANGED":
                    rel_change = "index_changed"
                    if qid in ("SYNTH-Q-001", "SYNTH-Q-009"):
                        # Column reordering reduced selectivity for prefix lookup
                        idx_status = "CHANGED"
                        curr_plan = base_plan + " (sub-optimal prefix match after column reorder)"
                        curr_plan_hash = compute_plan_hash(curr_plan)
                        plan_changed = 1
                        multiplier = random.uniform(1.6, 2.4)
                        exec_ms = round(base_ms * multiplier, 2)
                        cpu_ms = round(base_cpu * multiplier, 2)
                        io_cost = round(base_io * (multiplier * 1.3), 2)
                        rows_examined = int(base_rows_ex * multiplier * 1.5)
                        rows_returned = base_rows_ret
                    else:
                        jitter = random.uniform(-0.05, 0.08)
                        exec_ms = round(base_ms * (1.0 + jitter), 2)
                        cpu_ms = round(base_cpu * (1.0 + jitter), 2)
                        io_cost = round(base_io * (1.0 + jitter), 2)
                        rows_examined = base_rows_ex
                        rows_returned = base_rows_ret

                # Compute rule-based labels
                label, severity, exp_imp, usr_imp, evidence_data = evaluate_record_label(
                    exec_ms=exec_ms,
                    baseline_exec_ms=base_ms,
                    plan_changed=bool(plan_changed),
                    index_status=idx_status,
                    stats_status=stats_status,
                    workload_level=workload,
                    double_booking_critical=is_double_booking,
                    is_edge_fp=is_edge_fp
                )

                record = {
                    "query_id": qid,
                    "query_name": qname,
                    "query_type": qtype,
                    "release_id": rel_id,
                    "release_version": rel_version,
                    "timestamp": timestamp_str,
                    "execution_time_ms": exec_ms,
                    "baseline_execution_time_ms": base_ms,
                    "rows_examined": rows_examined,
                    "rows_returned": rows_returned,
                    "cpu_time_ms": cpu_ms,
                    "io_cost": io_cost,
                    "plan_hash": curr_plan_hash,
                    "baseline_plan_hash": base_plan_hash,
                    "plan_changed": plan_changed,
                    "index_name": idx_name,
                    "index_status": idx_status,
                    "statistics_age": stats_age,
                    "statistics_status": stats_status,
                    "workload_level": workload,
                    "schema_change": schema_change,
                    "release_change": rel_change,
                    "regression_label": label,
                    "regression_severity": severity,
                    "expected_impact": exp_imp,
                    "user_impact": usr_imp,
                    "evidence": json.dumps(evidence_data)
                }
                dataset.append(record)

    # ── Explicit Injection of Required Edge / Failure Scenarios ───────────────────

    # Edge Scenario 1: Missing Execution Plan
    edge_1_record = {
        "query_id": "SYNTH-Q-004",
        "query_name": "Verify whether an appointment slot is already booked",
        "query_type": "verify_slot_booked",
        "release_id": "REL-108",
        "release_version": "v2.1.0",
        "timestamp": "2026-09-06 08:30:00",
        "execution_time_ms": 28.5,
        "baseline_execution_time_ms": 13.8,
        "rows_examined": 50,
        "rows_returned": 1,
        "cpu_time_ms": 18.2,
        "io_cost": 3.8,
        "plan_hash": None,  # MISSING PLAN
        "baseline_plan_hash": compute_plan_hash("SEARCH appointments USING COVERING INDEX idx_appt_doctor_date_time_status"),
        "plan_changed": 1,
        "index_name": "idx_appt_doctor_date_time_status",
        "index_status": "UNKNOWN",
        "statistics_age": 7,
        "statistics_status": "CURRENT",
        "workload_level": "NORMAL",
        "schema_change": "NONE",
        "release_change": "query_plan_change",
        "regression_label": "WARNING",
        "regression_severity": "MEDIUM",
        "expected_impact": "Optimizer profiling unavailable; plan cache inspection yielded null tree.",
        "user_impact": "Slot verification succeeded but query plan telemetry is absent.",
        "evidence": json.dumps({
            "edge_case_type": "MISSING_EXECUTION_PLAN",
            "error_code": "PLAN_PROFILER_EMPTY",
            "diagnostics": "Database engine did not emit EXPLAIN rows before statement completed.",
            "recommendation": "Verify PRAGMA or query profiling permissions in database connection pool."
        })
    }
    dataset.append(edge_1_record)

    # Edge Scenario 2: Stale Statistics Causing Wrong Index Selection
    edge_2_record = {
        "query_id": "SYNTH-Q-001",
        "query_name": "Find available appointment slots",
        "query_type": "find_available_slots",
        "release_id": "REL-104",
        "release_version": "v1.3.0",
        "timestamp": "2026-08-15 14:10:00",
        "execution_time_ms": 38.2,
        "baseline_execution_time_ms": 14.5,
        "rows_examined": 1420,
        "rows_returned": 18,
        "cpu_time_ms": 25.1,
        "io_cost": 7.4,
        "plan_hash": compute_plan_hash("SCAN appointment_slots USING TEMP B-TREE"),
        "baseline_plan_hash": compute_plan_hash("SEARCH appointment_slots USING INDEX idx_appt_dept_date_status"),
        "plan_changed": 1,
        "index_name": "idx_appt_dept_date_status",
        "index_status": "OPTIMAL",
        "statistics_age": 52,
        "statistics_status": "STALE",
        "workload_level": "HIGH",
        "schema_change": "NONE",
        "release_change": "statistics_stale",
        "regression_label": "REGRESSION",
        "regression_severity": "HIGH",
        "expected_impact": "Planner selected temp b-tree because sqlite_stat1 indicates table has 500 rows instead of 200,000.",
        "user_impact": "Schedulers experience 2.6x lag during clinic calendar lookups.",
        "evidence": json.dumps({
            "edge_case_type": "STALE_STATISTICS",
            "stats_age_days": 52,
            "stat1_row_count": 500,
            "actual_row_count": 210000,
            "recommendation": "Execute 'ANALYZE appointment_slots;' to refresh table cardinality statistics."
        })
    }
    dataset.append(edge_2_record)

    # Edge Scenario 3: Time Increased Due to Workload But NO Actual Regression (FP Suppression Test)
    edge_3_record = {
        "query_id": "SYNTH-Q-002",
        "query_name": "Check doctor availability",
        "query_type": "check_doctor_availability",
        "release_id": "REL-107",
        "release_version": "v2.0.0",
        "timestamp": "2026-09-02 08:45:00",
        "execution_time_ms": 16.1,
        "baseline_execution_time_ms": 11.2,
        "rows_examined": 45,
        "rows_returned": 8,
        "cpu_time_ms": 7.8,
        "io_cost": 1.6,
        "plan_hash": compute_plan_hash("SEARCH appointments USING INDEX idx_appt_doctor_date (doctor_id=? AND appt_date=?)"),
        "baseline_plan_hash": compute_plan_hash("SEARCH appointments USING INDEX idx_appt_doctor_date (doctor_id=? AND appt_date=?)"),
        "plan_changed": 0,
        "index_name": "idx_appt_doctor_date",
        "index_status": "OPTIMAL",
        "statistics_age": 3,
        "statistics_status": "CURRENT",
        "workload_level": "PEAK",
        "schema_change": "NONE",
        "release_change": "workload_increase",
        "regression_label": "NORMAL",
        "regression_severity": "OK",
        "expected_impact": "Concurrency queueing only. Zero structural plan shift or index loss.",
        "user_impact": "Doctor availability check returns within 16ms (well within 200ms clinician SLA).",
        "evidence": json.dumps({
            "edge_case_type": "FALSE_POSITIVE_WORKLOAD_SPIKE_SUPPRESSION",
            "delta_pct": 43.75,
            "rule_applied": "FALSE_POSITIVE_GRACE_BAND",
            "plan_verified_identical": True,
            "recommendation": "Do not raise false alert; system is operating normally under transient morning peak."
        })
    }
    dataset.append(edge_3_record)

    # Edge Scenario 4: Missing Index with Plan Parsing Failure Fallback
    edge_4_record = {
        "query_id": "SYNTH-Q-004",
        "query_name": "Verify whether an appointment slot is already booked",
        "query_type": "verify_slot_booked",
        "release_id": "REL-102",
        "release_version": "v1.1.0",
        "timestamp": "2026-07-20 09:12:00",
        "execution_time_ms": 285.0,
        "baseline_execution_time_ms": 13.8,
        "rows_examined": 50000,
        "rows_returned": 1,
        "cpu_time_ms": 220.0,
        "io_cost": 45.0,
        "plan_hash": "PARSE_ERROR_SCAN",
        "baseline_plan_hash": compute_plan_hash("SEARCH appointments USING COVERING INDEX idx_appt_doctor_date_time_status"),
        "plan_changed": 1,
        "index_name": "idx_appt_doctor_date_time_status",
        "index_status": "MISSING",
        "statistics_age": 12,
        "statistics_status": "CURRENT",
        "workload_level": "HIGH",
        "schema_change": "INDEX_DROPPED",
        "release_change": "missing_index",
        "regression_label": "CRITICAL_REGRESSION",
        "regression_severity": "CRITICAL",
        "expected_impact": "Missing critical index causes sequential scan over 50,000 rows during atomic slot verification.",
        "user_impact": "ACUTE DOUBLE-BOOKING RISK: Concurrent patients booking identical 10:30 slot pass check concurrently.",
        "evidence": json.dumps({
            "edge_case_type": "MISSING_INDEX_PARSE_DEGRADATION",
            "missing_index": "idx_appt_doctor_date_time_status",
            "plan_parse_flag": "FALLBACK_DETECTED_TABLE_SCAN",
            "delta_pct": 1965.2,
            "sla_breach": True,
            "recommendation": "EMERGENCY ROLLBACK: Re-create index idx_appt_doctor_date_time_status immediately."
        })
    }
    dataset.append(edge_4_record)

    return dataset

# ── Exporters (CSV, JSON, SQLite) ─────────────────────────────────────────────

def export_to_csv(dataset: List[Dict[str, Any]], filepath: str = CSV_PATH) -> None:
    if not dataset:
        return
    fieldnames = list(dataset[0].keys())
    with open(filepath, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in dataset:
            writer.writerow(row)
    print(f"[DATASET] Successfully exported {len(dataset)} records to CSV: {filepath}")

def export_to_json(dataset: List[Dict[str, Any]], filepath: str = JSON_PATH) -> None:
    with open(filepath, mode="w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2)
    print(f"[DATASET] Successfully exported {len(dataset)} records to JSON: {filepath}")

def export_to_sqlite(dataset: List[Dict[str, Any]], filepath: str = SQLITE_PATH) -> None:
    if os.path.exists(filepath):
        os.remove(filepath)

    conn = sqlite3.connect(filepath)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE query_regression_records (
            record_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id                   TEXT NOT NULL,
            query_name                 TEXT NOT NULL,
            query_type                 TEXT NOT NULL,
            release_id                 TEXT NOT NULL,
            release_version            TEXT NOT NULL,
            timestamp                  TEXT NOT NULL,
            execution_time_ms          REAL NOT NULL,
            baseline_execution_time_ms REAL NOT NULL,
            rows_examined              INTEGER NOT NULL,
            rows_returned              INTEGER NOT NULL,
            cpu_time_ms                REAL NOT NULL,
            io_cost                    REAL NOT NULL,
            plan_hash                  TEXT,
            baseline_plan_hash         TEXT,
            plan_changed               INTEGER NOT NULL,
            index_name                 TEXT,
            index_status               TEXT NOT NULL,
            statistics_age             INTEGER NOT NULL,
            statistics_status          TEXT NOT NULL,
            workload_level             TEXT NOT NULL,
            schema_change              TEXT NOT NULL,
            release_change             TEXT NOT NULL,
            regression_label           TEXT NOT NULL,
            regression_severity        TEXT NOT NULL,
            expected_impact            TEXT NOT NULL,
            user_impact                TEXT NOT NULL,
            evidence                   TEXT NOT NULL
        );
    """)

    cur.execute("CREATE INDEX idx_dataset_query_id ON query_regression_records(query_id);")
    cur.execute("CREATE INDEX idx_dataset_release_id ON query_regression_records(release_id);")
    cur.execute("CREATE INDEX idx_dataset_label ON query_regression_records(regression_label);")
    cur.execute("CREATE INDEX idx_dataset_type ON query_regression_records(query_type);")

    insert_sql = """
        INSERT INTO query_regression_records (
            query_id, query_name, query_type, release_id, release_version, timestamp,
            execution_time_ms, baseline_execution_time_ms, rows_examined, rows_returned,
            cpu_time_ms, io_cost, plan_hash, baseline_plan_hash, plan_changed,
            index_name, index_status, statistics_age, statistics_status, workload_level,
            schema_change, release_change, regression_label, regression_severity,
            expected_impact, user_impact, evidence
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
    """

    for r in dataset:
        cur.execute(insert_sql, (
            r["query_id"], r["query_name"], r["query_type"], r["release_id"], r["release_version"],
            r["timestamp"], r["execution_time_ms"], r["baseline_execution_time_ms"],
            r["rows_examined"], r["rows_returned"], r["cpu_time_ms"], r["io_cost"],
            r["plan_hash"], r["baseline_plan_hash"], r["plan_changed"], r["index_name"],
            r["index_status"], r["statistics_age"], r["statistics_status"], r["workload_level"],
            r["schema_change"], r["release_change"], r["regression_label"],
            r["regression_severity"], r["expected_impact"], r["user_impact"], r["evidence"]
        ))

    conn.commit()
    conn.close()
    print(f"[DATASET] Successfully exported {len(dataset)} records to SQLite: {filepath}")

# ── Summary Reporter ──────────────────────────────────────────────────────────

def print_dataset_summary(dataset: List[Dict[str, Any]]) -> None:
    total = len(dataset)
    labels: Dict[str, int] = {}
    severities: Dict[str, int] = {}
    qtypes: Dict[str, int] = {}
    releases: Dict[str, int] = {}
    changes: Dict[str, int] = {}

    for r in dataset:
        labels[r["regression_label"]] = labels.get(r["regression_label"], 0) + 1
        severities[r["regression_severity"]] = severities.get(r["regression_severity"], 0) + 1
        qtypes[r["query_type"]] = qtypes.get(r["query_type"], 0) + 1
        releases[r["release_version"]] = releases.get(r["release_version"], 0) + 1
        changes[r["release_change"]] = changes.get(r["release_change"], 0) + 1

    print("\n" + "=" * 70)
    print("  SYNTHETIC DATASET GENERATION SUMMARY")
    print("=" * 70)
    print(f"  Total Records Generated: {total}")
    print(f"  Query Types Represented: {len(qtypes)} (all 9 hospital query types)")
    print(f"  Release Versions:        {len(releases)} (v1.0.0 through v2.1.0)")
    print(f"  Distinct Change Types:   {len(changes)} (indexes, stats, schema, load, plans)")
    print("-" * 70)
    print("  Regression Labels Distribution:")
    for lbl, count in sorted(labels.items()):
        pct = (count / total) * 100.0
        print(f"    {lbl:22s} : {count:4d} ({pct:5.1f}%)")
    print("-" * 70)
    print("  Double-Booking Sensitive Queries Count:")
    db_count = sum(1 for r in dataset if r["query_type"] in ("verify_slot_booked", "check_doctor_availability", "create_appointment", "cancel_appointment", "retrieve_doctor_schedule"))
    print(f"    Total Double-Booking Sensitive Records: {db_count} ({(db_count/total)*100:.1f}%)")
    print("=" * 70 + "\n")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("[DATASET] Generating Phase 2 synthetic hospital platform dataset...")
    # 9 queries * 8 releases * 10 reps = 720 records + 4 explicit edge scenarios = 724 records
    dataset = generate_synthetic_dataset(records_per_query_per_release=10)

    export_to_csv(dataset, CSV_PATH)
    export_to_json(dataset, JSON_PATH)
    export_to_sqlite(dataset, SQLITE_PATH)

    print_dataset_summary(dataset)

if __name__ == "__main__":
    main()
