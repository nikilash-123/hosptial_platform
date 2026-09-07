"""
plan_extractor.py
==================
Runs EXPLAIN QUERY PLAN on a SQL query and parses the output into
structured plan nodes. Detects index usage and SCAN vs SEARCH access patterns.
"""

import sqlite3
import re
from typing import List, Dict, Any, Tuple


def extract_plan(conn: sqlite3.Connection, sql: str) -> Dict[str, Any]:
    """
    Run EXPLAIN QUERY PLAN and return a structured plan dict.

    Returns:
        {
          "raw": str,               # raw EXPLAIN output lines
          "nodes": list[dict],      # parsed plan nodes
          "uses_index": bool,       # True if any index is used
          "index_names": list[str], # list of index names referenced
          "has_full_scan": bool,    # True if any SCAN (no index) found
          "row_est": int,           # estimated rows from EXPLAIN (best-effort)
        }
    """
    try:
        rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
    except sqlite3.Error as e:
        return _error_plan(str(e))

    nodes = []
    raw_lines = []
    index_names = []
    has_full_scan = False
    uses_index = False
    row_est = 0

    for row in rows:
        # SQLite EXPLAIN QUERY PLAN columns: id, parent, notused, detail
        detail = row[3] if len(row) >= 4 else str(row)
        raw_lines.append(detail)

        node = _parse_node(detail)
        nodes.append(node)

        if node["access_type"] in ("INDEX", "SEARCH"):
            uses_index = True
        if node["access_type"] == "SCAN":
            has_full_scan = True

        for idx in node["indexes"]:
            if idx and idx not in index_names:
                index_names.append(idx)

        # Row estimate from plan detail (e.g. "~1000 rows")
        m = re.search(r"~(\d+)\s+rows", detail)
        if m:
            row_est = max(row_est, int(m.group(1)))

    return {
        "raw": "\n".join(raw_lines),
        "nodes": nodes,
        "uses_index": uses_index,
        "index_names": index_names,
        "has_full_scan": has_full_scan,
        "row_est": row_est,
    }


def _parse_node(detail: str) -> Dict[str, Any]:
    """Parse a single EXPLAIN QUERY PLAN detail string into a structured node."""
    detail_upper = detail.upper()

    # Determine access type
    access_type = "OTHER"
    if re.search(r"\bSCAN\b", detail_upper) and not re.search(r"\bUSING\s+INDEX\b", detail_upper):
        access_type = "SCAN"
    elif re.search(r"\bSEARCH\b", detail_upper) or re.search(r"\bUSING\s+INDEX\b", detail_upper):
        access_type = "SEARCH"
    elif re.search(r"\bUSING\s+COVERING\s+INDEX\b", detail_upper):
        access_type = "INDEX"
    elif re.search(r"\bINDEX\b", detail_upper):
        access_type = "INDEX"

    # Extract index names
    indexes = re.findall(r"USING(?:\s+COVERING)?\s+INDEX\s+(\w+)", detail, re.IGNORECASE)
    indexes += re.findall(r"INDEX\s+(\w+)", detail, re.IGNORECASE)
    indexes = list(set(indexes))

    # Extract table name
    table_match = re.search(
        r"(?:SCAN|SEARCH)\s+(?:TABLE\s+)?(\w+)", detail, re.IGNORECASE
    )
    table = table_match.group(1) if table_match else ""

    return {
        "detail": detail,
        "access_type": access_type,
        "table": table,
        "indexes": indexes,
    }


def plans_differ(plan_a: Dict[str, Any], plan_b: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Compare two plans. Returns (changed: bool, diff_summary: str).
    """
    if plan_a.get("raw") == plan_b.get("raw"):
        return False, "Plans identical"

    changes = []

    # Index loss detection
    old_indexes = set(plan_a.get("index_names", []))
    new_indexes = set(plan_b.get("index_names", []))
    lost = old_indexes - new_indexes
    gained = new_indexes - old_indexes

    if lost:
        changes.append(f"Lost indexes: {sorted(lost)}")
    if gained:
        changes.append(f"Gained indexes: {sorted(gained)}")

    # Scan regression
    if not plan_a.get("has_full_scan") and plan_b.get("has_full_scan"):
        changes.append("New FULL TABLE SCAN appeared (was using index)")

    if plan_a.get("uses_index") and not plan_b.get("uses_index"):
        changes.append("Query stopped using any index")

    # Generic change
    if not changes:
        changes.append("Query plan structure changed (see raw diff)")

    return True, "; ".join(changes)


def _error_plan(error_msg: str) -> Dict[str, Any]:
    return {
        "raw": f"ERROR: {error_msg}",
        "nodes": [],
        "uses_index": False,
        "index_names": [],
        "has_full_scan": False,
        "row_est": 0,
        "error": error_msg,
    }
