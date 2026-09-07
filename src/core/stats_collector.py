"""
stats_collector.py
===================
Collects table-level statistics from the hospital.db (SQLite):
- sqlite_stat1 (index statistics after ANALYZE)
- Row counts per table
- Total database file size
- Index list
"""

import sqlite3
import os
import json
from typing import Dict, Any, List


def collect_stats(conn: sqlite3.Connection, db_path: str) -> Dict[str, Any]:
    """
    Collect table statistics from the connected SQLite database.

    Returns a dict with:
        {
          "tables": { table_name: { "row_count": int, "stat1": str | None } },
          "indexes": [ { "name": str, "table": str, "unique": int } ],
          "db_size_bytes": int,
          "sqlite_stat1": { "<table> <index>": stat_value },
        }
    """
    tables = _get_table_stats(conn)
    indexes = _get_index_list(conn)
    stat1 = _get_sqlite_stat1(conn)
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    return {
        "tables": tables,
        "indexes": indexes,
        "db_size_bytes": db_size,
        "sqlite_stat1": stat1,
    }


def _get_table_stats(conn: sqlite3.Connection) -> Dict[str, Any]:
    tables = {}
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for (tbl,) in rows:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM [{tbl}]").fetchone()[0]
        except sqlite3.Error:
            count = -1
        tables[tbl] = {"row_count": count}
    return tables


def _get_index_list(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    indexes = []
    rows = conn.execute(
        "SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for name, tbl_name in rows:
        try:
            info = conn.execute(f"PRAGMA index_info([{name}])").fetchall()
            unique_rows = conn.execute(f"PRAGMA index_list([{tbl_name}])").fetchall()
            is_unique = 0
            for r in unique_rows:
                if r[1] == name:
                    is_unique = r[2]
                    break
        except sqlite3.Error:
            info = []
            is_unique = 0
        indexes.append({
            "name": name,
            "table": tbl_name,
            "unique": int(is_unique),
            "columns": [r[2] for r in info],
        })
    return indexes


def _get_sqlite_stat1(conn: sqlite3.Connection) -> Dict[str, str]:
    """Read sqlite_stat1 table if it exists (populated after ANALYZE)."""
    stat1 = {}
    try:
        rows = conn.execute("SELECT tbl, idx, stat FROM sqlite_stat1").fetchall()
        for tbl, idx, stat in rows:
            key = f"{tbl} {idx}" if idx else tbl
            stat1[key] = stat
    except sqlite3.OperationalError:
        pass  # sqlite_stat1 doesn't exist yet
    return stat1


def get_row_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    """Quick helper to get {table: row_count} mapping."""
    tables = _get_table_stats(conn)
    return {t: v["row_count"] for t, v in tables.items()}
