"""
benchmark_experiment.py
=======================
Systematic, reproducible benchmark experiment evaluating the
Hospital Appointment Query-Regression Detection Engine against the
814 ground-truth records in data/synthetic_dataset.db.

Computes & Exports:
1. Confusion Matrix: TP, FP, TN, FN
2. Metrics: Precision, Recall, Specificity, F1-Score, FPR, FNR, Accuracy
3. Core Success Metric: Slow-query regressions detected BEFORE user impact (%)
4. Detection Timing & Lead Time Statistics (Mean, Median, Min, Max)
5. Synthetic Legacy Baseline Workaround Comparator
6. False Positive (FP) and False Negative (FN) In-depth Analysis
7. High-Priority Evidence Completeness Audit (100% Target)
8. Scenario-Level Evaluations (8 Canonical Scenarios)
9. Threshold Sensitivity Experiment (10%, 20%, 30%, 50%)
10. Signal Contribution Analysis (Plans, Times, Indexes, Stats, Releases)

Exports:
- data/experiment_results.json
- data/evaluation_results.json
- data/evaluation_results.csv
- data/scenario_evaluations.json
- data/threshold_sensitivity.json
"""

import os
import sys
import json
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.core import evaluation_engine

OUTPUT_EXP_JSON = os.path.join(BASE_DIR, "data", "experiment_results.json")


def run_benchmark(verbose: bool = True):
    if verbose:
        print("=" * 84)
        print("HOSPITAL APPOINTMENT PLATFORM — QUERY REGRESSION DETECTOR BENCHMARK (PHASE 10)")
        print("=" * 84)

    # 1. Run full evaluation across the 814 ground-truth records
    evaluations = evaluation_engine.run_full_evaluation()
    cm = evaluation_engine.compute_confusion_matrix(evaluations)
    impact = evaluation_engine.compute_detection_before_impact_metrics(evaluations)
    legacy = evaluation_engine.evaluate_legacy_baseline(evaluations)
    fp_analysis = evaluation_engine.perform_false_positive_analysis(evaluations)
    fn_analysis = evaluation_engine.perform_false_negative_analysis(evaluations)
    evidence_audit = evaluation_engine.audit_high_priority_evidence(evaluations)
    scenarios = evaluation_engine.run_scenario_evaluations()
    sensitivity = evaluation_engine.run_threshold_sensitivity_experiment()
    signals = evaluation_engine.analyze_signal_contributions(evaluations)

    # 2. Export evaluation files (CSV, JSON, Scenarios, Sensitivity)
    exported = evaluation_engine.export_evaluation_data(evaluations)

    # 3. Format compatibility summary payload for experiment_results.json
    summary = {
        "benchmark_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_records": cm["total_records"],
        "confusion_matrix": {
            "true_positives": cm["true_positives"],
            "false_positives": cm["false_positives"],
            "true_negatives": cm["true_negatives"],
            "false_negatives": cm["false_negatives"]
        },
        "metrics": {
            "accuracy": cm["accuracy"],
            "precision": cm["precision"],
            "recall": cm["recall"],
            "specificity": cm["specificity"],
            "f1_score": cm["f1_score"],
            "false_positive_rate": cm["false_positive_rate"],
            "false_negative_rate": cm["false_negative_rate"],
            "detection_rate": cm["detection_rate"]
        },
        "core_success_metric": {
            "name": "Slow-query regressions detected BEFORE user impact",
            "baseline_workaround_pct": legacy["legacy_detection_before_impact_rate_pct"],
            "legacy_detection_rate_pct": legacy["legacy_detection_rate_pct"],
            "project_target_pct": impact["project_target_pct"],
            "measured_detector_pct": impact["detection_before_user_impact_rate_pct"],
            "target_met": impact["target_met"],
            "lead_time_minutes": impact["lead_time_minutes"],
            "lead_time_seconds": impact["lead_time_seconds"]
        },
        "evidence_audit": evidence_audit,
        "signal_contributions": signals,
        "false_positive_count": len(fp_analysis),
        "false_negative_count": len(fn_analysis),
        "scenarios": scenarios,
        "threshold_sensitivity": sensitivity
    }

    with open(OUTPUT_EXP_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    if verbose:
        print(f"Total Records Evaluated:       {cm['total_records']}")
        print(f"True Positives (TP):           {cm['true_positives']}")
        print(f"False Positives (FP):          {cm['false_positives']}")
        print(f"True Negatives (TN):           {cm['true_negatives']}")
        print(f"False Negatives (FN):          {cm['false_negatives']}")
        print("-" * 84)
        print(f"Accuracy:                      {cm['accuracy_pct']:.1f}%")
        print(f"Precision:                     {cm['precision_pct']:.1f}%")
        print(f"Recall (Sensitivity):          {cm['recall_pct']:.1f}%")
        print(f"Specificity:                   {cm['specificity'] * 100:.1f}%")
        print(f"F1-Score:                      {cm['f1_pct']:.1f}%")
        print("-" * 84)
        print("CORE SUCCESS METRIC (DETECTION BEFORE USER IMPACT):")
        print(f"  Legacy Baseline Workaround:  {legacy['legacy_detection_before_impact_rate_pct']:.1f}% (Pre-impact: 0%, Total: {legacy['legacy_detection_rate_pct']:.1f}%)")
        print(f"  Platform Target Goal:        {impact['project_target_pct']:.1f}%")
        print(f"  Measured Detector Result:    {impact['detection_before_user_impact_rate_pct']:.1f}%  [TARGET EXCEEDED: {impact['target_met']}]")
        print(f"  Average Detection Lead Time: {impact['lead_time_minutes']['average']} minutes ({impact['lead_time_seconds']['average']:.0f} seconds)")
        print(f"  Median Detection Lead Time:  {impact['lead_time_minutes']['median']} minutes")
        print("-" * 84)
        print(f"High-Priority Evidence Audit:  {evidence_audit['high_priority_evidence_completeness_rate_pct']:.1f}% Complete across all {len(evidence_audit['checked_dimensions'])} dimensions")
        print("-" * 84)
        print("THRESHOLD SENSITIVITY EXPERIMENT:")
        print("  Threshold   Precision   Recall   F1-Score   FP   FN   Pre-Impact Det %")
        for s in sensitivity:
            print(f"    {s['threshold_pct']:4.1f}%       {s['precision']*100:5.1f}%    {s['recall']*100:5.1f}%    {s['f1_score']*100:5.1f}%    {s['false_positives']:3d}  {s['false_negatives']:2d}       {s['detected_before_impact_pct']:5.1f}%")
        print("=" * 84)
        print(f"Artifacts exported:")
        for k, p in exported.items():
            print(f"  - {k:18s} -> {p}")
        print(f"  - experiment_json    -> {OUTPUT_EXP_JSON}")
        print("=" * 84 + "\n")

    return summary


if __name__ == "__main__":
    run_benchmark()
