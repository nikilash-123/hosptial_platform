"""
regression_analyser.py
=======================
Core detection engine. Compares baseline vs run snapshots using configurable rules
and produces severity-labelled regression findings with evidence packages.
"""

import json
from typing import Dict, Any, List, Tuple, Optional

from .rules_loader import (
    get_threshold, get_plan_rule, get_stats_rule, get_noise_band
)
from .evidence_builder import build_evidence
from .plan_extractor import plans_differ


SEVERITY_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "OK": 0}


def analyse(
    baseline_execs: List[Dict[str, Any]],
    run_execs: List[Dict[str, Any]],
    baseline_snap: Dict[str, Any],
    run_snap: Dict[str, Any],
    rules: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Compare baseline and run query executions.
    Returns a list of regression finding dicts (one per query_id).
    """
    # Index executions by query_id
    baseline_map = {e["query_id"]: e for e in baseline_execs}
    run_map = {e["query_id"]: e for e in run_execs}

    all_query_ids = set(baseline_map) | set(run_map)
    findings = []

    for qid in sorted(all_query_ids):
        b = baseline_map.get(qid)
        r = run_map.get(qid)

        if b is None:
            findings.append(_missing_baseline_finding(qid, r))
            continue
        if r is None:
            findings.append(_missing_run_finding(qid, b))
            continue

        finding = _analyse_pair(b, r, baseline_snap, run_snap, rules)
        findings.append(finding)

    # Sort: CRITICAL → HIGH → MEDIUM → OK
    findings.sort(key=lambda x: -SEVERITY_ORDER.get(x["severity"], 0))
    return findings


def _analyse_pair(
    b: Dict[str, Any],
    r: Dict[str, Any],
    baseline_snap: Dict[str, Any],
    run_snap: Dict[str, Any],
    rules: Dict[str, Any],
) -> Dict[str, Any]:
    """Analyse one (baseline, run) query execution pair."""

    query_id = b["query_id"]
    query_label = b.get("query_label", query_id)

    # ── 1. Timing check ───────────────────────────────────────────────────────
    b_p95 = float(b.get("exec_ms_p95", 0) or 0)
    r_p95 = float(r.get("exec_ms_p95", 0) or 0)
    delta_ms = r_p95 - b_p95
    pct_change = (delta_ms / b_p95 * 100) if b_p95 > 0 else 0.0

    min_meaningful = get_threshold(rules, "minimum_meaningful_ms", 1.0)
    regression_pct = get_threshold(rules, "time_regression_pct", 20.0)
    abs_critical = get_threshold(rules, "absolute_critical_ms", 2000.0)
    abs_high = get_threshold(rules, "absolute_high_ms", 500.0)

    time_flag = (
        (b_p95 >= min_meaningful and pct_change >= regression_pct)
        or r_p95 >= abs_critical
        or (r_p95 >= abs_high and pct_change >= regression_pct / 2)
    )

    # ── 2. Plan check ─────────────────────────────────────────────────────────
    b_plan_fake = {"raw": b.get("plan_text", ""), "index_names": json.loads(b.get("index_names", "[]")),
                   "has_full_scan": bool(b.get("has_full_scan", 0)), "uses_index": bool(b.get("uses_index", 0))}
    r_plan_fake = {"raw": r.get("plan_text", ""), "index_names": json.loads(r.get("index_names", "[]")),
                   "has_full_scan": bool(r.get("has_full_scan", 0)), "uses_index": bool(r.get("uses_index", 0))}

    plan_changed, plan_diff_summary = plans_differ(b_plan_fake, r_plan_fake)
    scan_regression = (
        get_plan_rule(rules, "flag_scan_regression")
        and b_plan_fake["uses_index"]
        and r_plan_fake["has_full_scan"]
    )
    plan_flag = plan_changed and (
        get_plan_rule(rules, "flag_new_full_scan") and r_plan_fake["has_full_scan"]
        or get_plan_rule(rules, "flag_index_loss") and not r_plan_fake["uses_index"] and b_plan_fake["uses_index"]
        or scan_regression
        or plan_changed
    )

    # ── 3. Index check ────────────────────────────────────────────────────────
    b_indexes = set(json.loads(b.get("index_names", "[]")))
    r_indexes = set(json.loads(r.get("index_names", "[]")))
    index_lost = bool(b_indexes - r_indexes) if get_plan_rule(rules, "flag_index_loss") else False
    has_new_scan = not b_plan_fake["has_full_scan"] and r_plan_fake["has_full_scan"]

    # ── 4. Stats check ────────────────────────────────────────────────────────
    b_row_est = int(b.get("row_est", 0) or 0)
    r_row_est = int(r.get("row_est", 0) or 0)
    drift_threshold = get_stats_rule(rules, "flag_row_estimate_drift_pct", 50.0)
    if b_row_est > 0:
        row_drift_pct = abs(r_row_est - b_row_est) / b_row_est * 100
    else:
        row_drift_pct = 0.0

    b_rc = json.loads(baseline_snap.get("row_counts") or "{}") if isinstance(baseline_snap.get("row_counts"), str) else (baseline_snap.get("row_counts") or {})
    r_rc = json.loads(run_snap.get("row_counts") or "{}") if isinstance(run_snap.get("row_counts"), str) else (run_snap.get("row_counts") or {})
    table_growth_thresh = get_stats_rule(rules, "flag_table_growth_pct", 200.0)
    table_growth_flag = False
    for tbl, b_cnt in b_rc.items():
        r_cnt = r_rc.get(tbl, b_cnt)
        if b_cnt > 0 and ((r_cnt - b_cnt) / b_cnt * 100.0) >= table_growth_thresh:
            table_growth_flag = True
            break

    stats_flag = (row_drift_pct >= drift_threshold) or table_growth_flag

    # ── 5. Noise / FP grace ───────────────────────────────────────────────────
    noise_band = get_noise_band(rules)
    is_noise = (
        abs(pct_change) < noise_band
        and not plan_changed
        and not index_lost
    )
    if is_noise:
        time_flag = False

    # ── 6. Severity label ─────────────────────────────────────────────────────
    severity = _compute_severity(time_flag, plan_flag, index_lost, pct_change, r_p95, rules)

    # ── 7. Regression types list ──────────────────────────────────────────────
    regression_types = []
    if time_flag:
        regression_types.append("TIME")
    if plan_changed:
        regression_types.append("PLAN")
    if index_lost:
        regression_types.append("INDEX")
    if stats_flag:
        regression_types.append("STATS")
    if not regression_types and severity != "OK":
        regression_types.append("COMPOSITE")

    # ── 8. Evidence package ───────────────────────────────────────────────────
    evidence = {}
    if severity in ("CRITICAL", "HIGH", "MEDIUM"):
        evidence = build_evidence(
            query_id=query_id,
            query_label=query_label,
            severity=severity,
            regression_types=regression_types,
            baseline_release=baseline_snap.get("release_tag", "?"),
            run_release=run_snap.get("release_tag", "?"),
            baseline_exec=b,
            run_exec=r,
            plan_diff_summary=plan_diff_summary,
            delta_ms_p95=delta_ms,
            pct_change=pct_change,
            rules=rules,
        )

    return {
        "query_id": query_id,
        "query_label": query_label,
        "severity": severity,
        "regression_types": regression_types,
        "baseline_p95_ms": b_p95,
        "run_p95_ms": r_p95,
        "delta_ms_p95": round(delta_ms, 4),
        "pct_change": round(pct_change, 2),
        "plan_changed": plan_changed,
        "plan_diff_summary": plan_diff_summary,
        "index_lost": index_lost,
        "has_new_scan": has_new_scan,
        "stats_flag": stats_flag,
        "row_drift_pct": round(row_drift_pct, 2),
        "is_noise": is_noise,
        "evidence": evidence,
        "baseline_snap_id": baseline_snap.get("snapshot_id"),
        "run_snap_id": run_snap.get("snapshot_id"),
    }


def _compute_severity(
    time_flag: bool,
    plan_flag: bool,
    index_lost: bool,
    pct_change: float,
    run_p95: float,
    rules: Dict[str, Any],
) -> str:
    critical_pct = get_threshold(rules, "time_critical_pct", 100.0)
    high_pct = get_threshold(rules, "time_high_pct", 50.0)
    abs_critical = get_threshold(rules, "absolute_critical_ms", 2000.0)

    # Absolute critical
    if run_p95 >= abs_critical:
        return "CRITICAL"

    # Use severity matrix from rules
    matrix = rules.get("severity_matrix", [])
    for entry in matrix:
        cond = entry.get("condition", {})
        if (
            cond.get("time_flag") == time_flag
            and cond.get("plan_flag") == plan_flag
            and cond.get("index_loss") == index_lost
        ):
            return entry.get("severity", "OK")

    # Fallback heuristic
    if time_flag and plan_flag and index_lost:
        return "CRITICAL"
    if time_flag and (plan_flag or index_lost):
        return "HIGH"
    if plan_flag and index_lost:
        return "HIGH"
    if pct_change >= critical_pct:
        return "CRITICAL"
    if pct_change >= high_pct or plan_flag or index_lost:
        return "HIGH" if pct_change >= high_pct else "MEDIUM"
    if time_flag:
        return "MEDIUM"
    return "OK"


def _missing_baseline_finding(qid: str, r: Dict) -> Dict:
    return {
        "query_id": qid,
        "query_label": r.get("query_label", qid) if r else qid,
        "severity": "LOW",
        "regression_types": ["MISSING_BASELINE"],
        "baseline_p95_ms": 0, "run_p95_ms": r.get("exec_ms_p95", 0) if r else 0,
        "delta_ms_p95": 0, "pct_change": 0,
        "plan_changed": False, "plan_diff_summary": "No baseline to compare",
        "index_lost": False, "has_new_scan": False,
        "stats_flag": False, "row_drift_pct": 0, "is_noise": False,
        "evidence": {"note": "No baseline execution found for this query."},
    }


def _missing_run_finding(qid: str, b: Dict) -> Dict:
    return {
        "query_id": qid,
        "query_label": b.get("query_label", qid) if b else qid,
        "severity": "LOW",
        "regression_types": ["MISSING_RUN"],
        "baseline_p95_ms": b.get("exec_ms_p95", 0) if b else 0,
        "run_p95_ms": 0,
        "delta_ms_p95": 0, "pct_change": 0,
        "plan_changed": False, "plan_diff_summary": "No run execution found for this query",
        "index_lost": False, "has_new_scan": False,
        "stats_flag": False, "row_drift_pct": 0, "is_noise": False,
        "evidence": {"note": "No run execution found for this query."},
    }


def compute_evaluation_metrics(
    findings: List[Dict[str, Any]],
    ground_truth: Dict[str, str],
) -> Dict[str, Any]:
    """
    Compute precision, recall, F1 given ground-truth labels.

    ground_truth: { query_id: expected_severity }
    A positive is any severity != "OK".
    """
    tp = fp = fn = tn = 0
    per_query = []

    for f in findings:
        qid = f["query_id"]
        detected = f["severity"]
        expected = ground_truth.get(qid, "OK")

        det_pos = detected != "OK"
        exp_pos = expected != "OK"

        if det_pos and exp_pos:
            tp += 1
            match = "TP"
        elif det_pos and not exp_pos:
            fp += 1
            match = "FP"
        elif not det_pos and exp_pos:
            fn += 1
            match = "FN"
        else:
            tn += 1
            match = "TN"

        per_query.append({
            "query_id": qid,
            "expected": expected,
            "detected": detected,
            "result": match,
        })

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "per_query": per_query,
    }
