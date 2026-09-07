# Privacy Assumptions Document — PA-001
# Hospital Appointment Platform Query Regression Detector

**Document ID:** PA-001  
**Date:** 2026-09-07  
**Author:** Synthetic-data prototype team  
**Status:** In Effect

---

## 1. Scope

This document applies to all data used in the Hospital Appointment Platform Query Regression Detector prototype, including the application database (`hospital.db`) and the detector state store (`detector_store.db`).

---

## 2. Privacy Guarantees

| Guarantee | Detail |
|---|---|
| **No real patient data** | Zero real patient records are used at any layer |
| **No real PII** | No real names, NHS numbers, phone numbers, addresses, dates of birth, postcodes, email addresses, or National Insurance numbers |
| **No real hospital data** | No real hospital names, ward names, real doctor names, or real clinical appointment records |
| **No real medical records** | No diagnoses, medications, clinical notes, or treatment histories |

---

## 3. Synthetic Data Generation

All data is generated programmatically by `src/synthetic_data_generator.py` using:

- **Library:** [Faker](https://faker.readthedocs.io/) with a **fixed random seed (42)** for reproducibility
- **Patient identifiers:** Pattern `SYNTH-P-{6-digit-zero-padded-integer}` (e.g., `SYNTH-P-000001`)
- **Appointment identifiers:** Pattern `SYNTH-A-{6-digit-integer}`
- **Doctor identifiers:** Pattern `SYNTH-D-{3-digit-integer}`
- **Department identifiers:** Pattern `SYNTH-DEPT-{2-digit-integer}`
- **Age representation:** Age bands only (`25-34`, `35-44`, etc.) — no exact date of birth
- **Gender:** Stored as `M`, `F`, or `O` — no full name
- **Region:** Anonymised 2-letter code (`R01`–`R10`) — no real postcode or address
- **Doctor specialty:** Generic specialty strings (`Cardiology`, `Orthopaedics`, etc.) — no real clinician name

---

## 4. Data Retention

- `hospital.db` and `detector_store.db` are local SQLite files created at runtime
- No data is transmitted to any external service or network endpoint
- No data is persisted beyond the local development environment

---

## 5. Intended Use

This prototype is intended **solely** for demonstrating query regression detection logic. It must **not** be connected to any real hospital system, real appointment database, or any environment containing real patient records without a full Data Protection Impact Assessment (DPIA) and appropriate legal basis under UK GDPR / HIPAA (as applicable).

---

## 6. Researcher Responsibilities

Any researcher or engineer running this prototype confirms:
1. They will not substitute real patient data for the synthetic dataset
2. They will not deploy this prototype against a live hospital system without appropriate governance
3. They will delete all generated data files after the prototype evaluation period

---

*End of PA-001*
