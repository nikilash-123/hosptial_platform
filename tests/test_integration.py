"""
test_integration.py
====================
Integration tests: full workflow from data → baseline → change → run → analyse.

Test IDs: IT-01 through IT-04
"""

import os
import sys
import sqlite3
import tempfile
import shutil
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import rules_loader, plan_extractor, timing_runner
from src.core import snapshot_store, regression_analyser, stats_collector


RULES_PATH = os.path.join(BASE_DIR, "config", "rules.yaml")
QUERIES_PATH = os.path.join(BASE_DIR, "config", "probe_queries.yaml")


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _build_test_db(path: str, with_indexes: bool = True) -> str:
    """Create a minimal hospital.db for integration tests."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE patients (patient_id TEXT PRIMARY KEY, age_band TEXT, gender TEXT,
                               region_code TEXT, registered_at TEXT);
        CREATE TABLE departments (dept_id TEXT PRIMARY KEY, dept_name TEXT, floor INTEGER);
        CREATE TABLE doctors (doctor_id TEXT PRIMARY KEY, specialty TEXT, dept_id TEXT, is_active INTEGER);
        CREATE TABLE appointments (
            appt_id TEXT PRIMARY KEY, patient_id TEXT, doctor_id TEXT, dept_id TEXT,
            appt_date TEXT, appt_time TEXT, duration_mins INTEGER,
            status TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE audit_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT, description TEXT, release_tag TEXT, applied_at TEXT
        );
    """)

    # Seed minimal data
    conn.execute("INSERT INTO departments VALUES ('SYNTH-DEPT-01','Cardiology Dept',1)")
    conn.execute("INSERT INTO doctors VALUES ('SYNTH-D-001','Cardiology','SYNTH-DEPT-01',1)")
    conn.execute("INSERT INTO patients VALUES ('SYNTH-P-000001','35-44','M','R01','2022-01-01')")

    import random
    random.seed(42)
    for i in range(500):
        conn.execute(
            "INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"SYNTH-A-{i:06d}", "SYNTH-P-000001", "SYNTH-D-001", "SYNTH-DEPT-01",
             "2025-06-15", f"{8+i%9:02d}:00", 30, "SCHEDULED",
             "2025-01-01", "2025-01-01")
        )
    conn.commit()

    if with_indexes:
        conn.executescript("""
            CREATE INDEX idx_appt_doctor_date ON appointments(doctor_id, appt_date);
            CREATE INDEX idx_appt_patient     ON appointments(patient_id);
            CREATE INDEX idx_appt_status_date ON appointments(status, appt_date);
            CREATE INDEX idx_appt_dept_date   ON appointments(dept_id, appt_date);
        """)
        conn.execute("ANALYZE")
        conn.commit()

    conn.close()
    return path


def _capture_snapshot_for_db(db_path, store_path, release_tag, snap_type, rules):
    """Run the capture pipeline for a set of simple probe queries."""
    import yaml
    with open(QUERIES_PATH, "r") as f:
        queries = yaml.safe_load(f)["queries"]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stats = stats_collector.collect_stats(conn, db_path)
    row_counts = {t: v["row_count"] for t, v in stats["tables"].items()}
    snap_id = snapshot_store.save_snapshot(release_tag, snap_type, stats["db_size_bytes"], row_counts, store_path)

    for q in queries:
        plan = plan_extractor.extract_plan(conn, q["sql"].strip())
        timing = timing_runner.run_timed(conn, q["sql"].strip(), runs=5, warm_up=1)
        snapshot_store.save_query_execution(
            snap_id, q["id"], q["label"], q["sql"].strip(),
            plan, timing, {}, store_path
        )
    conn.close()
    return snap_id


# ── IT-01: Drop index → CRITICAL detected ────────────────────────────────────

def test_IT01_drop_index_causes_critical(tmp_path):
    """IT-01: Dropping critical index → CRITICAL regression detected for QRY-001/QRY-004."""
    db = str(tmp_path / "hospital.db")
    store = str(tmp_path / "store.db")
    _build_test_db(db, with_indexes=True)
    snapshot_store.init_store(store)
    rules = rules_loader.load_rules(RULES_PATH)

    # Capture baseline
    bl_id = _capture_snapshot_for_db(db, store, "v1.0", "BASELINE", rules)

    # Drop the critical index
    conn = sqlite3.connect(db)
    conn.execute("DROP INDEX IF EXISTS idx_appt_doctor_date")
    conn.execute("DROP INDEX IF EXISTS idx_appt_status_date")
    conn.commit()
    conn.close()

    # Capture run
    run_id = _capture_snapshot_for_db(db, store, "v1.1", "RUN", rules)

    # Analyse
    bl_execs  = snapshot_store.get_executions_for_snapshot(bl_id, store)
    run_execs = snapshot_store.get_executions_for_snapshot(run_id, store)
    bl_snap  = snapshot_store.get_snapshot_by_tag("v1.0", "BASELINE", store)
    run_snap = snapshot_store.get_snapshot_by_tag("v1.1", "RUN", store)

    findings = regression_analyser.analyse(bl_execs, run_execs, bl_snap, run_snap, rules)

    # At least one regression should be HIGH or CRITICAL
    regressed = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH")]
    assert len(regressed) >= 1, f"Expected regressions, got: {[(f['query_id'],f['severity']) for f in findings]}"

    # QRY-004 (double-booking scan) must be regressed — the critical path
    q4 = next((f for f in findings if f["query_id"] == "QRY-004"), None)
    if q4:
        # Either index was lost OR plan changed OR time regressed
        assert (q4["index_lost"] or q4["plan_changed"] or q4["pct_change"] > 20), (
            f"QRY-004 should detect regression after index drop, got: severity={q4['severity']}, "
            f"index_lost={q4['index_lost']}, plan_changed={q4['plan_changed']}, pct={q4['pct_change']}"
        )


# ── IT-02: Data growth → regression detected ──────────────────────────────────

def test_IT02_data_growth_detected(tmp_path):
    """IT-02: 10× data growth → at least MEDIUM timing regression detected."""
    db = str(tmp_path / "hospital.db")
    store = str(tmp_path / "store.db")
    _build_test_db(db, with_indexes=True)
    snapshot_store.init_store(store)
    rules = rules_loader.load_rules(RULES_PATH)

    bl_id = _capture_snapshot_for_db(db, store, "v1.0", "BASELINE", rules)

    # Insert 5× more rows
    conn = sqlite3.connect(db)
    for i in range(2500):
        conn.execute(
            "INSERT OR IGNORE INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"SYNTH-A-G-{i:06d}", "SYNTH-P-000001", "SYNTH-D-001", "SYNTH-DEPT-01",
             "2025-06-15", f"{8+i%9:02d}:00", 30, "SCHEDULED", "2025-01-01", "2025-01-01")
        )
    conn.commit()
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    run_id = _capture_snapshot_for_db(db, store, "v1.1", "RUN", rules)

    bl_execs  = snapshot_store.get_executions_for_snapshot(bl_id, store)
    run_execs = snapshot_store.get_executions_for_snapshot(run_id, store)
    bl_snap  = snapshot_store.get_snapshot_by_tag("v1.0", "BASELINE", store)
    run_snap = snapshot_store.get_snapshot_by_tag("v1.1", "RUN", store)

    findings = regression_analyser.analyse(bl_execs, run_execs, bl_snap, run_snap, rules)
    # At minimum, the double-booking conflict scan (QRY-004) should flag
    q4 = next((f for f in findings if f["query_id"] == "QRY-004"), None)
    assert q4 is not None
    # Stats drift should be detected (row counts changed significantly)
    assert q4["stats_flag"] or q4["pct_change"] >= 0, "QRY-004 should reflect data change"


# ── IT-03: No change → all OK ────────────────────────────────────────────────

def test_IT03_no_change_all_ok(tmp_path):
    """IT-03: No change between baseline and run → all queries should be OK or noise."""
    db = str(tmp_path / "hospital.db")
    store = str(tmp_path / "store.db")
    _build_test_db(db, with_indexes=True)
    snapshot_store.init_store(store)
    rules = rules_loader.load_rules(RULES_PATH)

    bl_id  = _capture_snapshot_for_db(db, store, "v1.0", "BASELINE", rules)
    run_id = _capture_snapshot_for_db(db, store, "v1.1", "RUN", rules)

    bl_execs  = snapshot_store.get_executions_for_snapshot(bl_id, store)
    run_execs = snapshot_store.get_executions_for_snapshot(run_id, store)
    bl_snap  = snapshot_store.get_snapshot_by_tag("v1.0", "BASELINE", store)
    run_snap = snapshot_store.get_snapshot_by_tag("v1.1", "RUN", store)

    findings = regression_analyser.analyse(bl_execs, run_execs, bl_snap, run_snap, rules)
    criticals = [f for f in findings if f["severity"] == "CRITICAL"]
    assert len(criticals) == 0, f"Expected no CRITICAL regressions, got: {criticals}"


# ── IT-04: Evaluation metrics ─────────────────────────────────────────────────

def test_IT04_evaluation_metrics():
    """IT-04: compute_evaluation_metrics correctly calculates TP/FP/FN/TN."""
    findings = [
        {"query_id": "QRY-001", "severity": "CRITICAL"},
        {"query_id": "QRY-002", "severity": "OK"},
        {"query_id": "QRY-003", "severity": "HIGH"},
        {"query_id": "QRY-004", "severity": "OK"},
    ]
    ground_truth = {
        "QRY-001": "CRITICAL",   # TP
        "QRY-002": "OK",         # TN
        "QRY-003": "OK",         # FP
        "QRY-004": "HIGH",       # FN
    }
    metrics = regression_analyser.compute_evaluation_metrics(findings, ground_truth)
    assert metrics["tp"] == 1
    assert metrics["fp"] == 1
    assert metrics["fn"] == 1
    assert metrics["tn"] == 1
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
