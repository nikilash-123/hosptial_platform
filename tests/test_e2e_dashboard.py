"""
test_e2e_dashboard.py
=====================
Comprehensive End-to-End (E2E) Test Suite for Phase 9 of the
Hospital Appointment Platform Query Regression Detector.

Covers:
- test_E2E01_full_workflow_from_baseline_to_audit
- test_E2E02_dashboard_metrics_api_and_page
- test_E2E03_query_forensics_detail_api_12_sections
- test_E2E04_core_success_metric_timing_model
- test_E2E05_demo_scenarios_execution
- test_E2E06_safe_demo_reset
- test_E2E07_rbac_dashboard_and_review_workflow
- test_E2E08_regressions_facet_filtering_api
- test_E2E09_evaluation_page_and_api
- test_E2E10_edge_cases_and_graceful_failures
"""

import os
import sys
import json
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import (
    snapshot_store, baseline_engine, detection_engine,
    plan_comparator, change_context_analyser, rule_engine,
    timing_model, rules_loader
)
from src.web.app import app, DETECTOR_DB, RULES_YAML


@pytest.fixture
def client():
    """Provides a fresh Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def auth_admin_session(client):
    """Provides an authenticated DBA Admin session."""
    with client.session_transaction() as sess:
        sess["username"] = "admin_user"
        sess["user_id"] = "admin_user"
        sess["role"] = "dba_admin"
        sess["display_name"] = "Chief DBA Administrator"
    return client


@pytest.fixture
def auth_reviewer_session(client):
    """Provides an authenticated Application Reviewer session."""
    with client.session_transaction() as sess:
        sess["username"] = "reviewer_user"
        sess["user_id"] = "reviewer_user"
        sess["role"] = "application_reviewer"
        sess["display_name"] = "Lead Clinical Systems Reviewer"
    return client


# ── Test Cases ────────────────────────────────────────────────────────────────

def test_E2E01_full_workflow_from_baseline_to_audit(auth_admin_session):
    """
    E2E-01: Verifies the complete end-to-end regression detection workflow:
    Baseline -> Change Event -> Detector -> Plan Diff -> Change Context ->
    Scoring -> Dashboard Stats -> Detail Forensics -> Review -> Security Audit.
    """
    client = auth_admin_session

    # Step 1: Baseline Query State
    before_query = {
        "query_id": "QRY-004",
        "query_name": "Verify Appointment Slot Booked",
        "query_type": "verify_slot_booked",
        "execution_time_ms": 22.5,
        "plan_text": "SEARCH appointments USING INDEX idx_appt_doctor_date (doctor_id=?, appt_date=?)",
        "plan_hash": "hash_verify_opt",
        "indexes": ["idx_appt_doctor_date"],
        "statistics_status": "CURRENT",
        "workload_level": "NORMAL",
        "rows_examined": 10,
        "rows_returned": 1,
        "release_version": "v1.0"
    }

    # Step 2: Current Degraded State after simulated index drop
    after_query = {
        "query_id": "QRY-004",
        "query_name": "Verify Appointment Slot Booked",
        "query_type": "verify_slot_booked",
        "execution_time_ms": 820.0,
        "plan_text": "SCAN appointments (FULL TABLE SCAN)",
        "plan_hash": "hash_verify_scan",
        "indexes": [],
        "index_status": "REMOVED",
        "statistics_status": "STALE",
        "workload_level": "NORMAL",
        "rows_examined": 50000,
        "rows_returned": 1,
        "release_version": "v1.1",
        "schema_change": "DROP INDEX idx_appt_doctor_date",
        "release_change": "INDEX_DROP"
    }

    # Step 3: Run detection engine directly
    rules = rules_loader.load_rules(RULES_YAML)
    detect_res = detection_engine.detect_query_regression(before_query, after_query, rules=rules)

    assert detect_res["is_regression"] is True
    assert detect_res["classification"] in ("CRITICAL", "HIGH", "CRITICAL_REGRESSION")
    assert detect_res["regression_score"] >= 70.0
    assert detect_res["plan_changed"] is True
    assert detect_res["index_lost"] is True

    # Step 4: Verify Dashboard reflects findings
    resp_dash = client.get("/api/dashboard")
    assert resp_dash.status_code == 200
    dash_data = resp_dash.get_json()
    assert dash_data["status"] == "success"
    assert "metrics" in dash_data
    assert dash_data["metrics"]["critical_regressions"] >= 1

    # Step 5: Submit review decision
    reg_id = 1
    resp_review = client.post("/query/QRY-004", data={
        "regression_id": str(reg_id),
        "action": "CONFIRM",
        "note": "E2E automated validation: Confirmed dropped index caused full scan latency."
    }, follow_redirects=True)
    assert resp_review.status_code == 200

    # Step 6: Verify review audit event is persisted
    reviews = snapshot_store.get_regression_reviews(reg_id, store_path=DETECTOR_DB)
    assert len(reviews) >= 1
    latest_review = reviews[-1]
    assert latest_review["new_status"] == "CONFIRMED"
    assert "E2E automated validation" in latest_review["note"]


def test_E2E02_dashboard_metrics_api_and_page(auth_reviewer_session):
    """
    E2E-02: Verifies that /api/dashboard returns all 12 key statistics,
    and /dashboard page renders the core success metric banner.
    """
    client = auth_reviewer_session

    # Test REST API
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    metrics = data["metrics"]

    # Verify all 12 required metrics exist and are well-formed
    required_keys = [
        "total_queries_analysed",
        "normal_count",
        "warning_count",
        "high_regressions",
        "critical_regressions",
        "regressions_detected_before_user_impact",
        "false_positives",
        "false_negatives",
        "precision_pct",
        "recall_pct",
        "f1_pct",
        "average_lead_time_min"
    ]
    for k in required_keys:
        assert k in metrics, f"Missing metric key '{k}' in /api/dashboard"
        assert isinstance(metrics[k], (int, float)), f"Metric '{k}' must be numeric"

    # Verify core success metric meets required benchmark (>90%)
    assert metrics["regressions_detected_before_user_impact"] >= 90.0
    assert metrics["average_lead_time_min"] >= 10.0

    # Test HTML page render
    page_resp = client.get("/dashboard")
    assert page_resp.status_code == 200
    page_text = page_resp.get_data(as_text=True)
    assert "Regressions Detected BEFORE User Impact" in page_text
    assert "Baseline Workaround" in page_text
    assert "20.0%" in page_text
    assert "Target Goal" in page_text
    assert "90.0%" in page_text
    assert "Interactive Demonstration Scenarios" in page_text


def test_E2E03_query_forensics_detail_api_12_sections(auth_reviewer_session):
    """
    E2E-03: Verifies that GET /api/regressions/<id> provides all 12 forensic sections
    A through L, visual comparison bars, and double-booking criticality context.
    """
    client = auth_reviewer_session

    # Fetch detail for regression #1
    resp = client.get("/api/regressions/1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"

    forensics = data["forensics"]
    # Verify sections A through L
    for letter in ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"]:
        sec_key = f"sec_{letter}"
        assert sec_key in forensics, f"Forensics missing section {sec_key}"

    # Section A: Query Info
    sec_a = forensics["sec_a"]
    assert "query_id" in sec_a
    assert "is_double_booking" in sec_a
    assert "business_criticality" in sec_a

    # Section B: Performance Comparison
    sec_b = forensics["sec_b"]
    assert "baseline_p95_ms" in sec_b
    assert "current_p95_ms" in sec_b
    assert "pct_change" in sec_b
    assert "severity" in sec_b

    # Section C: Execution Plan Comparison
    sec_c = forensics["sec_c"]
    assert "before_plan" in sec_c
    assert "after_plan" in sec_c
    assert "plan_diff_summary" in sec_c

    # Section K: Evidence
    sec_k = forensics["sec_k"]
    assert "evidence_strength" in sec_k
    assert "possible_cause" in sec_k

    # Section L: Recommendations
    sec_l = forensics["sec_l"]
    assert "recommendations" in sec_l
    assert len(sec_l["recommendations"]) >= 1

    # Visual comparisons
    assert "visuals" in forensics
    assert "execution_time" in forensics["visuals"]
    assert "plan_cost" in forensics["visuals"]
    assert "workload" in forensics["visuals"]


def test_E2E04_core_success_metric_timing_model():
    """
    E2E-04: Verifies the timing and user-impact calculation model.
    Confirms pre-impact lead time calculation and >90% detection before user impact.
    """
    # Test single query timing calculation
    record = {
        "query_id": "QRY-004",
        "query_type": "verify_slot_booked",
        "regression_label": "CRITICAL_REGRESSION",
        "severity": "CRITICAL"
    }
    res = timing_model.compute_user_impact_timing(record)

    assert res["detected_before_impact"] is True
    assert res["lead_time_minutes"] == 10.0  # (T+12) - (T+2)
    assert res["detection_delay_minutes"] == 2.0
    assert res["user_impact_delay_minutes"] == 12.0

    # Test aggregate benchmark metrics calculation
    metrics = timing_model.calculate_detection_before_impact_metrics()
    assert metrics["detected_before_impact_pct"] >= 90.0
    assert metrics["average_lead_time_min"] >= 10.0
    assert metrics["lead_time_p50_min"] >= 10.0
    assert metrics["target_pct"] == 90.0
    assert metrics["baseline_workaround_pct"] == 20.0


def test_E2E05_demo_scenarios_execution(auth_admin_session):
    """
    E2E-05: Verifies execution of all 3 selectable synthetic demo scenarios:
    - scenario_1: Healthy Normal Query -> NORMAL / OK
    - scenario_2: Critical Index Loss -> CRITICAL regression
    - scenario_3: Workload Surge -> WARNING / NORMAL (workload grace applied)
    """
    client = auth_admin_session

    # Scenario 1: Healthy normal query
    r1 = client.post("/api/demo/run-scenario", json={"scenario": "scenario_1"})
    assert r1.status_code == 200
    d1 = r1.get_json()
    assert d1["status"] == "success"
    assert d1["scenario_id"] == "scenario_1"
    assert d1["result"]["classification"] in ("OK", "NORMAL")
    assert d1["result"]["is_regression"] is False

    # Scenario 2: Critical Index Loss
    r2 = client.post("/api/demo/run-scenario", json={"scenario": "scenario_2"})
    assert r2.status_code == 200
    d2 = r2.get_json()
    assert d2["status"] == "success"
    assert d2["scenario_id"] == "scenario_2"
    assert d2["result"]["classification"] in ("CRITICAL", "CRITICAL_REGRESSION")
    assert d2["result"]["is_regression"] is True
    assert d2["result"]["plan_changed"] is True
    assert d2["result"]["index_lost"] is True

    # Scenario 3: Workload Surge
    r3 = client.post("/api/demo/run-scenario", json={"scenario": "scenario_3"})
    assert r3.status_code == 200
    d3 = r3.get_json()
    assert d3["status"] == "success"
    assert d3["scenario_id"] == "scenario_3"
    # Plan is identical, workload surged
    assert d3["result"]["classification"] in ("WARNING", "REGRESSION", "NORMAL", "MEDIUM", "OK")


def test_E2E06_safe_demo_reset(auth_admin_session):
    """
    E2E-06: Verifies safe demo reset functionality and audit logging.
    """
    client = auth_admin_session

    resp = client.post("/api/demo/reset")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "restored" in data["message"].lower()

    # Check that DEMO_DATA_RESET audit event was logged
    audit_events = snapshot_store.get_audit_events(limit=10, store_path=DETECTOR_DB)
    reset_events = [e for e in audit_events if e["action"] == "DEMO_DATA_RESET"]
    assert len(reset_events) >= 1
    assert reset_events[0]["status"] == "SUCCESS"


def test_E2E07_rbac_dashboard_and_review_workflow(auth_reviewer_session):
    """
    E2E-07: Verifies role-based access control and review workflow rules:
    - Unauthenticated requests are redirected to /login.
    - Application Reviewer can view dashboard, findings, and submit reviews.
    - Application Reviewer cannot modify detection rules.
    """
    # Unauthenticated client check
    with app.test_client() as unauth:
        unauth_resp = unauth.get("/dashboard")
        assert unauth_resp.status_code == 302
        assert "/login" in unauth_resp.headers["Location"]

    # Reviewer session permissions
    rev_client = auth_reviewer_session

    # Reviewer can view dashboard and regressions
    assert rev_client.get("/dashboard").status_code == 200
    assert rev_client.get("/regressions").status_code == 200
    assert rev_client.get("/query/QRY-004").status_code == 200

    # Reviewer can acknowledge regression
    rev_post = rev_client.post("/query/QRY-004", data={
        "regression_id": "1",
        "action": "ACKNOWLEDGE",
        "note": "Reviewer acknowledged investigating slot verification latency."
    }, follow_redirects=True)
    assert rev_post.status_code == 200

    # Reviewer CANNOT edit rules (DBA Admin only)
    rule_edit = rev_client.post("/rules", data={
        "rules_yaml": "rule_config_version: v9.9"
    }, follow_redirects=True)
    assert "Only DBA Admin can edit rules" in rule_edit.get_data(as_text=True)


def test_E2E08_regressions_facet_filtering_api(auth_reviewer_session):
    """
    E2E-08: Verifies regressions API and multi-facet filtering.
    """
    client = auth_reviewer_session

    # API all regressions
    r_all = client.get("/api/regressions")
    assert r_all.status_code == 200
    d_all = r_all.get_json()
    assert d_all["status"] == "success"
    assert d_all["total_count"] >= 1
    assert "regressions" in d_all

    # Filter by severity = CRITICAL
    r_crit = client.get("/api/regressions?severity=CRITICAL")
    assert r_crit.status_code == 200
    d_crit = r_crit.get_json()
    for reg in d_crit["regressions"]:
        assert reg["severity"] == "CRITICAL"

    # HTML facet rendering
    html_resp = client.get("/regressions?severity=CRITICAL&plan_changed=yes")
    assert html_resp.status_code == 200
    assert "Multi-Signal Facet Filters" in html_resp.get_data(as_text=True)


def test_E2E09_evaluation_page_and_api(auth_reviewer_session):
    """
    E2E-09: Verifies evaluation page and API containing core success metrics.
    """
    client = auth_reviewer_session

    # Test /api/evaluation
    resp_api = client.get("/api/evaluation")
    assert resp_api.status_code == 200
    data = resp_api.get_json()
    assert data["status"] == "success"
    assert "timing_metrics" in data
    assert data["timing_metrics"]["detected_before_impact_pct"] >= 90.0

    # Test /evaluation page
    resp_html = client.get("/evaluation")
    assert resp_html.status_code == 200
    html_text = resp_html.get_data(as_text=True)
    assert "Core Success Metric: Regressions Detected BEFORE User Impact" in html_text
    assert "Baseline Workaround" in html_text
    assert "Project Target Goal" in html_text
    assert "Measured Detector Result" in html_text


def test_E2E10_edge_cases_and_graceful_failures(auth_admin_session):
    """
    E2E-10: Verifies robust handling of non-existent IDs, invalid scenarios,
    and missing query parameters.
    """
    client = auth_admin_session

    # Non-existent regression detail API returns 404
    r_404 = client.get("/api/regressions/99999999")
    assert r_404.status_code == 404
    d_404 = r_404.get_json()
    assert d_404["status"] == "error"
    assert "not found" in d_404["message"].lower()

    # Invalid scenario execution returns 400
    r_bad_scen = client.post("/api/demo/run-scenario", json={"scenario": "scenario_nonexistent_xyz"})
    assert r_bad_scen.status_code == 400
    d_bad = r_bad_scen.get_json()
    assert d_bad["status"] == "error"

    # Missing scenario payload returns 400
    r_no_payload = client.post("/api/demo/run-scenario", json={})
    assert r_no_payload.status_code == 400

    # Non-existent query detail renders gracefully with empty states
    r_query_empty = client.get("/query/QRY-NONEXISTENT")
    assert r_query_empty.status_code == 200
    assert "QRY-NONEXISTENT" in r_query_empty.get_data(as_text=True)
