"""
test_rule_engine.py
===================
Unit and Integration tests for Phase 7: Priority and Configurable Rule Engine.

Verifies:
1. Configurable thresholds, weights, and priority scoring.
2. Explainability: triggered rules, conditions, point contributions, and versioning.
3. Evidence requirements and sufficiency check (MANUAL_REVIEW_REQUIRED on insufficient evidence).
4. Configuration versioning across runs.
5. Admin Configuration API (GET /api/rules, POST /api/rules with role enforcement).
6. Dynamic threshold behavior (changing configuration changes detection without code modifications).
7. Complete coverage of all 7 mandatory edge cases:
   - EC1: Invalid negative threshold rejected.
   - EC2: Critical threshold lower than warning threshold rejected.
   - EC3: Missing required configuration rejected safely.
   - EC4: Very high threshold produces fewer alerts.
   - EC5: Very low threshold produces more alerts.
   - EC6: Configuration changed between two runs records correct version in each result.
   - EC7: High score with insufficient evidence returns MANUAL_REVIEW_REQUIRED.
8. Configuration audit history logging.
"""

import os
import sys
import copy
import pytest
from typing import Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import (
    rule_engine,
    rules_loader,
    detection_engine,
    snapshot_store
)
from src.core.rules_loader import RulesValidationError

RULES_PATH = os.path.join(BASE_DIR, "config", "rules.yaml")


@pytest.fixture
def clean_rules() -> Dict[str, Any]:
    """Loads a fresh copy of rules.yaml for test isolation."""
    return rules_loader.load_rules(RULES_PATH)


@pytest.fixture
def baseline_query() -> Dict[str, Any]:
    return {
        "query_id": "QRY-001",
        "query_name": "Doctor schedule lookup",
        "query_type": "retrieve_doctor_schedule",
        "execution_time_ms": 120.0,
        "plan_text": "SEARCH doctor_schedule USING INDEX idx_doctor_schedule",
        "plan_hash": "hash_doc_idx_120",
        "indexes": ["idx_doctor_schedule"],
        "rows_examined": 50,
        "cpu_time_ms": 80.0,
        "io_cost": 10.0,
        "statistics_age": 2,
        "statistics_status": "CURRENT",
        "workload_level": "NORMAL",
        "release_version": "v1.3",
        "schema_change": "NONE"
    }


# ── 1. Basic Rule Engine Evaluation & Scoring ────────────────────────────────

def test_RE01_rule_engine_basic_scoring(clean_rules, baseline_query):
    """Verify RuleEngine evaluates multi-dimensional signals using configured weights."""
    engine = rule_engine.RuleEngine(rules=clean_rules)

    signals = {
        "baseline_exec_ms": 120.0,
        "current_exec_ms": 850.0,
        "time_pct_change": 608.33,
        "plan_changed": True,
        "full_table_scan_detected": True,
        "index_removed": True,
        "lost_indexes": ["idx_doctor_schedule"],
        "statistics_stale": False,
        "workload_increased": False,
        "schema_changed": False,
        "recent_release": True,
        "release_version": "v1.4",
        "release_change": "release_deployment"
    }

    result = engine.evaluate(signals, context=baseline_query)

    assert result["score"] >= 80.0
    assert result["severity"] == "CRITICAL"
    assert result["priority"] in ("CRITICAL", "HIGH")
    assert result["rule_config_version"] == clean_rules.get("rule_config_version", "v1.0")

    # Verify per-rule contributions are present
    rule_names = [r["rule_name"] for r in result["triggered_rules"]]
    assert "execution_time_regression" in rule_names
    assert "plan_changed" in rule_names
    assert "full_table_scan_detected" in rule_names
    assert "index_removed" in rule_names
    assert "recent_release" in rule_names


def test_RE02_explainability_data_driven_output(clean_rules, baseline_query):
    """Verify that explainability text details each triggered rule with actual data."""
    engine = rule_engine.RuleEngine(rules=clean_rules)

    signals = {
        "baseline_exec_ms": 120.0,
        "current_exec_ms": 850.0,
        "time_pct_change": 608.33,
        "plan_changed": True,
        "full_table_scan_detected": True,
        "index_removed": True,
        "lost_indexes": ["idx_doctor_schedule"],
        "recent_release": True,
        "release_version": "v1.4"
    }

    result = engine.evaluate(signals, context=baseline_query)
    explanation = result["explanation"]

    # Verify explainability requirements from Section 5
    assert "Priority: CRITICAL" in explanation or "Score:" in explanation
    assert "Execution time regression" in explanation
    assert "120.00 ms" in explanation
    assert "850.00 ms" in explanation
    assert "+608.3%" in explanation
    assert "Index removal" in explanation
    assert "idx_doctor_schedule" in explanation
    assert "Recent release" in explanation
    assert f"Configuration version: {clean_rules.get('rule_config_version', 'v1.0')}" in explanation


# ── 2. Dynamic Threshold Behavior Test (Requirement 12) ──────────────────────

def test_RE03_dynamic_threshold_behavior():
    """
    DYNAMIC BEHAVIOUR TEST (Requirement 12):
    Proves changing configuration changes detection behavior without code changes.
    Configuration A: regression threshold = 20%
    Baseline: 100 ms, Current: 115 ms (+15%) -> No regression triggered.
    Then modify configuration to 10% -> Regression triggered on same data!
    """
    rules_a = rules_loader.load_rules(RULES_PATH)
    rules_a["thresholds"]["execution_time_regression_percent"] = 20.0
    rules_a["thresholds"]["time_regression_pct"] = 20.0

    b_state = {
        "query_id": "QRY-DYN", "execution_time_ms": 100.0,
        "plan_text": "SEARCH t USING INDEX i", "plan_hash": "h1",
        "indexes": ["i"], "rows_examined": 10, "statistics_age": 1,
        "workload_level": "NORMAL", "release_version": "v1.0"
    }
    a_state = copy.deepcopy(b_state)
    a_state["execution_time_ms"] = 115.0  # +15.0%

    # Run with Configuration A (threshold = 20%)
    res_a = detection_engine.detect_query_regression(b_state, a_state, rules=rules_a)
    assert res_a["pct_change"] == 15.0
    # At 20% threshold with 15% increase, execution_time_regression should NOT trigger
    reg_rules_a = [r["rule_name"] for r in res_a.get("triggered_rules", [])]
    assert "execution_time_regression" not in reg_rules_a
    assert res_a["classification"] == "NORMAL"

    # Now change configuration to Configuration B (threshold = 10%)
    rules_b = copy.deepcopy(rules_a)
    rules_b["thresholds"]["execution_time_regression_percent"] = 10.0
    rules_b["thresholds"]["time_regression_pct"] = 10.0
    rules_b["false_positive_grace"]["noise_band_pct"] = 5.0  # Ensure 15% is outside noise band

    # Run with Configuration B on the EXACT same query data
    res_b = detection_engine.detect_query_regression(b_state, a_state, rules=rules_b)
    assert res_b["pct_change"] == 15.0
    reg_rules_b = [r["rule_name"] for r in res_b.get("triggered_rules", [])]
    assert "execution_time_regression" in reg_rules_b
    # Confirms detection behavior genuinely adapted to external configuration change


# ── 3. Edge Cases (Requirement 13 - 7 Mandatory Edge Cases) ───────────────────

def test_RE04_edge_case_1_invalid_negative_threshold(clean_rules):
    """Edge Case 1: Invalid negative threshold must be rejected by validator."""
    bad_rules = copy.deepcopy(clean_rules)
    bad_rules["thresholds"]["execution_time_regression_percent"] = -15.0

    with pytest.raises(RulesValidationError) as excinfo:
        rules_loader.validate_rules_dict(bad_rules)
    assert "must be non-negative" in str(excinfo.value)


def test_RE05_edge_case_2_critical_lower_than_warning_threshold(clean_rules):
    """Edge Case 2: Critical execution time lower than warning threshold must be rejected."""
    bad_rules = copy.deepcopy(clean_rules)
    # Set warning higher than critical
    bad_rules["thresholds"]["execution_time_warning_ms"] = 3000.0
    bad_rules["thresholds"]["execution_time_critical_ms"] = 1000.0

    with pytest.raises(RulesValidationError) as excinfo:
        rules_loader.validate_rules_dict(bad_rules)
    assert "cannot exceed critical threshold" in str(excinfo.value)


def test_RE06_edge_case_3_missing_required_configuration(clean_rules):
    """Edge Case 3: Missing required configuration section raises safe validation error."""
    broken_rules = copy.deepcopy(clean_rules)
    del broken_rules["thresholds"]

    with pytest.raises(RulesValidationError) as excinfo:
        rules_loader.validate_rules_dict(broken_rules)
    assert "missing required sections" in str(excinfo.value)


def test_RE07_edge_case_4_very_high_threshold_fewer_alerts(clean_rules, baseline_query):
    """Edge Case 4: Very high threshold produces fewer / zero regression alerts."""
    high_thresh_rules = copy.deepcopy(clean_rules)
    high_thresh_rules["thresholds"]["execution_time_regression_percent"] = 500.0
    high_thresh_rules["thresholds"]["time_regression_pct"] = 500.0
    high_thresh_rules["thresholds"]["time_high_pct"] = 700.0
    high_thresh_rules["thresholds"]["time_critical_pct"] = 1000.0
    high_thresh_rules["thresholds"]["absolute_critical_ms"] = 10000.0
    high_thresh_rules["thresholds"]["absolute_high_ms"] = 5000.0

    current_query = copy.deepcopy(baseline_query)
    current_query["execution_time_ms"] = baseline_query["execution_time_ms"] * 1.8  # +80% increase

    res = detection_engine.detect_query_regression(baseline_query, current_query, rules=high_thresh_rules)
    # Under a 500% threshold, an 80% latency increase should NOT trigger a performance regression
    triggered = [r["rule_name"] for r in res.get("triggered_rules", [])]
    assert "execution_time_regression" not in triggered


def test_RE08_edge_case_5_very_low_threshold_more_alerts(clean_rules, baseline_query):
    """Edge Case 5: Very low threshold produces more regression alerts for minor variance."""
    low_thresh_rules = copy.deepcopy(clean_rules)
    low_thresh_rules["thresholds"]["execution_time_regression_percent"] = 2.0
    low_thresh_rules["thresholds"]["time_regression_pct"] = 2.0
    low_thresh_rules["false_positive_grace"]["noise_band_pct"] = 1.0

    current_query = copy.deepcopy(baseline_query)
    current_query["execution_time_ms"] = baseline_query["execution_time_ms"] * 1.05  # only +5% increase

    res = detection_engine.detect_query_regression(baseline_query, current_query, rules=low_thresh_rules)
    triggered = [r["rule_name"] for r in res.get("triggered_rules", [])]
    assert "execution_time_regression" in triggered


def test_RE09_edge_case_6_version_recorded_per_run(clean_rules, baseline_query):
    """Edge Case 6: Configuration changed between two runs records correct version in each result."""
    rules_v1 = copy.deepcopy(clean_rules)
    rules_v1["rule_config_version"] = "v1.0"

    rules_v2 = copy.deepcopy(clean_rules)
    rules_v2["rule_config_version"] = "v1.1"

    current = copy.deepcopy(baseline_query)
    current["execution_time_ms"] = 300.0

    res_1 = detection_engine.detect_query_regression(baseline_query, current, rules=rules_v1)
    res_2 = detection_engine.detect_query_regression(baseline_query, current, rules=rules_v2)

    assert res_1["rule_config_version"] == "v1.0"
    assert res_1["evidence"]["rule_config_version"] == "v1.0"

    assert res_2["rule_config_version"] == "v1.1"
    assert res_2["evidence"]["rule_config_version"] == "v1.1"


def test_RE10_edge_case_7_high_score_insufficient_evidence(clean_rules):
    """
    Edge Case 7: High score but insufficient evidence.
    Expected: priority is set to MANUAL_REVIEW_REQUIRED / INSUFFICIENT_EVIDENCE to avoid false certainty.
    """
    strict_rules = copy.deepcopy(clean_rules)
    strict_rules["evidence_requirements"]["min_evidence_for_critical"] = 4
    strict_rules["evidence_requirements"]["insufficient_evidence_action"] = "MANUAL_REVIEW_REQUIRED"

    engine = rule_engine.RuleEngine(rules=strict_rules)

    # Signals produce high/critical score from latency alone, but missing plan/index/stats data
    signals = {
        "baseline_exec_ms": 100.0,
        "current_exec_ms": 2500.0,
        "time_pct_change": 2400.0,
        "plan_changed": False,
        "full_table_scan_detected": False,
        "index_removed": False,
        "statistics_stale": False,
        "workload_increased": False,
        "schema_changed": False,
        "recent_release": False
    }

    result = engine.evaluate(signals, context={})

    assert result["severity"] == "CRITICAL"
    assert result["priority"] == "MANUAL_REVIEW_REQUIRED"
    assert result["evidence_sufficiency"]["sufficient"] is False
    assert "MANUAL_REVIEW_REQUIRED" in result["evidence_sufficiency"]["status"]


# ── 4. Admin Configuration API & Role Enforcement Tests ───────────────────────

def test_RE11_api_get_rules():
    """Verify GET /api/rules returns current configuration and version."""
    from src.web.app import app
    client = app.test_client()

    res = client.get("/api/rules")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "version" in data
    assert "rules" in data
    assert "thresholds" in data["rules"]
    assert "audit_history" in data


def test_RE12_api_update_rules_role_enforcement(clean_rules):
    """Verify POST /api/rules strictly permits DBA Admin and rejects Engineering Reviewer with 403."""
    from src.web.app import app
    client = app.test_client()

    with open(RULES_PATH, "r", encoding="utf-8") as f:
        original_yaml = f.read()

    try:
        updated = copy.deepcopy(clean_rules)
        updated["thresholds"]["time_regression_pct"] = 25.0

        # 1. Attempt update as release_engineer -> Forbidden (403)
        res_eng = client.post("/api/rules", json={
            "rules": updated,
            "role": "release_engineer",
            "username": "reviewer"
        })
        assert res_eng.status_code == 403
        data_eng = res_eng.get_json()
        assert data_eng["status"] == "error"
        assert "Only DBA Admin" in data_eng["message"]

        # 2. Attempt update as dba_admin with invalid data -> Validation Error (400)
        bad_payload = copy.deepcopy(updated)
        bad_payload["thresholds"]["time_regression_pct"] = -5.0
        res_bad = client.post("/api/rules", json={
            "rules": bad_payload,
            "role": "dba_admin",
            "username": "dba_admin"
        })
        assert res_bad.status_code == 400
        data_bad = res_bad.get_json()
        assert data_bad["error_type"] == "ValidationError"

        # 3. Successful update as dba_admin -> Success (200)
        res_dba = client.post("/api/rules", json={
            "rules": updated,
            "role": "dba_admin",
            "username": "dba_admin"
        })
        assert res_dba.status_code == 200
        data_dba = res_dba.get_json()
        assert data_dba["status"] == "success"
        assert "version" in data_dba
    finally:
        with open(RULES_PATH, "w", encoding="utf-8") as f:
            f.write(original_yaml)


def test_RE13_configuration_audit_logging(tmp_path, clean_rules):
    """Verify that configuration changes are audited with timestamp, role, and changed fields."""
    db_path = str(tmp_path / "test_detector_store.db")
    snapshot_store.init_store(db_path)

    import yaml
    rules_text = yaml.dump(clean_rules)

    audit_id = snapshot_store.save_rules_audit(
        changed_by="dba_admin",
        role="dba_admin",
        rules_yaml=rules_text,
        config_version="v1.2",
        changed_fields=["thresholds.time_regression_pct"],
        previous_value="20.0",
        new_value="25.0",
        store_path=db_path
    )

    assert audit_id is not None
    history = snapshot_store.get_rules_audit_history(limit=5, store_path=db_path)
    assert len(history) >= 1
    latest = history[0]
    assert latest["changed_by"] == "dba_admin"
    assert latest["role"] == "dba_admin"
    assert latest["config_version"] == "v1.2"
    assert "thresholds.time_regression_pct" in latest["changed_fields"]
