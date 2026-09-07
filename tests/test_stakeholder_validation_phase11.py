"""
test_stakeholder_validation_phase11.py
======================================
Comprehensive Test Suite for Phase 11: Short User / Stakeholder Validation.

Covers:
- test_SV01_validation_data_and_document_exist
- test_SV02_required_synthetic_personas_exist
- test_SV03_required_ten_tasks_exist
- test_SV04_validation_questionnaire_exists
- test_SV05_four_validation_scenarios_exist
- test_SV06_role_specific_validation_and_rbac
- test_SV07_synthetic_disclaimer_and_no_real_claims
- test_SV08_usability_metrics_bounds_and_honesty
- test_SV09_key_findings_and_improvement_actions
- test_SV10_web_api_stakeholder_validation_endpoint
- test_SV11_web_ui_validation_page_rendering
- test_SV12_evaluation_page_validation_summary_card
"""

import os
import sys
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import stakeholder_validation
from src.web.app import app


@pytest.fixture
def client():
    """Test client for web endpoints."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_SV01_validation_data_and_document_exist():
    """Verify that documentation and structured data file exist and are accessible."""
    doc_path = os.path.join(BASE_DIR, "docs", "stakeholder_validation.md")
    assert os.path.exists(doc_path), "docs/stakeholder_validation.md must exist"
    
    with open(doc_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert len(content) > 1000, "Documentation must contain substantial content"
    assert "Stakeholder & User Validation Report" in content

    payload = stakeholder_validation.get_stakeholder_validation_payload()
    assert isinstance(payload, dict)
    assert "personas" in payload
    assert "tasks" in payload
    assert "questionnaire" in payload
    assert "scenarios" in payload


def test_SV02_required_synthetic_personas_exist():
    """Verify that at least two synthetic personas exist, specifically DBA and Engineering Reviewer."""
    personas = stakeholder_validation.SYNTHETIC_PERSONAS
    assert len(personas) >= 2, "Must define at least two personas"

    role_titles = [p["role_title"].upper() for p in personas]
    assert any("DATABASE" in r or "ADMIN" in r for r in role_titles), "Must include Database / Platform Admin persona"
    assert any("ENGINEERING" in r or "REVIEWER" in r for r in role_titles), "Must include Engineering Reviewer persona"

    # Verify all persona names use synthetic labeling
    for p in personas:
        assert p["name"].startswith("Synthetic "), f"Persona name {p['name']} must explicitly start with 'Synthetic '"
        assert len(p["primary_goals"]) >= 3, "Each persona must have defined primary goals"
        assert len(p["key_concerns"]) >= 2, "Each persona must have defined key concerns"


def test_SV03_required_ten_tasks_exist():
    """Verify all 10 canonical evaluation tasks are defined with ratings and outcomes."""
    tasks = stakeholder_validation.VALIDATION_TASKS
    assert len(tasks) == 10, f"Expected exactly 10 validation tasks, got {len(tasks)}"

    task_ids = [t["task_id"] for t in tasks]
    for i in range(1, 11):
        expected_id = f"TASK-{i:02d}"
        assert expected_id in task_ids, f"Task {expected_id} must be present"

    for t in tasks:
        assert t["title"], "Task must have a title"
        assert t["expected_outcome"], "Task must define expected outcome"
        assert t["observed_outcome"], "Task must document observed outcome"
        assert 1 <= t["rating"] <= 5, "Rating must be on a 1-5 scale"
        assert "suggested_improvement" in t, "Task must include suggested improvement field"


def test_SV04_validation_questionnaire_exists():
    """Verify that the 10-question questionnaire exists with 1-5 rating scale."""
    questions = stakeholder_validation.VALIDATION_QUESTIONS
    assert len(questions) == 10, f"Expected 10 validation questions, got {len(questions)}"

    q_ids = [q["question_id"] for q in questions]
    for i in range(1, 11):
        expected_id = f"Q{i:02d}"
        assert expected_id in q_ids, f"Question {expected_id} must be present"

    for q in questions:
        assert q["prompt"], "Question prompt must not be empty"
        assert q["average_rating"] > 0, "Average rating must be positive"
        assert q["summary_assessment"], "Assessment must not be empty"


def test_SV05_four_validation_scenarios_exist():
    """Verify all four required canonical usability scenarios are evaluated."""
    scenarios = stakeholder_validation.VALIDATION_SCENARIOS
    assert len(scenarios) >= 4, "Must evaluate at least 4 scenarios"

    scen_ids = [s["scenario_id"] for s in scenarios]
    assert "SCENARIO_A" in scen_ids, "Scenario A (Critical index loss & plan degradation) must exist"
    assert "SCENARIO_B" in scen_ids, "Scenario B (Workload surge without plan degradation) must exist"
    assert "SCENARIO_C" in scen_ids, "Scenario C (False positive near threshold) must exist"
    assert "SCENARIO_D" in scen_ids, "Scenario D (False negative subtle regression) must exist"

    for sc in scenarios:
        assert sc["expected_user_behavior"], "Scenario must specify expected behavior"
        assert sc["observed_user_behavior"], "Scenario must document observed behavior"
        assert sc["validation_outcome"] == "SUCCESS", "Scenario validation must pass"


def _set_session(client, username: str = "admin_user", role: str = "dba_admin", user_id: str = "USR-001"):
    """Helper to simulate an authenticated user session on the test client."""
    with client.session_transaction() as sess:
        sess["username"] = username
        sess["role"] = role
        sess["user_id"] = user_id
        sess["display_name"] = f"Test User {username}"


def test_SV06_role_specific_validation_and_rbac(client):
    """Verify role-based permissions: Reviewer can submit reviews, but CANNOT modify administrator rules."""
    # 1. Login as reviewer
    _set_session(client, username="reviewer_user", role="release_engineer", user_id="USR-REV-02")

    # 2. Attempt to save rules as reviewer -> Must be 403 Forbidden
    resp = client.post("/api/rules", json={"rules": {"thresholds": {"time_regression_pct": 50.0}}})
    assert resp.status_code == 403, "Reviewer must receive 403 when attempting to modify admin rules"

    # 3. Login as DBA admin
    _set_session(client, username="admin_user", role="dba_admin", user_id="USR-DBA-01")

    # 4. DBA access to rules page is permitted
    resp_rules = client.get("/rules")
    assert resp_rules.status_code == 200, "DBA must be permitted to view rules"


def test_SV07_synthetic_disclaimer_and_no_real_claims():
    """Verify that documentation and data strictly disclaim real human research and contain zero fake human claims."""
    doc_path = os.path.join(BASE_DIR, "docs", "stakeholder_validation.md")
    with open(doc_path, "r", encoding="utf-8") as f:
        doc_content = f.read()

    # Must contain prominent synthetic disclaimers
    assert "synthetic" in doc_content.lower()
    assert "no real human" in doc_content.lower()
    assert "scenario-based" in doc_content.lower()

    # Must NOT fabricate real human names or clinical titles from previous unverified drafts
    assert "Dr. Stephen Thorne" not in doc_content, "Must NOT claim Dr. Stephen Thorne as a real human participant"
    assert "Maria Alvarez" not in doc_content, "Must NOT claim Maria Alvarez as a real human participant"
    assert "Dr. Radhika Patel" not in doc_content, "Must NOT claim Dr. Radhika Patel as a real human participant"

    # Verify module notice
    payload = stakeholder_validation.get_stakeholder_validation_payload()
    notice = payload["validation_metadata"]["compliance_notice"]
    assert "synthetic" in notice.lower()
    assert "no real human claims" in notice.lower()


def test_SV08_usability_metrics_bounds_and_honesty():
    """Verify usability measures are within valid bounds and honestly characterized as prototype results."""
    measures = stakeholder_validation.PROTOTYPE_USABILITY_MEASURES
    assert measures["statistical_significance_claim"] == "None (Qualitative prototype evaluation)"
    
    metrics = measures["metrics"]
    assert metrics["task_completion_rate_pct"] == 100.0
    assert 4.0 <= metrics["average_task_rating"] <= 5.0
    assert 4.0 <= metrics["evidence_understandability_rating"] <= 5.0
    assert metrics["workflow_completion_rate_pct"] == 100.0
    assert metrics["rbac_enforcement_pass_rate_pct"] == 100.0


def test_SV09_key_findings_and_improvement_actions():
    """Verify realistic prototype findings and structured improvement actions."""
    payload = stakeholder_validation.get_stakeholder_validation_payload()
    findings = payload["key_findings"]
    assert len(findings) >= 5, "Must include at least 5 key findings"

    actions = payload["improvement_actions"]
    assert len(actions) >= 4, "Must include at least 4 improvement actions"

    for a in actions:
        assert a["finding"]
        assert a["impact"]
        assert a["recommended_improvement"]
        assert a["priority"] in ("HIGH", "MEDIUM", "LOW")
        assert a["status"] in ("IMPLEMENTED", "CONFIGURED", "PLANNED")


def test_SV10_web_api_stakeholder_validation_endpoint(client):
    """Verify GET /api/stakeholder-validation returns 200 with full schema."""
    resp = client.get("/api/stakeholder-validation")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "validation_metadata" in data
    assert "personas" in data
    assert "tasks" in data
    assert "questionnaire" in data
    assert "scenarios" in data
    assert "usability_measures" in data
    assert "key_findings" in data
    assert "improvement_actions" in data
    assert len(data["tasks"]) == 10
    assert len(data["personas"]) == 3


def test_SV11_web_ui_validation_page_rendering(client):
    """Verify GET /validation renders 200 and displays all personas, tasks, and disclaimers."""
    # Login to access protected page
    _set_session(client, username="admin_user", role="dba_admin", user_id="USR-DBA-01")

    resp = client.get("/validation")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "Stakeholder & Usability Validation" in html
    assert "Synthetic DBA" in html
    assert "Synthetic Engineering Reviewer" in html
    assert "TASK-01" in html
    assert "TASK-10" in html
    assert "Research Integrity Notice" in html
    assert "Scenario-Based Prototype Evaluation" in html


def test_SV12_evaluation_page_validation_summary_card(client):
    """Verify GET /evaluation includes the Phase 11 summary card and link."""
    _set_session(client, username="admin_user", role="dba_admin", user_id="USR-DBA-01")

    resp = client.get("/evaluation")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "Stakeholder & Usability Validation (Phase 11)" in html
    assert "href=\"/validation\"" in html
    assert "10 Tasks (100% Completion)" in html
