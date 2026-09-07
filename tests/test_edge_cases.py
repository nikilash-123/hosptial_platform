"""
test_edge_cases.py
==================
Edge/failure case tests.

Test IDs: ET-01 through ET-05
"""

import os
import sys
import sqlite3
import tempfile
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import snapshot_store, regression_analyser, rules_loader, plan_extractor, timing_runner
from src.core.rules_loader import RulesValidationError

RULES_PATH = os.path.join(BASE_DIR, "config", "rules.yaml")


# ── ET-01: Missing baseline ───────────────────────────────────────────────────

def test_ET01_missing_baseline_returns_graceful_finding():
    """ET-01: analyse() with no baseline execution returns LOW finding, no crash."""
    rules = rules_loader.load_rules(RULES_PATH)

    run_exec = {
        "query_id": "QRY-001", "query_label": "Doctor schedule lookup",
        "exec_ms_p50": 100.0, "exec_ms_p95": 200.0, "exec_ms_p99": 220.0,
        "plan_text": "SCAN appointments", "plan_nodes": "[]",
        "uses_index": 0, "index_names": "[]", "has_full_scan": 1, "row_est": 50000,
    }

    findings = regression_analyser.analyse(
        baseline_execs=[],           # no baseline!
        run_execs=[run_exec],
        baseline_snap={"snapshot_id": 1, "release_tag": "v1.0"},
        run_snap={"snapshot_id": 2, "release_tag": "v1.1"},
        rules=rules,
    )
    assert len(findings) == 1
    assert findings[0]["severity"] == "LOW"
    assert "MISSING_BASELINE" in findings[0]["regression_types"]


# ── ET-02: Probe query syntax error ───────────────────────────────────────────

def test_ET02_bad_sql_isolated_failure():
    """ET-02: A bad SQL query in EXPLAIN returns an error plan without crashing others."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE good_table (x INTEGER)")

    # Bad SQL
    bad_plan = plan_extractor.extract_plan(conn, "SELECT * FROM nonexistent_xyzzy_table")
    assert bad_plan["uses_index"] is False
    assert "error" in bad_plan

    # Good SQL still works
    good_plan = plan_extractor.extract_plan(conn, "SELECT * FROM good_table")
    # No error key (or error is None)
    assert good_plan.get("error") is None or good_plan.get("raw") != ""
    conn.close()


# ── ET-03: Malformed rules.yaml ───────────────────────────────────────────────

def test_ET03_malformed_rules_raises_error(tmp_path):
    """ET-03: Malformed rules.yaml raises exception — system refuses to run."""
    bad = tmp_path / "bad_rules.yaml"
    bad.write_text("this is: [broken: yaml\n  nope", encoding="utf-8")
    with pytest.raises(Exception):
        rules_loader.load_rules(str(bad))


def test_ET03b_empty_rules_raises_validation_error(tmp_path):
    """ET-03b: Empty rules.yaml raises RulesValidationError."""
    empty = tmp_path / "empty_rules.yaml"
    empty.write_text("{}", encoding="utf-8")
    with pytest.raises(RulesValidationError):
        rules_loader.load_rules(str(empty))


# ── ET-04: False positive noise correctly suppressed ─────────────────────────

def test_ET04_false_positive_noise_suppressed():
    """ET-04: Sub-noise-band Δ with no plan/index change → OK (false positive suppressed)."""
    rules = rules_loader.load_rules(RULES_PATH)

    baseline_exec = {
        "query_id": "QRY-TEST-FP", "query_label": "FP test",
        "exec_ms_p50": 10.0, "exec_ms_p95": 12.0, "exec_ms_p99": 13.0,
        "plan_text": "SEARCH t USING INDEX idx_t",
        "plan_nodes": "[]", "uses_index": 1, "index_names": '["idx_t"]',
        "has_full_scan": 0, "row_est": 10,
    }
    run_exec = {
        "query_id": "QRY-TEST-FP", "query_label": "FP test",
        "exec_ms_p50": 10.3, "exec_ms_p95": 12.8, "exec_ms_p99": 13.5,  # ~6.7% change
        "plan_text": "SEARCH t USING INDEX idx_t",  # same plan
        "plan_nodes": "[]", "uses_index": 1, "index_names": '["idx_t"]',
        "has_full_scan": 0, "row_est": 10,
    }
    bl_snap  = {"snapshot_id": 1, "release_tag": "v1.0"}
    run_snap = {"snapshot_id": 2, "release_tag": "v1.1"}

    findings = regression_analyser.analyse([baseline_exec], [run_exec], bl_snap, run_snap, rules)
    assert findings[0]["severity"] == "OK"
    assert findings[0]["is_noise"] is True


# ── ET-05: Deliberate false negative (threshold too high) ─────────────────────

def test_ET05_false_negative_documented():
    """
    ET-05: When threshold is set too high, a real regression is missed (FN).
    We document this and confirm the system can handle FN marking.
    """
    import yaml
    import copy

    rules = rules_loader.load_rules(RULES_PATH)
    # Simulate a very high threshold — real regression won't be detected
    high_threshold_rules = copy.deepcopy(rules)
    high_threshold_rules["thresholds"]["time_regression_pct"] = 10000.0  # unreachably high
    high_threshold_rules["thresholds"]["time_critical_pct"] = 10000.0
    high_threshold_rules["thresholds"]["time_high_pct"] = 10000.0
    high_threshold_rules["thresholds"]["time_medium_pct"] = 10000.0
    high_threshold_rules["thresholds"]["absolute_critical_ms"] = 99999.0
    high_threshold_rules["thresholds"]["absolute_high_ms"] = 99999.0

    baseline_exec = {
        "query_id": "QRY-TEST-FN", "query_label": "FN test",
        "exec_ms_p50": 10.0, "exec_ms_p95": 15.0, "exec_ms_p99": 16.0,
        "plan_text": "SEARCH t USING INDEX idx_t",
        "plan_nodes": "[]", "uses_index": 1, "index_names": '["idx_t"]',
        "has_full_scan": 0, "row_est": 10,
    }
    run_exec = {
        "query_id": "QRY-TEST-FN", "query_label": "FN test",
        "exec_ms_p50": 300.0, "exec_ms_p95": 400.0, "exec_ms_p99": 450.0,  # 2566% increase!
        "plan_text": "SEARCH t USING INDEX idx_t",  # plan same (no plan flag)
        "plan_nodes": "[]", "uses_index": 1, "index_names": '["idx_t"]',
        "has_full_scan": 0, "row_est": 10,
    }
    bl_snap  = {"snapshot_id": 1, "release_tag": "v1.0"}
    run_snap = {"snapshot_id": 2, "release_tag": "v1.1"}

    findings = regression_analyser.analyse(
        [baseline_exec], [run_exec], bl_snap, run_snap, high_threshold_rules
    )
    # With absurdly high thresholds, the real regression is missed → FN
    assert findings[0]["severity"] == "OK", (
        "Expected false negative (OK) with threshold=10000%. "
        f"Got: {findings[0]['severity']}"
    )
    # Document: this is a known FN — thresholds must be tuned appropriately
    # (In the real system, DBA Admin would use the FN marking API and lower the threshold)
    print(f"\n[ET-05] FN documented: real Δ={findings[0]['pct_change']:.1f}% missed "
          f"(threshold was set to 10000%). DBA should adjust rules.yaml.")


# ── ET-05b: Verify FP/FN are correctly stored ────────────────────────────────

def test_ET05b_fp_fn_marking_persisted(tmp_path):
    """ET-05b: FP and FN flags can be saved and retrieved from the store."""
    store = str(tmp_path / "store.db")
    snapshot_store.init_store(store)

    b_id = snapshot_store.save_snapshot("v1.0", "BASELINE", 0, {}, store)
    r_id = snapshot_store.save_snapshot("v1.1", "RUN", 0, {}, store)

    reg_id = snapshot_store.save_regression(
        baseline_snap_id=b_id, run_snap_id=r_id,
        query_id="QRY-001", query_label="Test",
        severity="OK",  # was initially OK — actually a FN
        regression_types=[], delta_ms_p95=50.0, pct_change=250.0,
        plan_changed=False, index_lost=False, has_new_scan=False,
        evidence={}, store_path=store,
    )

    snapshot_store.update_regression_flag(
        regression_id=reg_id, is_false_neg=True,
        analyst_note="Threshold was too high — this was a real regression",
        store_path=store,
    )

    regs = snapshot_store.get_regressions(store_path=store)
    assert regs[0]["is_false_neg"] == 1
    assert "Threshold was too high" in regs[0]["analyst_note"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
