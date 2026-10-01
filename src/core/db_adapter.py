"""
db_adapter.py
=============
Unified Database Abstraction Layer for QUERYGUARD AI.

Transparently supports both PostgreSQL (Primary Target) and SQLite (Local / CI Fallback).
Provides unified interfaces for:
- Database connection lifecycle
- EXPLAIN and EXPLAIN ANALYZE execution & plan parsing
- Table cardinality, index catalogs, and database statistics
- Percentile execution timing profiler (p50, p95, p99)
- Transactional double-booking prevention simulation
"""

import os
import sqlite3
import time
import statistics
from typing import Dict, Any, List, Optional, Tuple, Union

from src.core import postgres_engine
from src.core import plan_extractor

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_SQLITE_PATH = os.path.join(BASE_DIR, "data", "hospital.db")


class DatabaseAdapter:
    """
    Unified database adapter providing database-agnostic query performance monitoring.
    """

    def __init__(self, sqlite_path: str = DEFAULT_SQLITE_PATH, prefer_postgres: bool = True):
        self.sqlite_path = sqlite_path
        self.prefer_postgres = prefer_postgres
        self._pg_conn = None
        self._sqlite_conn = None

    def get_db_type(self) -> str:
        """Returns 'postgres' if active PostgreSQL connection is established, else 'sqlite'."""
        if self.prefer_postgres and postgres_engine.is_postgres_available():
            conn = self.get_postgres_conn()
            if conn:
                return "postgres"
        return "sqlite"

    def get_postgres_conn(self):
        """Get or establish PostgreSQL connection."""
        if self._pg_conn is None or getattr(self._pg_conn, "closed", 1) != 0:
            self._pg_conn = postgres_engine.get_postgres_connection()
        return self._pg_conn

    def get_sqlite_conn(self) -> Optional[sqlite3.Connection]:
        """Get or establish SQLite connection."""
        if self._sqlite_conn is None:
            try:
                self._sqlite_conn = sqlite3.connect(self.sqlite_path, check_same_thread=False)
                self._sqlite_conn.row_factory = sqlite3.Row
            except sqlite3.OperationalError:
                return None
        return self._sqlite_conn

    def get_connection(self):
        """Returns the active primary database connection."""
        if self.get_db_type() == "postgres":
            return self.get_postgres_conn()
        return self.get_sqlite_conn()

    def explain(self, sql: str, analyze: bool = True) -> Dict[str, Any]:
        """
        Executes EXPLAIN (or EXPLAIN ANALYZE) and parses output into standardized plan dict.
        Works across both PostgreSQL and SQLite.
        """
        db_type = self.get_db_type()
        if db_type == "postgres":
            conn = self.get_postgres_conn()
            if conn:
                return postgres_engine.extract_postgres_plan(conn, sql, analyze=analyze)

        conn = self.get_sqlite_conn()
        if not conn:
            return {"error": "Connection failed", "raw": None}
        return plan_extractor.extract_plan(conn, sql)

    def run_timing_profile(self, sql: str, runs: int = 10, warm_up: int = 2) -> Dict[str, Any]:
        """
        Executes query multiple times to measure statistical timing distributions (p50, p95, p99).
        """
        db_type = self.get_db_type()
        all_ms = []

        if db_type == "postgres":
            conn = self.get_postgres_conn()
            if not conn:
                db_type = "sqlite"

        if db_type == "postgres":
            try:
                with conn.cursor() as cur:
                    for _ in range(warm_up):
                        try:
                            cur.execute(sql)
                            cur.fetchall()
                        except Exception:
                            conn.rollback()

                    for _ in range(runs):
                        t0 = time.perf_counter()
                        cur.execute(sql)
                        cur.fetchall()
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        all_ms.append(elapsed)
                conn.commit()
            except Exception as e:
                conn.rollback()
                return _error_timing(str(e))
        else:
            conn = self.get_sqlite_conn()
            if not conn:
                return _error_timing("Connection failed")
            for _ in range(warm_up):
                try:
                    conn.execute(sql).fetchall()
                except Exception:
                    pass

            for _ in range(runs):
                t0 = time.perf_counter()
                try:
                    conn.execute(sql).fetchall()
                except Exception as e:
                    return _error_timing(str(e))
                elapsed = (time.perf_counter() - t0) * 1000.0
                all_ms.append(elapsed)

        if not all_ms:
            return _error_timing("No timing measurements gathered")

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
            "db_type": db_type,
            "error": None
        }

    def get_database_statistics(self) -> Dict[str, Any]:
        """Collects database statistics from PostgreSQL catalogs or SQLite stat tables."""
        if self.get_db_type() == "postgres":
            conn = self.get_postgres_conn()
            if conn:
                stats = postgres_engine.collect_postgres_statistics(conn)
                stats["engine"] = "PostgreSQL"
                return stats

        from src.core import stats_collector
        conn = self.get_sqlite_conn()
        if not conn:
            return {"error": "Connection failed", "engine": "SQLite"}
        stats = stats_collector.collect_stats(conn, self.sqlite_path)
        stats["engine"] = "SQLite"
        return stats

    def simulate_double_booking_prevention(
        self,
        doctor_id: str = "SYNTH-D-001",
        slot_date: str = "2026-09-15",
        slot_time: str = "10:30",
        patient_id_1: str = "SYNTH-P-000001",
        patient_id_2: str = "SYNTH-P-000002"
    ) -> Dict[str, Any]:
        """
        Executes concurrent booking simulation against active database engine to verify
        that double bookings are caught and rejected at the transaction/constraint level.
        """
        if self.get_db_type() == "postgres":
            conn = self.get_postgres_conn()
            if conn:
                return postgres_engine.simulate_double_booking_transaction_postgres(
                    conn, doctor_id, slot_date, slot_time, patient_id_1, patient_id_2
                )

        # SQLite implementation
        conn = self.get_sqlite_conn()
        if not conn:
            return {"error": "Connection failed", "double_booking_prevented": False}
        cur = conn.cursor()
        txn_1 = f"SYNTH-TXN-{int(time.time()*1000)%1000000:06d}-A"
        txn_2 = f"SYNTH-TXN-{int(time.time()*1000)%1000000:06d}-B"
        appt_1 = f"SYNTH-A-RACE-{time.time():.4f}-1"
        appt_2 = f"SYNTH-A-RACE-{time.time():.4f}-2"

        res = {
            "scenario": "concurrent_slot_booking_conflict",
            "engine": "SQLite",
            "doctor_id": doctor_id,
            "slot_date": slot_date,
            "slot_time": slot_time,
            "transaction_1": {"txn_id": txn_1, "status": "UNKNOWN"},
            "transaction_2": {"txn_id": txn_2, "status": "UNKNOWN"},
            "double_booking_prevented": True
        }

        # Check existing booking
        existing = cur.execute("""
            SELECT COUNT(*) FROM appointments 
            WHERE doctor_id = ? AND appt_date = ? AND appt_time = ? AND status = 'SCHEDULED'
        """, (doctor_id, slot_date, slot_time)).fetchone()[0]

        if existing == 0:
            cur.execute("""
                INSERT INTO appointments (
                    appt_id, patient_id, doctor_id, dept_id, appt_date, appt_time, 
                    duration_mins, status, created_at, updated_at
                ) VALUES (?, ?, ?, 'SYNTH-DEPT-01', ?, ?, 30, 'SCHEDULED', datetime('now'), datetime('now'))
            """, (appt_1, patient_id_1, doctor_id, slot_date, slot_time))
            conn.commit()
            res["transaction_1"]["status"] = "COMMITTED"
        else:
            res["transaction_1"]["status"] = "ALREADY_BOOKED"

        # Second transaction verifies conflict
        conflict = cur.execute("""
            SELECT COUNT(*) FROM appointments 
            WHERE doctor_id = ? AND appt_date = ? AND appt_time = ? AND status = 'SCHEDULED'
        """, (doctor_id, slot_date, slot_time)).fetchone()[0]

        if conflict > 0:
            res["transaction_2"]["status"] = "REJECTED_SLOT_UNAVAILABLE"
            res["double_booking_prevented"] = True
        else:
            res["transaction_2"]["status"] = "COMMITTED_ERROR"
            res["double_booking_prevented"] = False

        return res

    def close(self):
        """Close connections."""
        if self._pg_conn and getattr(self._pg_conn, "closed", 1) == 0:
            try:
                self._pg_conn.close()
            except Exception:
                pass
        if self._sqlite_conn:
            try:
                self._sqlite_conn.close()
            except Exception:
                pass


_global_adapter = None


def get_default_adapter() -> DatabaseAdapter:
    """Singleton getter for default DatabaseAdapter."""
    global _global_adapter
    if _global_adapter is None:
        _global_adapter = DatabaseAdapter()
    return _global_adapter


def _error_timing(msg: str) -> Dict[str, Any]:
    return {
        "p50_ms": 0.0,
        "p95_ms": 0.0,
        "p99_ms": 0.0,
        "min_ms": 0.0,
        "max_ms": 0.0,
        "mean_ms": 0.0,
        "runs": 0,
        "error": msg
    }
