"""
synthetic_data_generator.py
============================
Generates the synthetic hospital.db SQLite database.

PRIVACY: All data is fully synthetic. No real PII. See config/privacy_assumptions.md (PA-001).
         Fixed random seed (42) for full reproducibility.
"""

import sqlite3
import random
import os
from datetime import date, datetime, timedelta

SEED = 42
random.seed(SEED)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "..", "data", "hospital.db")

SPECIALTIES = [
    "Cardiology", "Orthopaedics", "Neurology", "Dermatology",
    "Oncology", "Paediatrics", "Radiology", "General Surgery",
    "Psychiatry", "Endocrinology"
]

DEPT_NAMES = [
    "Cardiology Dept", "Orthopaedics Dept", "Neurology Dept",
    "Dermatology Dept", "Oncology Dept", "Paediatrics Dept",
    "Radiology Dept", "General Surgery Dept", "Psychiatry Dept",
    "Endocrinology Dept"
]

AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75+"]
GENDERS = ["M", "F", "O"]
REGIONS = [f"R{i:02d}" for i in range(1, 11)]
STATUSES = ["SCHEDULED", "CANCELLED", "COMPLETED"]
STATUS_WEIGHTS = [0.6, 0.15, 0.25]
TIME_SLOTS = [f"{h:02d}:{m:02d}" for h in range(8, 18) for m in (0, 15, 30, 45)]
DURATIONS = [15, 20, 30, 45, 60]


def create_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS patients (
            patient_id    TEXT PRIMARY KEY,
            age_band      TEXT NOT NULL,
            gender        TEXT NOT NULL,
            region_code   TEXT NOT NULL,
            registered_at DATETIME NOT NULL
        );

        CREATE TABLE IF NOT EXISTS departments (
            dept_id   TEXT PRIMARY KEY,
            dept_name TEXT NOT NULL,
            floor     INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS doctors (
            doctor_id  TEXT PRIMARY KEY,
            specialty  TEXT NOT NULL,
            dept_id    TEXT NOT NULL REFERENCES departments(dept_id),
            is_active  INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS appointments (
            appt_id       TEXT PRIMARY KEY,
            patient_id    TEXT NOT NULL REFERENCES patients(patient_id),
            doctor_id     TEXT NOT NULL REFERENCES doctors(doctor_id),
            dept_id       TEXT NOT NULL REFERENCES departments(dept_id),
            appt_date     TEXT NOT NULL,
            appt_time     TEXT NOT NULL,
            duration_mins INTEGER NOT NULL,
            status        TEXT NOT NULL DEFAULT 'SCHEDULED',
            created_at    DATETIME NOT NULL,
            updated_at    DATETIME NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type  TEXT NOT NULL,
            description TEXT NOT NULL,
            release_tag TEXT NOT NULL DEFAULT 'v1.0',
            applied_at  DATETIME NOT NULL
        );
    """)
    conn.commit()


def create_indexes(conn: sqlite3.Connection) -> None:
    """Create the baseline index set."""
    cur = conn.cursor()
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_appt_doctor_date ON appointments(doctor_id, appt_date);",
        "CREATE INDEX IF NOT EXISTS idx_appt_patient     ON appointments(patient_id);",
        "CREATE INDEX IF NOT EXISTS idx_appt_status_date ON appointments(status, appt_date);",
        "CREATE INDEX IF NOT EXISTS idx_appt_dept_date   ON appointments(dept_id, appt_date);",
        "CREATE INDEX IF NOT EXISTS idx_appt_date        ON appointments(appt_date);",
        "CREATE INDEX IF NOT EXISTS idx_doctors_dept     ON doctors(dept_id);",
    ]
    for sql in indexes:
        cur.execute(sql)
    conn.commit()


def seed_departments(conn: sqlite3.Connection) -> list:
    cur = conn.cursor()
    depts = []
    for i, name in enumerate(DEPT_NAMES, start=1):
        dept_id = f"SYNTH-DEPT-{i:02d}"
        cur.execute(
            "INSERT OR IGNORE INTO departments VALUES (?, ?, ?)",
            (dept_id, name, (i % 6) + 1)
        )
        depts.append(dept_id)
    conn.commit()
    return depts


def seed_doctors(conn: sqlite3.Connection, depts: list, count: int = 30) -> list:
    cur = conn.cursor()
    doctors = []
    for i in range(1, count + 1):
        doc_id = f"SYNTH-D-{i:03d}"
        specialty = SPECIALTIES[(i - 1) % len(SPECIALTIES)]
        dept_id = depts[(i - 1) % len(depts)]
        cur.execute(
            "INSERT OR IGNORE INTO doctors VALUES (?, ?, ?, ?)",
            (doc_id, specialty, dept_id, 1)
        )
        doctors.append(doc_id)
    conn.commit()
    return doctors


def seed_patients(conn: sqlite3.Connection, count: int = 5000) -> list:
    cur = conn.cursor()
    patients = []
    base_date = datetime(2020, 1, 1)
    for i in range(1, count + 1):
        pat_id = f"SYNTH-P-{i:06d}"
        age_band = random.choice(AGE_BANDS)
        gender = random.choice(GENDERS)
        region = random.choice(REGIONS)
        reg_at = base_date + timedelta(days=random.randint(0, 1825))
        cur.execute(
            "INSERT OR IGNORE INTO patients VALUES (?, ?, ?, ?, ?)",
            (pat_id, age_band, gender, region, reg_at.isoformat())
        )
        patients.append(pat_id)
        if i % 500 == 0:
            conn.commit()
    conn.commit()
    return patients


def seed_appointments(
    conn: sqlite3.Connection,
    patients: list,
    doctors: list,
    count: int = 50000
) -> None:
    cur = conn.cursor()
    start_date = date(2024, 1, 1)
    end_date = date(2026, 12, 31)
    delta_days = (end_date - start_date).days

    rows = []
    for i in range(1, count + 1):
        appt_id = f"SYNTH-A-{i:06d}"
        patient_id = random.choice(patients)
        doctor_id = random.choice(doctors)

        # derive dept from doctor
        dept_num = (int(doctor_id.split("-")[2]) - 1) % 10 + 1
        dept_id = f"SYNTH-DEPT-{dept_num:02d}"

        appt_date = (start_date + timedelta(days=random.randint(0, delta_days))).isoformat()
        appt_time = random.choice(TIME_SLOTS)
        duration = random.choice(DURATIONS)
        status = random.choices(STATUSES, weights=STATUS_WEIGHTS)[0]
        now = datetime.now().isoformat()

        rows.append((appt_id, patient_id, doctor_id, dept_id,
                     appt_date, appt_time, duration, status, now, now))

        if len(rows) == 1000:
            cur.executemany(
                "INSERT OR IGNORE INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows
            )
            conn.commit()
            rows = []

    if rows:
        cur.executemany(
            "INSERT OR IGNORE INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows
        )
        conn.commit()


def run_analyze(conn: sqlite3.Connection) -> None:
    """Update SQLite statistics (sqlite_stat1)."""
    conn.execute("ANALYZE;")
    conn.commit()


def log_event(conn: sqlite3.Connection, event_type: str, description: str, release: str = "v1.0") -> None:
    conn.execute(
        "INSERT INTO audit_log(event_type, description, release_tag, applied_at) VALUES (?,?,?,?)",
        (event_type, description, release, datetime.now().isoformat())
    )
    conn.commit()


def main(db_path: str = DB_PATH, appointment_count: int = 50000) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"[GENERATOR] Removed existing {db_path}")

    conn = sqlite3.connect(db_path)
    print("[GENERATOR] Creating schema...")
    create_schema(conn)

    print("[GENERATOR] Seeding departments...")
    depts = seed_departments(conn)

    print("[GENERATOR] Seeding doctors (30)...")
    doctors = seed_doctors(conn, depts)

    print(f"[GENERATOR] Seeding patients (5 000)...")
    patients = seed_patients(conn)

    print(f"[GENERATOR] Seeding appointments ({appointment_count:,})...")
    seed_appointments(conn, patients, doctors, count=appointment_count)

    print("[GENERATOR] Creating indexes...")
    create_indexes(conn)

    print("[GENERATOR] Running ANALYZE...")
    run_analyze(conn)

    log_event(conn, "DATA_LOAD", f"Initial synthetic data load: {appointment_count} appointments", "v1.0")
    log_event(conn, "INDEX_ADD", "Created baseline index set (6 indexes)", "v1.0")

    row_count = conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    db_size = os.path.getsize(db_path) / (1024 * 1024)
    print(f"[GENERATOR] Done. Appointments: {row_count:,} | DB size: {db_size:.1f} MB")
    conn.close()


if __name__ == "__main__":
    main()
