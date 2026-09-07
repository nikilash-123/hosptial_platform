# Baseline Creation & Methodology

**Hospital Appointment Platform — Query Regression Detector**  
**Document ID:** DOC-BL-001  
**Version:** 1.0.0  
**Status:** Approved & Implemented  

---

## 1. Executive Summary & Core Principle

In mission-critical healthcare environments such as hospital appointment booking, detecting performance degradation before release deployment is vital. An increase of a few hundred milliseconds in schedule lookup or slot verification creates a concurrency hazard where two patients or clinical coordinators book the identical doctor appointment simultaneously (**double-booking**).

### The Multi-Dimensional Baseline Principle
> **Rule:** A single arbitrary execution-time number (e.g. "runs in 15ms") is **insufficient and unacceptable** as a production baseline.

A real database baseline must be a **multi-dimensional fingerprint** combining:
1. Statistical execution distribution (median, p90, p95, p99, mean) over multiple warm runs.
2. Query optimizer plan fingerprint (`EXPLAIN QUERY PLAN` hash).
3. Structural plan characteristics (index access, temporary b-trees, full table scans).
4. Supporting index state (indexes used, covering index availability).
5. Cardinality and statistics health (table size, statistics age, staleness status).
6. Operational workload context (normal vs peak concurrency envelopes).
7. Data access volume (rows examined vs rows returned).

---

## 2. Multi-Dimensional Baseline Dimensions

For every query in the hospital platform, [`src/core/baseline_engine.py`](file:///c:/Users/NIKILASH%20SV/Desktop/COE%20PROJECT%20SPECIAL/hospital%20appointment%20management/src/core/baseline_engine.py) calculates and persists:

| Dimension | Field in `query_baselines` | Type | Operational Meaning & Significance |
|---|---|---|---|
| **Mean Execution Time** | `mean_exec_ms` | REAL | Arithmetic mean of runtimes across stable runs. |
| **Median Execution Time** | `median_exec_ms` | REAL | 50th percentile ($p50$); eliminates transient OS scheduling noise. |
| **P90 Execution Time** | `p90_exec_ms` | REAL | Upper tail boundary for standard booking latency. |
| **P95 Execution Time** | `p95_exec_ms` | REAL | Primary SLA benchmark threshold. |
| **P99 Execution Time** | `p99_exec_ms` | REAL | Worst-case tail latency under normal operational conditions. |
| **Sample Count** | `sample_count` | INTEGER | Number of timed iterations collected ($N \ge 10$). |
| **Query Plan Hash** | `plan_hash` | TEXT | SHA-256 fingerprint of the normalized optimizer plan tree. |
| **Plan Characteristics** | `plan_characteristics` | JSON | Nodes, scan types (`SEARCH` vs `SCAN`), index lookups, covering flags. |
| **Baseline Indexes** | `indexes` | JSON | List of indexes utilized by the baseline optimizer. |
| **Statistics State** | `statistics_state` | JSON | Age in days of `sqlite_stat1`, staleness flag, and table row counts. |
| **Normal Workload** | `normal_workload_level` | TEXT | Concurrency envelope (`NORMAL` / `LOW`). |
| **Rows Examined** | `rows_examined` | INTEGER | Cardinality scanned by the storage engine (detects unindexed cartesian scans). |
| **Rows Returned** | `rows_returned` | INTEGER | Result set cardinality emitted to caller. |
| **CPU Time** | `cpu_time_ms` | REAL | Kernel + user CPU time consumed. |
| **Estimated I/O Cost** | `io_cost` | REAL | Relative buffer cache and storage block read cost units. |

---

## 3. Configurable Rules & Threshold Architecture

To prevent hard-coded decisions in detector logic, all detection criteria are externalized in [`config/rules.yaml`](file:///c:/Users/NIKILASH%20SV/Desktop/COE%20PROJECT%20SPECIAL/hospital%20appointment%20management/config/rules.yaml):

```yaml
# ── Timing Thresholds ─────────────────────────────────────────────────────────
thresholds:
  time_regression_pct: 20.0       # Flag warning if p95 increases by 20%
  time_high_pct: 50.0             # Flag HIGH regression if p95 increases by 50%
  time_critical_pct: 100.0        # Flag CRITICAL regression if p95 increases by 100%
  absolute_critical_ms: 2000.0    # Absolute SLA breach (blocks release)
  absolute_high_ms: 500.0         # High-latency operational warning
  minimum_meaningful_ms: 1.0      # Sub-millisecond noise floor

# ── Query Plan Rules ──────────────────────────────────────────────────────────
plan_rules:
  flag_scan_regression: true      # Flag SEARCH -> SCAN conversions
  flag_index_loss: true           # Flag dropped or bypassed indexes
  flag_new_full_scan: true        # Flag introduction of unindexed scans
  strict_plan_diff: true          # Require cryptographic plan hash comparison

# ── Statistics Rules ──────────────────────────────────────────────────────────
stats_rules:
  flag_row_estimate_drift_pct: 50.0     # Flag planner row misestimate drift > 50%
  flag_table_growth_pct: 200.0          # Flag unindexed data explosion > 200%
  stats_staleness_days_threshold: 30    # Flag statistics older than 30 days

# ── Workload Rules ────────────────────────────────────────────────────────────
workload_rules:
  flag_workload_surge: true             # Flag concurrency state changes
  max_allowed_workload_level: "HIGH"    # Allowed workload ceiling
  workload_variance_pct: 40.0           # Concurrency grace band (suppresses false positives)

# ── Index Rules ───────────────────────────────────────────────────────────────
index_rules:
  flag_index_modification: true         # Flag column reordering in composite index
  flag_index_loss: true                 # Flag missing required index
```

---

## 4. Reproducibility & Synthetic Dataset Ground Truth

Baselines are **100% reproducible**:

- **From Synthetic Dataset:**
  ```python
  from src.core import baseline_engine
  baselines = baseline_engine.generate_baseline(source="dataset", baseline_tag="v1.0.0")
  ```
  Extracts deterministic observations (seed 42) from [`data/synthetic_dataset.db`](file:///c:/Users/NIKILASH%20SV/Desktop/COE%20PROJECT%20SPECIAL/hospital%20appointment%20management/data/synthetic_dataset.db) representing the verified stable release `REL-101` (`v1.0.0`).

- **From Live Application Database:**
  ```python
  from src.core import baseline_engine
  baselines = baseline_engine.generate_baseline(source="live", baseline_tag="v1.0.0", runs=15)
  ```
  Executes probe queries against [`data/hospital.db`](file:///c:/Users/NIKILASH%20SV/Desktop/COE%20PROJECT%20SPECIAL/hospital%20appointment%20management/data/hospital.db), collecting multi-sample percentiles, EXPLAIN plans, and index statistics.

---

## 5. API Reference

### 1. `generate_baseline(...)`
```python
generate_baseline(
    source: str = "dataset",            # "dataset" or "live"
    baseline_tag: str = "v1.0.0",        # Version identifier
    store_path: str = DEFAULT_STORE_PATH,
    runs: int = 10,
    set_as_active: bool = True
) -> Dict[str, Dict[str, Any]]
```
Calculates and persists all multi-dimensional baseline metrics into the `query_baselines` table and sets the baseline as active.

### 2. `get_baseline(...)`
```python
get_baseline(
    query_id: Optional[str] = None,     # If None, returns all baselines
    baseline_tag: Optional[str] = None, # If None, returns active baseline
    store_path: str = DEFAULT_STORE_PATH
) -> Union[Optional[Dict[str, Any]], Dict[str, Dict[str, Any]]]
```
Retrieves the complete baseline fingerprint for a target query or all queries.

### 3. `compare_against_baseline(...)`
```python
compare_against_baseline(
    new_execution: Dict[str, Any],      # Observed runtime, plan, index, stats
    query_id: Optional[str] = None,
    baseline_tag: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
    store_path: str = DEFAULT_STORE_PATH
) -> Dict[str, Any]
```
Compares a new query run against the baseline fingerprint. Returns structured diagnostics:
- `is_regression`: boolean indicator.
- `regression_label`: `NORMAL`, `WARNING`, `REGRESSION`, `CRITICAL_REGRESSION`.
- `severity`: `OK`, `MEDIUM`, `HIGH`, `CRITICAL`.
- `deltas`: `delta_ms`, `pct_change_p95`, `pct_change_median`, `row_drift_pct`.
- `flags`: detailed boolean flags for time, plan, index, stats, workload, and noise grace.
- `double_booking_risk`: flagged True if regression affects slot verification or availability check.
- `evidence`: forensic audit package with plan hashes and triggered rules.
- `recommendations`: actionable DBA recovery steps (e.g. restore specific index).

---

## 6. Double-Booking Sensitive Query Protections

The queries below directly protect the platform from double-booking race conditions:
1. `SYNTH-Q-002` / `check_doctor_availability`
2. `SYNTH-Q-003` / `create_appointment`
3. `SYNTH-Q-004` / `verify_slot_booked`
4. `SYNTH-Q-007` / `cancel_appointment`
5. `SYNTH-Q-008` / `retrieve_doctor_schedule`

**Special Rule:** If any double-booking sensitive query suffers an index loss or runtime surge $>35\%$, the baseline comparator immediately escalates the finding to **`CRITICAL_REGRESSION`** and flags `double_booking_risk = True` to halt CI/CD pipeline deployments.
