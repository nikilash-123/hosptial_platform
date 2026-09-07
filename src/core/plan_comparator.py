"""
plan_comparator.py
==================
Execution Plan Comparison Module for Hospital Appointment Platform.

Compares baseline and current execution plans across multiple characteristics:
- Plan Hash (SHA-256 fingerprint)
- Scan Type (Index Scan / Search vs Table / Full Scan)
- Estimated Rows & Actual Rows examined
- Estimated Cost, CPU Cost, and IO Cost
- Join Strategy (Nested Loop, Hash Join, Merge Join)
- Sort Operations (e.g. temporary B-Tree or in-memory sorting)
- Filter Operations (residual filters, non-sargable predicates)
- Index Usage (retained, lost, or added indexes)

Generates:
1. Structured plan difference dictionary
2. Deterministic human-readable explanation of WHY the plan changed
3. Remediation recommendations for DBAs and Release Engineers
"""

import re
import hashlib
from typing import Dict, Any, List, Optional, Union


def normalize_plan_input(plan: Union[str, Dict[str, Any], None]) -> Dict[str, Any]:
    """
    Normalizes various input formats (JSON dict, raw EXPLAIN text, or None)
    into a standard structured plan dictionary.
    """
    if plan is None:
        return {
            "plan_hash": "none",
            "raw_text": "",
            "scan_type": "Unknown",
            "is_full_scan": False,
            "uses_index": False,
            "indexes": [],
            "table": "",
            "estimated_rows": 0,
            "actual_rows": 0,
            "estimated_cost": 0.0,
            "cpu_cost": 0.0,
            "io_cost": 0.0,
            "join_strategy": "None",
            "sort_operations": [],
            "filter_operations": [],
            "nodes": []
        }

    if isinstance(plan, dict):
        raw_text = str(plan.get("raw_text") or plan.get("raw") or plan.get("plan_text") or plan.get("detail") or "")
        nodes = plan.get("nodes", [])

        # Extract or infer indexes
        indexes = plan.get("indexes") or plan.get("index_names") or []
        if isinstance(indexes, str):
            indexes = [indexes] if indexes and indexes != "None" else []
        elif not isinstance(indexes, list):
            indexes = []

        # Infer scan type
        scan_type = plan.get("scan_type")
        is_full_scan = bool(plan.get("has_full_scan") or plan.get("is_full_scan"))
        uses_index = bool(plan.get("uses_index") or len(indexes) > 0)

        if not scan_type:
            raw_upper = raw_text.upper()
            if "SCAN TABLE" in raw_upper and "USING INDEX" not in raw_upper:
                scan_type = "Full Table Scan"
                is_full_scan = True
            elif "USING COVERING INDEX" in raw_upper:
                scan_type = "Covering Index Scan"
                uses_index = True
            elif "USING INDEX" in raw_upper or "SEARCH TABLE" in raw_upper:
                scan_type = "Index Scan"
                uses_index = True
            elif uses_index:
                scan_type = "Index Scan"
            elif is_full_scan:
                scan_type = "Full Table Scan"
            else:
                scan_type = "Table Scan" if "SCAN" in raw_upper else "Index Search" if "SEARCH" in raw_upper else "Scan"

        # If raw text mentions index but list is empty
        if not indexes and raw_text:
            found_idx = re.findall(r"USING(?:\s+COVERING)?\s+INDEX\s+(\w+)", raw_text, re.IGNORECASE)
            if found_idx:
                indexes = list(set(found_idx))
                uses_index = True

        # Extract joins, sorts, filters if not explicitly provided
        join_strategy = plan.get("join_strategy")
        if not join_strategy:
            raw_upper = raw_text.upper()
            if "HASH JOIN" in raw_upper:
                join_strategy = "Hash Join"
            elif "MERGE JOIN" in raw_upper:
                join_strategy = "Merge Join"
            elif "NESTED LOOP" in raw_upper:
                join_strategy = "Nested Loop"
            elif "JOIN" in raw_upper:
                join_strategy = "Nested Loop"
            else:
                join_strategy = "None"

        sort_operations = list(plan.get("sort_operations") or [])
        if not sort_operations and raw_text:
            if "USE TEMP B-TREE FOR ORDER BY" in raw_text.upper():
                sort_operations.append("Temporary B-Tree Sort (ORDER BY)")
            if "USE TEMP B-TREE FOR GROUP BY" in raw_text.upper():
                sort_operations.append("Temporary B-Tree Sort (GROUP BY)")

        filter_operations = list(plan.get("filter_operations") or [])

        # Plan hash
        plan_hash = plan.get("plan_hash")
        if not plan_hash and raw_text:
            plan_hash = hashlib.sha256(raw_text.strip().encode("utf-8")).hexdigest()[:16]
        elif not plan_hash:
            plan_hash = "unhashed"

        # Costs and Rows
        estimated_cost = float(plan.get("estimated_cost") or plan.get("cost") or 0.0)
        cpu_cost = float(plan.get("cpu_cost") or plan.get("cpu_time_ms") or 0.0)
        io_cost = float(plan.get("io_cost") or 0.0)
        estimated_rows = int(plan.get("estimated_rows") or plan.get("row_est") or plan.get("rows_examined") or 0)
        actual_rows = int(plan.get("actual_rows") or plan.get("rows_returned") or 0)
        table = str(plan.get("table") or "")

        return {
            "plan_hash": plan_hash,
            "raw_text": raw_text,
            "scan_type": scan_type,
            "is_full_scan": is_full_scan,
            "uses_index": uses_index,
            "indexes": indexes,
            "table": table,
            "estimated_rows": estimated_rows,
            "actual_rows": actual_rows,
            "estimated_cost": estimated_cost,
            "cpu_cost": cpu_cost,
            "io_cost": io_cost,
            "join_strategy": join_strategy,
            "sort_operations": sort_operations,
            "filter_operations": filter_operations,
            "nodes": nodes
        }

    elif isinstance(plan, str):
        # Raw text string
        raw_text = plan.strip()
        raw_upper = raw_text.upper()

        is_full_scan = bool(re.search(r"\bSCAN\b", raw_upper) and not re.search(r"\bUSING\s+INDEX\b", raw_upper))
        uses_index = bool(re.search(r"\bUSING(?:\s+COVERING)?\s+INDEX\b", raw_upper) or re.search(r"\bSEARCH\b", raw_upper))

        scan_type = "Full Table Scan" if is_full_scan else ("Covering Index Scan" if "USING COVERING INDEX" in raw_upper else ("Index Scan" if uses_index else "Table Scan"))
        indexes = list(set(re.findall(r"USING(?:\s+COVERING)?\s+INDEX\s+(\w+)", raw_text, re.IGNORECASE)))

        table_m = re.search(r"(?:SCAN|SEARCH)\s+(?:TABLE\s+)?(\w+)", raw_text, re.IGNORECASE)
        table = table_m.group(1) if table_m else ""

        plan_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]

        sort_ops = []
        if "USE TEMP B-TREE FOR ORDER BY" in raw_upper:
            sort_ops.append("Temporary B-Tree Sort (ORDER BY)")
        if "USE TEMP B-TREE FOR GROUP BY" in raw_upper:
            sort_ops.append("Temporary B-Tree Sort (GROUP BY)")

        # Extract cost/rows if present in string like "cost=20.5 rows=100"
        cost_m = re.search(r"(?:cost|estimated_cost)[=:\s]+([\d\.]+)", raw_text, re.IGNORECASE)
        rows_m = re.search(r"(?:rows|rows_examined)[=:\s]+(\d+)", raw_text, re.IGNORECASE)

        return {
            "plan_hash": plan_hash,
            "raw_text": raw_text,
            "scan_type": scan_type,
            "is_full_scan": is_full_scan,
            "uses_index": uses_index,
            "indexes": indexes,
            "table": table,
            "estimated_rows": int(rows_m.group(1)) if rows_m else 0,
            "actual_rows": 0,
            "estimated_cost": float(cost_m.group(1)) if cost_m else 0.0,
            "cpu_cost": 0.0,
            "io_cost": 0.0,
            "join_strategy": "Nested Loop" if "JOIN" in raw_upper else "None",
            "sort_operations": sort_ops,
            "filter_operations": [],
            "nodes": []
        }

    return normalize_plan_input(None)


def compare_execution_plans(
    baseline_plan: Union[str, Dict[str, Any], None],
    current_plan: Union[str, Dict[str, Any], None]
) -> Dict[str, Any]:
    """
    Compares baseline and current execution plans and identifies all structural,
    cost, row, index, and operational discrepancies.

    Returns a comprehensive dictionary with differences and an explainable WHY narrative.
    """
    bp = normalize_plan_input(baseline_plan)
    cp = normalize_plan_input(current_plan)

    # 1. Plan Hash Comparison
    hash_changed = (bp["plan_hash"] != cp["plan_hash"]) and (bp["plan_hash"] != "none" and cp["plan_hash"] != "none")

    # 2. Scan Type Comparison
    scan_changed = (bp["scan_type"].lower() != cp["scan_type"].lower())
    index_to_full_scan = (bp["uses_index"] and not cp["uses_index"]) or (not bp["is_full_scan"] and cp["is_full_scan"])
    full_to_index_scan = (bp["is_full_scan"] and not cp["is_full_scan"]) or (not bp["uses_index"] and cp["uses_index"])

    scan_transition = "UNCHANGED"
    if index_to_full_scan:
        scan_transition = "INDEX_TO_FULL_SCAN"
    elif full_to_index_scan:
        scan_transition = "FULL_SCAN_TO_INDEX"
    elif scan_changed:
        scan_transition = "SCAN_TYPE_MODIFIED"

    # 3. Index Usage Comparison
    b_indexes = bp["indexes"]
    c_indexes = cp["indexes"]
    lost_indexes = [idx for idx in b_indexes if idx not in c_indexes]
    added_indexes = [idx for idx in c_indexes if idx not in b_indexes]

    # 4. Cost Comparison
    b_cost = bp["estimated_cost"]
    c_cost = cp["estimated_cost"]
    cost_delta = c_cost - b_cost
    cost_pct_change = ((cost_delta / b_cost) * 100.0) if b_cost > 0 else (100.0 if c_cost > 0 else 0.0)

    b_cpu = bp["cpu_cost"]
    c_cpu = cp["cpu_cost"]
    cpu_delta = c_cpu - b_cpu
    cpu_pct_change = ((cpu_delta / b_cpu) * 100.0) if b_cpu > 0 else (100.0 if c_cpu > 0 else 0.0)

    b_io = bp["io_cost"]
    c_io = cp["io_cost"]
    io_delta = c_io - b_io
    io_pct_change = ((io_delta / b_io) * 100.0) if b_io > 0 else (100.0 if c_io > 0 else 0.0)

    # 5. Row Estimates & Actuals
    b_est_rows = bp["estimated_rows"]
    c_est_rows = cp["estimated_rows"]
    rows_delta = c_est_rows - b_est_rows
    rows_pct_change = ((rows_delta / b_est_rows) * 100.0) if b_est_rows > 0 else (100.0 if c_est_rows > 0 else 0.0)

    # 6. Join Strategy
    b_join = bp["join_strategy"]
    c_join = cp["join_strategy"]
    join_strategy_changed = (b_join != c_join) and (b_join != "None" or c_join != "None")

    # 7. Sort Operations
    b_sorts = set(bp["sort_operations"])
    c_sorts = set(cp["sort_operations"])
    added_sorts = list(c_sorts - b_sorts)
    removed_sorts = list(b_sorts - c_sorts)

    # 8. Filter Operations
    b_filters = set(bp["filter_operations"])
    c_filters = set(cp["filter_operations"])
    added_filters = list(c_filters - b_filters)
    removed_filters = list(b_filters - c_filters)

    # Determine overall plan change flag
    plan_meaningfully_changed = bool(
        hash_changed or index_to_full_scan or full_to_index_scan or
        lost_indexes or added_indexes or join_strategy_changed or
        added_sorts or (abs(cost_pct_change) >= 20.0 and (b_cost > 0 or c_cost > 0)) or
        (abs(rows_pct_change) >= 50.0 and (b_est_rows > 0 or c_est_rows > 0))
    )

    # ── Derive Severity and Human-Readable WHY Explanation ────────────────────
    reasons = []
    explanation_parts = []
    recommendations = []
    severity = "OK"

    # Case A: Critical Index Loss / Full Table Scan Regression
    if index_to_full_scan:
        severity = "CRITICAL"
        idx_str = f" ({', '.join(lost_indexes)})" if lost_indexes else (f" ({', '.join(b_indexes)})" if b_indexes else "")
        reasons.append(f"Query access path degraded from {bp['scan_type']}{idx_str} to {cp['scan_type']}.")
        
        cost_phrase = ""
        if c_cost > 0 or b_cost > 0:
            cost_phrase = f" and estimated cost increased from {b_cost:.1f} to {c_cost:.1f} (+{cost_pct_change:.1f}%)"

        row_phrase = ""
        if c_est_rows > b_est_rows and b_est_rows > 0:
            row_phrase = f", with rows examined increasing from {b_est_rows} to {c_est_rows} (+{rows_pct_change:.1f}%)"

        explanation_parts.append(
            f"Potential regression because the query changed from {bp['scan_type']}{idx_str} to {cp['scan_type']}{cost_phrase}{row_phrase}."
        )
        recommendations.append(f"Restore supporting index {b_indexes} to eliminate sequential scan on {cp['table'] or 'target table'}.")

    # Case B: Significant Cost Surge without Full Scan
    elif cost_pct_change >= 50.0 and (b_cost > 0 or c_cost > 0):
        if severity != "CRITICAL":
            severity = "HIGH"
        reasons.append(f"Estimated query cost surged by +{cost_pct_change:.1f}% (from {b_cost:.1f} to {c_cost:.1f}).")
        explanation_parts.append(
            f"Query planner estimated cost increased significantly from {b_cost:.1f} to {c_cost:.1f} (+{cost_pct_change:.1f}%), indicating resource-heavy plan divergence."
        )
        recommendations.append("Investigate optimizer statistics; cost increase may stem from cardinality misestimation or join reordering.")

    # Case C: CPU or IO Cost Surge
    if cpu_pct_change >= 50.0 and b_cpu > 0:
        if severity == "OK":
            severity = "HIGH"
        reasons.append(f"CPU cost increased by +{cpu_pct_change:.1f}%.")
        explanation_parts.append(f"Processor time escalated from {b_cpu:.1f}ms to {c_cpu:.1f}ms (+{cpu_pct_change:.1f}%).")

    if io_pct_change >= 50.0 and b_io > 0:
        if severity == "OK":
            severity = "HIGH"
        reasons.append(f"I/O cost increased by +{io_pct_change:.1f}%.")
        explanation_parts.append(f"Storage buffer reads jumped from {b_io:.1f} to {c_io:.1f} (+{io_pct_change:.1f}%).")

    # Case D: Join Strategy Regression
    if join_strategy_changed:
        if b_join == "Hash Join" and c_join == "Nested Loop":
            if severity == "OK":
                severity = "HIGH"
            reasons.append(f"Join strategy regressed from {b_join} to unindexed {c_join}.")
            explanation_parts.append(
                f"Join algorithm shifted from efficient {b_join} to {c_join}, which multiplies row access across outer and inner tables."
            )
            recommendations.append("Verify foreign key indexes on join predicates to allow optimizer to select hash or merge joins.")
        else:
            if severity == "OK":
                severity = "MEDIUM"
            reasons.append(f"Join strategy modified from {b_join} to {c_join}.")
            explanation_parts.append(f"Join strategy altered from {b_join} to {c_join}.")

    # Case E: Added Temporary Sort Operations
    if added_sorts:
        if severity == "OK":
            severity = "MEDIUM"
        sort_names = ", ".join(added_sorts)
        reasons.append(f"Plan introduced temporary sorting overhead: {sort_names}.")
        explanation_parts.append(
            f"Optimizer was unable to utilize index order for sorting and injected temporary disk/B-Tree sort operation ({sort_names})."
        )
        recommendations.append("Add covering index with matching ORDER BY columns to eliminate explicit sorting phase.")

    # Case F: Rows Examined Surge (Optimizer Underestimation)
    if rows_pct_change >= 100.0 and b_est_rows > 0:
        if severity == "OK":
            severity = "MEDIUM"
        reasons.append(f"Rows examined drifted by +{rows_pct_change:.1f}% (from {b_est_rows} to {c_est_rows}).")
        explanation_parts.append(f"Data volume scanned surged from {b_est_rows} to {c_est_rows} rows (+{rows_pct_change:.1f}%).")
        recommendations.append("Run 'ANALYZE' to refresh table histograms and update optimizer cardinality calculations.")

    # Case G: Plan Improved (Full Scan to Index)
    if full_to_index_scan:
        severity = "OK"
        idx_str = f" ({', '.join(added_indexes)})" if added_indexes else ""
        reasons.append(f"Plan improved: switched from {bp['scan_type']} to optimized {cp['scan_type']}{idx_str}.")
        explanation_parts.append(
            f"Query execution improved because access path transitioned from {bp['scan_type']} to {cp['scan_type']}{idx_str}."
        )
        recommendations.append("Approve change; index addition successfully eliminated sequential table scan.")

    # Case H: Plan Hash Changed but no major regression detected
    if hash_changed and not reasons:
        severity = "MEDIUM"
        reasons.append(f"Plan hash shifted from {bp['plan_hash']} to {cp['plan_hash']}.")
        explanation_parts.append(f"Query plan graph nodes shifted from hash {bp['plan_hash']} to {cp['plan_hash']}.")
        recommendations.append("Verify query results and execution time variance across representative sample.")

    # Default Case: No Plan Change
    if not plan_meaningfully_changed and not reasons:
        severity = "OK"
        reasons.append(f"Execution plan conforms to baseline (Plan Hash: {bp['plan_hash']}).")
        explanation_parts.append(
            f"No meaningful plan change detected. Access type ({bp['scan_type']}) and index usage are consistent with verified baseline."
        )
        recommendations.append("No action required; query execution plan is optimal.")

    # Compose final narrative
    human_explanation = " ".join(explanation_parts)
    primary_reason = reasons[0] if reasons else "Plan consistent with baseline."

    return {
        "plan_changed": plan_meaningfully_changed,
        "plan_hash_diff": {
            "baseline_hash": bp["plan_hash"],
            "current_hash": cp["plan_hash"],
            "hash_changed": hash_changed
        },
        "scan_diff": {
            "baseline_scan_type": bp["scan_type"],
            "current_scan_type": cp["scan_type"],
            "scan_transition": scan_transition,
            "index_to_full_scan": index_to_full_scan,
            "full_to_index_scan": full_to_index_scan,
            "is_full_scan_introduced": cp["is_full_scan"] and not bp["is_full_scan"]
        },
        "index_diff": {
            "baseline_indexes": b_indexes,
            "current_indexes": c_indexes,
            "lost_indexes": lost_indexes,
            "added_indexes": added_indexes,
            "indexes_lost_count": len(lost_indexes)
        },
        "cost_diff": {
            "baseline_estimated_cost": b_cost,
            "current_estimated_cost": c_cost,
            "cost_delta": round(cost_delta, 2),
            "cost_pct_change": round(cost_pct_change, 2),
            "baseline_cpu_cost": b_cpu,
            "current_cpu_cost": c_cpu,
            "cpu_pct_change": round(cpu_pct_change, 2),
            "baseline_io_cost": b_io,
            "current_io_cost": c_io,
            "io_pct_change": round(io_pct_change, 2)
        },
        "rows_diff": {
            "baseline_estimated_rows": b_est_rows,
            "current_estimated_rows": c_est_rows,
            "rows_examined_delta": rows_delta,
            "rows_pct_change": round(rows_pct_change, 2),
            "baseline_actual_rows": bp["actual_rows"],
            "current_actual_rows": cp["actual_rows"]
        },
        "join_diff": {
            "baseline_strategy": b_join,
            "current_strategy": c_join,
            "strategy_changed": join_strategy_changed
        },
        "operations_diff": {
            "added_sort_operations": added_sorts,
            "removed_sort_operations": removed_sorts,
            "added_filter_operations": added_filters,
            "removed_filter_operations": removed_filters
        },
        "severity": severity,
        "reason": primary_reason,
        "explanation": human_explanation,
        "recommendations": recommendations
    }
