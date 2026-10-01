-- ============================================================================
-- QUERYGUARD AI: PostgreSQL Database Schema
-- Hospital Appointment Platform — Query Regression Detector
-- Focus: Database Telemetry, Query Performance Analysis & Double-Booking Prevention
-- All data synthetic (PA-001 / PA-002 compliant, Zero PII)
-- ============================================================================

-- Drop tables in dependency order if recreating
DROP TABLE IF EXISTS query_telemetry CASCADE;
DROP TABLE IF EXISTS transaction_log CASCADE;
DROP TABLE IF EXISTS appointments CASCADE;
DROP TABLE IF EXISTS appointment_slots CASCADE;
DROP TABLE IF EXISTS doctors CASCADE;
DROP TABLE IF EXISTS departments CASCADE;
DROP TABLE IF EXISTS patients CASCADE;
DROP TABLE IF EXISTS audit_log CASCADE;

-- 1. Patients (Synthetic Demographics only, No PII)
CREATE TABLE patients (
    patient_id    VARCHAR(32) PRIMARY KEY,
    age_band      VARCHAR(16) NOT NULL,
    gender        VARCHAR(8)  NOT NULL,
    region_code   VARCHAR(16) NOT NULL,
    registered_at TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Hospital Departments
CREATE TABLE departments (
    dept_id   VARCHAR(32) PRIMARY KEY,
    dept_name VARCHAR(64) NOT NULL,
    floor     INTEGER     NOT NULL
);

-- 3. Medical Doctors
CREATE TABLE doctors (
    doctor_id  VARCHAR(32) PRIMARY KEY,
    specialty  VARCHAR(64) NOT NULL,
    dept_id    VARCHAR(32) NOT NULL REFERENCES departments(dept_id),
    is_active  INTEGER     NOT NULL DEFAULT 1
);

-- 4. Appointment Slots (Available and Booked Slot Schedule)
CREATE TABLE appointment_slots (
    slot_id        VARCHAR(32) PRIMARY KEY,
    doctor_id      VARCHAR(32) NOT NULL REFERENCES doctors(doctor_id),
    dept_id        VARCHAR(32) NOT NULL REFERENCES departments(dept_id),
    slot_date      DATE        NOT NULL,
    slot_time      TIME        NOT NULL,
    duration_mins  INTEGER     NOT NULL DEFAULT 30,
    is_available   BOOLEAN     NOT NULL DEFAULT TRUE,
    release_version VARCHAR(16) NOT NULL DEFAULT 'v1.0',
    schema_version VARCHAR(16) NOT NULL DEFAULT 'v1.0'
);

-- 5. Appointments (Bookings with Anti-Double Booking Guard)
CREATE TABLE appointments (
    appt_id          VARCHAR(32) PRIMARY KEY,
    patient_id       VARCHAR(32) NOT NULL REFERENCES patients(patient_id),
    doctor_id        VARCHAR(32) NOT NULL REFERENCES doctors(doctor_id),
    dept_id          VARCHAR(32) NOT NULL REFERENCES departments(dept_id),
    slot_id          VARCHAR(32) REFERENCES appointment_slots(slot_id),
    appt_date        DATE        NOT NULL,
    appt_time        TIME        NOT NULL,
    duration_mins    INTEGER     NOT NULL DEFAULT 30,
    status           VARCHAR(32) NOT NULL DEFAULT 'SCHEDULED',
    transaction_id   VARCHAR(64),
    release_version  VARCHAR(16) NOT NULL DEFAULT 'v1.0',
    schema_version   VARCHAR(16) NOT NULL DEFAULT 'v1.0',
    booking_timestamp TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at       TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 6. Platform Audit Log (Schema DDL & Release Changes)
CREATE TABLE audit_log (
    log_id         SERIAL PRIMARY KEY,
    event_type     VARCHAR(64)  NOT NULL,
    description    TEXT         NOT NULL,
    release_tag    VARCHAR(32)  NOT NULL DEFAULT 'v1.0',
    schema_version VARCHAR(16)  NOT NULL DEFAULT 'v1.0',
    applied_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 7. Transaction Audit Log (Double-booking contention & isolation traces)
CREATE TABLE transaction_log (
    txn_id          VARCHAR(64) PRIMARY KEY,
    appt_id         VARCHAR(32),
    doctor_id       VARCHAR(32),
    action          VARCHAR(32)  NOT NULL,
    isolation_level VARCHAR(32)  NOT NULL DEFAULT 'READ COMMITTED',
    status          VARCHAR(32)  NOT NULL,
    duration_ms     DOUBLE PRECISION,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 8. Database Query Telemetry (EXPLAIN & EXPLAIN ANALYZE traces)
CREATE TABLE query_telemetry (
    telemetry_id     SERIAL PRIMARY KEY,
    query_id         VARCHAR(32)      NOT NULL,
    query_name       VARCHAR(128)     NOT NULL,
    release_version  VARCHAR(16)      NOT NULL,
    schema_version   VARCHAR(16)      NOT NULL DEFAULT 'v1.0',
    transaction_id   VARCHAR(64),
    exec_time_ms     DOUBLE PRECISION NOT NULL,
    planning_time_ms DOUBLE PRECISION,
    total_cost       DOUBLE PRECISION NOT NULL,
    startup_cost     DOUBLE PRECISION,
    estimated_rows   BIGINT           NOT NULL,
    actual_rows      BIGINT,
    scan_type        VARCHAR(64)      NOT NULL,
    shared_hit_blocks BIGINT          DEFAULT 0,
    shared_read_blocks BIGINT         DEFAULT 0,
    plan_json        JSONB,
    plan_text        TEXT,
    created_at       TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- BASELINE INDEXES & CONSTRAINTS
-- ============================================================================

-- Anti Double-Booking Unique Index (Enforces zero double-booking at DB engine level)
CREATE UNIQUE INDEX idx_prevent_double_booking 
ON appointments(doctor_id, appt_date, appt_time) 
WHERE status = 'SCHEDULED';

-- Supporting composite query indexes
CREATE INDEX idx_appt_doctor_date ON appointments(doctor_id, appt_date);
CREATE INDEX idx_appt_doctor_date_time ON appointments(doctor_id, appt_date, appt_time);
CREATE INDEX idx_appt_patient ON appointments(patient_id);
CREATE INDEX idx_appt_status_date ON appointments(status, appt_date);
CREATE INDEX idx_appt_dept_date ON appointments(dept_id, appt_date);
CREATE INDEX idx_slots_doc_date_avail ON appointment_slots(doctor_id, slot_date, is_available);
CREATE INDEX idx_doctors_dept ON doctors(dept_id);
CREATE INDEX idx_telemetry_query_rel ON query_telemetry(query_id, release_version);
