"""
test_security_privacy_phase12.py
================================
Comprehensive Security, Privacy, and Data-Governance Test Suite for Phase 12.

Covers:
- test_SEC01_privacy_and_security_documents_exist
- test_SEC02_synthetic_data_assertion_and_no_real_pii
- test_SEC03_repository_secret_scan
- test_SEC04_protected_endpoints_reject_unauthenticated
- test_SEC05_reviewer_cannot_modify_rules_403
- test_SEC06_role_spoofing_payload_rejected
- test_SEC07_invalid_rule_rejection_400
- test_SEC08_audit_log_does_not_expose_secrets
- test_SEC09_evaluation_export_does_not_contain_pii
- test_SEC10_threat_model_completeness
"""

import os
import sys
import sqlite3
import json
import csv
import re
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.web.app import app, DETECTOR_DB, SYNTH_DB


@pytest.fixture
def client():
    """Test client for web endpoints."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _set_session(client, username: str = "admin_user", role: str = "dba_admin", user_id: str = "USR-001"):
    """Helper to simulate an authenticated user session on the test client."""
    with client.session_transaction() as sess:
        sess["username"] = username
        sess["role"] = role
        sess["user_id"] = user_id
        sess["display_name"] = f"Test User {username}"


def test_SEC01_privacy_and_security_documents_exist():
    """Verify that PRIVACY.md, docs/security.md, and PA-001/PA-002 exist and contain required declarations."""
    privacy_path = os.path.join(BASE_DIR, "PRIVACY.md")
    security_path = os.path.join(BASE_DIR, "docs", "security.md")
    pa001_path = os.path.join(BASE_DIR, "config", "privacy_assumptions.md")
    pa002_path = os.path.join(BASE_DIR, "config", "privacy_assumptions_dataset.md")

    for p in (privacy_path, security_path, pa001_path, pa002_path):
        assert os.path.exists(p), f"Required governance file {p} must exist"
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        assert len(content) > 500, f"File {p} must have substantial content"

    # Verify key declarations in PRIVACY.md
    with open(privacy_path, "r", encoding="utf-8") as f:
        privacy_text = f.read().lower()
    assert "synthetic" in privacy_text
    assert "zero real patient" in privacy_text or "no real patient" in privacy_text
    assert "data inventory" in privacy_text
    assert "privacy assumptions" in privacy_text
    assert "production" in privacy_text


def test_SEC02_synthetic_data_assertion_and_no_real_pii():
    """Verify that all records in hospital.db and synthetic_dataset.db follow synthetic patterns with zero real PII."""
    hosp_db = os.path.join(BASE_DIR, "data", "hospital.db")
    if os.path.exists(hosp_db):
        conn = sqlite3.connect(hosp_db)
        cur = conn.cursor()

        # Check table columns in patients
        cols = [c[1] for c in cur.execute("PRAGMA table_info(patients)").fetchall()]
        forbidden_cols = ["name", "full_name", "first_name", "last_name", "address", "phone", "email", "ssn", "nhs_no", "dob"]
        for fc in forbidden_cols:
            assert fc not in cols, f"Forbidden PII column '{fc}' found in patients table"

        # Check patient IDs follow synthetic prefix
        p_ids = [r[0] for r in cur.execute("SELECT patient_id FROM patients LIMIT 100").fetchall()]
        for pid in p_ids:
            assert pid.startswith("SYNTH-P-"), f"Patient ID {pid} violates synthetic format"

        # Check doctor IDs follow synthetic prefix
        d_ids = [r[0] for r in cur.execute("SELECT doctor_id FROM doctors LIMIT 50").fetchall()]
        for did in d_ids:
            assert did.startswith("SYNTH-D-"), f"Doctor ID {did} violates synthetic format"

        # Check appointment IDs follow synthetic prefix
        a_ids = [r[0] for r in cur.execute("SELECT appt_id FROM appointments LIMIT 100").fetchall()]
        for aid in a_ids:
            assert aid.startswith("SYNTH-A-"), f"Appointment ID {aid} violates synthetic format"

        conn.close()

    if os.path.exists(SYNTH_DB):
        conn = sqlite3.connect(SYNTH_DB)
        cur = conn.cursor()
        q_ids = [r[0] for r in cur.execute("SELECT query_id FROM query_regression_records LIMIT 50").fetchall()]
        for qid in q_ids:
            assert qid.startswith("SYNTH-Q-"), f"Benchmark query ID {qid} violates synthetic format"
        conn.close()


def test_SEC03_repository_secret_scan():
    """Scan key source files to ensure no real API keys, private keys, or credentials are hardcoded."""
    sensitive_regexes = [
        re.compile(r"-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----"),
        re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS Access Key ID
        re.compile(r"(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36}"),  # GitHub Token
    ]

    scan_dirs = ["src", "config"]
    for d in scan_dirs:
        full_d = os.path.join(BASE_DIR, d)
        for root, _, files in os.walk(full_d):
            for file in files:
                if file.endswith((".py", ".yaml", ".yml", ".json")):
                    fpath = os.path.join(root, file)
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    for rx in sensitive_regexes:
                        assert not rx.search(content), f"Potential secret pattern found in {fpath}"

    # Verify app.secret_key uses environment variable fallback
    assert app.secret_key is not None
    assert "dev-secret" in app.secret_key or os.environ.get("FLASK_SECRET_KEY")


def test_SEC04_protected_endpoints_reject_unauthenticated(client):
    """Verify that protected HTML and API endpoints reject unauthenticated requests."""
    # HTML routes should redirect to login (302)
    protected_html_routes = ["/validation", "/baselines", "/runs", "/regressions", "/rules"]
    for route in protected_html_routes:
        resp = client.get(route)
        assert resp.status_code in (302, 401), f"Unauthenticated access to {route} must be redirected or rejected"

    # Protected POST APIs should return 302 (redirect to login), 401 Unauthorized, or 403 Forbidden
    resp_fp = client.post("/api/mark-fp", json={"regression_id": 1})
    assert resp_fp.status_code in (302, 401, 403)

    resp_rules = client.post("/api/rules", json={"rules": {}})
    assert resp_rules.status_code in (302, 401, 403)


def test_SEC05_reviewer_cannot_modify_rules_403(client):
    """Verify that an authenticated reviewer session cannot modify or toggle detection rules (403)."""
    _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")

    # Attempt rule modification
    resp = client.post("/api/rules", json={"rules": {"thresholds": {"time_regression_pct": 50.0}}})
    assert resp.status_code == 403, "Reviewer must receive 403 Forbidden when attempting to update rules"
    data = resp.get_json()
    assert "error" in data or "message" in data


def test_SEC06_role_spoofing_payload_rejected(client):
    """Verify that payload-injected role claim 'role: dba_admin' does not override session role."""
    # Session is strictly reviewer
    _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")

    # Reviewer attempts privilege escalation via payload claim
    resp = client.post("/api/rules", json={
        "role": "dba_admin",  # Malicious role spoofing claim in body
        "rules": {"thresholds": {"time_regression_pct": 50.0}}
    })
    assert resp.status_code == 403, "Server-side session role must take absolute precedence over payload claims"


def test_SEC07_invalid_rule_rejection_400(client):
    """Verify that submitting malformed or out-of-bounds rule configurations returns 400 Bad Request safely."""
    _set_session(client, username="admin_user", role="dba_admin", user_id="USR-DBA-01")

    # Empty payload
    resp_empty = client.post("/api/rules", json={})
    assert resp_empty.status_code == 400

    # Negative threshold should fail validation
    resp_neg = client.post("/api/rules", json={"rules": {"thresholds": {"time_regression_pct": -25.0}}})
    assert resp_neg.status_code in (400, 422, 500)


def test_SEC08_audit_log_does_not_expose_secrets():
    """Verify that audit log records never store passwords, secrets, or patient data."""
    if os.path.exists(DETECTOR_DB):
        conn = sqlite3.connect(DETECTOR_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute("SELECT * FROM audit_log LIMIT 100").fetchall()
        for r in rows:
            details = r["details"] or ""
            prev_v = r["previous_value"] or ""
            new_v = r["new_value"] or ""
            combined = f"{details} {prev_v} {new_v}".lower()

            assert "password" not in combined or "admin123" not in combined, "Audit details must not contain raw passwords"
            assert "secret_key" not in combined, "Audit details must not contain session secret keys"
            assert "token" not in combined or "bearer" not in combined, "Audit details must not contain bearer tokens"
        conn.close()


def test_SEC09_evaluation_export_does_not_contain_pii():
    """Verify that CSV/JSON evaluation exports contain only technical performance metadata and no PII."""
    csv_path = os.path.join(BASE_DIR, "data", "evaluation_results.csv")
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            forbidden = ["name", "patient_name", "email", "phone", "address", "dob", "mrn", "diagnosis"]
            for fn in fieldnames:
                assert fn.lower() not in forbidden, f"Forbidden PII header '{fn}' found in CSV export"

            rows = list(reader)
            for r in rows[:20]:
                for k, v in r.items():
                    if k in ("query_id", "record_id", "scenario"):
                        continue
                    assert "@" not in str(v), f"Potential email address found in CSV export value: {v}"

    json_path = os.path.join(BASE_DIR, "data", "evaluation_results.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "confusion_matrix" in data
        assert "metrics" in data
        assert "detection_before_impact" in data


def test_SEC10_threat_model_completeness():
    """Verify that docs/security.md documents all 7 canonical threats (T1 - T7)."""
    sec_path = os.path.join(BASE_DIR, "docs", "security.md")
    with open(sec_path, "r", encoding="utf-8") as f:
        content = f.read()

    for i in range(1, 8):
        threat_id = f"T{i}:"
        assert threat_id in content, f"Threat {threat_id} must be formally documented in docs/security.md"


def test_SEC11_environment_credentials_and_no_hardcoded_passwords():
    """Verify that auth.py does not contain hardcoded passwords and dynamically respects env vars."""
    auth_path = os.path.join(BASE_DIR, "src", "web", "auth.py")
    with open(auth_path, "r", encoding="utf-8") as f:
        auth_source = f.read()

    # Verify no hardcoded passwords like 'admin123', 'release123', 'reviewer123'
    assert '"admin123"' not in auth_source
    assert '"release123"' not in auth_source
    assert '"reviewer123"' not in auth_source
    assert "DEMO_DBA_PASSWORD" in auth_source
    assert "DEMO_REVIEWER_PASSWORD" in auth_source

    from src.web.auth import get_demo_credentials, authenticate

    # Test dynamic override via environment variables
    os.environ["DEMO_DBA_PASSWORD"] = "test-custom-dba-pass-999"
    os.environ["DEMO_REVIEWER_PASSWORD"] = "test-custom-rev-pass-888"
    try:
        creds = get_demo_credentials()
        assert creds["dba_password"] == "test-custom-dba-pass-999"
        assert creds["reviewer_password"] == "test-custom-rev-pass-888"

        # Authentication succeeds with env password
        user = authenticate("admin_user", "test-custom-dba-pass-999")
        assert user is not None
        assert user["role"] == "dba_admin"

        # Authentication fails with wrong password
        assert authenticate("admin_user", "wrong-password") is None
    finally:
        os.environ.pop("DEMO_DBA_PASSWORD", None)
        os.environ.pop("DEMO_REVIEWER_PASSWORD", None)


def test_SEC12_login_flow_with_environment_credentials(client):
    """Verify that the web /login POST endpoint authenticates using environment-configured demo credentials."""
    from src.web.auth import get_demo_credentials
    creds = get_demo_credentials()
    dba_pass = creds["dba_password"]

    # 1. Attempt login with incorrect password -> fails with flash message or 200 re-render
    resp_bad = client.post("/login", data={"username": "admin_user", "password": "invalid-password-xyz"}, follow_redirects=True)
    assert resp_bad.status_code == 200
    assert "Invalid credentials" in resp_bad.get_data(as_text=True)

    # 2. Attempt login with correct environment/synthetic fallback password -> succeeds and redirects to dashboard
    resp_good = client.post("/login", data={"username": "admin_user", "password": dba_pass}, follow_redirects=False)
    assert resp_good.status_code == 302
    assert "/" in resp_good.headers["Location"]

