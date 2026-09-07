"""
change_context_analyser.py
==========================
Phase 6: Change Context Analysis Layer for Hospital Appointment Platform.

Answers the critical question:
"What changed before this query became slow?"

Correlates:
1. Index changes (added, removed, modified, status changed, unused, missing)
2. Database statistics changes (staleness, age, updates, row drift)
3. Workload changes (NORMAL, INCREASED, HIGH, SPIKE) & causal classification
4. Schema changes (table, column, constraint, index DDL events)
5. Release history (deployments, version changes, chronological timeline)

Produces explainable correlation evidence with cautious, scientifically honest
attribution ("Strong evidence", "Likely contributor", "Possible contributor",
"Insufficient evidence").
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union

from src.core import rules_loader

DEFAULT_STALE_DAYS_THRESHOLD = 7
DEFAULT_WORKLOAD_SPIKE_PCT = 30.0


# ── 1. Index Change Analysis ──────────────────────────────────────────────────

def analyze_index_changes(
    before_indexes: Union[List[str], str, None],
    after_indexes: Union[List[str], str, None],
    query_id: Optional[str] = None,
    index_status_before: str = "ACTIVE",
    index_status_after: str = "ACTIVE",
    index_metadata: Optional[Dict[str, Any]] = None,
    plan_used_index_before: bool = True,
    plan_used_index_after: bool = True,
    has_full_scan_after: bool = False
) -> List[Dict[str, Any]]:
    """
    Analyzes index alterations between baseline and post-change states.
    Detects additions, removals, modifications, status shifts, index abandonment,
    and potentially missing indexes.
    """
    def _to_list(src: Any) -> List[str]:
        if isinstance(src, list):
            return [str(x) for x in src if x]
        if isinstance(src, str):
            if src.startswith("[") and src.endswith("]"):
                try:
                    return [str(x) for x in json.loads(src) if x]
                except Exception:
                    pass
            return [src] if src and src.upper() != "NONE" else []
        return []

    b_list = _to_list(before_indexes)
    a_list = _to_list(after_indexes)
    qids = [query_id] if query_id else []

    events = []

    # A. Index Removed
    removed = [idx for idx in b_list if idx not in a_list]
    for idx in removed:
        events.append({
            "index_name": idx,
            "change_type": "INDEX_REMOVED",
            "before_state": "ACTIVE",
            "after_state": "REMOVED",
            "affected_query_ids": qids,
            "impact": "HIGH_REGRESSION_RISK",
            "evidence": f"Potential performance regression because index '{idx}' was removed, potentially eliminating query index access path."
        })

    # B. Index Added
    added = [idx for idx in a_list if idx not in b_list]
    for idx in added:
        events.append({
            "index_name": idx,
            "change_type": "INDEX_ADDED",
            "before_state": "ABSENT",
            "after_state": "ACTIVE",
            "affected_query_ids": qids,
            "impact": "POSITIVE",
            "evidence": f"Index '{idx}' was newly added, providing potential optimization path."
        })

    # C. Index Status Changed
    if index_status_before != index_status_after:
        target_name = (a_list[0] if a_list else (b_list[0] if b_list else "index"))
        impact = "HIGH_REGRESSION_RISK" if index_status_after in ("REMOVED", "MISSING", "UNUSED", "DISABLED") else "NEUTRAL"
        events.append({
            "index_name": target_name,
            "change_type": "INDEX_STATUS_CHANGED",
            "before_state": index_status_before,
            "after_state": index_status_after,
            "affected_query_ids": qids,
            "impact": impact,
            "evidence": f"Index state shifted from '{index_status_before}' to '{index_status_after}'."
        })

    # D. Index Abandoned (Present in schema, but query optimizer stopped using it)
    if plan_used_index_before and not plan_used_index_after and not removed:
        for idx in a_list:
            events.append({
                "index_name": idx,
                "change_type": "INDEX_ABANDONED",
                "before_state": "USED_BY_PLAN",
                "after_state": "BYPASSED_BY_OPTIMIZER",
                "affected_query_ids": qids,
                "impact": "MODERATE_RISK",
                "evidence": f"Index '{idx}' is present in schema but was bypassed by query optimizer in favor of another access path."
            })

    # E. Potentially Missing Index
    if has_full_scan_after and not a_list:
        events.append({
            "index_name": "none",
            "change_type": "POTENTIALLY_MISSING",
            "before_state": "UNINDEXED_OR_UNKNOWN",
            "after_state": "FULL_SCAN_DETECTED",
            "affected_query_ids": qids,
            "impact": "HIGH_REGRESSION_RISK",
            "evidence": "Query executed a sequential table scan without supporting index; composite index on filter predicates recommended."
        })

    # F. Index Modified (from metadata if provided)
    if index_metadata and index_metadata.get("definition_changed"):
        idx_name = index_metadata.get("index_name", "index")
        events.append({
            "index_name": idx_name,
            "change_type": "INDEX_MODIFIED",
            "before_state": index_metadata.get("old_definition", "ORIGINAL"),
            "after_state": index_metadata.get("new_definition", "MODIFIED"),
            "affected_query_ids": qids,
            "impact": "MODERATE_RISK",
            "evidence": f"Index '{idx_name}' structure/columns were altered, which may impact predicate selectivity."
        })

    if not events:
        events.append({
            "index_name": (b_list[0] if b_list else "none"),
            "change_type": "NO_CHANGE",
            "before_state": index_status_before,
            "after_state": index_status_after,
            "affected_query_ids": qids,
            "impact": "NEUTRAL",
            "evidence": "Index definition and usage are stable between baseline and current observation."
        })

    return events


# ── 2. Statistics Analysis ────────────────────────────────────────────────────

def analyze_statistics_changes(
    before_stats: Optional[Dict[str, Any]],
    after_stats: Optional[Dict[str, Any]],
    query_id: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
    table_name: str = "appointments"
) -> Dict[str, Any]:
    """
    Analyzes database statistics staleness, age, and cardinality drift.
    Uses configurable thresholds without hard-coded limits.
    """
    threshold = DEFAULT_STALE_DAYS_THRESHOLD
    if rules:
        threshold = int(
            rules_loader.get_change_context_rule(rules, "stale_statistics_threshold_days", None)
            or rules_loader.get_staleness_threshold(rules, DEFAULT_STALE_DAYS_THRESHOLD)
        )

    b = before_stats or {}
    a = after_stats or {}
    qids = [query_id] if query_id else []

    age = int(a.get("statistics_age", a.get("statistics_age_days", b.get("statistics_age", 1))))
    status_raw = str(a.get("statistics_status", "CURRENT")).upper()

    b_rows = int(b.get("rows_examined", b.get("row_count", 0)) or 0)
    a_rows = int(a.get("rows_examined", a.get("row_count", b_rows)) or b_rows)
    row_drift_pct = abs(a_rows - b_rows) / b_rows * 100.0 if b_rows > 0 else 0.0

    has_stats_data = bool(
        "statistics_age" in a or "statistics_age_days" in a or "statistics_status" in a or "table_stats" in a
        or "statistics_age" in b or "statistics_age_days" in b or "statistics_status" in b or "table_stats" in b
    )

    # Determine status
    if not has_stats_data or (not a and not b):
        status = "MISSING"
        evidence = "Statistics metadata is missing or unrecorded for target table."
    elif age > threshold or status_raw == "STALE":
        status = "STALE"
        evidence = f"Statistics for table '{table_name}' are stale ({age} days old, threshold: {threshold} days). Stale statistics may contribute to an incorrect query plan if the optimizer's cost model relies on outdated cardinality."
    elif row_drift_pct >= 50.0:
        status = "UPDATED"
        evidence = f"Table statistics recorded significant row cardinality shift ({b_rows} -> {a_rows}, +{row_drift_pct:.1f}%)."
    else:
        status = "CURRENT"
        evidence = f"Table statistics are fresh (age: {age} days, threshold: {threshold} days)."

    return {
        "table_name": table_name,
        "statistics_name": f"stats_{table_name}",
        "age": age,
        "threshold": threshold,
        "status": status,
        "before_value": {"age_days": b.get("statistics_age", 1), "rows": b_rows},
        "after_value": {"age_days": age, "rows": a_rows},
        "row_drift_pct": round(row_drift_pct, 2),
        "affected_query_ids": qids,
        "evidence": evidence
    }


# ── 3. Workload Change Analysis ───────────────────────────────────────────────

def analyze_workload_changes(
    before_workload: Union[str, Dict[str, Any], None],
    after_workload: Union[str, Dict[str, Any], None],
    query_id: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
    plan_changed: bool = False,
    index_lost: bool = False,
    pct_latency_change: float = 0.0
) -> Dict[str, Any]:
    """
    Analyzes workload changes and classifies causal relationship:
    A. plan/query regression
    B. workload-induced slowdown
    C. mixed cause
    D. insufficient evidence
    """
    spike_threshold_pct = DEFAULT_WORKLOAD_SPIKE_PCT
    if rules:
        spike_threshold_pct = float(
            rules_loader.get_change_context_rule(rules, "workload_increase_threshold_pct", DEFAULT_WORKLOAD_SPIKE_PCT)
        )

    # Extract level and metrics
    if isinstance(before_workload, dict):
        b_lvl = str(before_workload.get("workload_level", "NORMAL")).upper()
        b_qps = float(before_workload.get("query_frequency", before_workload.get("qps", 10.0)))
        b_conc = int(before_workload.get("concurrent_requests", 5))
        b_count = int(before_workload.get("execution_count", 100))
    else:
        b_lvl = str(before_workload or "NORMAL").upper()
        b_qps, b_conc, b_count = 10.0, 5, 100

    if isinstance(after_workload, dict):
        a_lvl = str(after_workload.get("workload_level", "NORMAL")).upper()
        a_qps = float(after_workload.get("query_frequency", after_workload.get("qps", b_qps)))
        a_conc = int(after_workload.get("concurrent_requests", b_conc))
        a_count = int(after_workload.get("execution_count", b_count))
    else:
        a_lvl = str(after_workload or "NORMAL").upper()
        a_qps, a_conc, a_count = b_qps, b_conc, b_count

    # Classification
    level_weights = {"LOW": 1, "NORMAL": 2, "INCREASED": 3, "HIGH": 4, "PEAK": 5, "SPIKE": 5}
    b_score = level_weights.get(b_lvl, 2)
    a_score = level_weights.get(a_lvl, 2)

    if a_lvl in ("SPIKE", "PEAK") or (a_score - b_score >= 2):
        classification = "SPIKE"
    elif a_lvl == "HIGH" or (a_score - b_score == 1 and a_score >= 3):
        classification = "HIGH"
    elif a_lvl == "INCREASED" or a_qps > b_qps * 1.25:
        classification = "INCREASED"
    else:
        classification = "NORMAL"

    # Distinguish causal relationship
    has_structural_regression = plan_changed or index_lost
    is_workload_elevated = classification in ("SPIKE", "HIGH", "INCREASED")

    if not before_workload and not after_workload:
        cause_category = "D. insufficient evidence"
        explanation = "Insufficient workload telemetry available to evaluate concurrency impact."
    elif has_structural_regression and is_workload_elevated:
        cause_category = "C. mixed cause"
        explanation = f"Both a structural query/index change and elevated workload ({classification}) occurred concurrently."
    elif has_structural_regression and not is_workload_elevated:
        cause_category = "A. plan/query regression"
        explanation = f"Slowdown is attributable to query execution plan shift or index modification under normal workload ({a_lvl})."
    elif not has_structural_regression and is_workload_elevated and pct_latency_change > 0:
        cause_category = "B. workload-induced slowdown"
        explanation = f"Slowdown (+{pct_latency_change:.1f}%) is likely workload-induced concurrency contention ({classification}) with query plan and indexes intact."
    else:
        cause_category = "A. plan/query regression" if has_structural_regression else "D. insufficient evidence"
        explanation = "Workload metrics are consistent with baseline operations."

    return {
        "before_workload_level": b_lvl,
        "current_workload_level": a_lvl,
        "workload_classification": classification,
        "query_frequency_delta_pct": round(((a_qps - b_qps) / b_qps * 100.0) if b_qps > 0 else 0.0, 1),
        "concurrent_requests": a_conc,
        "cause_category": cause_category,
        "explanation": explanation
    }


# ── 4. Schema Change Analysis ─────────────────────────────────────────────────

def analyze_schema_changes(
    schema_events: Union[List[Dict[str, Any]], str, None],
    query_id: Optional[str] = None,
    table_name: Optional[str] = None,
    release_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Analyzes schema DDL events and correlates them with affected queries and tables.
    """
    if not schema_events:
        return []

    # Handle string event representation (e.g. "INDEX_DROPPED" or "DROP INDEX idx_appt")
    raw_list = []
    if isinstance(schema_events, str):
        if schema_events.upper() in ("NONE", ""):
            return []
        raw_list = [{
            "change_id": f"SCH-{datetime.now().strftime('%Y%m%d%H%M%S')}-01",
            "release_id": release_id or "REL-CURRENT",
            "timestamp": datetime.now().isoformat(),
            "affected_table": table_name or "appointments",
            "change_description": schema_events,
            "change_type": "INDEX_RELATED" if "INDEX" in schema_events.upper() else "TABLE_MODIFICATION"
        }]
    elif isinstance(schema_events, list):
        raw_list = schema_events

    parsed_events = []
    for ev in raw_list:
        desc = ev.get("change_description") or ev.get("event") or ev.get("schema_change") or str(ev)
        table = ev.get("affected_table") or table_name or "appointments"
        cid = ev.get("change_id") or f"SCH-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        rel = ev.get("release_id") or release_id or "REL-CURRENT"
        ts = ev.get("timestamp") or datetime.now().isoformat()

        # Determine relevance
        desc_upper = desc.upper()
        if "DROP" in desc_upper or "RENAME" in desc_upper or "MODIFY" in desc_upper:
            relevance = "DIRECT"
        elif "ADD" in desc_upper or "CREATE" in desc_upper:
            relevance = "INDIRECT"
        else:
            relevance = "DIRECT" if table in str(query_id or "") else "INDIRECT"

        parsed_events.append({
            "change_id": cid,
            "release_id": rel,
            "timestamp": ts,
            "affected_table": table,
            "affected_query_ids": [query_id] if query_id else [],
            "change_description": desc,
            "relevance": relevance
        })

    return parsed_events


# ── 5. Release History Analysis & Timeline Builder ────────────────────────────

def analyze_release_history(
    releases: Union[List[Dict[str, Any]], Dict[str, Any], None],
    current_release_id: Optional[str] = None,
    query_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Parses release history records and builds deployment context for affected queries.
    """
    if not releases:
        return {
            "current_release_id": current_release_id or "UNKNOWN",
            "release_version": "unknown",
            "deployment_timestamp": None,
            "schema_changes": [],
            "index_changes": [],
            "application_changes": [],
            "affected_queries": [query_id] if query_id else []
        }

    rel_list = [releases] if isinstance(releases, dict) else releases
    target = rel_list[-1]  # Most recent
    if current_release_id:
        match = [r for r in rel_list if r.get("release_id") == current_release_id or r.get("release_tag") == current_release_id or r.get("release_version") == current_release_id]
        if match:
            target = match[0]

    schema_ch = target.get("schema_changes", [])
    if isinstance(schema_ch, str):
        schema_ch = [schema_ch] if schema_ch and schema_ch != "NONE" else []

    index_ch = target.get("index_changes", [])
    if isinstance(index_ch, str):
        index_ch = [index_ch] if index_ch and index_ch != "NONE" else []

    app_ch = target.get("application_changes", target.get("changes", []))
    if isinstance(app_ch, str):
        app_ch = [app_ch]

    return {
        "release_id": target.get("release_id", target.get("release_tag", "REL-CURRENT")),
        "release_version": target.get("release_version", target.get("release_tag", "v1.0")),
        "deployment_timestamp": target.get("deployment_timestamp", target.get("released_at", datetime.now().isoformat())),
        "schema_changes": schema_ch,
        "index_changes": index_ch,
        "application_changes": app_ch,
        "affected_queries": target.get("affected_queries", [query_id] if query_id else [])
    }


def build_change_timeline(
    release_info: Dict[str, Any],
    schema_events: List[Dict[str, Any]],
    index_events: List[Dict[str, Any]],
    statistics_info: Dict[str, Any],
    workload_info: Dict[str, Any],
    plan_diff: Dict[str, Any],
    timing_info: Dict[str, Any]
) -> List[Dict[str, str]]:
    """
    Builds a chronological timeline of actual events for affected queries:
    Release -> Schema change -> Index change -> Statistics change -> Workload change -> Plan change -> Timing change
    """
    timeline = []

    # 1. Release Event
    rel_ver = release_info.get("release_version") or release_info.get("release_id") or "v1.0"
    timeline.append({
        "step": "1. Release Deployment",
        "event": f"Release {rel_ver} deployed",
        "detail": f"Target release identifier {release_info.get('release_id', rel_ver)}"
    })

    # 2. Schema Change Event
    if schema_events:
        for ev in schema_events:
            timeline.append({
                "step": "2. Schema Change",
                "event": ev.get("change_description", "Schema altered"),
                "detail": f"Table '{ev.get('affected_table', 'appointments')}' modified"
            })

    # 3. Index Change Event
    for idx_ev in index_events:
        if idx_ev.get("change_type") != "NO_CHANGE":
            timeline.append({
                "step": "3. Index Change",
                "event": f"Index {idx_ev['index_name']}: {idx_ev['change_type']}",
                "detail": idx_ev.get("evidence", "")
            })

    # 4. Statistics Event
    if statistics_info.get("status") == "STALE":
        timeline.append({
            "step": "4. Statistics Staleness",
            "event": f"Table statistics became stale ({statistics_info.get('age')} days old)",
            "detail": f"Exceeded threshold of {statistics_info.get('threshold')} days"
        })

    # 5. Workload Event
    if workload_info.get("workload_classification") in ("SPIKE", "HIGH", "INCREASED"):
        timeline.append({
            "step": "5. Workload Shift",
            "event": f"Workload surge detected ({workload_info.get('workload_classification')})",
            "detail": f"Cause categorization: {workload_info.get('cause_category')}"
        })

    # 6. Plan Change Event
    if plan_diff.get("plan_changed", False):
        scan_desc = plan_diff.get("scan_diff", {}).get("scan_transition", "PLAN_MODIFIED")
        timeline.append({
            "step": "6. Execution Plan Change",
            "event": f"Query execution plan shifted ({scan_desc})",
            "detail": plan_diff.get("reason", "Plan hash altered")
        })

    # 7. Execution Time Impact
    delta_pct = timing_info.get("pct_change", 0.0)
    if delta_pct >= 20.0:
        b_t = timing_info.get("baseline_ms", 0.0)
        c_t = timing_info.get("current_ms", 0.0)
        timeline.append({
            "step": "7. Latency Surge",
            "event": f"Execution latency increased: {b_t:.1f}ms → {c_t:.1f}ms (+{delta_pct:.1f}%)",
            "detail": "Regression threshold breached"
        })

    return timeline


# ── 6. Change Correlation Engine ──────────────────────────────────────────────

def correlate_change_context(
    query_id: str,
    before_state: Dict[str, Any],
    after_state: Dict[str, Any],
    plan_diff: Optional[Dict[str, Any]] = None,
    rules: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Main Change Correlation Function.
    Correlates release, schema, index, statistics, workload, and plan changes.
    Assigns cautious confidence assessment:
    - "Strong evidence"
    - "Likely contributor"
    - "Possible contributor"
    - "Insufficient evidence"
    """
    if rules is None:
        try:
            rules = rules_loader.load_rules()
        except Exception:
            rules = {}

    table_name = before_state.get("table", after_state.get("table", "appointments"))

    # Timing metrics
    b_ms = float(before_state.get("execution_time_ms", 1.0) or 1.0)
    a_ms = float(after_state.get("execution_time_ms", 0.0) or 0.0)
    delta_ms = a_ms - b_ms
    pct_change = (delta_ms / b_ms * 100.0) if b_ms > 0 else 0.0

    # 1. Index Change Analysis
    b_indexes = before_state.get("indexes", [])
    a_indexes = after_state.get("indexes", [])
    idx_stat_before = before_state.get("index_status", "ACTIVE")
    idx_stat_after = after_state.get("index_status", "ACTIVE")
    has_scan = bool(after_state.get("has_full_scan") or after_state.get("is_full_scan"))

    index_events = analyze_index_changes(
        before_indexes=b_indexes,
        after_indexes=a_indexes,
        query_id=query_id,
        index_status_before=idx_stat_before,
        index_status_after=idx_stat_after,
        has_full_scan_after=has_scan
    )

    # 2. Statistics Analysis
    stats_analysis = analyze_statistics_changes(
        before_stats=before_state,
        after_stats=after_state,
        query_id=query_id,
        rules=rules,
        table_name=table_name
    )

    # 3. Workload Analysis
    plan_changed = bool(plan_diff.get("plan_changed")) if plan_diff else False
    index_lost = any(ev["change_type"] in ("INDEX_REMOVED", "INDEX_STATUS_CHANGED") for ev in index_events if ev.get("impact") == "HIGH_REGRESSION_RISK")

    workload_analysis = analyze_workload_changes(
        before_workload=before_state.get("workload_level", "NORMAL"),
        after_workload=after_state.get("workload_level", "NORMAL"),
        query_id=query_id,
        rules=rules,
        plan_changed=plan_changed,
        index_lost=index_lost,
        pct_latency_change=pct_change
    )

    # 4. Schema Change Analysis
    schema_raw = after_state.get("schema_change") or before_state.get("schema_change")
    schema_events = analyze_schema_changes(
        schema_events=schema_raw,
        query_id=query_id,
        table_name=table_name,
        release_id=after_state.get("release_id")
    )

    # 5. Release History Analysis
    rel_info = analyze_release_history(
        releases=after_state.get("release_history") or {
            "release_id": after_state.get("release_id", "REL-CURRENT"),
            "release_version": after_state.get("release_version", "v1.1"),
            "deployment_timestamp": after_state.get("timestamp", datetime.now().isoformat()),
            "schema_changes": [schema_raw] if schema_raw and schema_raw != "NONE" else [],
            "index_changes": [e["index_name"] for e in index_events if e["change_type"] != "NO_CHANGE"],
            "application_changes": [after_state.get("release_change", "release_deployment")]
        },
        current_release_id=after_state.get("release_id"),
        query_id=query_id
    )

    # 6. Timeline Construction
    timing_info = {"baseline_ms": b_ms, "current_ms": a_ms, "pct_change": pct_change}
    timeline = build_change_timeline(
        release_info=rel_info,
        schema_events=schema_events,
        index_events=index_events,
        statistics_info=stats_analysis,
        workload_info=workload_analysis,
        plan_diff=plan_diff or {},
        timing_info=timing_info
    )

    # 7. Correlation & Confidence Assessment
    # Weights and signals
    confidence = "Insufficient evidence"
    possible_causes = []
    supporting_evidence = []

    has_index_loss = index_lost or (plan_diff and plan_diff.get("scan_diff", {}).get("index_to_full_scan"))
    has_plan_shift = plan_changed or (plan_diff and plan_diff.get("plan_changed"))
    has_latency_surge = pct_change >= 20.0
    is_stats_stale = stats_analysis.get("status") == "STALE"
    is_workload_elevated = workload_analysis.get("workload_classification") in ("SPIKE", "HIGH")

    # Check if any change context metadata is actually available
    has_change_metadata = bool(
        before_state.get("indexes") or after_state.get("indexes")
        or before_state.get("schema_change") or after_state.get("schema_change")
        or before_state.get("release_version") or after_state.get("release_version")
        or before_state.get("release_id") or after_state.get("release_id")
        or before_state.get("statistics_age") or after_state.get("statistics_age")
        or before_state.get("workload_level") or after_state.get("workload_level")
        or (plan_diff and plan_diff.get("plan_changed"))
    )

    # Evaluate correlation strength
    if not has_change_metadata:
        confidence = "Insufficient evidence"
        possible_causes.append("Insufficient change-context metadata available to correlate execution variance with database changes.")
        supporting_evidence.append("No release, schema, index, or statistics history available in input records.")
    elif has_index_loss and has_plan_shift and has_latency_surge:
        confidence = "Strong evidence"
        possible_causes.append("Index removal or alteration caused optimizer access path regression to sequential table scan.")
        supporting_evidence.append(f"Query changed from index scan to full table scan with +{pct_change:.1f}% latency increase.")
    elif is_stats_stale and has_plan_shift and has_latency_surge:
        confidence = "Likely contributor"
        possible_causes.append("Stale table statistics may have degraded query planner cardinality estimates, resulting in sub-optimal access path.")
        supporting_evidence.append(f"Table statistics age ({stats_analysis.get('age')} days) exceeds freshness threshold.")
    elif is_workload_elevated and not has_plan_shift and has_latency_surge:
        confidence = "Likely contributor"
        possible_causes.append("Concurrent execution contention and queueing under elevated operational workload.")
        supporting_evidence.append(f"Workload escalated to '{workload_analysis.get('workload_classification')}' with query plan unchanged.")
    elif has_latency_surge and (schema_events or any(e["change_type"] != "NO_CHANGE" for e in index_events)):
        confidence = "Possible contributor"
        possible_causes.append("Recent release DDL migrations correlate with observed execution variance.")
        supporting_evidence.append("Schema or index alterations detected in release deployment window.")
    elif has_latency_surge:
        confidence = "Possible contributor"
        possible_causes.append("Execution time variance observed; root-cause correlation inconclusive.")
        supporting_evidence.append(f"Latency drifted by +{pct_change:.1f}%.")
    else:
        # Performance stable
        confidence = "Insufficient evidence"
        possible_causes.append("Query execution conforms to normal operational parameters.")
        supporting_evidence.append("No adverse performance or plan degradation observed.")

    return {
        "query_id": query_id,
        "affected_database_object": table_name,
        "release_information": rel_info,
        "index_changes": index_events,
        "statistics_status": stats_analysis,
        "workload_analysis": workload_analysis,
        "schema_changes": schema_events,
        "timeline": timeline,
        "relevant_changes": [e for e in index_events if e["change_type"] != "NO_CHANGE"] + schema_events,
        "supporting_evidence": supporting_evidence,
        "possible_cause": possible_causes[0] if possible_causes else "No significant change detected.",
        "confidence": confidence,
        "evidence_strength": confidence
    }
