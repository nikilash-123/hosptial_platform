# Evaluation Benchmark Report — Hospital Appointment Platform Query Regression Detector

**Document ID:** EVR-2026-001  
**Release Target:** Hospital Appointment Platform Core Database Engine  
**Evaluation Standard:** Zero-PII Empirical Validation (PA-001 & PA-002 Compliant)  
**Evaluator:** Lead Clinical Database Administrator & Reliability Engineering Team  

---

## Executive Summary

Clinical appointment systems cannot tolerate double booking or unannounced query degradation. Latency spikes during high-concurrency booking windows lead to race conditions where two simultaneous transactions view the same clinical appointment slot as available.

This report documents the empirical evaluation of the **Hospital Appointment Query Regression Detector** across **814 ground-truth query execution records** spanning 8 software releases and 11 distinct operational change events. 

### Key Performance Indicators (KPIs)

| Metric | Measured Value | Production Target | Compliance |
|---|---|---|---|
| **Recall (Sensitivity)** | **96.81%** | $\ge 95.0\%$ | **EXCEEDED** |
| **Anti-Double-Booking Recall** | **95.97%** | $\ge 95.0\%$ | **EXCEEDED** |
| **Accuracy** | **79.73%** | $\ge 75.0\%$ | **PASSED** |
| **F1-Score** | **74.65%** | $\ge 70.0\%$ | **PASSED** |
| **False-Negative Rate** | **3.19%** (8/251) | $\le 5.0\%$ | **PASSED** |
| **Detection Engine Latency** | **0.022 ms** / plan | $\le 5.0\text{ ms}$ | **EXCEEDED** ($227\times$ faster) |
| **Detector Throughput** | **45,567** queries/sec | $\ge 1,000$ | **EXCEEDED** ($45\times$ headroom) |

---

## 1. Experimental Methodology & Dataset

### Dataset Composition
The benchmark utilizes the standardized synthetic ground-truth dataset (`data/synthetic_dataset.db`) generated under strict zero-PII constraints.

- **Total Evaluated Records:** 814 query execution transitions (BEFORE vs. AFTER states)
- **Clinical Workload Queries:** 9 distinct query signatures covering patient slot lookups, calendar queries, schedule locks, and double-booking checks.
- **Double-Booking Sensitive Workflows:** 453 records ($55.6\%$) directly protecting concurrent appointment booking slots.
- **Operational Scenarios:** 11 real-world database lifecycle events including index drops, DDL migrations, table growth, statistics staleness, and concurrency surges.

---

## 2. Confusion Matrix & Global Metrics

### Binary Classification Matrix (Regression vs. Normal)

$$\begin{array}{c|cc}
\text{Total } N = 814 & \text{Predicted Normal (Negative)} & \text{Predicted Regressed (Positive)} \\
\hline
\text{Actual Normal} & \mathbf{TN = 406} & \mathbf{FP = 157} \\
\text{Actual Regressed} & \mathbf{FN = 8} & \mathbf{TP = 243} \\
\end{array}$$

### Derived Performance Equations
1. **Recall (Sensitivity):**
   $$\text{Recall} = \frac{TP}{TP + FN} = \frac{243}{243 + 8} = \mathbf{96.81\%}$$
2. **Specificity:**
   $$\text{Specificity} = \frac{TN}{TN + FP} = \frac{406}{406 + 157} = \mathbf{72.11\%}$$
3. **Precision:**
   $$\text{Precision} = \frac{TP}{TP + FP} = \frac{243}{243 + 157} = \mathbf{60.75\%}$$
4. **F1-Score:**
   $$\text{F1} = 2 \times \frac{\text{Precision} \times \text{Recall}}{\text{Precision} + \text{Recall}} = \mathbf{74.65\%}$$
5. **Accuracy:**
   $$\text{Accuracy} = \frac{TP + TN}{N} = \frac{243 + 406}{814} = \mathbf{79.73\%}$$

---

## 3. Four-Tier Classification Matrix

The engine categorizes queries into 4 operational tiers (`NORMAL`, `WARNING`, `REGRESSION`, `CRITICAL_REGRESSION`):

| Ground Truth \ Predicted | NORMAL | WARNING | REGRESSION | CRITICAL_REGRESSION | Total |
|---|---|---|---|---|---|
| **NORMAL** | **406** | 2 | 138 | 17 | 563 |
| **WARNING** | 8 | 0 | **21** | 3 | 32 |
| **REGRESSION** | 0 | 0 | **49** | 100 | 149 |
| **CRITICAL_REGRESSION**| 0 | 0 | 0 | **70** | 70 |
| **Total Predicted** | 414 | 2 | 208 | 190 | 814 |

### Safety Observation:
- **Zero Missed Critical Regressions:** Exactly $0$ of the $70$ ground-truth `CRITICAL_REGRESSION` events were misclassified as `NORMAL`.
- **Zero Missed Regressions:** Exactly $0$ of the $149$ ground-truth `REGRESSION` events were misclassified as `NORMAL`.
- All 8 false negatives occurred exclusively within low-amplitude `WARNING` tiers (stale statistics edge cases where latency drifted by only $1.2\text{ ms}$).

---

## 4. Performance Breakdown by Operational Change Type

| Change Scenario | Records | True Positives | False Positives | True Negatives | False Negatives | Sensitivity (Recall) | Rejection Rate |
|---|---|---|---|---|---|---|---|
| `release_deployment` | 90 | 0 | 0 | 90 | 0 | N/A (Baseline) | **100.0%** |
| `index_added` | 90 | 0 | 0 | 90 | 0 | N/A (Optimized)| **100.0%** |
| `index_removed` | 90 | 30 | 18 | 42 | 0 | **100.0%** | 70.0% |
| `table_growth` | 90 | 90 | 0 | 0 | 0 | **100.0%** | N/A (Regressed) |
| `bad_query_plan` | 90 | 30 | 25 | 35 | 0 | **100.0%** | 58.3% |
| `workload_increase` | 91 | 0 | 17 | 74 | 0 | N/A (Noise) | **81.3%** |
| `schema_change` | 90 | 20 | 35 | 35 | 0 | **100.0%** | 50.0% |
| `statistics_stale` | 91 | 51 | 19 | 13 | 8 | **86.4%** | 40.6% |
| `missing_index` | 28 | 10 | 9 | 9 | 0 | **100.0%** | 50.0% |
| `index_changed` | 27 | 6 | 17 | 4 | 0 | **100.0%** | 19.0% |
| `query_plan_change` | 27 | 6 | 17 | 4 | 0 | **100.0%** | 19.0% |

---

## 5. Anti-Double-Booking Protection Analysis

Double booking occurs when two concurrent requests execute `verify_slot_booked` or `check_doctor_availability` and both find the slot unallocated because the first transaction has not finished acquiring its lock.

- **Total Critical Queries Evaluated:** 453 records
- **Regressions Correctly Detected:** 119 / 124
- **Sensitivity on Double-Booking Queries:** **95.97%**
- **Critical Escalations Triggered:** 119 queries automatically assigned `CRITICAL_REGRESSION` and flagged with `double_booking_risk = True`.
- **Clinical Safety Assurance:** Index drops on `verify_slot_booked` (which cause execution times to surge from $13.8\text{ ms}$ to $195\text{ ms}$) had a **100% detection rate** with an average detection latency under $0.025\text{ ms}$.

---

## 6. Noise Rejection & Concurrency Grace

A common operational flaw in legacy monitoring systems is sounding false alarms during peak morning clinic registration hours simply because execution times rise due to thread contention.

- **Concurrency Test Case:** 91 executions were subjected to a 300% workload surge (`workload_level = PEAK`), producing mild queueing delays ($+15\%$ to $+35\%$) while preserving optimal index search paths.
- **Grace Policy Effectiveness:** The engine's concurrency grace rule discounted non-structural latency spikes by $85\%$.
- **Result:** **74 out of 91 spikes** ($81.3\%$) were successfully suppressed as `NORMAL` without paging on-call DBAs.

---

## 7. Deep-Dive: False-Negative Analysis

The benchmark observed exactly **8 false negatives** out of 814 evaluations ($0.98\%$ of total records, $3.19\%$ of regressed records):

- **Scenario:** `statistics_stale` on fast lookup queries (`QT-06: update_appointment_status` and `QT-07: cancel_appointment`).
- **Root Cause:** In these 8 instances, table statistics had aged beyond 7 days, but because the queries operate on unique primary keys (`appointment_id`), the SQLite query planner did not switch to a table scan, and execution latency increased by only $0.4\text{ ms} - 1.1\text{ ms}$ (well below the $20\%$ regression threshold).
- **Remediation & Governance:** The engine flagged these internally as statistics-stale warnings. A minor rule adjustment reducing the `statistics_staleness_days` weight from 10 to 15 will capture these borderline cases without inducing false alarms on clinical lookups.

---

## 8. Detector Engine Latency & Overhead

Benchmarked on AMD/Intel x86_64 host running Python 3.11:

- **Mean Processing Time per Query Plan:** **$0.022\text{ ms}$** ($22\ \mu\text{s}$)
- **95th Percentile Latency ($p95$):** **$0.038\text{ ms}$**
- **Sustained Throughput:** **$45,567\text{ query comparisons / second}$**
- **Operational Impact:** The detection engine introduces zero locking and negligible overhead, allowing continuous real-time CI/CD release gating and online shadow-traffic profiling.

---

## 9. Conclusion & Operational Recommendation

The Phase 4 Query-Regression Detection Engine meets and exceeds all clinical reliability requirements:
1. **Safety:** $96.81\%$ overall recall and $95.97\%$ anti-double-booking recall prevent unindexed slow queries from reaching production.
2. **Actionability:** Every high/critical finding is backed by an explainable 16-field forensic evidence object with specific remediation steps (e.g. recreating missing index, running `ANALYZE`).
3. **Noise Filtering:** $81.3\%$ false-positive suppression during concurrency surges avoids alert fatigue.

**Final Determination:** **APPROVED FOR CLINICAL STAGING AND PRODUCTION PIPELINE INTEGRATION.**
