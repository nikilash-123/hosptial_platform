"""
test_demo_phase13.py
====================
Test suite verifying Phase 13: Three-Minute Demo Video Preparation.

Covers:
- test_DEMO01_documentation_artifacts_exist_and_complete
- test_DEMO02_demo_scenario_configuration_and_execution
- test_DEMO03_demo_reset_functionality_and_endpoint
- test_DEMO04_evaluation_metrics_exact_values
- test_DEMO05_forensic_query_details_for_demo_target
"""

import os
import sys
import json
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.web.app import app, DEMO_SCENARIOS, _execute_demo_scenario, _reset_demo_data
from src.core import snapshot_store


@pytest.fixture
def client():
    """Provides a fresh Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_DEMO01_documentation_artifacts_exist_and_complete():
    """Verifies that demo video guide and 3-minute script exist with required sections."""
    guide_path = os.path.join(BASE_DIR, "docs", "demo_video_guide.md")
    script_path = os.path.join(BASE_DIR, "docs", "demo_script_3min.md")

    assert os.path.isfile(guide_path), f"Missing {guide_path}"
    assert os.path.isfile(script_path), f"Missing {script_path}"

    with open(guide_path, "r", encoding="utf-8") as f:
        guide_content = f.read()

    # Verify key sections in the video guide
    required_guide_phrases = [
        "Three-Minute Demonstration Video Guide",
        "Mandatory Demo Claims Policy",
        "Synthetic experiment",
        "Simulated user impact",
        "scenario_2",
        "QRY-004",
        "WHAT CHANGED?",
        "96.8%",
        "90.0%",
        "13.1",
        "Recording Checklist",
        "Deterministic Backup Demonstration Path"
    ]
    for phrase in required_guide_phrases:
        assert phrase in guide_content, f"Guide missing expected phrase: {phrase}"

    with open(script_path, "r", encoding="utf-8") as f:
        script_content = f.read()

    # Verify structured teleprompter format in script
    required_script_phrases = [
        "[0:00 – 0:20] 1. PROBLEM",
        "[0:20 – 0:45] 2. BASELINE",
        "[0:45 – 1:15] 3. FIND THE REGRESSION",
        "[1:15 – 1:45] 4. WHY DID IT REGRESS?",
        "[1:45 – 2:05] 5. EVIDENCE + REVIEW",
        "[2:05 – 2:30] 6. MEASURABLE RESULT",
        "[2:30 – 2:45] 7. ERROR ANALYSIS",
        "[2:45 – 3:00] 8. PRIVACY + CONCLUSION",
        "TIME:", "SCREEN:", "ACTION:", "NARRATION:"
    ]
    for phrase in required_script_phrases:
        assert phrase in script_content, f"Script missing expected phrase: {phrase}"


def test_DEMO02_demo_scenario_configuration_and_execution():
    """Verifies that canonical demo scenario (QRY-004) executes and returns expected CRITICAL severity."""
    assert "scenario_2" in DEMO_SCENARIOS
    s2 = DEMO_SCENARIOS["scenario_2"]
    assert s2["query_id"] == "QRY-004"
    assert s2["expected_severity"] == "CRITICAL"
    assert "verify_slot_booked" in s2["query_type"]

    # Execute scenario_2 within request context
    with app.test_request_context():
        res = _execute_demo_scenario("scenario_2")
    assert res["scenario_id"] == "scenario_2"
    assert res["result"]["classification"] in ("CRITICAL", "CRITICAL_REGRESSION")
    assert res["result"]["is_regression"] is True
    assert res["result"]["plan_changed"] is True
    assert res["result"]["index_lost"] is True


def test_DEMO03_demo_reset_functionality_and_endpoint(client):
    """Verifies that demo dataset reset works both via internal function and REST API."""
    # Internal reset function within request context
    with app.test_request_context():
        direct_res = _reset_demo_data()
    assert direct_res["status"] == "success"

    # API endpoint POST /api/demo/reset
    api_res = client.post("/api/demo/reset")
    assert api_res.status_code == 200
    json_data = api_res.get_json()
    assert json_data["status"] == "success"


def test_DEMO04_evaluation_metrics_exact_values():
    """Verifies that empirical benchmark evaluation values match ground-truth audit numbers."""
    exp_path = os.path.join(BASE_DIR, "data", "experiment_results.json")
    assert os.path.isfile(exp_path), f"Missing {exp_path}"

    with open(exp_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["total_records"] == 814

    cm = data["confusion_matrix"]
    assert cm["true_positives"] == 243
    assert cm["false_positives"] == 157
    assert cm["true_negatives"] == 406
    assert cm["false_negatives"] == 8

    csm = data["core_success_metric"]
    assert csm["measured_detector_pct"] == 96.8
    assert csm["project_target_pct"] == 90.0
    assert csm["baseline_workaround_pct"] == 0.0
    assert csm["lead_time_minutes"]["average"] == 13.1
    assert csm["lead_time_minutes"]["median"] == 16.0

    ea = data["evidence_audit"]
    assert ea["high_priority_evidence_completeness_rate_pct"] == 100.0
    assert ea["total_high_priority_records"] == 398
    assert ea["complete_records"] == 398


def test_DEMO05_forensic_query_details_for_demo_target():
    """Verifies that QRY-004 contains full forensic plan comparison and latency delta."""
    regs = snapshot_store.get_regressions()
    q4_regs = [r for r in regs if r["query_id"] == "QRY-004"]
    assert len(q4_regs) > 0, "QRY-004 must be present in regression store"

    reg = q4_regs[0]
    assert reg["severity"] == "CRITICAL"
    assert reg["plan_changed"] == 1
    assert reg["index_lost"] == 1

    evidence = json.loads(reg["evidence"])
    assert "timing" in evidence
    assert "plan" in evidence
    assert "index" in evidence
    assert evidence["plan"]["plan_changed"] is True
    assert evidence["timing"]["pct_change"] > 500.0  # Latency surged significantly
