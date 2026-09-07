# Data Dictionary: Hospital Appointment Platform Query Regression Dataset

**Document Version:** 1.0.0  
**Dataset Format:** CSV (`synthetic_dataset.csv`), JSON (`synthetic_dataset.json`), SQLite (`synthetic_dataset.db`)  
**Scope:** Synthetic query execution fingerprints, query plans, index statuses, database telemetry, and rule-derived regression labels.  
**Zero-PII Certification:** 100% anonymised/synthetic data. No real patient, clinical, or hospital identifiers.

---

## 1. Overview & Entity Relationship

The synthetic dataset provides query execution profiles across 9 release lifecycles (`REL-101` through `REL-109`), simulating operational health, workload fluctuations, index modifications, and regression events.

Each record represents an observed execution of a hospital appointment platform query against a specific release tag, capturing performance metrics relative to a verified baseline.

---

## 2. Field Specifications

| # | Field Name | Data Type | Nullable | Permitted Values / Pattern | Description & Operational Relevance |
|---|---|---|:---:|---|---|
| 1 | `query_id` | TEXT | No | `SYNTH-Q-001` to `SYNTH-Q-009` | Unique identifier for the probe query template. |
| 2 | `query_name` | TEXT | No | String | Human-readable title of the query operation (e.g., *Find available appointment slots*). |
| 3 | `query_type` | TEXT | No | `find_available_slots`, `check_doctor_availability`, `create_appointment`, `verify_slot_booked`, `search_appointments`, `update_appointment_status`, `cancel_appointment`, `retrieve_doctor_schedule`, `retrieve_department_schedule` | Functional domain category of the query. Determines critical path designation. |
| 4 | `release_id` | TEXT | No | `REL-101` to `REL-109` | Unique tracking ID for the deployment or change event. |
| 5 | `release_version` | TEXT | No | `v1.0.0` to `v2.2.0` | Semantic version string for the hospital platform release. |
| 6 | `timestamp` | TEXT | No | ISO-8601 string (`YYYY-MM-DD HH:MM:SS`) | Timestamp when the query execution was measured. |
| 7 | `execution_time_ms` | REAL | No | Positive float (`>= 0.1`) | Measured 95th-percentile (p95) runtime in milliseconds for the query under test. |
| 8 | `baseline_execution_time_ms` | REAL | No | Positive float (`>= 0.1`) | Benchmark p95 runtime in milliseconds established in the verified baseline release (`v1.0.0`). |
| 9 | `rows_examined` | INTEGER | No | Positive integer (`>= 0`) | Total records scanned/inspected by the storage engine during query evaluation. Surges during unindexed full-table scans. |
| 10 | `rows_returned` | INTEGER | No | Positive integer (`>= 0`) | Number of records emitted by the query to the client application. |
| 11 | `cpu_time_ms` | REAL | No | Positive float (`>= 0.0`) | Kernel and user CPU time consumed by the database engine executing the query plan. |
| 12 | `io_cost` | REAL | No | Positive float (`>= 0.0`) | Estimated I/O cost units (disk read operations, cache misses, buffer manager page fetches). |
| 13 | `plan_hash` | TEXT | Yes | 16-character hex string, or `NULL` / `PARSE_ERROR_SCAN` | SHA-256 fingerprint of the normalized `EXPLAIN QUERY PLAN` tree. Null indicates missing execution plan. |
| 14 | `baseline_plan_hash` | TEXT | No | 16-character hex string | SHA-256 fingerprint of the verified baseline query execution plan. |
| 15 | `plan_changed` | INTEGER | No | `0` (False), `1` (True) | Boolean indicator if `plan_hash` differs from `baseline_plan_hash`. |
| 16 | `index_name` | TEXT | Yes | String (e.g., `idx_appt_doctor_date`, `None`) | Primary index utilized or expected by the query optimizer. |
| 17 | `index_status` | TEXT | No | `OPTIMAL`, `ADDED`, `REMOVED`, `CHANGED`, `MISSING`, `UNUSED`, `UNKNOWN` | Operational state of the query's supporting index. |
| 18 | `statistics_age` | INTEGER | No | Integer (`>= 0`) | Number of days elapsed since the database statistics (`sqlite_stat1`) were last refreshed via `ANALYZE`. |
| 19 | `statistics_status` | TEXT | No | `CURRENT` (<= 30 days), `STALE` (> 30 days), `MISSING` | Health status of table and index distribution statistics. |
| 20 | `workload_level` | TEXT | No | `LOW`, `NORMAL`, `HIGH`, `PEAK` | Concurrency state of the platform during the benchmark run. |
| 21 | `schema_change` | TEXT | No | `NONE`, `COLUMN_ADDED`, `TYPE_ALTERED`, `INDEX_DROPPED`, `INDEX_ADDED`, `INDEX_MODIFIED`, `TABLE_PARTITIONED` | DDL schema modification applied in this release. |
| 22 | `release_change` | TEXT | No | `index_added`, `index_removed`, `index_changed`, `statistics_stale`, `schema_change`, `workload_increase`, `query_plan_change`, `table_growth`, `bad_query_plan`, `missing_index`, `release_deployment` | High-level categorization of the underlying system change. |
| 23 | `regression_label` | TEXT | No | `NORMAL`, `WARNING`, `REGRESSION`, `CRITICAL_REGRESSION` | Rule-derived classification of query regression status. |
| 24 | `regression_severity` | TEXT | No | `OK`, `MEDIUM`, `HIGH`, `CRITICAL` | Severity rating corresponding to the regression label. |
| 25 | `expected_impact` | TEXT | No | String description | Technical and architectural database impact (CPU saturation, lock contention, scan overhead). |
| 26 | `user_impact` | TEXT | No | String description | Clinical and operational impact on patients and hospital staff (e.g., double-booking exposure, UI freeze). |
| 27 | `evidence` | TEXT | No | Valid JSON string | Structured forensic evidence package containing triggered rule, delta percentages, plan diff, and remediation advice. |

---

## 3. Query Catalog Details (9 Query Types)

### QT-01: Find Available Appointment Slots (`find_available_slots`)
- **Query ID:** `SYNTH-Q-001`
- **Purpose:** Identifies open schedule slots for specific clinic departments on a target date.
- **Baseline Plan:** `SEARCH appointment_slots USING INDEX idx_appt_dept_date_status`
- **Sensitivity:** High patient throughput; essential for portal booking responsiveness.

### QT-02: Check Doctor Availability (`check_doctor_availability`)
- **Query ID:** `SYNTH-Q-002`
- **Purpose:** Confirms if a physician has an opening on a given date.
- **Baseline Plan:** `SEARCH appointments USING INDEX idx_appt_doctor_date`
- **Sensitivity:** **Double-Booking Sensitive**. Must execute in < 25ms to prevent overlapping scheduling.

### QT-03: Create Appointment (`create_appointment`)
- **Query ID:** `SYNTH-Q-003`
- **Purpose:** Inserts a newly committed appointment record into the appointments table.
- **Baseline Plan:** `INSERT INTO appointments USING UNIQUE INDEX idx_appt_pk`
- **Sensitivity:** **Double-Booking Sensitive**. Atomic reservation step.

### QT-04: Verify Slot Already Booked (`verify_slot_booked`)
- **Query ID:** `SYNTH-Q-004`
- **Purpose:** Directly checks whether an overlapping appointment exists for a doctor at a designated time.
- **Baseline Plan:** `SEARCH appointments USING COVERING INDEX idx_appt_doctor_date_time_status`
- **Sensitivity:** **CRITICAL Double-Booking Safeguard**. Any regression exposes concurrent bookings to race conditions.

### QT-05: Search Appointments (`search_appointments`)
- **Query ID:** `SYNTH-Q-005`
- **Purpose:** Multi-parameter search across patient history, doctor specialties, and dates.
- **Baseline Plan:** `SEARCH a USING INDEX idx_appt_patient_date; SEARCH d USING INDEX idx_doctor_pk`
- **Sensitivity:** Read-heavy clinical lookup.

### QT-06: Update Appointment Status (`update_appointment_status`)
- **Query ID:** `SYNTH-Q-006`
- **Purpose:** Transitions appointment state (`SCHEDULED` -> `CHECKED_IN` -> `COMPLETED`).
- **Baseline Plan:** `SEARCH appointments USING INDEX idx_appt_pk`
- **Sensitivity:** Clinical desk workflow.

### QT-07: Cancel Appointment (`cancel_appointment`)
- **Query ID:** `SYNTH-Q-007`
- **Purpose:** Cancels an existing booking and frees physician capacity.
- **Baseline Plan:** `SEARCH appointments USING INDEX idx_appt_pk`
- **Sensitivity:** **Double-Booking Sensitive**. Released slots must immediately reflect availability.

### QT-08: Retrieve Doctor Schedule (`retrieve_doctor_schedule`)
- **Query ID:** `SYNTH-Q-008`
- **Purpose:** Fetches daily timetable of scheduled patient appointments for a clinician.
- **Baseline Plan:** `SEARCH appointments USING INDEX idx_appt_doctor_date`
- **Sensitivity:** **Double-Booking Sensitive**. Used in clinician calendar views.

### QT-09: Retrieve Department Schedule (`retrieve_department_schedule`)
- **Query ID:** `SYNTH-Q-009`
- **Purpose:** Aggregates slot counts and utilization across department clinics over a date range.
- **Baseline Plan:** `SEARCH appointments USING INDEX idx_appt_dept_date USE TEMP B-TREE FOR GROUP BY`
- **Sensitivity:** Administrative and capacity planning reporting.

---

## 4. Measurable Rule Engine & Label Calculation

Labels are **never randomly generated**. They are evaluated deterministically using measurable criteria aligned with `config/rules.yaml`:

```
delta_ms   = execution_time_ms - baseline_execution_time_ms
pct_change = (delta_ms / baseline_execution_time_ms) * 100.0
```

1. **`CRITICAL_REGRESSION` (`severity = CRITICAL`):**
   - `execution_time_ms >= 2000.0 ms` (Absolute SLA timeout threshold), OR
   - `pct_change >= 100.0%` AND (`plan_changed == 1` OR `index_status IN ('REMOVED', 'MISSING')`), OR
   - Double-booking sensitive query (`verify_slot_booked`, `check_doctor_availability`) AND index dropped/missing AND `pct_change >= 40.0%`.
   - *Action:* Block platform release.

2. **`REGRESSION` (`severity = HIGH`):**
   - `pct_change >= 50.0%`, OR
   - `plan_changed == 1` AND `pct_change >= 20.0%`.
   - *Action:* Require DBA review and optimization before deployment.

3. **`WARNING` (`severity = MEDIUM`):**
   - `pct_change >= 20.0%` (below 50%), OR
   - `statistics_status == 'STALE'` (statistics age > 30 days causing planner row estimate drift).
   - *Action:* Log alert; trigger `ANALYZE` or schedule index defragmentation.

4. **`NORMAL` (`severity = OK`):**
   - `abs(pct_change) <= 10.0%` (Within false-positive noise band), OR
   - Execution time increased due to high concurrency (`workload_level IN ('HIGH', 'PEAK')`) without query plan change or index drop (False Positive grace suppression).

---

## 5. Edge & Failure Scenarios

| Scenario ID | Edge Scenario Description | Encoded Attributes | Expected Detector Behavior |
|---|---|---|---|
| **EDGE-01** | **Missing Execution Plan** | `plan_hash = NULL`, `index_status = 'UNKNOWN'`, `error_code = 'PLAN_PROFILER_EMPTY'` | System gracefully flags warning without crashing. |
| **EDGE-02** | **Stale Database Statistics** | `statistics_age = 52`, `statistics_status = 'STALE'`, row misestimate | Flags planner drift; recommends running `ANALYZE`. |
| **EDGE-03** | **Workload Surge Without Plan Shift** | `workload_level = 'PEAK'`, `delta_pct = +43.75%`, `plan_changed = 0`, `index_status = 'OPTIMAL'` | Evaluates to `NORMAL` (suppresses false alarm). |
| **EDGE-04** | **Missing Index with Plan Parsing Degradation** | `index_status = 'MISSING'`, `plan_hash = 'PARSE_ERROR_SCAN'`, `delta_pct = +1965%` | Flags `CRITICAL_REGRESSION` on double-booking workflow. |
