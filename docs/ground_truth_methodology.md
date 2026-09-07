# Ground Truth Methodology & Label Assignment

## 1. Overview and Objective
This document outlines the formal methodology used to establish verifiable ground-truth labels for the Hospital Appointment Platform Query Regression Detector benchmark dataset ($N = 814$). 

To avoid arbitrary or subjective evaluation, all ground-truth labels and severity classifications are assigned using deterministic, reproducible rules based on observable database physical execution characteristics, schema transitions, index states, workload metrics, and deployment history.

## 2. Zero-PII Compliance (PA-002)
In accordance with the project privacy mandate (PA-002):
- The benchmark dataset contains **zero real patient data (0% PII)**.
- All patient identifiers (`patient_id`), appointment dates, doctor schedules, and clinical departments are synthetically generated.
- Query execution plans, scan types, and timings simulate real-world relational database behavior under controlled conditions.

---

## 3. Ground Truth Categorization Scheme

Every evaluated query execution record is classified into one of four primary categorical classes:

| Class | Definition | Inclusion Criteria |
| :--- | :--- | :--- |
| **`TRUE_REGRESSION`** | Query suffers performance degradation caused by a physical plan change, missing index, stale statistics, or release defect. | • Plan scan changed from Index to Table Scan (`is_table_scan=True` when baseline had index)<br>• Execution latency increased by $\ge 20\%$ relative to baseline<br>• Index dropped or missing on filtered columns<br>• Stale table statistics producing suboptimal cardinality estimates |
| **`WORKLOAD_SLOWDOWN`** | Latency elevated solely due to external concurrency and queueing pressure, while query plan remains optimal. | • Execution latency increased by $\ge 20\%$<br>• Execution plan retained optimal index lookups (`scan_type == 'Index Scan'`)<br>• High active concurrent query volume ($\ge 80$ QPS)<br>• No index drops or schema alterations |
| **`NORMAL`** | Healthy, expected execution within standard operating thresholds. | • Latency variation within $[-10\%, +20\%]$ of baseline<br>• Plan structure intact<br>• No dropped indexes or critical warnings |
| **`INSUFFICIENT_EVIDENCE`** | Indeterminate or ambiguous signals where baseline or current metrics are incomplete. | • Missing baseline plan or timing telemetry<br>• Unresolvable schema version tag |

---

## 4. Ground Truth Severity Assignment Rules

For binary and multi-class classification, severity is determined according to operational risk to hospital clinical workflows:

### CRITICAL Severity
- **Criteria:**
  - Double-booking sensitive query (`q_check_conflict`, `q_active_slots`) experiencing a regression.
  - Plan degradation to Full Table Scan on patient or appointment tables exceeding 5,000 rows.
  - Absolute execution time increase exceeding $200\%$ with dropped primary or composite index.
- **Clinical Impact:** Potential double-booking of doctor slots, clinic check-in gridlocks, or patient wait-time escalations.

### HIGH Severity
- **Criteria:**
  - Non-slot query experiencing an execution plan degradation (Index Scan $\to$ Table Scan).
  - Relative execution latency increase $\ge 50\%$.
  - Dropped secondary index impacting doctor schedule or departmental reporting queries.
- **Clinical Impact:** Degraded administrative workflow, slow patient medical record lookups.

### WARNING / MEDIUM Severity
- **Criteria:**
  - Execution time increase between $20\%$ and $50\%$.
  - Suboptimal index choice due to stale table statistics without full table scan.
  - External workload concurrency spike elevating response latency without structural plan failure.

### NORMAL / LOW Severity
- **Criteria:**
  - Performance delta $< 20\%$ and plans identical to baseline.
  - Successful index addition improving or maintaining latency.

---

## 5. Causal Evidence Audit Requirements
Every record labeled as `TRUE_REGRESSION` or evaluated as high priority must possess concrete, verifiable causal evidence across 17 distinct operational dimensions:
1. Baseline execution time ($ms$)
2. Current execution time ($ms$)
3. Relative delta percentage ($\%$)
4. Baseline plan hash
5. Current plan hash
6. Scan type transition (`Index Scan` vs `Full Table Scan`)
7. Estimated query cost transition
8. Rows examined delta
9. Index availability and presence
10. Database statistics staleness level
11. Workload concurrency metrics
12. Schema migration history
13. Software release tag
14. Execution timestamps
15. Rule-derived priority score
16. Actionable remediation recommendation
17. Detection-before-impact lead time
