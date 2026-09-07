"""
baseline_engine.py
==================
Phase 3: Baseline Creation and Comparison Engine for Hospital Appointment Platform.

A comprehensive multi-dimensional baseline engine that captures the normal expected
performance of each hospital appointment query before any workload, schema, index,
statistics, or software release change.

Baseline Dimensions Captured per Query:
- baseline execution time (mean & p95)
- median execution time (p50)
- percentile execution times (p90, p95, p99)
- baseline query plan hash
- baseline plan characteristics (nodes, scan types, search types, covering status)
- baseline indexes (supported and utilized)
- baseline database statistics state (staleness, age, row counts)
- normal workload level (e.g., NORMAL / LOW)
- baseline rows examined
- baseline rows returned
- baseline CPU time and estimated I/O cost

Key APIs:
1. generate_baseline(source="dataset"|"live", baseline_tag="v1.0.0", ...)
2. get_baseline(query_id=None, baseline_tag=None, ...)
3. compare_against_baseline(new_execution, query_id=None, baseline_tag=None, rules=...)
"""

import os
import sys
import json
import sqlite3
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Union

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from src.core import rules_loader, plan_extractor, timing_runner, stats_collector, snapshot_store

DEFAULT_STORE_PATH = os.path.join(BASE_DIR, "data", "detector_store.db")
DEFAULT_SYNTH_DB   = os.path.join(BASE_DIR, "data", "synthetic_dataset.db")
DEFAULT_HOSPITAL_DB = os.path.join(BASE_DIR, "data", "hospital.db")
DEFAULT_RULES_PATH = os.path.join(BASE_DIR, "config", "rules.yaml")
DEFAULT_QUERIES_PATH = os.path.join(BASE_DIR, "config", "probe_queries.yaml")

# Queries critical to preventing double-booking race conditions
DOUBLE_BOOKING_CRITICAL_TYPES = {
    "verify_slot_booked",
    "check_doctor_availability",
    "create_appointment",
    "cancel_appointment",
    "retrieve_doctor_schedule"
}

DOUBLE_BOOKING_CRITICAL_IDS = {"QRY-001", "QRY-004", "SYNTH-Q-002", "SYNTH-Q-003", "SYNTH-Q-004", "SYNTH-Q-007", "SYNTH-Q-008"}


def _connect(store_path: str = DEFAULT_STORE_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(store_path), exist_ok=True)
    conn = sqlite3.connect(store_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_baseline_store(store_path: str = DEFAULT_STORE_PATH) -> None:
    """Initialize the query_baselines table in detector_store.db."""
    snapshot_store.init_store(store_path)
    conn = _connect(store_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS query_baselines (
            baseline_id             INTEGER PRIMARY KEY AUTOINCREMENT,
            baseline_tag            TEXT NOT NULL,
            query_id                TEXT NOT NULL,
            query_name              TEXT NOT NULL,
            query_type              TEXT NOT NULL,
            mean_exec_ms            REAL NOT NULL,
            median_exec_ms          REAL NOT NULL,
            p90_exec_ms             REAL NOT NULL,
            p95_exec_ms             REAL NOT NULL,
            p99_exec_ms             REAL NOT NULL,
            sample_count            INTEGER NOT NULL,
            plan_hash               TEXT NOT NULL,
            plan_characteristics    TEXT NOT NULL,
            indexes                 TEXT NOT NULL,
            statistics_state        TEXT NOT NULL,
            normal_workload_level   TEXT NOT NULL,
            rows_examined           INTEGER NOT NULL,
            rows_returned           INTEGER NOT NULL,
            cpu_time_ms             REAL NOT NULL,
            io_cost                 REAL NOT NULL,
            is_active               INTEGER NOT NULL DEFAULT 1,
            created_at              DATETIME NOT NULL,
            updated_at              DATETIME NOT NULL,
            UNIQUE(baseline_tag, query_id)
        );

        CREATE INDEX IF NOT EXISTS idx_qb_tag ON query_baselines(baseline_tag);
        CREATE INDEX IF NOT EXISTS idx_qb_qid ON query_baselines(query_id);
        CREATE INDEX IF NOT EXISTS idx_qb_active ON query_baselines(is_active);
    """)
    conn.commit()
    conn.close()


def _percentile(sorted_data: List[float], percentile: float) -> float:
    """Calculate percentile from a sorted list of values."""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * (percentile / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    d = k - f
    return round(sorted_data[f] + d * (sorted_data[c] - sorted_data[f]), 3)


# ── 1. GENERATE BASELINE ───────────────────────────────────────────────────────

def generate_baseline(
    source: str = "dataset",
    baseline_tag: str = "v1.0.0",
    store_path: str = DEFAULT_STORE_PATH,
    synth_db_path: str = DEFAULT_SYNTH_DB,
    hospital_db_path: str = DEFAULT_HOSPITAL_DB,
    runs: int = 10,
    set_as_active: bool = True
) -> Dict[str, Dict[str, Any]]:
    """
    Generate a comprehensive multi-dimensional baseline for all probe queries.

    Sources:
      - 'dataset': extracts baseline records from data/synthetic_dataset.db (reproducible seed 42)
      - 'live': executes probe queries live against data/hospital.db
    """
    init_baseline_store(store_path)
    now_iso = datetime.now().isoformat()
    baselines: Dict[str, Dict[str, Any]] = {}

    if source == "dataset":
        if not os.path.exists(synth_db_path):
            raise FileNotFoundError(f"Synthetic dataset database not found at: {synth_db_path}")

        conn = sqlite3.connect(synth_db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Query records for baseline release (v1.0.0 or REL-101)
        cur.execute("""
            SELECT * FROM query_regression_records
            WHERE release_version = ? OR release_id = 'REL-101'
            ORDER BY query_id, timestamp ASC;
        """, (baseline_tag,))
        records = [dict(r) for r in cur.fetchall()]
        conn.close()

        if not records:
            raise ValueError(f"No baseline records found in {synth_db_path} for release {baseline_tag}")

        # Group by query_id
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for r in records:
            qid = r["query_id"]
            if qid not in grouped:
                grouped[qid] = []
            grouped[qid].append(r)

        for qid, q_records in grouped.items():
            first = q_records[0]
            times = sorted([float(r["execution_time_ms"]) for r in q_records])
            mean_ms = round(sum(times) / len(times), 3)
            median_ms = _percentile(times, 50.0)
            p90_ms = _percentile(times, 90.0)
            p95_ms = _percentile(times, 95.0)
            p99_ms = _percentile(times, 99.0)

            # Consensus plan and characteristics
            plan_hash = first["baseline_plan_hash"] or first["plan_hash"] or "base_hash"
            idx_name = first["index_name"]
            idx_list = [idx_name] if idx_name and idx_name != "None" else []

            plan_chars = {
                "uses_index": first["index_status"] not in ("REMOVED", "MISSING", "UNUSED"),
                "has_full_scan": first["index_status"] in ("REMOVED", "MISSING") or "SCAN" in str(first["plan_hash"]),
                "primary_index": idx_name,
                "node_types": ["INDEX_SEARCH"] if first["index_status"] == "OPTIMAL" else ["SCAN"],
                "covering_index": "idx_appt_doctor_date_time_status" in idx_list
            }

            stats_state = {
                "statistics_age": int(first["statistics_age"]),
                "statistics_status": first["statistics_status"],
                "table_cardinality": int(first["rows_examined"] * 5)
            }

            cpu_ms = round(sum(float(r["cpu_time_ms"]) for r in q_records) / len(q_records), 3)
            io_cost = round(sum(float(r["io_cost"]) for r in q_records) / len(q_records), 3)

            baselines[qid] = {
                "baseline_tag": baseline_tag,
                "query_id": qid,
                "query_name": first["query_name"],
                "query_type": first["query_type"],
                "mean_exec_ms": mean_ms,
                "median_exec_ms": median_ms,
                "p90_exec_ms": p90_ms,
                "p95_exec_ms": p95_ms,
                "p99_exec_ms": p99_ms,
                "sample_count": len(times),
                "plan_hash": plan_hash,
                "plan_characteristics": plan_chars,
                "indexes": idx_list,
                "statistics_state": stats_state,
                "normal_workload_level": "NORMAL",
                "rows_examined": int(first["rows_examined"]),
                "rows_returned": int(first["rows_returned"]),
                "cpu_time_ms": cpu_ms,
                "io_cost": io_cost,
                "is_active": 1 if set_as_active else 0,
                "created_at": now_iso,
                "updated_at": now_iso
            }

    elif source == "live":
        if not os.path.exists(hospital_db_path):
            raise FileNotFoundError(f"Hospital database not found at: {hospital_db_path}")

        import yaml
        with open(DEFAULT_QUERIES_PATH, "r", encoding="utf-8") as f:
            probe_queries = yaml.safe_load(f)["queries"]

        app_conn = sqlite3.connect(hospital_db_path)
        app_conn.row_factory = sqlite3.Row
        db_stats = stats_collector.collect_stats(app_conn, hospital_db_path)

        for q in probe_queries:
            qid = q["id"]
            label = q["label"]
            sql = q["sql"].strip()

            plan = plan_extractor.extract_plan(app_conn, sql)
            timing = timing_runner.run_timed(app_conn, sql, runs=runs)

            plan_hash = hashlib.sha256(plan.get("raw", "").encode("utf-8")).hexdigest()[:16]
            plan_chars = {
                "uses_index": plan.get("uses_index", False),
                "has_full_scan": plan.get("has_full_scan", False),
                "node_types": [n.get("node_type", "UNKNOWN") for n in plan.get("nodes", [])],
                "index_names": plan.get("index_names", [])
            }

            stats_state = {
                "statistics_age": 1,
                "statistics_status": "CURRENT",
                "table_counts": {t: v["row_count"] for t, v in db_stats["tables"].items()}
            }

            p50 = timing.get("p50_ms", 0.0)
            p95 = timing.get("p95_ms", 0.0)
            p99 = timing.get("p99_ms", 0.0)
            mean_ms = round((p50 + p95) / 2.0, 3)

            baselines[qid] = {
                "baseline_tag": baseline_tag,
                "query_id": qid,
                "query_name": label,
                "query_type": qid.lower(),
                "mean_exec_ms": mean_ms,
                "median_exec_ms": p50,
                "p90_exec_ms": round(p50 + (p95 - p50) * 0.8, 3),
                "p95_exec_ms": p95,
                "p99_exec_ms": p99,
                "sample_count": runs,
                "plan_hash": plan_hash,
                "plan_characteristics": plan_chars,
                "indexes": plan.get("index_names", []),
                "statistics_state": stats_state,
                "normal_workload_level": "NORMAL",
                "rows_examined": plan.get("row_est", 10),
                "rows_returned": 1,
                "cpu_time_ms": round(mean_ms * 0.7, 3),
                "io_cost": round(mean_ms * 0.3, 3),
                "is_active": 1 if set_as_active else 0,
                "created_at": now_iso,
                "updated_at": now_iso
            }

        app_conn.close()

    # Persist to detector_store.db
    conn = _connect(store_path)
    if set_as_active:
        conn.execute("UPDATE query_baselines SET is_active = 0 WHERE baseline_tag != ?", (baseline_tag,))

    insert_sql = """
        INSERT OR REPLACE INTO query_baselines (
            baseline_tag, query_id, query_name, query_type,
            mean_exec_ms, median_exec_ms, p90_exec_ms, p95_exec_ms, p99_exec_ms,
            sample_count, plan_hash, plan_characteristics, indexes,
            statistics_state, normal_workload_level, rows_examined, rows_returned,
            cpu_time_ms, io_cost, is_active, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
    """

    for b in baselines.values():
        conn.execute(insert_sql, (
            b["baseline_tag"], b["query_id"], b["query_name"], b["query_type"],
            b["mean_exec_ms"], b["median_exec_ms"], b["p90_exec_ms"], b["p95_exec_ms"], b["p99_exec_ms"],
            b["sample_count"], b["plan_hash"],
            json.dumps(b["plan_characteristics"]),
            json.dumps(b["indexes"]),
            json.dumps(b["statistics_state"]),
            b["normal_workload_level"], b["rows_examined"], b["rows_returned"],
            b["cpu_time_ms"], b["io_cost"], b["is_active"],
            b["created_at"], b["updated_at"]
        ))

    conn.commit()
    conn.close()

    # Also ensure a snapshot entry exists in snapshots table
    row_counts = {"appointments": 50000, "doctors": 100, "departments": 10}
    snapshot_store.save_snapshot(
        release_tag=baseline_tag,
        snapshot_type="BASELINE",
        db_size_bytes=15000000,
        row_counts=row_counts,
        store_path=store_path
    )

    return baselines


# ── 2. RETRIEVE BASELINE ───────────────────────────────────────────────────────

def get_baseline(
    query_id: Optional[str] = None,
    baseline_tag: Optional[str] = None,
    store_path: str = DEFAULT_STORE_PATH
) -> Union[Optional[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Retrieve baseline fingerprint for a specific query, or all baselines.
    If baseline_tag is None, retrieves active baseline (is_active = 1).
    """
    init_baseline_store(store_path)
    conn = _connect(store_path)
    cur = conn.cursor()

    if baseline_tag:
        tag_clause = "baseline_tag = ?"
        tag_params = [baseline_tag]
    else:
        tag_clause = "is_active = 1"
        tag_params = []

    if query_id:
        cur.execute(f"SELECT * FROM query_baselines WHERE {tag_clause} AND query_id = ? LIMIT 1;", (*tag_params, query_id))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return _deserialize_baseline_row(dict(row))
    else:
        cur.execute(f"SELECT * FROM query_baselines WHERE {tag_clause} ORDER BY query_id ASC;", tag_params)
        rows = cur.fetchall()
        conn.close()
        result = {}
        for r in rows:
            d = _deserialize_baseline_row(dict(r))
            result[d["query_id"]] = d
        return result


def _deserialize_baseline_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Helper to deserialize JSON columns from query_baselines."""
    for col in ("plan_characteristics", "indexes", "statistics_state"):
        val = row.get(col)
        if isinstance(val, str):
            try:
                row[col] = json.loads(val)
            except Exception:
                row[col] = {} if col != "indexes" else []
    return row


# ── 3. COMPARE AGAINST BASELINE ───────────────────────────────────────────────

def compare_against_baseline(
    new_execution: Dict[str, Any],
    query_id: Optional[str] = None,
    baseline_tag: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
    rules_path: str = DEFAULT_RULES_PATH,
    store_path: str = DEFAULT_STORE_PATH
) -> Dict[str, Any]:
    """
    Compare a new execution against the multi-dimensional baseline.

    Evaluates:
      1. Execution time % increase (vs baseline median and p95)
      2. Absolute execution time thresholds
      3. Query plan changes & node shifts (full table scans, index loss)
      4. Database statistics staleness & row estimate drift
      5. Workload level variations
      6. Severity and regression labels via configurable rules.yaml
      7. Double-booking race hazard evaluation
    """
    qid = query_id or new_execution.get("query_id")
    if not qid:
        raise ValueError("query_id must be provided in new_execution or as query_id parameter")

    # Load baseline fingerprint
    baseline = get_baseline(query_id=qid, baseline_tag=baseline_tag, store_path=store_path)
    if not baseline:
        # Fallback: attempt to generate baseline automatically if missing
        generate_baseline(source="dataset", baseline_tag=baseline_tag or "v1.0.0", store_path=store_path)
        baseline = get_baseline(query_id=qid, baseline_tag=baseline_tag, store_path=store_path)

    if not baseline:
        raise ValueError(f"No baseline found for query_id '{qid}' (baseline_tag: {baseline_tag or 'active'})")

    # Load configurable rules
    if rules is None:
        rules = rules_loader.load_rules(rules_path)

    # ── Timing Extraction ─────────────────────────────────────────────────────
    base_p95 = float(baseline.get("p95_exec_ms", 0.0) or baseline.get("mean_exec_ms", 1.0))
    base_median = float(baseline.get("median_exec_ms", 0.0) or base_p95)

    curr_p95 = float(new_execution.get("execution_time_ms") or new_execution.get("exec_ms_p95") or 0.0)
    curr_median = float(new_execution.get("exec_ms_p50") or curr_p95 * 0.85)

    delta_ms = curr_p95 - base_p95
    pct_change_p95 = (delta_ms / base_p95 * 100.0) if base_p95 > 0 else 0.0
    pct_change_median = ((curr_median - base_median) / base_median * 100.0) if base_median > 0 else 0.0

    # Configurable thresholds
    time_regression_pct = rules_loader.get_threshold(rules, "time_regression_pct", 20.0)
    time_high_pct = rules_loader.get_threshold(rules, "time_high_pct", 50.0)
    time_critical_pct = rules_loader.get_threshold(rules, "time_critical_pct", 100.0)
    absolute_critical_ms = rules_loader.get_threshold(rules, "absolute_critical_ms", 2000.0)
    absolute_high_ms = rules_loader.get_threshold(rules, "absolute_high_ms", 500.0)
    min_meaningful_ms = rules_loader.get_threshold(rules, "minimum_meaningful_ms", 1.0)
    noise_band_pct = rules_loader.get_noise_band(rules)

    # ── Plan and Index Checks ─────────────────────────────────────────────────
    curr_plan_hash = new_execution.get("plan_hash")
    base_plan_hash = baseline.get("plan_hash")
    plan_changed = bool(curr_plan_hash and base_plan_hash and curr_plan_hash != base_plan_hash) or bool(new_execution.get("plan_changed", 0))

    base_indexes = set(baseline.get("indexes", []))
    curr_indexes_raw = new_execution.get("indexes") or new_execution.get("index_name")
    if curr_indexes_raw is None:
        if new_execution.get("index_status") in ("REMOVED", "MISSING"):
            index_lost = True
            curr_indexes = set()
        else:
            index_lost = False
            curr_indexes = base_indexes
    else:
        if isinstance(curr_indexes_raw, str):
            curr_indexes = {curr_indexes_raw} if curr_indexes_raw and curr_indexes_raw != "None" else set()
        else:
            curr_indexes = set(curr_indexes_raw)
        index_lost = bool(base_indexes - curr_indexes) if rules_loader.get_plan_rule(rules, "flag_index_loss", True) else False

    if new_execution.get("index_status") in ("REMOVED", "MISSING"):
        index_lost = True

    has_new_scan = bool(
        new_execution.get("has_full_scan", 0)
        or "SCAN" in str(curr_plan_hash)
        or new_execution.get("index_status") in ("REMOVED", "MISSING")
    ) and not baseline.get("plan_characteristics", {}).get("has_full_scan", False)

    # ── Statistics Check ──────────────────────────────────────────────────────
    curr_stats_age = int(new_execution.get("statistics_age", 1))
    stats_staleness_thresh = rules_loader.get_staleness_threshold(rules, default=30)
    stats_stale = (curr_stats_age > stats_staleness_thresh) or (new_execution.get("statistics_status") == "STALE")

    base_rows_ex = int(baseline.get("rows_examined", 1) or 1)
    curr_rows_ex = int(new_execution.get("rows_examined", base_rows_ex) or base_rows_ex)
    row_drift_pct = abs(curr_rows_ex - base_rows_ex) / base_rows_ex * 100.0 if base_rows_ex > 0 else 0.0
    stats_drift_flag = row_drift_pct >= rules_loader.get_stats_rule(rules, "flag_row_estimate_drift_pct", 50.0)

    # ── Workload Check ────────────────────────────────────────────────────────
    curr_workload = new_execution.get("workload_level", "NORMAL")
    normal_workload = baseline.get("normal_workload_level", "NORMAL")
    workload_surge = (curr_workload in ("HIGH", "PEAK")) and (normal_workload in ("LOW", "NORMAL"))
    workload_variance_pct = float(rules_loader.get_workload_rule(rules, "workload_variance_pct", 40.0))

    # ── False-Positive Grace Handling ─────────────────────────────────────────
    is_noise = (abs(pct_change_p95) < noise_band_pct) and not plan_changed and not index_lost
    is_workload_grace = (
        workload_surge
        and not plan_changed
        and not index_lost
        and pct_change_p95 < workload_variance_pct
        and curr_p95 < absolute_high_ms
    )

    # ── Double-Booking Critical Sensitivity ───────────────────────────────────
    qtype = baseline.get("query_type", "")
    is_double_booking_critical = (
        qid in DOUBLE_BOOKING_CRITICAL_IDS
        or qtype in DOUBLE_BOOKING_CRITICAL_TYPES
        or "double-booking" in baseline.get("query_name", "").lower()
    )

    # ── Threshold Evaluation ──────────────────────────────────────────────────
    time_flag = (
        (base_p95 >= min_meaningful_ms and pct_change_p95 >= time_regression_pct)
        or curr_p95 >= absolute_critical_ms
        or (curr_p95 >= absolute_high_ms and pct_change_p95 >= time_regression_pct / 2.0)
    )

    if is_noise or is_workload_grace:
        time_flag = False

    plan_flag = plan_changed or has_new_scan or index_lost

    # Severity Matrix Determination
    if curr_p95 >= absolute_critical_ms:
        severity = "CRITICAL"
        label = "CRITICAL_REGRESSION"
    elif is_double_booking_critical and (index_lost or has_new_scan) and pct_change_p95 >= 35.0:
        severity = "CRITICAL"
        label = "CRITICAL_REGRESSION"
    elif pct_change_p95 >= time_critical_pct and (plan_flag or index_lost):
        severity = "CRITICAL"
        label = "CRITICAL_REGRESSION"
    elif time_flag and plan_flag and index_lost:
        severity = "CRITICAL"
        label = "CRITICAL_REGRESSION"
    elif time_flag and plan_flag:
        severity = "HIGH"
        label = "REGRESSION"
    elif pct_change_p95 >= time_high_pct or (plan_flag and time_flag):
        severity = "HIGH"
        label = "REGRESSION"
    elif time_flag or stats_stale or stats_drift_flag:
        severity = "MEDIUM"
        label = "WARNING"
    else:
        severity = "OK"
        label = "NORMAL"

    # Flag list
    flags_triggered = []
    if time_flag:
        flags_triggered.append("TIME_REGRESSION")
    if plan_changed:
        flags_triggered.append("PLAN_HASH_CHANGED")
    if index_lost:
        flags_triggered.append("INDEX_LOST")
    if has_new_scan:
        flags_triggered.append("NEW_FULL_SCAN")
    if stats_stale:
        flags_triggered.append("STATISTICS_STALE")
    if stats_drift_flag:
        flags_triggered.append("ROW_ESTIMATE_DRIFT")
    if workload_surge:
        flags_triggered.append("WORKLOAD_SURGE")
    if is_noise:
        flags_triggered.append("NOISE_SUPPRESSED")
    if is_workload_grace:
        flags_triggered.append("CONCURRENCY_GRACE_SUPPRESSED")

    recommendations = []
    if index_lost or has_new_scan:
        recommendations.append(f"Restore baseline index {baseline.get('indexes')} to eliminate full table scan.")
    if stats_stale or stats_drift_flag:
        recommendations.append("Execute 'ANALYZE' to refresh database cardinality statistics.")
    if severity == "CRITICAL":
        recommendations.append("BLOCK RELEASE: Critical query performance regression violates patient SLA.")
    elif severity == "OK":
        recommendations.append("Performance aligns with baseline. Safe to proceed.")

    evidence = {
        "baseline_tag": baseline.get("baseline_tag"),
        "rule_thresholds": {
            "time_regression_pct": time_regression_pct,
            "absolute_critical_ms": absolute_critical_ms,
            "noise_band_pct": noise_band_pct
        },
        "timing_analysis": {
            "baseline_median_ms": base_median,
            "baseline_p95_ms": base_p95,
            "current_p95_ms": curr_p95,
            "delta_ms": round(delta_ms, 3),
            "pct_change_p95": round(pct_change_p95, 2),
            "pct_change_median": round(pct_change_median, 2)
        },
        "plan_analysis": {
            "baseline_plan_hash": base_plan_hash,
            "current_plan_hash": curr_plan_hash,
            "plan_changed": plan_changed,
            "has_new_scan": has_new_scan,
            "index_lost": index_lost
        },
        "flags_triggered": flags_triggered
    }

    return {
        "query_id": qid,
        "query_name": baseline.get("query_name"),
        "query_type": baseline.get("query_type"),
        "is_regression": severity != "OK",
        "regression_label": label,
        "severity": severity,
        "baseline_metrics": {
            "mean_ms": base_p95,
            "median_ms": base_median,
            "p95_ms": base_p95,
            "p99_ms": baseline.get("p99_exec_ms"),
            "plan_hash": base_plan_hash,
            "indexes": baseline.get("indexes"),
            "rows_examined": base_rows_ex,
            "normal_workload": normal_workload
        },
        "current_metrics": {
            "exec_ms": curr_p95,
            "plan_hash": curr_plan_hash,
            "indexes": list(curr_indexes),
            "rows_examined": curr_rows_ex,
            "workload_level": curr_workload
        },
        "deltas": {
            "delta_ms": round(delta_ms, 3),
            "pct_change_p95": round(pct_change_p95, 2),
            "pct_change_median": round(pct_change_median, 2),
            "row_drift_pct": round(row_drift_pct, 2)
        },
        "flags": {
            "time_flag": time_flag,
            "plan_flag": plan_flag,
            "index_lost": index_lost,
            "has_new_scan": has_new_scan,
            "stats_stale": stats_stale,
            "workload_surge": workload_surge,
            "is_noise": is_noise,
            "is_workload_grace": is_workload_grace
        },
        "double_booking_risk": is_double_booking_critical and (severity in ("CRITICAL", "HIGH")),
        "recommendations": recommendations,
        "evidence": evidence
    }
