"""
snapshot_store.py
==================
Manages reading and writing snapshots (baselines + runs) to detector_store.db.
"""

import sqlite3
import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_STORE_PATH = os.path.join(BASE_DIR, "data", "detector_store.db")


def _connect(store_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(store_path), exist_ok=True)
    conn = sqlite3.connect(store_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_store(store_path: str = DEFAULT_STORE_PATH) -> None:
    """Create the detector_store schema if it doesn't exist."""
    conn = _connect(store_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            release_tag   TEXT NOT NULL,
            snapshot_type TEXT NOT NULL,
            captured_at   DATETIME NOT NULL,
            db_size_bytes INTEGER DEFAULT 0,
            row_counts    TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS query_executions (
            exec_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id    INTEGER NOT NULL REFERENCES snapshots(snapshot_id),
            query_id       TEXT NOT NULL,
            query_label    TEXT NOT NULL,
            sql_text       TEXT NOT NULL,
            plan_text      TEXT NOT NULL,
            plan_nodes     TEXT NOT NULL,
            uses_index     INTEGER NOT NULL DEFAULT 0,
            index_names    TEXT NOT NULL DEFAULT '[]',
            exec_ms_p50    REAL NOT NULL DEFAULT 0,
            exec_ms_p95    REAL NOT NULL DEFAULT 0,
            exec_ms_p99    REAL NOT NULL DEFAULT 0,
            exec_runs      INTEGER NOT NULL DEFAULT 0,
            row_est        INTEGER NOT NULL DEFAULT 0,
            has_full_scan  INTEGER NOT NULL DEFAULT 0,
            table_stats    TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS regressions (
            regression_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            baseline_snap_id INTEGER NOT NULL REFERENCES snapshots(snapshot_id),
            run_snap_id      INTEGER NOT NULL REFERENCES snapshots(snapshot_id),
            query_id         TEXT NOT NULL,
            query_label      TEXT NOT NULL DEFAULT '',
            severity         TEXT NOT NULL,
            regression_types TEXT NOT NULL DEFAULT '[]',
            delta_ms_p95     REAL NOT NULL DEFAULT 0,
            pct_change       REAL NOT NULL DEFAULT 0,
            plan_changed     INTEGER NOT NULL DEFAULT 0,
            index_lost       INTEGER NOT NULL DEFAULT 0,
            has_new_scan     INTEGER NOT NULL DEFAULT 0,
            evidence         TEXT NOT NULL DEFAULT '{}',
            is_false_pos     INTEGER NOT NULL DEFAULT 0,
            is_false_neg     INTEGER NOT NULL DEFAULT 0,
            analyst_note     TEXT DEFAULT '',
            detected_at      DATETIME NOT NULL
        );

        CREATE TABLE IF NOT EXISTS release_history (
            release_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            release_tag TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            changes     TEXT NOT NULL DEFAULT '[]',
            released_at DATETIME NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rules_audit (
            audit_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            changed_by     TEXT NOT NULL,
            role           TEXT NOT NULL,
            rules_yaml     TEXT NOT NULL,
            config_version TEXT DEFAULT 'v1.0',
            changed_fields TEXT DEFAULT '[]',
            previous_value TEXT DEFAULT '',
            new_value      TEXT DEFAULT '',
            changed_at     DATETIME NOT NULL
        );

        CREATE TABLE IF NOT EXISTS regression_reviews (
            review_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            regression_id   INTEGER NOT NULL REFERENCES regressions(regression_id),
            reviewer_user   TEXT NOT NULL,
            reviewer_role   TEXT NOT NULL,
            action          TEXT NOT NULL,
            previous_status TEXT NOT NULL,
            new_status      TEXT NOT NULL,
            note            TEXT DEFAULT '',
            reviewed_at     DATETIME NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       DATETIME NOT NULL,
            user_id         TEXT NOT NULL,
            role            TEXT NOT NULL,
            action          TEXT NOT NULL,
            resource_type   TEXT NOT NULL,
            resource_id     TEXT NOT NULL,
            previous_value  TEXT DEFAULT '',
            new_value       TEXT DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'SUCCESS',
            details         TEXT DEFAULT '{}'
        );
    """)
    # Check and migrate existing rules_audit columns if necessary
    cols = [c[1] for c in conn.execute("PRAGMA table_info(rules_audit)").fetchall()]
    if "config_version" not in cols:
        conn.execute("ALTER TABLE rules_audit ADD COLUMN config_version TEXT DEFAULT 'v1.0'")
    if "changed_fields" not in cols:
        conn.execute("ALTER TABLE rules_audit ADD COLUMN changed_fields TEXT DEFAULT '[]'")
    if "previous_value" not in cols:
        conn.execute("ALTER TABLE rules_audit ADD COLUMN previous_value TEXT DEFAULT ''")
    if "new_value" not in cols:
        conn.execute("ALTER TABLE rules_audit ADD COLUMN new_value TEXT DEFAULT ''")

    # Check and migrate regressions review columns if necessary
    r_cols = [c[1] for c in conn.execute("PRAGMA table_info(regressions)").fetchall()]
    if "review_status" not in r_cols:
        conn.execute("ALTER TABLE regressions ADD COLUMN review_status TEXT DEFAULT 'NEW'")
    if "reviewed_by" not in r_cols:
        conn.execute("ALTER TABLE regressions ADD COLUMN reviewed_by TEXT DEFAULT ''")
    if "reviewer_role" not in r_cols:
        conn.execute("ALTER TABLE regressions ADD COLUMN reviewer_role TEXT DEFAULT ''")
    if "reviewed_at" not in r_cols:
        conn.execute("ALTER TABLE regressions ADD COLUMN reviewed_at DATETIME")

    conn.commit()
    conn.close()


# ── Snapshot CRUD ─────────────────────────────────────────────────────────────

def save_snapshot(
    release_tag: str,
    snapshot_type: str,
    db_size_bytes: int,
    row_counts: Dict[str, int],
    store_path: str = DEFAULT_STORE_PATH,
) -> int:
    """Insert a new snapshot row. Returns snapshot_id."""
    conn = _connect(store_path)
    cur = conn.execute(
        """INSERT INTO snapshots(release_tag, snapshot_type, captured_at, db_size_bytes, row_counts)
           VALUES (?, ?, ?, ?, ?)""",
        (release_tag, snapshot_type, datetime.now().isoformat(),
         db_size_bytes, json.dumps(row_counts))
    )
    snap_id = cur.lastrowid
    conn.commit()
    conn.close()
    return snap_id


def save_query_execution(
    snapshot_id: int,
    query_id: str,
    query_label: str,
    sql_text: str,
    plan: Dict[str, Any],
    timing: Dict[str, Any],
    stats: Dict[str, Any],
    store_path: str = DEFAULT_STORE_PATH,
) -> int:
    conn = _connect(store_path)
    cur = conn.execute(
        """INSERT INTO query_executions(
               snapshot_id, query_id, query_label, sql_text,
               plan_text, plan_nodes, uses_index, index_names,
               exec_ms_p50, exec_ms_p95, exec_ms_p99, exec_runs,
               row_est, has_full_scan, table_stats)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            snapshot_id, query_id, query_label, sql_text,
            plan.get("raw", ""), json.dumps(plan.get("nodes", [])),
            int(plan.get("uses_index", False)),
            json.dumps(plan.get("index_names", [])),
            timing.get("p50_ms", 0), timing.get("p95_ms", 0),
            timing.get("p99_ms", 0), timing.get("runs", 0),
            plan.get("row_est", 0),
            int(plan.get("has_full_scan", False)),
            json.dumps(stats),
        )
    )
    exec_id = cur.lastrowid
    conn.commit()
    conn.close()
    return exec_id


def get_latest_baseline(store_path: str = DEFAULT_STORE_PATH) -> Optional[Dict]:
    conn = _connect(store_path)
    row = conn.execute(
        "SELECT * FROM snapshots WHERE snapshot_type='BASELINE' ORDER BY snapshot_id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_snapshot_by_tag(
    release_tag: str,
    snapshot_type: str,
    store_path: str = DEFAULT_STORE_PATH,
) -> Optional[Dict]:
    conn = _connect(store_path)
    row = conn.execute(
        "SELECT * FROM snapshots WHERE release_tag=? AND snapshot_type=? ORDER BY snapshot_id DESC LIMIT 1",
        (release_tag, snapshot_type)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_executions_for_snapshot(
    snapshot_id: int,
    store_path: str = DEFAULT_STORE_PATH,
) -> List[Dict]:
    conn = _connect(store_path)
    rows = conn.execute(
        "SELECT * FROM query_executions WHERE snapshot_id=?", (snapshot_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_snapshots(store_path: str = DEFAULT_STORE_PATH) -> List[Dict]:
    conn = _connect(store_path)
    rows = conn.execute(
        "SELECT * FROM snapshots ORDER BY snapshot_id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Regression CRUD ───────────────────────────────────────────────────────────

def save_regression(
    baseline_snap_id: int,
    run_snap_id: int,
    query_id: str,
    query_label: str,
    severity: str,
    regression_types: List[str],
    delta_ms_p95: float,
    pct_change: float,
    plan_changed: bool,
    index_lost: bool,
    has_new_scan: bool,
    evidence: Dict[str, Any],
    store_path: str = DEFAULT_STORE_PATH,
) -> int:
    conn = _connect(store_path)
    cur = conn.execute(
        """INSERT INTO regressions(
               baseline_snap_id, run_snap_id, query_id, query_label,
               severity, regression_types, delta_ms_p95, pct_change,
               plan_changed, index_lost, has_new_scan, evidence, detected_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            baseline_snap_id, run_snap_id, query_id, query_label,
            severity, json.dumps(regression_types),
            delta_ms_p95, pct_change,
            int(plan_changed), int(index_lost), int(has_new_scan),
            json.dumps(evidence),
            datetime.now().isoformat()
        )
    )
    reg_id = cur.lastrowid
    conn.commit()
    conn.close()
    return reg_id


def get_regressions(
    baseline_snap_id: Optional[int] = None,
    run_snap_id: Optional[int] = None,
    store_path: str = DEFAULT_STORE_PATH,
) -> List[Dict]:
    conn = _connect(store_path)
    q = "SELECT * FROM regressions WHERE 1=1"
    params = []
    if baseline_snap_id:
        q += " AND baseline_snap_id=?"
        params.append(baseline_snap_id)
    if run_snap_id:
        q += " AND run_snap_id=?"
        params.append(run_snap_id)
    q += " ORDER BY regression_id DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_regression_flag(
    regression_id: int,
    is_false_pos: Optional[bool] = None,
    is_false_neg: Optional[bool] = None,
    analyst_note: Optional[str] = None,
    store_path: str = DEFAULT_STORE_PATH,
) -> None:
    conn = _connect(store_path)
    updates = []
    params = []
    if is_false_pos is not None:
        updates.append("is_false_pos=?")
        params.append(int(is_false_pos))
    if is_false_neg is not None:
        updates.append("is_false_neg=?")
        params.append(int(is_false_neg))
    if analyst_note is not None:
        updates.append("analyst_note=?")
        params.append(analyst_note)
    if updates:
        params.append(regression_id)
        conn.execute(f"UPDATE regressions SET {', '.join(updates)} WHERE regression_id=?", params)
        conn.commit()
    conn.close()


# ── Release History ───────────────────────────────────────────────────────────

def record_release(
    release_tag: str,
    description: str,
    changes: List[str],
    store_path: str = DEFAULT_STORE_PATH,
) -> None:
    conn = _connect(store_path)
    conn.execute(
        """INSERT OR REPLACE INTO release_history(release_tag, description, changes, released_at)
           VALUES (?, ?, ?, ?)""",
        (release_tag, description, json.dumps(changes), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_release_history(store_path: str = DEFAULT_STORE_PATH) -> List[Dict]:
    conn = _connect(store_path)
    rows = conn.execute("SELECT * FROM release_history ORDER BY release_id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Rules Audit History ───────────────────────────────────────────────────────

def save_rules_audit(
    changed_by: str,
    role: str,
    rules_yaml: str,
    config_version: str = "v1.0",
    changed_fields: Optional[List[str]] = None,
    previous_value: str = "",
    new_value: str = "",
    store_path: str = DEFAULT_STORE_PATH
) -> int:
    """Inserts a configuration audit entry and returns audit_id."""
    init_store(store_path)
    conn = _connect(store_path)
    now = datetime.now().isoformat()
    fields_json = json.dumps(changed_fields or [])
    cur = conn.execute(
        """INSERT INTO rules_audit(changed_by, role, rules_yaml, config_version,
                                  changed_fields, previous_value, new_value, changed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (changed_by, role, rules_yaml, config_version, fields_json, previous_value, new_value, now)
    )
    audit_id = cur.lastrowid
    conn.commit()
    conn.close()
    return audit_id


def get_rules_audit_history(limit: int = 50, store_path: str = DEFAULT_STORE_PATH) -> List[Dict[str, Any]]:
    """Fetches configuration change history ordered by most recent first."""
    init_store(store_path)
    conn = _connect(store_path)
    rows = conn.execute(
        """SELECT audit_id, changed_by, role, rules_yaml, config_version,
                  changed_fields, previous_value, new_value, changed_at
           FROM rules_audit ORDER BY audit_id DESC LIMIT ?""",
        (limit,)
    )
    results = []
    for r in rows:
        item = dict(r)
        try:
            item["changed_fields"] = json.loads(item.get("changed_fields") or "[]")
        except Exception:
            item["changed_fields"] = []
        results.append(item)
    conn.close()
    return results


# ── Security Audit Log ────────────────────────────────────────────────────────

def record_audit_event(
    user_id: str,
    role: str,
    action: str,
    resource_type: str,
    resource_id: str,
    previous_value: str = "",
    new_value: str = "",
    status: str = "SUCCESS",
    details: Optional[Dict[str, Any]] = None,
    store_path: str = DEFAULT_STORE_PATH
) -> int:
    """Inserts a security audit record into audit_log table."""
    init_store(store_path)
    conn = _connect(store_path)
    now = datetime.now().isoformat()
    det_json = json.dumps(details or {})
    uid_str = str(user_id) if user_id is not None else "anonymous"
    role_str = str(role) if role is not None else "unauthenticated"
    cur = conn.execute(
        """INSERT INTO audit_log(timestamp, user_id, role, action, resource_type,
                                resource_id, previous_value, new_value, status, details)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (now, uid_str, role_str, action, resource_type, resource_id,
         str(previous_value), str(new_value), status, det_json)
    )
    event_id = cur.lastrowid
    conn.commit()
    conn.close()
    return event_id


def get_audit_events(
    limit: int = 100,
    resource_type: Optional[str] = None,
    action: Optional[str] = None,
    store_path: str = DEFAULT_STORE_PATH
) -> List[Dict[str, Any]]:
    """Fetches security audit events ordered by most recent first."""
    init_store(store_path)
    conn = _connect(store_path)
    query = "SELECT * FROM audit_log"
    params = []
    clauses = []
    if resource_type:
        clauses.append("resource_type = ?")
        params.append(resource_type)
    if action:
        clauses.append("action = ?")
        params.append(action)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY event_id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    results = []
    for r in rows:
        item = dict(r)
        try:
            item["details"] = json.loads(item.get("details") or "{}")
        except Exception:
            item["details"] = {}
        results.append(item)
    conn.close()
    return results


# ── Regression Review Workflow ────────────────────────────────────────────────

def get_regression_by_id(regression_id: int, store_path: str = DEFAULT_STORE_PATH) -> Optional[Dict[str, Any]]:
    """Fetches single regression row by ID."""
    init_store(store_path)
    conn = _connect(store_path)
    row = conn.execute("SELECT * FROM regressions WHERE regression_id = ?", (regression_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def review_regression(
    regression_id: int,
    reviewer_user: str,
    reviewer_role: str,
    action: str,
    new_status: str,
    note: str = "",
    store_path: str = DEFAULT_STORE_PATH
) -> Dict[str, Any]:
    """
    Executes a formal regression review lifecycle action.
    Updates regression review status, inserts review history, and records an audit event.
    """
    init_store(store_path)
    conn = _connect(store_path)
    now = datetime.now().isoformat()

    # Get current status
    cur_row = conn.execute("SELECT review_status, is_false_pos FROM regressions WHERE regression_id = ?", (regression_id,)).fetchone()
    if not cur_row:
        conn.close()
        raise ValueError(f"Regression ID {regression_id} not found.")

    prev_status = cur_row["review_status"] or "NEW"

    # Determine is_false_pos flag update
    updates = [
        "review_status = ?",
        "reviewed_by = ?",
        "reviewer_role = ?",
        "reviewed_at = ?",
        "analyst_note = ?"
    ]
    params = [new_status, reviewer_user, reviewer_role, now, note]

    if new_status == "FALSE_POSITIVE" or action.upper() in ("MARK_FALSE_POSITIVE", "FALSE_POSITIVE"):
        updates.append("is_false_pos = 1")
    elif new_status == "CONFIRMED" or action.upper() in ("CONFIRM", "CONFIRMED"):
        updates.append("is_false_pos = 0")

    params.append(regression_id)
    conn.execute(f"UPDATE regressions SET {', '.join(updates)} WHERE regression_id = ?", params)

    # Insert into regression_reviews table
    cur = conn.execute(
        """INSERT INTO regression_reviews(regression_id, reviewer_user, reviewer_role,
                                         action, previous_status, new_status, note, reviewed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (regression_id, reviewer_user, reviewer_role, action, prev_status, new_status, note, now)
    )
    review_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Record security audit log entries
    record_audit_event(
        user_id=reviewer_user,
        role=reviewer_role,
        action="REGRESSION_REVIEW",
        resource_type="REGRESSION",
        resource_id=str(regression_id),
        previous_value=prev_status,
        new_value=new_status,
        status="SUCCESS",
        details={"note": note, "review_id": review_id, "action": action},
        store_path=store_path
    )

    specific_action = (
        "REGRESSION_CONFIRMED" if action.upper() in ("CONFIRM", "CONFIRMED") else
        "REGRESSION_FALSE_POSITIVE" if action.upper() in ("FALSE_POSITIVE", "MARK_FALSE_POSITIVE") else
        "REGRESSION_ACKNOWLEDGED" if action.upper() in ("ACKNOWLEDGE", "ACK") else
        f"REGRESSION_{action.upper()}"
    )
    if specific_action != "REGRESSION_REVIEW":
        record_audit_event(
            user_id=reviewer_user,
            role=reviewer_role,
            action=specific_action,
            resource_type="REGRESSION",
            resource_id=str(regression_id),
            previous_value=prev_status,
            new_value=new_status,
            status="SUCCESS",
            details={"note": note, "review_id": review_id},
            store_path=store_path
        )

    return {
        "review_id": review_id,
        "regression_id": regression_id,
        "reviewer_user": reviewer_user,
        "reviewer_role": reviewer_role,
        "action": action,
        "previous_status": prev_status,
        "new_status": new_status,
        "note": note,
        "reviewed_at": now
    }


def get_regression_reviews(regression_id: int, store_path: str = DEFAULT_STORE_PATH) -> List[Dict[str, Any]]:
    """Fetches review audit history for a specific regression finding."""
    init_store(store_path)
    conn = _connect(store_path)
    rows = conn.execute(
        """SELECT * FROM regression_reviews WHERE regression_id = ? ORDER BY review_id DESC""",
        (regression_id,)
    ).fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["reviewer"] = d.get("reviewer_user")
        d["role"] = d.get("reviewer_role")
        res.append(d)
    return res


