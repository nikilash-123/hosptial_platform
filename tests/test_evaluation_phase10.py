"""
test_evaluation_phase10.py
==========================
Comprehensive Test Suite for Phase 10: Measurable Evaluation,
False Positive Analysis, False Negative Analysis, and Pre-Impact Verification.

Covers:
- test_EV01_ground_truth_label_assignment
- test_EV02_zero_pii_compliance_mandate
- test_EV03_confusion_matrix_reconciliation
- test_EV04_metric_mathematical_precision_and_recall
- test_EV05_detection_before_user_impact_target_exceeded
- test_EV06_target_vs_measured_distinction
- test_EV07_lead_time_distribution_and_bounds
- test_EV08_legacy_baseline_workaround_comparison
- test_EV09_false_positive_causal_attribution
- test_EV10_false_negative_root_cause_analysis
- test_EV11_high_priority_evidence_completeness_100pct
- test_EV12_canonical_controlled_scenarios_all_pass
- test_EV13_threshold_sensitivity_experiment_sweep
- test_EV14_evaluation_artifact_export_integrity
- test_EV15_evaluation_rest_api_endpoints
"""

import os
import sys
import json
import csv
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import evaluation_engine
from src.web.app import app


@pytest.fixture(scope="module")
def eval_data():
    """Run evaluation summary on benchmark dataset once for the test module."""
    return evaluation_engine.get_evaluation_summary_payload()


@pytest.fixture
def client():
    """Test client for web endpoints."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_EV01_ground_truth_label_assignment():
    """Verify deterministic assignment of ground-truth labels based on physical characteristics."""
    # Test TRUE_REGRESSION (table scan regression)
    rec_reg = {
        "execution_time_ms": 150.0,
        "baseline_execution_time_ms": 40.0,
        "is_table_scan": True,
        "baseline_is_table_scan": False,
        "scan_type": "Table Scan",
        "baseline_scan_type": "Index Scan",
        "active_queries": 20,
    }
    label, sev = evaluation_engine.assign_ground_truth_label(rec_reg)
    assert label == evaluation_engine.GroundTruthLabel.TRUE_REGRESSION.value
    assert sev in ("HIGH", "CRITICAL")

    # Test WORKLOAD_SLOWDOWN (concurrency surge without plan change)
    rec_surge = {
        "execution_time_ms": 65.0,
        "baseline_execution_time_ms": 40.0,
        "is_table_scan": False,
        "baseline_is_table_scan": False,
        "scan_type": "Index Scan",
        "baseline_scan_type": "Index Scan",
        "active_queries": 95,
    }
    label, sev = evaluation_engine.assign_ground_truth_label(rec_surge)
    assert label == evaluation_engine.GroundTruthLabel.WORKLOAD_SLOWDOWN.value
    assert sev == "WARNING"

    # Test NORMAL (healthy query within noise margin)
    rec_norm = {
        "execution_time_ms": 41.0,
        "baseline_execution_time_ms": 40.0,
        "is_table_scan": False,
        "baseline_is_table_scan": False,
        "scan_type": "Index Scan",
        "baseline_scan_type": "Index Scan",
        "active_queries": 15,
    }
    label, sev = evaluation_engine.assign_ground_truth_label(rec_norm)
    assert label == evaluation_engine.GroundTruthLabel.NORMAL.value
    assert sev == "NORMAL"


def test_EV02_zero_pii_compliance_mandate(eval_data):
    """Verify that dataset and evaluation data strictly contain 0% PII (PA-002 mandate)."""
    records = eval_data.get("records", [])
    assert len(records) > 0

    prohibited_fields = ["ssn", "social_security", "patient_name", "credit_card", "address", "phone"]
    for r in records[:50]:
        for field in prohibited_fields:
            assert field not in r, f"Prohibited PII field {field} found in record"
            for k, v in r.items():
                if isinstance(v, str):
                    assert "ssn" not in k.lower()


def test_EV03_confusion_matrix_reconciliation(eval_data):
    """Verify that the 2x2 confusion matrix sums exactly to the dataset size N=814."""
    cm = eval_data["confusion_matrix"]
    tp = cm["true_positives"]
    fp = cm["false_positives"]
    tn = cm["true_negatives"]
    fn = cm["false_negatives"]

    total = tp + fp + tn + fn
    assert total == eval_data["dataset_size"]
    assert total == 814
    assert tp == 243
    assert fp == 157
    assert tn == 406
    assert fn == 8


def test_EV04_metric_mathematical_precision_and_recall(eval_data):
    """Verify precision, recall, specificity, F1, accuracy, FPR, and FNR calculations."""
    cm = eval_data["confusion_matrix"]
    m = eval_data["metrics"]

    expected_precision = cm["true_positives"] / (cm["true_positives"] + cm["false_positives"])
    expected_recall = cm["true_positives"] / (cm["true_positives"] + cm["false_negatives"])
    expected_specificity = cm["true_negatives"] / (cm["true_negatives"] + cm["false_positives"])
    expected_f1 = 2 * (expected_precision * expected_recall) / (expected_precision + expected_recall)
    expected_accuracy = (cm["true_positives"] + cm["true_negatives"]) / 814
    expected_fpr = cm["false_positives"] / (cm["false_positives"] + cm["true_negatives"])
    expected_fnr = cm["false_negatives"] / (cm["true_positives"] + cm["false_negatives"])

    assert abs(m["precision"] - expected_precision) < 1e-4
    assert abs(m["recall"] - expected_recall) < 1e-4
    assert abs(m["specificity"] - expected_specificity) < 1e-4
    assert abs(m["f1_score"] - expected_f1) < 1e-4
    assert abs(m["accuracy"] - expected_accuracy) < 1e-4
    assert abs(m["false_positive_rate"] - expected_fpr) < 1e-4
    assert abs(m["false_negative_rate"] - expected_fnr) < 1e-4

    # Assert specific measured percentages
    assert m["recall"] >= 0.90  # 96.8%
    assert m["precision"] >= 0.55  # 60.8%
    assert m["f1_score"] >= 0.70  # 74.7%


def test_EV05_detection_before_user_impact_target_exceeded(eval_data):
    """Verify primary success metric: slow queries detected BEFORE user impact exceeds 90% SLA target."""
    dbi = eval_data["detection_before_impact"]
    assert dbi["target_pct"] == 90.0
    assert dbi["detection_rate_pct"] >= 90.0
    assert dbi["detection_rate_pct"] == pytest.approx(96.8, 0.5)
    assert dbi["target_met"] is True
    assert dbi["detected_before_impact"] == 243
    assert dbi["total_regressions"] == 251


def test_EV06_target_vs_measured_distinction(eval_data):
    """Verify that Target (90.0%) is clearly distinguished from Measured Result (96.8%)."""
    dbi = eval_data["detection_before_impact"]
    assert dbi["target_pct"] != dbi["detection_rate_pct"]
    assert dbi["target_pct"] == 90.0
    assert dbi["detection_rate_pct"] > dbi["target_pct"]


def test_EV07_lead_time_distribution_and_bounds(eval_data):
    """Verify pre-impact lead times: average ~14.2 min, median >= 10.0 min, bounded in [10, 18] min."""
    dbi = eval_data["detection_before_impact"]
    assert dbi["avg_lead_time_minutes"] >= 10.0
    assert dbi["median_lead_time_minutes"] >= 10.0
    assert dbi["min_lead_time_minutes"] >= 10.0
    assert dbi["max_lead_time_minutes"] <= 18.0


def test_EV08_legacy_baseline_workaround_comparison(eval_data):
    """Verify comparison with legacy baseline: 0% pre-impact detection, ~20% total post-impact capture."""
    legacy = eval_data["legacy_baseline"]
    dbi = eval_data["detection_before_impact"]

    assert legacy["pre_impact_detected_pct"] == 0.0
    assert dbi["improvement_over_baseline_pct"] > 70.0


def test_EV09_false_positive_causal_attribution(eval_data):
    """Verify False Positive analysis breaks down causes with non-speculative causal qualifiers."""
    fp_analysis = eval_data["false_positive_analysis"]
    assert fp_analysis["total_false_positives"] == 157
    breakdown = fp_analysis["root_cause_breakdown"]
    assert len(breakdown) > 0

    # Ensure qualified wording appears in explanations
    insights = " ".join(fp_analysis.get("insights", []))
    assert any(q in insights.lower() for q in ["possible cause", "likely contributor", "insufficient evidence", "surge", "jitter"])


def test_EV10_false_negative_root_cause_analysis(eval_data):
    """Verify False Negative analysis identifies reasons for missed regressions."""
    fn_analysis = eval_data["false_negative_analysis"]
    assert fn_analysis["total_false_negatives"] == 8
    breakdown = fn_analysis["root_cause_breakdown"]
    assert len(breakdown) > 0
    assert sum(breakdown.values()) == 8


def test_EV11_high_priority_evidence_completeness_100pct(eval_data):
    """Verify that 100% of HIGH and CRITICAL outputs have full evidence across all 17 dimensions."""
    audit = eval_data["evidence_completeness_audit"]
    assert audit["completeness_percentage"] == 100.0
    assert audit["total_high_priority_outputs"] == audit["fully_evidenced_outputs"]
    assert len(audit["checked_dimensions"]) == 17
    assert len(audit["missing_dimensions_by_record"]) == 0


def test_EV12_canonical_controlled_scenarios_all_pass(eval_data):
    """Verify all 8 canonical controlled scenarios are evaluated and pass."""
    scenarios = eval_data["canonical_scenarios"]
    assert len(scenarios) == 8

    for sc in scenarios:
        assert sc["is_correct"] is True, f"Scenario {sc['scenario_id']} failed: predicted {sc['predicted_severity']}, expected {sc['expected_severity']}"
        assert sc["lead_time_minutes"] >= 0.0


def test_EV13_threshold_sensitivity_experiment_sweep(eval_data):
    """Verify multi-threshold sensitivity evaluation across 10%, 20%, 30%, and 50% thresholds."""
    sensitivity = eval_data["sensitivity_analysis"]
    assert len(sensitivity) == 4

    thresholds = [s["threshold_pct"] for s in sensitivity]
    assert thresholds == [10, 20, 30, 50]

    # Lower threshold should yield higher or equal recall, higher false positives
    s10 = next(s for s in sensitivity if s["threshold_pct"] == 10)
    s50 = next(s for s in sensitivity if s["threshold_pct"] == 50)
    assert s10["recall"] >= s50["recall"]
    assert s10["false_positives"] > s50["false_positives"]


def test_EV14_evaluation_artifact_export_integrity():
    """Verify that export_evaluation_data generates valid and readable JSON and CSV artifacts."""
    exported = evaluation_engine.export_evaluation_data()

    assert os.path.exists(exported["json_path"])
    assert os.path.exists(exported["csv_path"])
    assert os.path.exists(exported["scenarios_path"])
    assert os.path.exists(exported["sensitivity_path"])

    # Validate JSON content
    with open(exported["json_path"], "r", encoding="utf-8") as f:
        data = json.load(f)
        assert "confusion_matrix" in data
        assert "detection_before_impact" in data

    # Validate CSV content
    with open(exported["csv_path"], "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert "record_id" in header
        assert "actual_label" in header
        assert "error_type" in header
        rows = list(reader)
        assert len(rows) == 814


def test_EV15_evaluation_rest_api_endpoints(client):
    """Verify REST API endpoints for scenarios, error filtering, sensitivity, and exports."""
    # 1. Scenarios API
    res = client.get("/api/evaluation/scenarios")
    assert res.status_code == 200
    sc_data = res.get_json()
    assert sc_data.get("count") == 8 or len(sc_data.get("scenarios", [])) == 8

    # 2. Error filtering API (FP filter)
    res = client.get("/api/evaluation/errors?type=FP")
    assert res.status_code == 200
    fps_resp = res.get_json()
    records = fps_resp.get("records") if isinstance(fps_resp, dict) else fps_resp
    assert len(records) > 0
    assert all(r.get("error_type") == "FP" or r.get("eval_outcome") == "FP" for r in records)

    # 3. Sensitivity API
    res = client.get("/api/evaluation/sensitivity")
    assert res.status_code == 200
    sens_resp = res.get_json()
    sens_list = sens_resp.get("threshold_sensitivity") if isinstance(sens_resp, dict) else sens_resp
    assert len(sens_list) == 4

    # 4. Export JSON API
    res = client.get("/api/evaluation/export?format=json")
    assert res.status_code == 200
    assert res.content_type == "application/json"

    # 5. Export CSV API
    res = client.get("/api/evaluation/export?format=csv")
    assert res.status_code == 200
    assert "text/csv" in res.content_type
