"""
detection_engine.py
===================
Phase 4: Query-Regression Detection Engine for Hospital Appointment Platform.

Compares BEFORE and AFTER states for queries across 9 distinct evidence signals:
  1. Execution time increase (percentage & absolute limits)
  2. Query plan changes (hash mismatch, scan vs search, new full table scan)
  3. Increased rows examined (storage scan cardinality drift)
  4. Increased CPU / IO cost (kernel/user execution cost)
  5. Index changes (index removed, modified, missing, unused)
  6. Statistics staleness (age > threshold, un-analyzed tables)
  7. Workload changes (concurrency variance vs structural regression)
  8. Schema changes (column added, index dropped, type altered)
  9. Release changes (deployment changes, migration context)

Calculates an explainable regression score (0.0 to 100.0) based on configurable
scoring weights and thresholds in config/rules.yaml.

Classifies findings into:
  - NORMAL
  - WARNING
  - REGRESSION
  - CRITICAL_REGRESSION

Every HIGH or CRITICAL regression produces an explainable, forensic evidence package
specifying the exact root cause, deltas, and actionable investigation recommendations.
"""

import os
import sys
import json
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Union

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from src.core import rules_loader, plan_extractor, plan_comparator, change_context_analyser, rule_engine

DEFAULT_RULES_PATH = os.path.join(BASE_DIR, "config", "rules.yaml")

# Hospital platform queries that directly protect against double-booking race conditions
DOUBLE_BOOKING_QUERIES = {
    "SYNTH-Q-002", "SYNTH-Q-003", "SYNTH-Q-004", "SYNTH-Q-007", "SYNTH-Q-008",
    "QRY-001", "QRY-004"
}

DOUBLE_BOOKING_TYPES = {
    "verify_slot_booked", "check_doctor_availability", "create_appointment",
    "cancel_appointment", "retrieve_doctor_schedule"
}


def compute_plan_hash(plan_text: Optional[str]) -> str:
    """Computes a standardized SHA-256 fingerprint for a query plan."""
    if not plan_text:
        return "NULL_PLAN"
    normalized = " ".join(plan_text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def calculate_regression_score(
    signals: Dict[str, Any],
    rules: Dict[str, Any]
) -> Tuple[float, Dict[str, float]]:
    """
    Computes a normalized regression score from 0.0 to 100.0 based on configurable weights.

    Signals evaluated:
      - time_pct_change, absolute_time_ms
      - plan_changed, has_new_scan
      - index_lost, index_status
      - stats_stale, row_drift_pct
      - schema_altered, release_change_severity
      - is_double_booking_critical
      - is_workload_grace
    """
    w_perf = rules_loader.get_scoring_weight(rules, "performance_weight", 35.0)
    w_plan = rules_loader.get_scoring_weight(rules, "plan_weight", 25.0)
    w_idx  = rules_loader.get_scoring_weight(rules, "index_weight", 20.0)
    w_stat = rules_loader.get_scoring_weight(rules, "statistics_weight", 10.0)
    w_ctx  = rules_loader.get_scoring_weight(rules, "change_context_weight", 10.0)
    db_multiplier = rules_loader.get_scoring_weight(rules, "double_booking_multiplier", 1.25)

    subscores: Dict[str, float] = {
        "performance": 0.0,
        "plan": 0.0,
        "index": 0.0,
        "statistics": 0.0,
        "change_context": 0.0
    }

    # 1. Performance Subscore (0 to w_perf)
    time_pct = float(signals.get("time_pct_change", 0.0))
    abs_ms = float(signals.get("current_exec_ms", 0.0))
    abs_critical = rules_loader.get_threshold(rules, "absolute_critical_ms", 2000.0)

    if abs_ms >= abs_critical:
        subscores["performance"] = w_perf
    elif time_pct >= 200.0:
        subscores["performance"] = w_perf
    elif time_pct >= 100.0:
        subscores["performance"] = w_perf * 0.90
    elif time_pct >= 70.0:
        subscores["performance"] = w_perf * 0.75
    elif time_pct >= 50.0:
        subscores["performance"] = w_perf * 0.60
    elif time_pct >= 20.0:
        subscores["performance"] = w_perf * 0.35
    elif time_pct > 10.0:
        subscores["performance"] = w_perf * 0.15

    # 2. Plan Subscore (0 to w_plan)
    if signals.get("has_new_scan", False):
        subscores["plan"] = w_plan
    elif signals.get("plan_changed", False):
        subscores["plan"] = w_plan * 0.70

    # 3. Index Subscore (0 to w_idx)
    idx_status = signals.get("index_status", "OPTIMAL")
    if signals.get("index_lost", False) or idx_status in ("REMOVED", "MISSING"):
        subscores["index"] = w_idx
    elif signals.get("has_new_scan", False):
        subscores["index"] = w_idx * 0.60
    elif idx_status == "CHANGED":
        subscores["index"] = w_idx * 0.60
    elif idx_status == "UNUSED":
        subscores["index"] = w_idx * 0.75

    # 4. Statistics Subscore (0 to w_stat)
    if signals.get("stats_stale", False):
        subscores["statistics"] += w_stat * 0.60
    if signals.get("row_drift_pct", 0.0) >= 50.0:
        subscores["statistics"] += w_stat * 0.40
    subscores["statistics"] = min(w_stat, subscores["statistics"])

    # 5. Change Context Subscore (0 to w_ctx)
    if signals.get("schema_change") in ("INDEX_DROPPED", "TABLE_PARTITIONED"):
        subscores["change_context"] += w_ctx * 0.70
    elif signals.get("schema_change") in ("COLUMN_ADDED", "INDEX_MODIFIED"):
        subscores["change_context"] += w_ctx * 0.40

    if signals.get("release_change") in ("index_removed", "bad_query_plan", "missing_index"):
        subscores["change_context"] += w_ctx * 0.60
    elif signals.get("release_change") in ("table_growth", "statistics_stale"):
        subscores["change_context"] += w_ctx * 0.30
    subscores["change_context"] = min(w_ctx, subscores["change_context"])

    raw_score = sum(subscores.values())

    # Concurrency Grace Reduction
    if signals.get("is_workload_grace", False):
        # Workload spike without structural degradation
        raw_score = max(0.0, raw_score * 0.15)
        subscores["performance"] *= 0.15

    # Double-booking multiplier for sensitive healthcare workflows
    if signals.get("is_double_booking_critical", False) and raw_score >= 35.0:
        raw_score = min(100.0, raw_score * db_multiplier)

    final_score = round(min(100.0, max(0.0, raw_score)), 2)
    return final_score, subscores


def detect_query_regression(
    before_state: Dict[str, Any],
    after_state: Dict[str, Any],
    rules: Optional[Dict[str, Any]] = None,
    rules_path: str = DEFAULT_RULES_PATH
) -> Dict[str, Any]:
    """
    Main Detection Engine API.
    Compares BEFORE and AFTER states across all 9 signals and produces
    a regression classification and mandatory forensic evidence object.
    """
    if rules is None:
        rules = rules_loader.load_rules(rules_path)

    qid = before_state.get("query_id") or after_state.get("query_id", "UNKNOWN-Q")
    qname = before_state.get("query_name") or after_state.get("query_name", qid)
    qtype = before_state.get("query_type") or after_state.get("query_type", "")

    # ── Signal 1: Execution Time ──────────────────────────────────────────────
    b_ms = float(before_state.get("execution_time_ms") or before_state.get("exec_ms_p95") or before_state.get("p95_exec_ms") or 1.0)
    a_ms = float(after_state.get("execution_time_ms") or after_state.get("exec_ms_p95") or after_state.get("p95_exec_ms") or 0.0)
    delta_ms = a_ms - b_ms
    pct_change = (delta_ms / b_ms * 100.0) if b_ms > 0 else 0.0

    time_reg_pct = rules_loader.get_threshold(rules, "time_regression_pct", 20.0)
    abs_critical = rules_loader.get_threshold(rules, "absolute_critical_ms", 2000.0)
    abs_high = rules_loader.get_threshold(rules, "absolute_high_ms", 500.0)
    noise_band = rules_loader.get_noise_band(rules)

    # ── Signal 2: Query Plan Change ───────────────────────────────────────────
    b_plan_raw = before_state.get("plan_text") or before_state.get("raw_plan") or ""
    a_plan_raw = after_state.get("plan_text") or after_state.get("raw_plan") or ""

    b_plan_hash = before_state.get("plan_hash") or before_state.get("baseline_plan_hash") or compute_plan_hash(b_plan_raw)
    a_plan_hash = after_state.get("plan_hash") or compute_plan_hash(a_plan_raw)

    plan_changed = bool(a_plan_hash and b_plan_hash and a_plan_hash != b_plan_hash) or bool(after_state.get("plan_changed", 0))

    b_has_scan = bool(before_state.get("has_full_scan", False) or "SCAN" in str(b_plan_raw).upper() and "INDEX" not in str(b_plan_raw).upper())
    a_has_scan = bool(after_state.get("has_full_scan", False) or "SCAN" in str(a_plan_raw).upper() or after_state.get("index_status") in ("REMOVED", "MISSING"))
    has_new_scan = a_has_scan and not b_has_scan

    # ── Signal 3: Rows Examined ───────────────────────────────────────────────
    b_rows_ex = int(before_state.get("rows_examined", 1) or 1)
    a_rows_ex = int(after_state.get("rows_examined", b_rows_ex) or b_rows_ex)
    row_drift_pct = abs(a_rows_ex - b_rows_ex) / b_rows_ex * 100.0 if b_rows_ex > 0 else 0.0
    rows_drift_flag = row_drift_pct >= rules_loader.get_stats_rule(rules, "flag_row_estimate_drift_pct", 50.0)

    # ── Signal 4: CPU & IO Cost ───────────────────────────────────────────────
    b_cpu = float(before_state.get("cpu_time_ms", b_ms * 0.7))
    a_cpu = float(after_state.get("cpu_time_ms", a_ms * 0.7))
    cpu_drift_pct = ((a_cpu - b_cpu) / b_cpu * 100.0) if b_cpu > 0 else 0.0

    b_io = float(before_state.get("io_cost", 1.0))
    a_io = float(after_state.get("io_cost", 1.0))
    io_drift_pct = ((a_io - b_io) / b_io * 100.0) if b_io > 0 else 0.0

    # ── Signal 5: Index Status & Loss ─────────────────────────────────────────
    def _parse_indexes(src: Any) -> List[str]:
        if isinstance(src, list):
            return src
        if isinstance(src, str):
            if src.startswith("[") and src.endswith("]"):
                try:
                    return json.loads(src)
                except Exception:
                    pass
            return [src] if src and src != "None" else []
        return []

    b_indexes = _parse_indexes(before_state.get("indexes") or before_state.get("index_name") or before_state.get("index_names"))
    a_indexes = _parse_indexes(after_state.get("indexes") or after_state.get("index_name") or after_state.get("index_names"))
    lost_indexes = list(set(b_indexes) - set(a_indexes))
    index_lost = bool(lost_indexes) or (after_state.get("index_status") in ("REMOVED", "MISSING"))
    idx_status = after_state.get("index_status", "REMOVED" if index_lost else "OPTIMAL")

    # ── Signal 5b: Deep Execution Plan Comparison ─────────────────────────────
    b_plan_struct = {
        "plan_hash": b_plan_hash,
        "raw_text": b_plan_raw,
        "indexes": b_indexes,
        "is_full_scan": b_has_scan,
        "scan_type": before_state.get("scan_type"),
        "table": before_state.get("table", ""),
        "estimated_rows": b_rows_ex,
        "actual_rows": int(before_state.get("rows_returned", 0) or 0),
        "estimated_cost": float(before_state.get("estimated_cost") or b_cpu + b_io),
        "cpu_cost": b_cpu,
        "io_cost": b_io,
        "join_strategy": before_state.get("join_strategy", "None"),
        "sort_operations": before_state.get("sort_operations", []),
        "filter_operations": before_state.get("filter_operations", [])
    }
    a_plan_struct = {
        "plan_hash": a_plan_hash,
        "raw_text": a_plan_raw,
        "indexes": a_indexes,
        "is_full_scan": a_has_scan,
        "scan_type": after_state.get("scan_type"),
        "table": after_state.get("table", ""),
        "estimated_rows": a_rows_ex,
        "actual_rows": int(after_state.get("rows_returned", 0) or 0),
        "estimated_cost": float(after_state.get("estimated_cost") or a_cpu + a_io),
        "cpu_cost": a_cpu,
        "io_cost": a_io,
        "join_strategy": after_state.get("join_strategy", "None"),
        "sort_operations": after_state.get("sort_operations", []),
        "filter_operations": after_state.get("filter_operations", [])
    }
    plan_comparison = plan_comparator.compare_execution_plans(b_plan_struct, a_plan_struct)

    # ── Signal 6: Statistics Staleness ────────────────────────────────────────
    stats_age = int(after_state.get("statistics_age", before_state.get("statistics_age", 1)))
    stats_status = after_state.get("statistics_status", "CURRENT")
    staleness_threshold = rules_loader.get_staleness_threshold(rules, 30)
    stats_stale = (stats_age > staleness_threshold) or (stats_status == "STALE")

    # ── Signal 7: Workload Changes ────────────────────────────────────────────
    b_workload = before_state.get("workload_level", "NORMAL")
    a_workload = after_state.get("workload_level", "NORMAL")
    workload_surge = (a_workload in ("HIGH", "PEAK")) and (b_workload in ("LOW", "NORMAL"))
    workload_variance_pct = float(rules_loader.get_workload_rule(rules, "workload_variance_pct", 40.0))

    is_noise = (abs(pct_change) < noise_band) and not plan_changed and not index_lost
    is_workload_grace = (
        workload_surge
        and not plan_changed
        and not index_lost
        and pct_change < workload_variance_pct
        and a_ms < abs_high
    )

    # ── Signal 8: Schema Changes ──────────────────────────────────────────────
    schema_change = after_state.get("schema_change", "NONE")

    # ── Signal 9: Release Changes ─────────────────────────────────────────────
    b_rel = before_state.get("release_version") or before_state.get("release_id", "v1.0.0")
    a_rel = after_state.get("release_version") or after_state.get("release_id", "v1.1.0")
    rel_change = after_state.get("release_change", "release_deployment")

    # ── Phase 6: Change Context Correlation Layer ─────────────────────────────
    change_ctx = change_context_analyser.correlate_change_context(
        query_id=qid,
        before_state=before_state,
        after_state=after_state,
        plan_diff=plan_comparison,
        rules=rules
    )

    # ── Double-Booking Critical Sensitivity ───────────────────────────────────
    is_double_booking_critical = (
        qid in DOUBLE_BOOKING_QUERIES
        or qtype in DOUBLE_BOOKING_TYPES
        or "double-booking" in qname.lower()
        or before_state.get("double_booking_critical", False)
    )

    # ── Calculate Regression Score ────────────────────────────────────────────
    signals_bundle = {
        "time_pct_change": pct_change,
        "current_exec_ms": a_ms,
        "plan_changed": plan_changed,
        "has_new_scan": has_new_scan,
        "index_lost": index_lost,
        "index_status": idx_status,
        "stats_stale": stats_stale,
        "row_drift_pct": row_drift_pct,
        "schema_change": schema_change,
        "release_change": rel_change,
        "is_workload_grace": is_workload_grace,
        "is_double_booking_critical": is_double_booking_critical
    }

    # ── Phase 7: Priority & Configurable Rule Engine Evaluation ───────────────
    rule_eval = rule_engine.evaluate_rules(
        signals={
            "baseline_exec_ms": b_ms,
            "current_exec_ms": a_ms,
            "time_pct_change": pct_change,
            "plan_changed": plan_changed,
            "has_new_scan": has_new_scan,
            "full_table_scan_detected": has_new_scan,
            "index_removed": index_lost,
            "index_lost": index_lost,
            "index_status": idx_status,
            "lost_indexes": lost_indexes,
            "statistics_stale": stats_stale,
            "stats_stale": stats_stale,
            "statistics_age": stats_age,
            "statistics_status": stats_status,
            "row_drift_pct": row_drift_pct,
            "cost_drift_pct": plan_comparison.get("cost_drift_pct", cpu_drift_pct + io_drift_pct),
            "workload_increased": workload_surge,
            "workload_surge": workload_surge,
            "workload_level": a_workload,
            "schema_change": schema_change,
            "schema_changed": schema_change not in ("NONE", "", None),
            "release_version": a_rel,
            "release_change": rel_change,
            "recent_release": rel_change not in ("release_deployment", "NONE", "", None) or (a_rel != b_rel),
            "is_workload_grace": is_workload_grace,
            "is_double_booking_critical": is_double_booking_critical,
        },
        rules=rules,
        context={
            "query_id": qid,
            "query_name": qname,
            "baseline_execution_time": b_ms,
            "current_execution_time": a_ms,
            "baseline_plan_hash": b_plan_hash,
            "current_plan_hash": a_plan_hash,
            "lost_indexes": lost_indexes,
            "plan_explanation": plan_comparison.get("explanation", ""),
            "plan_diff": plan_comparison,
            "schema_change": schema_change,
            "release_version": a_rel,
        }
    )

    regression_score, score_breakdown = calculate_regression_score(signals_bundle, rules)

    # ── Classification Logic ──────────────────────────────────────────────────
    crit_score_thresh = rules_loader.get_score_threshold(rules, "critical_regression_score", 75.0)
    reg_score_thresh  = rules_loader.get_score_threshold(rules, "regression_score", 50.0)
    warn_score_thresh = rules_loader.get_score_threshold(rules, "warning_score", 25.0)

    time_flag = (
        (b_ms >= rules_loader.get_threshold(rules, "minimum_meaningful_ms", 1.0) and pct_change >= time_reg_pct)
        or a_ms >= abs_critical
        or (a_ms >= abs_high and pct_change >= time_reg_pct / 2.0)
    )
    if is_noise or is_workload_grace:
        time_flag = False

    time_high_pct = rules_loader.get_threshold(rules, "time_high_pct", 50.0)

    # Decisive overrides for patient safety / SLA limits
    if a_ms >= abs_critical:
        label = "CRITICAL_REGRESSION"
        severity = "CRITICAL"
        reason = f"Absolute execution time ({a_ms:.1f}ms) breached critical SLA threshold ({abs_critical}ms)."
    elif is_double_booking_critical and (index_lost or has_new_scan) and pct_change >= 35.0:
        label = "CRITICAL_REGRESSION"
        severity = "CRITICAL"
        reason = "Acute double-booking hazard: Index lost or full scan introduced on appointment slot locking path."
    elif pct_change >= rules_loader.get_threshold(rules, "time_critical_pct", 100.0) and (plan_changed or index_lost):
        label = "CRITICAL_REGRESSION"
        severity = "CRITICAL"
        reason = f"Catastrophic latency surge (+{pct_change:.1f}%) combined with query plan degradation."
    elif regression_score >= crit_score_thresh:
        label = "CRITICAL_REGRESSION"
        severity = "CRITICAL"
        reason = f"Multi-signal regression score ({regression_score:.1f}/100) exceeded critical release threshold."
    elif (time_flag and pct_change >= time_high_pct) or regression_score >= reg_score_thresh:
        label = "REGRESSION"
        severity = "HIGH"
        reason = f"Substantial performance regression ({regression_score:.1f}/100) driven by query slowdown (+{pct_change:.1f}%) or plan shift."
    elif (not is_workload_grace and not is_noise and (regression_score >= warn_score_thresh or stats_stale or time_flag)):
        label = "WARNING"
        severity = "MEDIUM"
        reason = "Moderate performance drift or stale table statistics requiring investigation."
    else:
        label = "NORMAL"
        severity = "OK"
        if is_workload_grace:
            reason = f"Latency increase (+{pct_change:.1f}%) matches transient queueing under {a_workload} load with optimal index search maintained."
        elif is_noise:
            reason = f"Execution variance (+{pct_change:.1f}%) remains within acceptable noise band ({noise_band}%)."
        else:
            reason = "Query performance and execution plan conform to verified baseline."

    # ── Remediation Recommendations ───────────────────────────────────────────
    recommendations = []
    if index_lost or has_new_scan:
        recommendations.append(f"Restore supporting index {b_indexes} on target table to eliminate sequential table scan.")
    if stats_stale:
        recommendations.append(f"Execute 'ANALYZE' to refresh table cardinality statistics (current stats age: {stats_age} days).")
    if rows_drift_flag:
        recommendations.append(f"Investigate query predicate selectivity; rows examined surged from {b_rows_ex} to {a_rows_ex} (+{row_drift_pct:.0f}%).")
    if severity == "CRITICAL":
        recommendations.append("BLOCK RELEASE: Immediate rollback or index fix required prior to clinical deployment.")
    elif severity == "HIGH":
        recommendations.append("Require DBA sign-off before releasing build to staging environment.")
    elif severity == "OK":
        recommendations.append("Release approved from query regression perspective.")

    # ── Mandatory Forensic Evidence Object ─────────────────────────────────────
    now_iso = datetime.now().isoformat()
    evidence_obj = {
        "evidence_id": f"EVD-{now_iso[:10].replace('-', '')}-{qid}-{b_rel}-{a_rel}",
        "query_id": qid,
        "query_name": qname,
        "query_type": qtype,
        "baseline_execution_time": f"{b_ms:.2f} ms",
        "current_execution_time": f"{a_ms:.2f} ms",
        "percentage_change": f"{'+' if pct_change > 0 else ''}{pct_change:.2f}%",
        "baseline_plan_hash": b_plan_hash,
        "current_plan_hash": a_plan_hash,
        "plan_changed": "yes" if plan_changed else "no",
        "index_difference": {
            "baseline_indexes": b_indexes,
            "current_indexes": a_indexes,
            "lost_indexes": lost_indexes,
            "index_status": idx_status
        },
        "statistics_difference": {
            "baseline_rows_examined": b_rows_ex,
            "current_rows_examined": a_rows_ex,
            "row_drift_percentage": f"{row_drift_pct:.1f}%",
            "statistics_age_days": stats_age,
            "statistics_status": stats_status,
            "stats_stale": stats_stale
        },
        "workload_difference": {
            "baseline_workload": b_workload,
            "current_workload": a_workload,
            "workload_surge": workload_surge,
            "concurrency_grace_applied": is_workload_grace
        },
        "cost_difference": {
            "cpu_change_percentage": f"{cpu_drift_pct:.1f}%",
            "io_cost_change_percentage": f"{io_drift_pct:.1f}%"
        },
        "release_change_information": {
            "baseline_release": b_rel,
            "current_release": a_rel,
            "release_change_event": rel_change,
            "schema_change_event": schema_change
        },
        "plan_difference": plan_comparison,
        "plan_explanation": plan_comparison.get("explanation", ""),
        "change_context": change_ctx,
        "timeline": change_ctx.get("timeline", []),
        "evidence_strength": change_ctx.get("evidence_strength", "Insufficient evidence"),
        "possible_cause": change_ctx.get("possible_cause", ""),
        "schema_changes": change_ctx.get("schema_changes", []),
        "index_changes_detail": change_ctx.get("index_changes", []),
        "workload_analysis": change_ctx.get("workload_analysis", {}),
        "regression_score": regression_score,
        "score_breakdown": score_breakdown,
        "severity": severity,
        "regression_label": label,
        "priority": rule_eval.get("priority", severity),
        "rule_config_version": rule_eval.get("rule_config_version", "v1.0"),
        "triggered_rules": rule_eval.get("triggered_rules", []),
        "rule_explanation": rule_eval.get("explanation", ""),
        "evidence_sufficiency": rule_eval.get("evidence_sufficiency", {}),
        "reason": reason,
        "recommended_investigation_action": recommendations,
        "double_booking_risk": is_double_booking_critical and (severity in ("CRITICAL", "HIGH")),
        "evaluated_at": now_iso
    }

    return {
        "query_id": qid,
        "query_name": qname,
        "query_type": qtype,
        "is_regression": severity != "OK",
        "classification": label,
        "regression_label": label,
        "severity": severity,
        "priority": rule_eval.get("priority", severity),
        "rule_config_version": rule_eval.get("rule_config_version", "v1.0"),
        "triggered_rules": rule_eval.get("triggered_rules", []),
        "rule_explanation": rule_eval.get("explanation", ""),
        "evidence_sufficiency": rule_eval.get("evidence_sufficiency", {}),
        "regression_score": regression_score,
        "delta_ms_p95": round(delta_ms, 3),
        "pct_change": round(pct_change, 2),
        "plan_changed": plan_changed,
        "index_lost": index_lost,
        "has_new_scan": has_new_scan,
        "stats_flag": stats_stale or rows_drift_flag,
        "double_booking_risk": evidence_obj["double_booking_risk"],
        "evidence_strength": change_ctx.get("evidence_strength", "Insufficient evidence"),
        "change_context": change_ctx,
        "reason": reason,
        "evidence": evidence_obj
    }


def detect_batch_regressions(
    baseline_records: List[Dict[str, Any]],
    current_records: List[Dict[str, Any]],
    baseline_context: Optional[Dict[str, Any]] = None,
    current_context: Optional[Dict[str, Any]] = None,
    rules: Optional[Dict[str, Any]] = None,
    rules_path: str = DEFAULT_RULES_PATH
) -> List[Dict[str, Any]]:
    """
    Executes regression detection across a full batch of queries.
    Pairs query records by query_id and passes baseline/current contexts.
    """
    if rules is None:
        rules = rules_loader.load_rules(rules_path)

    base_map = {r.get("query_id"): r for r in baseline_records if r.get("query_id")}
    curr_map = {r.get("query_id"): r for r in current_records if r.get("query_id")}

    all_qids = sorted(set(base_map.keys()) | set(curr_map.keys()))
    findings = []

    for qid in all_qids:
        b = base_map.get(qid)
        c = curr_map.get(qid)

        if not b and c:
            # New query without baseline
            findings.append({
                "query_id": qid,
                "query_name": c.get("query_name", qid),
                "is_regression": False,
                "classification": "WARNING",
                "regression_label": "WARNING",
                "severity": "LOW",
                "regression_score": 20.0,
                "delta_ms_p95": 0.0,
                "pct_change": 0.0,
                "plan_changed": False,
                "index_lost": False,
                "has_new_scan": False,
                "stats_flag": False,
                "double_booking_risk": False,
                "reason": "New query introduced without baseline observation.",
                "evidence": {"query_id": qid, "note": "No baseline record available."}
            })
            continue

        if b and not c:
            # Query missing in run
            findings.append({
                "query_id": qid,
                "query_name": b.get("query_name", qid),
                "is_regression": True,
                "classification": "WARNING",
                "regression_label": "WARNING",
                "severity": "MEDIUM",
                "regression_score": 35.0,
                "delta_ms_p95": 0.0,
                "pct_change": 0.0,
                "plan_changed": False,
                "index_lost": False,
                "has_new_scan": False,
                "stats_flag": False,
                "double_booking_risk": False,
                "reason": "Query missing from post-change execution run.",
                "evidence": {"query_id": qid, "note": "Missing from target run."}
            })
            continue

        # Merge snapshot-level context if available
        b_merged = dict(b)
        c_merged = dict(c)
        if baseline_context:
            b_merged.setdefault("release_version", baseline_context.get("release_tag"))
        if current_context:
            c_merged.setdefault("release_version", current_context.get("release_tag"))
            c_merged.setdefault("schema_change", current_context.get("schema_change", "NONE"))
            c_merged.setdefault("release_change", current_context.get("release_change", "release_deployment"))

        finding = detect_query_regression(b_merged, c_merged, rules=rules)
        findings.append(finding)

    # Sort descending by regression score
    findings.sort(key=lambda x: -x.get("regression_score", 0.0))
    return findings
