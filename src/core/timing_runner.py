"""
timing_runner.py
=================
Executes a probe query multiple times and measures p50, p95, p99 execution times.
"""

import sqlite3
import time
import statistics
from typing import Dict, Any


def run_timed(
    conn: sqlite3.Connection,
    sql: str,
    runs: int = 10,
    warm_up: int = 2,
) -> Dict[str, Any]:
    """
    Execute `sql` `runs` times, preceded by `warm_up` discarded runs.

    Returns:
        {
          "p50_ms": float,
          "p95_ms": float,
          "p99_ms": float,
          "min_ms": float,
          "max_ms": float,
          "mean_ms": float,
          "runs": int,
          "error": str | None,
        }
    """
    all_ms = []

    # Warm-up (discarded)
    for _ in range(warm_up):
        try:
            conn.execute(sql).fetchall()
        except sqlite3.Error:
            pass

    for _ in range(runs):
        t0 = time.perf_counter()
        try:
            conn.execute(sql).fetchall()
        except sqlite3.Error as e:
            return _error_timing(str(e))
        elapsed = (time.perf_counter() - t0) * 1000.0  # ms
        all_ms.append(elapsed)

    if not all_ms:
        return _error_timing("No timing samples collected")

    all_ms.sort()
    n = len(all_ms)

    def percentile(data, pct):
        k = (pct / 100) * (len(data) - 1)
        lo, hi = int(k), min(int(k) + 1, len(data) - 1)
        return data[lo] + (k - lo) * (data[hi] - data[lo])

    return {
        "p50_ms": round(percentile(all_ms, 50), 4),
        "p95_ms": round(percentile(all_ms, 95), 4),
        "p99_ms": round(percentile(all_ms, 99), 4),
        "min_ms": round(min(all_ms), 4),
        "max_ms": round(max(all_ms), 4),
        "mean_ms": round(statistics.mean(all_ms), 4),
        "runs": n,
        "error": None,
    }


def _error_timing(msg: str) -> Dict[str, Any]:
    return {
        "p50_ms": 0.0,
        "p95_ms": 0.0,
        "p99_ms": 0.0,
        "min_ms": 0.0,
        "max_ms": 0.0,
        "mean_ms": 0.0,
        "runs": 0,
        "error": msg,
    }
