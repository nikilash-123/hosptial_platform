"""
evidence_builder.py
====================
Constructs a mandatory evidence package for every HIGH/CRITICAL regression finding.
"""

import json
from datetime import datetime
from typing import Dict, Any, List


EVIDENCE_VERSION = "1.0"

REQUIRED_EVIDENCE_FIELDS = [
    "evidence_id", "query_id", "query_label", "severity",
    "regression_types", "baseline_release", "run_release",
    "timing", "plan", "index", "statistics", "rules_applied",
    "recommendation", "detected_before_user_impact", "detected_at",
]


def build_evidence(
    query_id: str,
    query_label: str,
    severity: str,
    regression_types: List[str],
    baseline_release: str,
    run_release: str,
    baseline_exec: Dict[str, Any],
    run_exec: Dict[str, Any],
    plan_diff_summary: str,
    delta_ms_p95: float,
    pct_change: float,
    rules: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build a complete evidence package for a regression finding.
    Every HIGH/CRITICAL finding must have one of these.
    """
    now = datetime.now().isoformat()

    evidence_id = (
        f"EVD-{now[:10].replace('-', '')}-{query_id}-{baseline_release}-{run_release}"
    )

    baseline_indexes = json.loads(baseline_exec.get("index_names", "[]"))
    run_indexes = json.loads(run_exec.get("index_names", "[]"))

    baseline_row_est = baseline_exec.get("row_est", 0)
    run_row_est = run_exec.get("row_est", 0)
    if baseline_row_est > 0:
        stat_drift_pct = abs(run_row_est - baseline_row_est) / baseline_row_est * 100
    else:
        stat_drift_pct = 0.0

    recommendation = _build_recommendation(
        severity, regression_types, baseline_indexes, run_indexes, pct_change
    )

    evidence = {
        "evidence_version": EVIDENCE_VERSION,
        "evidence_id": evidence_id,
        "query_id": query_id,
        "query_label": query_label,
        "severity": severity,
        "regression_types": regression_types,
        "baseline_release": baseline_release,
        "run_release": run_release,
        "timing": {
            "baseline_p50_ms": baseline_exec.get("exec_ms_p50", 0),
            "baseline_p95_ms": baseline_exec.get("exec_ms_p95", 0),
            "baseline_p99_ms": baseline_exec.get("exec_ms_p99", 0),
            "run_p50_ms": run_exec.get("exec_ms_p50", 0),
            "run_p95_ms": run_exec.get("exec_ms_p95", 0),
            "run_p99_ms": run_exec.get("exec_ms_p99", 0),
            "delta_ms_p95": round(delta_ms_p95, 4),
            "pct_change": round(pct_change, 2),
        },
        "plan": {
            "baseline_plan": baseline_exec.get("plan_text", ""),
            "run_plan": run_exec.get("plan_text", ""),
            "plan_changed": bool(baseline_exec.get("plan_text") != run_exec.get("plan_text")),
            "diff_summary": plan_diff_summary,
            "baseline_has_full_scan": bool(baseline_exec.get("has_full_scan", 0)),
            "run_has_full_scan": bool(run_exec.get("has_full_scan", 0)),
        },
        "index": {
            "baseline_indexes": baseline_indexes,
            "run_indexes": run_indexes,
            "index_lost": bool(set(baseline_indexes) - set(run_indexes)),
            "indexes_lost_names": list(set(baseline_indexes) - set(run_indexes)),
        },
        "statistics": {
            "baseline_row_est": baseline_row_est,
            "run_row_est": run_row_est,
            "row_est_drift_pct": round(stat_drift_pct, 2),
        },
        "rules_applied": {
            "thresholds": rules.get("thresholds", {}),
            "plan_rules": rules.get("plan_rules", {}),
            "stats_rules": rules.get("stats_rules", {}),
        },
        "recommendation": recommendation,
        "detected_before_user_impact": True,
        "detected_at": now,
    }

    return evidence


def _build_recommendation(
    severity: str,
    regression_types: List[str],
    baseline_indexes: List[str],
    run_indexes: List[str],
    pct_change: float,
) -> str:
    parts = []

    lost = list(set(baseline_indexes) - set(run_indexes))
    if "INDEX" in regression_types and lost:
        parts.append(
            f"RESTORE missing indexes before deployment: {', '.join(lost)}."
        )

    if "PLAN" in regression_types:
        parts.append(
            "Review query execution plan — a full table scan has appeared. "
            "Consider adding or rebuilding the appropriate index."
        )

    if "TIME" in regression_types:
        parts.append(
            f"Query p95 time has increased by {pct_change:.1f}%. "
            "Block this release until root cause is identified."
            if severity in ("CRITICAL", "HIGH")
            else f"Query p95 time increased by {pct_change:.1f}%. Monitor closely."
        )

    if "STATS" in regression_types:
        parts.append(
            "Run ANALYZE to refresh table statistics and re-check query plans."
        )

    if not parts:
        parts.append("No action required — regression is within acceptable bounds.")

    return " ".join(parts)


def validate_evidence(evidence: Dict[str, Any]) -> List[str]:
    """Return list of missing required fields (empty = valid)."""
    return [f for f in REQUIRED_EVIDENCE_FIELDS if f not in evidence]
