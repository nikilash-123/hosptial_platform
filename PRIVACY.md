# Privacy, Data Governance & Confidentiality Policy

**Project Title:** Hospital Appointment Platform Query Regression Detector  
**Document ID:** PRIVACY-GOV-2026-v1.0  
**Status:** In Effect · Formal Prototype Governance Declaration  
**Scope:** Repository-wide Data Inventory, Privacy Assumptions, and Healthcare Governance  

---

> [!IMPORTANT]
> **EXECUTIVE PRIVACY & SYNTHETIC DATA MANDATE:**  
> This software is an engineering research and demonstration prototype for database query-regression detection. **All data used, generated, benchmarked, and evaluated within this repository is 100% synthetic or anonymised.**  
> - **Zero real patient data** is used at any architectural layer.  
> - **Zero real electronic health records (EHR)** or clinical notes are accessed.  
> - **Zero real patient names, NHS/MRN numbers, phone numbers, or email addresses** exist.  
> - **Zero real clinical infrastructure credentials** are embedded or requested.  
> This prototype must **never** be connected to a production clinical database or real appointment system without an independent Data Protection Impact Assessment (DPIA) and formal healthcare security certification.

---

## 1. Comprehensive Data Inventory & Classification

Every data asset within the repository has been inventoried and classified according to its nature, origin, and sensitivity profile:

| Asset Name / Path | File Type | Classification | Description & Privacy Profile |
|---|---|:---:|---|
| `data/synthetic_dataset.db` | SQLite DB | **Synthetic / Technical** | 814 benchmark query regression scenarios across 11 query types; purely synthetic timing, plan hashes, and index metadata. Zero PII. |
| `data/hospital.db` | SQLite DB | **Synthetic** | Local demonstration schema with synthetic patients (`SYNTH-P-*`), doctors (`SYNTH-D-*`), departments, and appointments. |
| `data/detector_store.db` | SQLite DB | **Technical Metadata** | Detector snapshots, query execution timing metrics, execution plan hashes, and local review triage logs. |
| `data/evaluation_results.json` | JSON | **Technical Metadata** | 814 evaluation outputs with confusion matrix, lead-time metrics, and rule evaluation evidence. |
| `data/evaluation_results.csv` | CSV | **Technical Metadata** | Tabular benchmark evaluation export containing query performance metrics and regression classifications. |
| `data/scenario_evaluations.json`| JSON | **Technical Metadata** | Results for 8 canonical controlled test scenarios. |
| `data/threshold_sensitivity.json`| JSON | **Technical Metadata** | Sensitivity sweep results (10%, 20%, 30%, 50% thresholds). |
| `config/rules.yaml` | YAML | **Configuration** | Configurable detection thresholds, rule weights, double-booking multipliers, and role capabilities. |
| `config/probe_queries.yaml` | YAML | **Configuration** | Synthetic SQL templates for canary probe query execution. |
| `src/web/auth.py` | Python | **User / Session Data** | In-memory mock user dictionary with synthetic testing credentials (`admin_user`, `reviewer_user`). |
| `audit_log` (in detector DB) | SQLite Table | **Technical Metadata** | Timestamped audit records for login, rule modifications, and regression reviews with synthetic user IDs. |

---

## 2. Core Privacy Guarantees

1. **Synthetic Patient Profiles:** All patient entities are generated programmatically via `src/synthetic_data_generator.py` with reproducible random seeds. Identifiers strictly follow the synthetic pattern `SYNTH-P-{06d}`.
2. **Age Banding (No Exact DOB):** Patients are represented only by broad statistical age bands (`18-24`, `25-34`, `35-44`, etc.) rather than exact birthdates.
3. **Regional Anonymisation:** Geographic locations use synthetic regional codes (`R01`–`R10`); no street addresses, postal codes, or GPS coordinates are stored.
4. **No Medical Diagnoses or Notes:** The schema purposefully omits clinical diagnoses, medication histories, treatment outcomes, or free-text clinical notes.
5. **Synthetic Clinician Personas:** Doctor entities use synthetic identifiers (`SYNTH-D-{03d}`) and generic specialties (`Cardiology`, `Orthopaedics`). No real clinicians or hospital staff are named.
6. **Synthetic Plan & Workload Telemetry:** Execution plans, storage reads, CPU costs, and concurrency levels are simulated or extracted from synthetic test databases.
7. **Local Isolated Storage:** All SQLite databases and JSON/CSV exports reside locally in the project `data/` directory. No data is transmitted externally or logged to external telemetry services.
8. **No Clinical Decision Support:** The detector analyzes SQL query latency and execution plan graphs; it performs zero clinical diagnosis or medical decision support.

---

## 3. Privacy Assumptions & Operational Risk Matrix

The table below contrasts how data is handled in this prototype versus requirements for a live production clinical deployment:

| Data Dimension | Prototype Source | Sensitive in Production? | Prototype Handling | Production Deployment Requirement |
|---|---|:---:|---|---|
| **Patient Identifiers** | Fully synthetic (`SYNTH-P-*`) | **CRITICAL (PHI / PII)** | Anonymised age bands and region codes; zero PII. | Cryptographic tokenization, pseudonymization, or exclusion from telemetry pipelines. |
| **Appointment Schedules** | Synthetic slots (`SYNTH-A-*`) | **HIGH (Confidential)** | Synthetic dates and times in `appointments` table. | Zero appointment payload leakage; queries must not expose clinic attendance lists. |
| **Query Metadata & SQL** | Synthetic SQL templates | **HIGH (Operational Risk)** | Static parameter-tokenized SQL queries. | **Query parameter masking:** Parameter values (e.g. patient IDs in WHERE clauses) must be stripped to prevent data leakage in slow-query logs. |
| **Execution Plans** | Synthetic plan trees | **MEDIUM (Security Sensitive)** | JSON representations of scan types, row counts, and plan hashes. | Execution plans can reveal schema topology and index presence; restrict access to authorized DBAs via RBAC. |
| **Execution Latencies** | Synthetic performance runs | **LOW (Operational)** | Microsecond/millisecond performance delta tracking. | Latency metadata is non-sensitive operational telemetry; safe for platform monitoring. |
| **Database Indexes** | Synthetic schema definitions | **MEDIUM (Security Sensitive)** | Index presence and drop tracking (`idx_appt_*`). | Internal architectural metadata; protect against unauthorized external inspection. |
| **Database Statistics** | Synthetic `sqlite_stat1` | **LOW (Operational)** | Cardinality estimates and table row count metadata. | Operational optimizer state; safe for DBA diagnostic review. |
| **Release History** | Synthetic release tags (`v1.0`–`v2.1`) | **MEDIUM (Operational)** | Commit hashes and simulated PR references. | Secure repository metadata; integrate with enterprise CI/CD audit logs. |
| **User Identities** | Synthetic test users (`admin_user`) | **HIGH (Identity & Access)** | Local mock users with synthetic usernames. | Enterprise Single Sign-On (SSO) via SAML 2.0 / OIDC with Multi-Factor Authentication (MFA). |
| **Audit Logs** | Local SQLite `audit_log` table | **HIGH (Compliance)** | Action tracking with synthetic user IDs; zero secrets logged. | Write-once append-only centralized audit repository (SIEM) with immutable retention policies. |

> [!WARNING]
> **Operational Privacy Insight: Query Metadata as an Attack Surface**  
> In real-world hospital environments, raw database queries often contain sensitive parameters (e.g., `WHERE patient_id = '12345' AND clinic_id = 'ONCOLOGY'`). If an APM or regression detector logs raw SQL strings without parameter sanitization, it can inadvertently expose patient visit details. In this prototype, query templates are parameterized and run strictly against synthetic identifiers. Production deployment mandates automated SQL bind-variable sanitization.

---

## 4. Secret & Credential Scanning Audit

A comprehensive automated secret scan of the entire codebase confirmed:
- **No production API keys** exist in any file.
- **No live database connection strings** (e.g., Postgres, MySQL, Oracle) exist.
- **No private TLS certificates or SSH keys** are stored in the repository.
- **Application Session Secret:** `app.secret_key` in `src/web/app.py` is configured to load dynamically from the environment variable `FLASK_SECRET_KEY`, falling back to a dedicated synthetic development secret key for local standalone execution.
- **Authentication Credentials:** Application source code does not contain hardcoded passwords. Demo credentials are dynamically resolved via environment variables (`DEMO_DBA_PASSWORD` and `DEMO_REVIEWER_PASSWORD`), with a documented synthetic development fallback for local standalone testing. Production deployment requires an enterprise Identity Provider (OIDC / SAML).

---

## 5. Prototype Security Limitations & Production Requirements

### Current Prototype Limitations:
1. **In-Memory Session Authentication:** The prototype uses Flask client-side cookie sessions signed with a local secret key.
2. **Local SQLite Architecture:** Database state is stored in local, unencrypted SQLite files (`data/*.db`).
3. **Mock Password Authentication:** Local authentication uses plain-text password comparison against an in-memory dictionary for rapid standalone evaluation.
4. **No Real Healthcare Integration:** The application does not interface with HL7, FHIR, Epic, Cerner, or NHS Spine.

### Requirements for Live Healthcare Deployment:
- **Identity & Access Management:** Integration with enterprise identity providers (Active Directory, Okta, Keycloak) using OAuth 2.0 / OIDC and mandatory MFA.
- **Role-Based Authorization:** Strict server-side authorization mapped to verified clinical and infrastructure directory groups.
- **Encryption in Transit & at Rest:** Mandatory TLS 1.3 for all HTTP traffic; AES-256 transparent database encryption for data stores.
- **SQL Sanitization:** Automatic redaction of literal values from SQL statements before forensic plan analysis.
- **SIEM & Audit Retention:** Shipping audit logs to a secure, write-protected logging pipeline (e.g., Splunk, AWS CloudTrail) with multi-year retention complying with healthcare regulations.
- **Compliance Certification:** Formal Data Protection Impact Assessment (DPIA) under UK GDPR / HIPAA prior to hospital staging deployment.

---

*Hospital Appointment Platform Query Regression Detector — Phase 12 Privacy & Data Governance Certification.*
