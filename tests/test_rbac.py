"""
test_rbac.py
============
Comprehensive Role-Based Access Control (RBAC) and Audit Workflow Test Suite
for Phase 8 of Hospital Appointment Platform Query Regression Detector.

Covers:
1. Two Enforced Roles:
   - DATABASE / PLATFORM ADMIN (dba_admin, admin_user)
   - APPLICATION / ENGINEERING REVIEWER (release_engineer, reviewer_user)
2. 15 Required Test Cases:
   - RBAC-01: Admin can view detection rules
   - RBAC-02: Admin can modify detection rules and weights
   - RBAC-03: Reviewer can view detection rules
   - RBAC-04: Reviewer cannot modify detection rules (403 Forbidden)
   - RBAC-05: Admin can view configuration history
   - RBAC-06: Reviewer cannot modify or access configuration history (403 Forbidden)
   - RBAC-07: Admin can review regression (status change, note, audit recorded)
   - RBAC-08: Reviewer can review regression (acknowledge, confirm, mark FP, note)
   - RBAC-09: Unauthenticated requests rejected with 401 Unauthorized
   - RBAC-10: Payload role escalation prevented (server enforces session role)
   - RBAC-11: Frontend spoofing prevented (cannot bypass backend checks)
   - RBAC-12: Audit event generated on rule configuration change
   - RBAC-13: Audit event generated on regression review
   - RBAC-14: Audit event generated on false-positive marking
   - RBAC-15: Audit event generated on regression confirmation
3. 7 Security Edge Cases:
   - SEC-01: Protected endpoint without authenticated session returns 401
   - SEC-02: Reviewer session attempts PUT /api/rules -> returns 403
   - SEC-03: Reviewer session sends payload claim {"role": "DATABASE_PLATFORM_ADMIN"} -> returns 403
   - SEC-04: Corrupted or unknown role session receives 403 on protected resources
   - SEC-05: Malformed session data handled safely without uncaught 500 crash
   - SEC-06: Admin modifies invalid rule value -> 400 validation error, no file corruption
   - SEC-07: Reviewer session calls GET /api/config/history -> returns 403
"""

import os
import sys
import copy
import pytest
from typing import Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import snapshot_store, rules_loader
from src.web.app import app, DETECTOR_DB, RULES_YAML


@pytest.fixture
def client():
    """Provides a fresh Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def clean_rules():
    """Loads a pristine copy of rules.yaml."""
    return rules_loader.load_rules(RULES_YAML)


@pytest.fixture
def sample_regression():
    """Seeds a baseline, run, and regression in DETECTOR_DB for testing reviews."""
    snapshot_store.init_store(DETECTOR_DB)
    snap_id = snapshot_store.save_snapshot(
        release_tag="v1.0-test-base",
        snapshot_type="BASELINE",
        db_size_bytes=10000,
        row_counts={"appointments": 100},
        store_path=DETECTOR_DB,
    )
    run_id = snapshot_store.save_snapshot(
        release_tag="v1.1-test-run",
        snapshot_type="RUN",
        db_size_bytes=12000,
        row_counts={"appointments": 100},
        store_path=DETECTOR_DB,
    )
    reg_id = snapshot_store.save_regression(
        baseline_snap_id=snap_id,
        run_snap_id=run_id,
        query_id="QRY-RBAC-01",
        query_label="Doctor schedule lookup test",
        severity="HIGH",
        regression_types=["TIME_REGRESSION"],
        delta_ms_p95=120.5,
        pct_change=95.0,
        plan_changed=False,
        index_lost=False,
        has_new_scan=False,
        evidence={"summary": "Sample regression for RBAC audit"},
        store_path=DETECTOR_DB,
    )
    return reg_id


def _set_session(client, username: str, role: str, user_id: str = "USR-001"):
    """Helper to simulate an active session on the test client."""
    with client.session_transaction() as sess:
        sess["username"] = username
        sess["role"] = role
        sess["user_id"] = user_id
        sess["display_name"] = f"Test User {username}"


# ==============================================================================
# SECTION 1: 15 RBAC & Governance Test Cases
# ==============================================================================

def test_RBAC01_admin_can_view_rules(client):
    """RBAC-01: Admin can view detection rules."""
    _set_session(client, username="admin_user", role="dba_admin", user_id="USR-DBA-02")
    res = client.get("/api/rules")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "rules" in data
    assert "thresholds" in data["rules"]
    assert "version" in data


def test_RBAC02_admin_can_modify_rules(client, clean_rules):
    """RBAC-02: Admin can modify detection rules and weights."""
    with open(RULES_YAML, "r", encoding="utf-8") as f:
        orig = f.read()

    try:
        _set_session(client, username="admin_user", role="dba_admin", user_id="USR-DBA-02")
        payload = copy.deepcopy(clean_rules)
        payload["thresholds"]["time_regression_pct"] = 33.0

        res = client.post("/api/rules", json={"rules": payload})
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "success"
        assert "version" in data
    finally:
        with open(RULES_YAML, "w", encoding="utf-8") as f:
            f.write(orig)


def test_RBAC03_reviewer_can_view_rules(client):
    """RBAC-03: Reviewer can view detection rules."""
    _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")
    res = client.get("/api/rules")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "rules" in data
    assert "thresholds" in data["rules"]


def test_RBAC04_reviewer_cannot_modify_rules(client, clean_rules):
    """RBAC-04: Reviewer cannot modify detection rules (must return 403)."""
    with open(RULES_YAML, "r", encoding="utf-8") as f:
        orig = f.read()

    try:
        _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")
        payload = copy.deepcopy(clean_rules)
        payload["thresholds"]["time_regression_pct"] = 45.0

        res = client.post("/api/rules", json={"rules": payload})
        assert res.status_code == 403
        data = res.get_json()
        assert data["status"] == "error"
        assert "Only DBA Admin" in data["message"] or "Forbidden" in data["message"]
    finally:
        with open(RULES_YAML, "w", encoding="utf-8") as f:
            f.write(orig)


def test_RBAC05_admin_can_view_configuration_history(client):
    """RBAC-05: Admin can view configuration history."""
    _set_session(client, username="admin_user", role="dba_admin", user_id="USR-DBA-02")
    res = client.get("/api/config/history")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "history" in data
    assert isinstance(data["history"], list)


def test_RBAC06_reviewer_cannot_modify_or_access_config_history(client):
    """RBAC-06: Reviewer cannot modify or access configuration history (403)."""
    _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")

    # Read access prohibited for reviewer
    res_get = client.get("/api/config/history")
    assert res_get.status_code == 403

    # Mutation prohibited
    res_post = client.post("/api/config/history", json={"action": "DELETE"})
    assert res_post.status_code == 403

    res_put = client.put("/api/config/history", json={"action": "OVERWRITE"})
    assert res_put.status_code == 403

    res_del = client.delete("/api/config/history")
    assert res_del.status_code == 403


def test_RBAC07_admin_can_review_regression(client, sample_regression):
    """RBAC-07: Admin can review regression, update status, and record audit."""
    _set_session(client, username="admin_user", role="dba_admin", user_id="USR-DBA-02")
    res = client.post(f"/api/regressions/{sample_regression}/review", json={
        "action": "CONFIRM",
        "note": "Confirmed by DBA Platform Admin"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["new_status"] == "CONFIRMED"

    # Verify review record
    reviews = snapshot_store.get_regression_reviews(sample_regression, store_path=DETECTOR_DB)
    assert len(reviews) >= 1
    assert reviews[0]["reviewer"] == "admin_user"
    assert reviews[0]["role"] == "dba_admin"
    assert reviews[0]["action"] == "CONFIRM"
    assert reviews[0]["new_status"] == "CONFIRMED"


def test_RBAC08_reviewer_can_review_regression(client, sample_regression):
    """RBAC-08: Reviewer can review regression (acknowledge, confirm, mark FP, add notes)."""
    _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")

    # Acknowledge
    res_ack = client.post(f"/api/regressions/{sample_regression}/review", json={
        "action": "ACKNOWLEDGE",
        "note": "Investigating slot availability query"
    })
    assert res_ack.status_code == 200
    assert res_ack.get_json()["new_status"] == "UNDER_REVIEW"

    # Confirm
    res_conf = client.post(f"/api/regressions/{sample_regression}/confirm", json={
        "note": "Confirmed slot availability regression"
    })
    assert res_conf.status_code == 200
    assert res_conf.get_json()["new_status"] == "CONFIRMED"

    # Mark False Positive
    res_fp = client.post(f"/api/regressions/{sample_regression}/false-positive", json={
        "note": "Intentional full scan due to small doctor table"
    })
    assert res_fp.status_code == 200
    assert res_fp.get_json()["new_status"] == "FALSE_POSITIVE"


def test_RBAC09_unauthenticated_rejected_401(client, sample_regression):
    """RBAC-09: Unauthenticated requests to protected endpoints return 401 Unauthorized."""
    # Protected config history
    res_hist = client.get("/api/config/history")
    assert res_hist.status_code == 401
    assert res_hist.get_json()["error"] in ("Unauthorized", "Authentication required")

    # Protected review API
    res_rev = client.post(f"/api/regressions/{sample_regression}/review", json={"action": "CONFIRM"})
    assert res_rev.status_code == 401

    # Protected audit log
    res_audit = client.get("/api/audit-log")
    assert res_audit.status_code == 401


def test_RBAC10_payload_role_escalation_prevented(client, clean_rules):
    """RBAC-10: Payload role escalation prevented. Server uses session role, ignoring body role claims."""
    with open(RULES_YAML, "r", encoding="utf-8") as f:
        orig = f.read()

    try:
        # Session is reviewer
        _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")

        # Client attempts to spoof role in JSON payload
        spoofed_payload = {
            "role": "dba_admin",
            "username": "admin_impersonator",
            "rules": clean_rules
        }

        res = client.post("/api/rules", json=spoofed_payload)
        # Server MUST reject with 403 Forbidden because active session is release_engineer
        assert res.status_code == 403
        data = res.get_json()
        assert data["status"] == "error"
    finally:
        with open(RULES_YAML, "w", encoding="utf-8") as f:
            f.write(orig)


def test_RBAC11_frontend_spoofing_prevented(client, clean_rules):
    """RBAC-11: Frontend spoofing via custom headers cannot bypass session validation."""
    with open(RULES_YAML, "r", encoding="utf-8") as f:
        orig = f.read()

    try:
        # Reviewer session with spoofed HTTP headers
        _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")
        headers = {
            "X-User-Role": "dba_admin",
            "X-User-Id": "USR-DBA-01",
            "X-Admin": "true"
        }

        res = client.post("/api/rules", json={"rules": clean_rules}, headers=headers)
        assert res.status_code == 403
    finally:
        with open(RULES_YAML, "w", encoding="utf-8") as f:
            f.write(orig)


def test_RBAC12_audit_event_on_config_change(client, clean_rules):
    """RBAC-12: Audit event generated on rule configuration change."""
    with open(RULES_YAML, "r", encoding="utf-8") as f:
        orig = f.read()

    try:
        _set_session(client, username="admin_user", role="dba_admin", user_id="USR-DBA-02")
        payload = copy.deepcopy(clean_rules)
        payload["thresholds"]["time_regression_pct"] = 38.5

        res = client.post("/api/rules", json={"rules": payload})
        assert res.status_code == 200

        # Check audit log in DB
        events = snapshot_store.get_audit_events(action="RULE_UPDATE", store_path=DETECTOR_DB)
        assert len(events) >= 1
        latest = events[0]
        assert latest["user_id"] == "admin_user"
        assert latest["role"] == "dba_admin"
        assert latest["resource_type"] in ("config_rules", "CONFIGURATION")
        assert latest["status"] == "SUCCESS"
    finally:
        with open(RULES_YAML, "w", encoding="utf-8") as f:
            f.write(orig)


def test_RBAC13_audit_event_on_regression_review(client, sample_regression):
    """RBAC-13: Audit event generated on regression review."""
    _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")
    res = client.post(f"/api/regressions/{sample_regression}/review", json={
        "action": "ACKNOWLEDGE",
        "note": "Investigating slot verification lock contention"
    })
    assert res.status_code == 200

    events = snapshot_store.get_audit_events(action="REGRESSION_REVIEW", store_path=DETECTOR_DB)
    matching = [e for e in events if e["resource_id"] == str(sample_regression)]
    assert len(matching) >= 1
    ev = matching[0]
    assert ev["user_id"] == "reviewer_user"
    assert ev["role"] == "release_engineer"
    assert ev["new_value"] == "UNDER_REVIEW"


def test_RBAC14_audit_event_on_false_positive(client, sample_regression):
    """RBAC-14: Audit event generated on false-positive marking."""
    _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")
    res = client.post(f"/api/regressions/{sample_regression}/false-positive", json={
        "note": "Acceptable variance in staging environment"
    })
    assert res.status_code == 200

    events = snapshot_store.get_audit_events(action="REGRESSION_FALSE_POSITIVE", store_path=DETECTOR_DB)
    matching = [e for e in events if e["resource_id"] == str(sample_regression)]
    assert len(matching) >= 1
    assert matching[0]["new_value"] == "FALSE_POSITIVE"


def test_RBAC15_audit_event_on_confirmation(client, sample_regression):
    """RBAC-15: Audit event generated on regression confirmation."""
    _set_session(client, username="admin_user", role="dba_admin", user_id="USR-DBA-02")
    res = client.post(f"/api/regressions/{sample_regression}/confirm", json={
        "note": "Blocking release due to missing doctor index"
    })
    assert res.status_code == 200

    events = snapshot_store.get_audit_events(action="REGRESSION_CONFIRMED", store_path=DETECTOR_DB)
    matching = [e for e in events if e["resource_id"] == str(sample_regression)]
    assert len(matching) >= 1
    assert matching[0]["new_value"] == "CONFIRMED"


# ==============================================================================
# SECTION 2: 7 Security Edge Cases
# ==============================================================================

def test_SEC01_no_session_on_protected_endpoint_returns_401(client):
    """SEC-01: Protected endpoint without authenticated session returns 401."""
    res = client.get("/api/config/history")
    assert res.status_code == 401
    data = res.get_json()
    assert data["error"] in ("Unauthorized", "Authentication required")


def test_SEC02_reviewer_session_attempts_put_api_rules_returns_403(client, clean_rules):
    """SEC-02: Reviewer session attempts PUT /api/rules -> returns 403."""
    _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")
    res = client.put("/api/rules", json={"rules": clean_rules})
    assert res.status_code == 403
    assert res.get_json()["status"] == "error"


def test_SEC03_reviewer_session_spoofs_admin_in_payload_returns_403(client, clean_rules):
    """SEC-03: Reviewer session sends payload claim {'role': 'DATABASE_PLATFORM_ADMIN'} -> returns 403."""
    _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")
    res = client.post("/api/rules", json={
        "role": "DATABASE_PLATFORM_ADMIN",
        "rules": clean_rules
    })
    assert res.status_code == 403
    assert res.get_json()["status"] == "error"


def test_SEC04_unknown_role_session_returns_403(client, clean_rules):
    """SEC-04: Corrupted or unknown role session receives 403 on protected resources."""
    _set_session(client, username="intruder", role="anonymous_guest", user_id="USR-UNKNOWN")
    res = client.post("/api/rules", json={"rules": clean_rules})
    assert res.status_code == 403

    res_hist = client.get("/api/config/history")
    assert res_hist.status_code == 403


def test_SEC05_malformed_session_data_handled_safely(client, clean_rules):
    """SEC-05: Malformed session data (None or numeric role) handled safely without 500 crash."""
    with client.session_transaction() as sess:
        sess["username"] = None
        sess["role"] = 12345

    res = client.post("/api/rules", json={"rules": clean_rules})
    # Should safely return 401 or 403, never 500 Internal Server Error
    assert res.status_code in (401, 403)


def test_SEC06_admin_modifies_invalid_rule_value_returns_400_no_corruption(client, clean_rules):
    """SEC-06: Admin modifies invalid rule value -> 400 validation error, no file corruption."""
    with open(RULES_YAML, "r", encoding="utf-8") as f:
        orig = f.read()

    try:
        _set_session(client, username="admin_user", role="dba_admin", user_id="USR-DBA-02")
        bad_payload = copy.deepcopy(clean_rules)
        bad_payload["thresholds"]["time_regression_pct"] = -99.0

        res = client.post("/api/rules", json={"rules": bad_payload})
        assert res.status_code == 400
        data = res.get_json()
        assert data["error_type"] == "ValidationError"

        # Verify rules file is uncorrupted and still parses
        reloaded = rules_loader.load_rules(RULES_YAML)
        assert reloaded["thresholds"]["time_regression_pct"] > 0
    finally:
        with open(RULES_YAML, "w", encoding="utf-8") as f:
            f.write(orig)


def test_SEC07_reviewer_session_calls_get_config_history_returns_403(client):
    """SEC-07: Reviewer session calls GET /api/config/history -> returns 403."""
    _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")
    res = client.get("/api/config/history")
    assert res.status_code == 403
    data = res.get_json()
    assert data["status"] == "error"
    assert "DBA Admin" in data["message"] or "Admin" in data["message"]
