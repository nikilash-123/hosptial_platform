"""
simulate_change.py
==================
Applies one of 5 change scenarios to hospital.db to simulate
real-world regression causes. Used in edge-case testing and the
end-to-end evaluation experiment.

Scenarios:
  drop_index   — drops critical composite index (EC-1)
  data_growth  — inserts 10× appointments (EC-2)
  stats_stale  — alters status values to skew statistics (EC-3)
  noise_only   — no structural change, tiny safe update (EC-4, FP test)
  restore      — restores all indexes and re-runs ANALYZE
"""

import sqlite3
import os
import sys
import random
import argparse
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOSPITAL_DB = os.path.join(BASE_DIR, "data", "hospital.db")

SEED = 99
random.seed(SEED)


def _connect() -> sqlite3.Connection:
    if not os.path.exists(HOSPITAL_DB):
        print("[ERROR] hospital.db not found. Run: python src/synthetic_data_generator.py")
        sys.exit(1)
    conn = sqlite3.connect(HOSPITAL_DB)
    return conn


def log_event(conn, event_type: str, description: str, release: str):
    conn.execute(
        "INSERT INTO audit_log(event_type, description, release_tag, applied_at) VALUES (?,?,?,?)",
        (event_type, description, release, datetime.now().isoformat())
    )
    conn.commit()


# ── EC-1: Drop critical index ─────────────────────────────────────────────────

def scenario_drop_index(release: str = "v1.1"):
    """
    Edge Case 1: Drop the critical composite index used by the double-booking check.
    Expected: CRITICAL regression on QRY-001, QRY-004.
    """
    conn = _connect()
    print("[SIMULATE] EC-1: Dropping critical index idx_appt_doctor_date ...")
    try:
        conn.execute("DROP INDEX IF EXISTS idx_appt_doctor_date")
        conn.execute("DROP INDEX IF EXISTS idx_appt_status_date")
        conn.commit()
        log_event(conn, "INDEX_DROP",
                  "Dropped idx_appt_doctor_date and idx_appt_status_date (simulating accidental migration drop)",
                  release)
        print("[SIMULATE] Done. Indexes dropped. Queries QRY-001, QRY-004 will now full-scan.")
    finally:
        conn.close()


# ── EC-2: Data volume explosion ───────────────────────────────────────────────

def scenario_data_growth(release: str = "v1.1", multiplier: int = 8):
    """
    Edge Case 2: Insert 8× more appointments (simulating bulk data import).
    Expected: HIGH regression on QRY-003, QRY-004 (timing + row_est drift).
    """
    conn = _connect()
    print(f"[SIMULATE] EC-2: Inserting ~{multiplier}× data growth ...")

    doctors = [r[0] for r in conn.execute("SELECT doctor_id FROM doctors").fetchall()]
    patients = [r[0] for r in conn.execute("SELECT patient_id FROM patients LIMIT 5000").fetchall()]

    max_id = conn.execute("SELECT MAX(CAST(SUBSTR(appt_id, 9) AS INTEGER)) FROM appointments").fetchone()[0] or 0
    start_date = date(2024, 1, 1)
    end_date = date(2027, 12, 31)
    delta = (end_date - start_date).days

    TIME_SLOTS = [f"{h:02d}:{m:02d}" for h in range(8, 18) for m in (0, 15, 30, 45)]
    STATUSES = ["SCHEDULED", "CANCELLED", "COMPLETED"]
    WEIGHTS = [0.7, 0.1, 0.2]
    DURATIONS = [15, 20, 30, 45, 60]

    rows = []
    target = 50000 * multiplier
    now = datetime.now().isoformat()
    for i in range(1, target + 1):
        idx = max_id + i
        appt_id = f"SYNTH-A-{idx:07d}"
        patient_id = random.choice(patients)
        doctor_id = random.choice(doctors)
        dept_num = (int(doctor_id.split("-")[2]) - 1) % 10 + 1
        dept_id = f"SYNTH-DEPT-{dept_num:02d}"
        appt_date = (start_date + timedelta(days=random.randint(0, delta))).isoformat()
        appt_time = random.choice(TIME_SLOTS)
        duration = random.choice(DURATIONS)
        status = random.choices(STATUSES, weights=WEIGHTS)[0]
        rows.append((appt_id, patient_id, doctor_id, dept_id, appt_date, appt_time, duration, status, now, now))

        if len(rows) == 2000:
            conn.executemany(
                "INSERT OR IGNORE INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?)", rows
            )
            conn.commit()
            rows = []

    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?)", rows
        )
        conn.commit()

    # Re-run ANALYZE to update statistics
    conn.execute("ANALYZE")
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    log_event(conn, "DATA_LOAD",
              f"Bulk data import: {target} new appointments added (total={total})",
              release)
    print(f"[SIMULATE] Done. Appointments now: {total:,}")
    conn.close()


# ── EC-3: Stale / skewed statistics ──────────────────────────────────────────

def scenario_stats_stale(release: str = "v1.1"):
    """
    Edge Case 3: Introduce a massive batch of SCHEDULED appointments to skew selectivity,
    then deliberately NOT run ANALYZE — leaving statistics stale.
    Expected: MEDIUM regression (stats drift, possible plan change).
    """
    conn = _connect()
    print("[SIMULATE] EC-3: Skewing status distribution (stale stats) ...")

    doctors = [r[0] for r in conn.execute("SELECT doctor_id FROM doctors").fetchall()]
    patients = [r[0] for r in conn.execute("SELECT patient_id FROM patients LIMIT 1000").fetchall()]

    max_id = conn.execute("SELECT MAX(CAST(SUBSTR(appt_id, 9) AS INTEGER)) FROM appointments").fetchone()[0] or 0
    now = datetime.now().isoformat()
    rows = []
    target = 30000
    for i in range(1, target + 1):
        idx = max_id + i
        appt_id = f"SYNTH-A-{idx:08d}"
        patient_id = random.choice(patients)
        doctor_id = random.choice(doctors)
        dept_num = (int(doctor_id.split("-")[2]) - 1) % 10 + 1
        dept_id = f"SYNTH-DEPT-{dept_num:02d}"
        # All SCHEDULED on SYNTH-D-001 on a busy date to force bad selectivity
        appt_date = "2025-06-15"
        appt_time = f"{random.randint(8,17):02d}:{random.choice([0,15,30,45]):02d}"
        rows.append((appt_id, patient_id, doctor_id, dept_id,
                     appt_date, appt_time, 15, "SCHEDULED", now, now))
        if len(rows) == 1000:
            conn.executemany("INSERT OR IGNORE INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            conn.commit()
            rows = []
    if rows:
        conn.executemany("INSERT OR IGNORE INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()

    # Intentionally skip ANALYZE → statistics are now stale
    log_event(conn, "SCHEMA_CHANGE",
              f"Added {target} skewed SCHEDULED appointments without ANALYZE (stale stats scenario)",
              release)
    total = conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    print(f"[SIMULATE] Done. Statistics are now stale. Total appointments: {total:,}")
    conn.close()


# ── EC-4: Noise only (FP test) ────────────────────────────────────────────────

def scenario_noise_only(release: str = "v1.1"):
    """
    Edge Case 4: Touch the audit_log only. No structural change.
    Expected: All queries return OK — false positive correctly suppressed.
    """
    conn = _connect()
    print("[SIMULATE] EC-4: Noise-only scenario (no structural change) ...")
    log_event(conn, "SCHEMA_CHANGE",
              "Minor configuration update — no schema or index changes", release)
    print("[SIMULATE] Done. No structural changes applied. Expect all OK.")
    conn.close()


# ── Restore ───────────────────────────────────────────────────────────────────

def scenario_restore(release: str = "v1.0-restored"):
    """
    Restore all indexes and re-run ANALYZE. Brings DB back to baseline state.
    """
    conn = _connect()
    print("[SIMULATE] RESTORE: Recreating all baseline indexes ...")
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_appt_doctor_date ON appointments(doctor_id, appt_date)",
        "CREATE INDEX IF NOT EXISTS idx_appt_patient     ON appointments(patient_id)",
        "CREATE INDEX IF NOT EXISTS idx_appt_status_date ON appointments(status, appt_date)",
        "CREATE INDEX IF NOT EXISTS idx_appt_dept_date   ON appointments(dept_id, appt_date)",
        "CREATE INDEX IF NOT EXISTS idx_appt_date        ON appointments(appt_date)",
        "CREATE INDEX IF NOT EXISTS idx_doctors_dept     ON doctors(dept_id)",
    ]
    for sql in indexes:
        conn.execute(sql)
    conn.execute("ANALYZE")
    conn.commit()
    log_event(conn, "INDEX_ADD", "Restored all baseline indexes and ran ANALYZE", release)
    print("[SIMULATE] Done. All indexes restored.")
    conn.close()


SCENARIOS = {
    "drop_index":  scenario_drop_index,
    "data_growth": scenario_data_growth,
    "stats_stale": scenario_stats_stale,
    "noise_only":  scenario_noise_only,
    "restore":     scenario_restore,
}


def main():
    parser = argparse.ArgumentParser(
        description="Apply a change scenario to hospital.db for regression testing."
    )
    parser.add_argument(
        "--scenario", required=True, choices=list(SCENARIOS.keys()),
        help="Which scenario to apply"
    )
    parser.add_argument(
        "--release", default="v1.1",
        help="Release tag to log in audit_log (default: v1.1)"
    )
    args = parser.parse_args()
    SCENARIOS[args.scenario](release=args.release)


if __name__ == "__main__":
    main()
