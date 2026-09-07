"""
test_unit.py
=============
Unit tests for individual core modules.

Test IDs: T-01 through T-08
"""

import json
import os
import sqlite3
import sys
import tempfile
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core.plan_extractor import extract_plan, plans_differ, _parse_node
from src.core.timing_runner import run_timed
from src.core.rules_loader import load_rules, RulesValidationError
from src.core.evidence_builder import build_evidence, validate_evidence, REQUIRED_EVIDENCE_FIELDS
from src.core.regression_analyser import analyse, compute_evaluation_metrics
from src.core.snapshot_store import init_store, save_snapshot, save_query_execution, get_executions_for_snapshot

RULES_PATH = os.path.join(BASE_DIR, "config", "rules.yaml")


# ── T-01: Plan extraction ─────────────────────────────────────────────────────

def _make_indexed_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE appts (id INTEGER PRIMARY KEY, doctor_id TEXT, appt_date TEXT, status TEXT);
        CREATE INDEX idx_doc_date ON appts(doctor_id, appt_date);
        INSERT INTO appts VALUES (1,'D001','2025-01-01','SCHEDULED');
    """)
    return conn


def test_T01_plan_extractor_parses_index_search():
    """T-01: EXPLAIN output parsed; index-using query shows uses_index=True."""
    conn = _make_indexed_db()
    plan = extract_plan(conn, "SELECT * FROM appts WHERE doctor_id='D001' AND appt_date='2025-01-01'")
    assert plan["uses_index"] is True
    assert len(plan["nodes"]) >= 1
    assert "idx_doc_date" in plan["index_names"]
    conn.close()


def test_T01b_plan_extractor_detects_full_scan():
    """T-01b: Query without index shows has_full_scan=True."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (x INTEGER, y TEXT)")
    conn.execute("INSERT INTO t VALUES (1,'a')")
    # No index on y
    plan = extract_plan(conn, "SELECT * FROM t WHERE y='a'")
    assert plan["has_full_scan"] is True
    assert plan["uses_index"] is False
    conn.close()


# ── T-02: Timing runner ───────────────────────────────────────────────────────

def test_T02_timing_runner_returns_percentiles():
    """T-02: Timing runner returns valid p50/p95/p99 for a simple query."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (x INTEGER)")
    for i in range(100):
        conn.execute("INSERT INTO t VALUES (?)", (i,))
    timing = run_timed(conn, "SELECT SUM(x) FROM t", runs=8, warm_up=2)
    assert timing["error"] is None
    assert timing["runs"] == 8
    assert 0 < timing["p50_ms"] <= timing["p99_ms"]
    assert timing["p95_ms"] >= timing["p50_ms"]
    conn.close()


def test_T02b_timing_runner_handles_bad_sql():
    """T-02b: Timing runner returns error dict on invalid SQL."""
    conn = sqlite3.connect(":memory:")
    timing = run_timed(conn, "SELECT * FROM nonexistent_table_xyz", runs=3, warm_up=0)
    assert timing["error"] is not None
    assert timing["runs"] == 0
    conn.close()


# ── T-03: Index loss detection ────────────────────────────────────────────────

def test_T03_index_loss_detected():
    """T-03: plans_differ detects when baseline used index, run has full scan."""
    plan_a = {"raw": "SEARCH appts USING INDEX idx_doc_date", "index_names": ["idx_doc_date"],
              "has_full_scan": False, "uses_index": True}
    plan_b = {"raw": "SCAN appts", "index_names": [],
              "has_full_scan": True, "uses_index": False}
    changed, summary = plans_differ(plan_a, plan_b)
    assert changed is True
    assert "index" in summary.lower() or "scan" in summary.lower()


def test_T03b_no_change_detected_for_identical_plans():
    """T-03b: plans_differ returns False when plans are identical."""
    plan = {"raw": "SEARCH appts USING INDEX idx_doc_date", "index_names": ["idx_doc_date"],
            "has_full_scan": False, "uses_index": True}
    changed, _ = plans_differ(plan, plan)
    assert changed is False


# ── T-04: Plan node diff ──────────────────────────────────────────────────────

def test_T04_parse_node_identifies_scan():
    """T-04: _parse_node correctly identifies a SCAN detail string."""
    node = _parse_node("SCAN TABLE appointments")
    assert node["access_type"] == "SCAN"
    assert node["table"] == "appointments"


def test_T04b_parse_node_identifies_search_with_index():
    """T-04b: _parse_node identifies SEARCH + index name."""
    node = _parse_node("SEARCH appointments USING INDEX idx_appt_doctor_date (doctor_id=? AND appt_date=?)")
    assert node["access_type"] in ("SEARCH", "INDEX")
    assert "idx_appt_doctor_date" in node["indexes"]


# ── T-05: False positive noise band ──────────────────────────────────────────

def test_T05_noise_band_suppresses_ok():
    """T-05: Sub-noise-band change with no plan/index change → severity OK."""
    rules = load_rules(RULES_PATH)

    # Manufacture near-identical executions (< noise_band % change, no plan diff)
    baseline_exec = {
        "query_id": "QRY-TST", "query_label": "Test",
        "exec_ms_p50": 10.0, "exec_ms_p95": 15.0, "exec_ms_p99": 16.0,
        "plan_text": "SEARCH appts USING INDEX idx_doc",
        "plan_nodes": "[]", "uses_index": 1, "index_names": '["idx_doc"]',
        "has_full_scan": 0, "row_est": 4,
    }
    run_exec = {
        "query_id": "QRY-TST", "query_label": "Test",
        "exec_ms_p50": 10.5, "exec_ms_p95": 15.9, "exec_ms_p99": 16.5,  # <10% change
        "plan_text": "SEARCH appts USING INDEX idx_doc",
        "plan_nodes": "[]", "uses_index": 1, "index_names": '["idx_doc"]',
        "has_full_scan": 0, "row_est": 4,
    }
    baseline_snap = {"snapshot_id": 1, "release_tag": "v1.0"}
    run_snap = {"snapshot_id": 2, "release_tag": "v1.1"}

    findings = analyse([baseline_exec], [run_exec], baseline_snap, run_snap, rules)
    assert findings[0]["severity"] == "OK"
    assert findings[0]["is_noise"] is True


# ── T-06: Rules validation ────────────────────────────────────────────────────

def test_T06_rules_loader_valid():
    """T-06: Valid rules.yaml loads without exception."""
    rules = load_rules(RULES_PATH)
    assert "thresholds" in rules
    assert "plan_rules" in rules


def test_T06b_rules_loader_rejects_malformed(tmp_path):
    """T-06b: Malformed YAML raises RulesValidationError or FileNotFoundError."""
    bad_yaml = tmp_path / "bad_rules.yaml"
    bad_yaml.write_text("not_a_mapping: [\n  broken yaml", encoding="utf-8")
    with pytest.raises(Exception):  # yaml.YAMLError or RulesValidationError
        load_rules(str(bad_yaml))


def test_T06c_rules_loader_rejects_missing_section(tmp_path):
    """T-06c: rules.yaml missing required section raises RulesValidationError."""
    incomplete = tmp_path / "incomplete.yaml"
    incomplete.write_text("thresholds:\n  time_regression_pct: 20\n", encoding="utf-8")
    with pytest.raises(RulesValidationError):
        load_rules(str(incomplete))


# ── T-07: Evidence builder ────────────────────────────────────────────────────

def test_T07_evidence_contains_required_fields():
    """T-07: Evidence package contains all REQUIRED_EVIDENCE_FIELDS."""
    rules = load_rules(RULES_PATH)
    b_exec = {
        "exec_ms_p50": 12.0, "exec_ms_p95": 15.0, "exec_ms_p99": 16.0,
        "plan_text": "SEARCH appts USING INDEX idx", "index_names": '["idx"]',
        "has_full_scan": 0, "row_est": 5,
    }
    r_exec = {
        "exec_ms_p50": 2000.0, "exec_ms_p95": 2500.0, "exec_ms_p99": 2700.0,
        "plan_text": "SCAN appts", "index_names": "[]",
        "has_full_scan": 1, "row_est": 250000,
    }
    evidence = build_evidence(
        query_id="QRY-001", query_label="Test", severity="CRITICAL",
        regression_types=["TIME", "PLAN", "INDEX"],
        baseline_release="v1.0", run_release="v1.1",
        baseline_exec=b_exec, run_exec=r_exec,
        plan_diff_summary="SCAN appeared",
        delta_ms_p95=2485.0, pct_change=16567.0, rules=rules,
    )
    missing = validate_evidence(evidence)
    assert missing == [], f"Missing evidence fields: {missing}"


# ── T-08: Snapshot store idempotency ─────────────────────────────────────────

def test_T08_snapshot_store_idempotent(tmp_path):
    """T-08: init_store called multiple times is safe (idempotent)."""
    db = str(tmp_path / "test_store.db")
    init_store(db)
    init_store(db)  # second call must not raise
    snap_id = save_snapshot("v1.0", "BASELINE", 1024, {"appointments": 100}, db)
    assert snap_id >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
