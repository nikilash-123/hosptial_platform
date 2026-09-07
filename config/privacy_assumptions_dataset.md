# Privacy Assumptions Document — PA-002
# Synthetic Dataset Generation & Regression Telemetry

**Document ID:** PA-002  
**Supersedes:** Extends PA-001 (Application Database Privacy Assumptions)  
**Date:** 2026-09-07  
**Status:** Approved & Enforced  
**Classification:** Public / Open Research Artifact  

---

## 1. Executive Privacy Statement

The synthetic dataset generated for the **Hospital Appointment Platform Query Regression Detector** (`synthetic_dataset.csv`, `synthetic_dataset.json`, `synthetic_dataset.db`) is **100% synthetically fabricated** using rule-based simulation and pseudo-random generation with fixed deterministic seeds.

**NO REAL PATIENTS, NO REAL CLINICIANS, AND NO REAL MEDICAL RECORDS EXIST ANYWHERE WITHIN THIS DATASET.**

The dataset has been specifically engineered to eliminate any risk of Protected Health Information (PHI) leakage under HIPAA, Personally Identifiable Information (PII) exposure under GDPR / UK Data Protection Act 2018, or cross-referencing re-identification.

---

## 2. Privacy Guarantees & Non-Derivation Principles

| Privacy Dimension | Guarantee | Verification Mechanism |
|---|---|---|
| **Patient Identities** | Zero real patient names, NHS numbers, SSNs, or MRNs. | All patient identifiers strictly follow pattern `SYNTH-P-[0-9]{6}`. |
| **Doctor / Clinician Records** | Zero real doctor names, GMC registrations, or staff IDs. | Doctor identifiers strictly follow pattern `SYNTH-D-[0-9]{3}`. |
| **Department & Ward Info** | Generic clinical disciplines only (*Cardiology*, *Orthopaedics*, etc.). | Identifiers follow `SYNTH-DEPT-[0-9]{2}`. |
| **Direct Identifiers** | Absolute absence of phone numbers, email addresses, street addresses, postal codes, and IP addresses. | Schema design omits contact attribute fields entirely. |
| **Quasi-Identifiers** | No precise dates of birth, admission times, or fine-grained geographic tags. | Timestamps represent synthetic simulation offsets only. |
| **Clinical Content** | No diagnosis codes (ICD-10/11), medication names, prescription details, or clinical notes. | Scope restricted to operational query metrics (slots, times, counts, durations). |

---

## 3. Synthetic Generation Methodology

All data points in `data/synthetic_dataset.*` are generated programmatically via [`src/dataset_generator.py`](file:///c:/Users/NIKILASH%20SV/Desktop/COE%20PROJECT%20SPECIAL/hospital%20appointment%20management/src/dataset_generator.py):

1. **Deterministic Random Seed:** Uses Python `random.seed(42)` to ensure exact reproducibility across test runs without relying on live database feeds or external telemetry.
2. **Operational Simulation:** Query plans, execution runtimes, CPU costs, and buffer reads are mathematically modeled based on relational database cost heuristics (index lookups: $O(\log N)$, full table scans: $O(N)$).
3. **No External Network Requests:** The generator runs completely offline in an air-gapped local environment without transmitting or fetching remote data.

---

## 4. Double-Booking Sensitivity & Anonymised Workflows

The dataset explicitly models the critical failure mode of concurrent double-booking:

- In queries such as `verify_slot_booked` (`SYNTH-Q-004`) and `check_doctor_availability` (`SYNTH-Q-002`), regressions in index availability (`idx_appt_doctor_date_time_status`) cause query execution time to spike from 13.8ms to > 280ms.
- This creates an atomic concurrency window during which two booking requests might pass validation simultaneously.
- **Privacy Preservation during Double-Booking Simulation:**
  - The slots and doctor IDs involved in the conflict simulation (`SYNTH-D-012`, `2026-09-15 10:30`) are purely synthetic fixtures.
  - No real calendar or schedule information is consulted.

---

## 5. Security & Threat Model

### Re-Identification Threat Analysis
- **Linkage Attack:** Impossible. There are no demographic attributes (names, birthdates, postcodes) that can be correlated with public registries, electoral rolls, or hospital audit logs.
- **Membership Inference:** Impossible. No machine learning model was trained on private hospital records to generate this synthetic data.
- **Attribute Disclosure:** Impossible. No confidential medical attributes (e.g., test outcomes, diagnoses) exist in the data model.

---

## 6. Permitted Use & Distribution

1. **Benchmarking & Research:** This dataset is safe for open-source publication, query regression detector benchmarking, academic demonstration, and CI/CD automated pipeline testing.
2. **Zero Clinical Reliance:** This dataset must **never** be used for clinical decision support or real hospital scheduling operations.
3. **Governance:** Any future integration with live hospital database endpoints requires a formal Data Protection Impact Assessment (DPIA) and institutional Caldicott Guardian approval prior to connection.

---

*End of Privacy Assumptions Document PA-002*
