# Three-Minute Demonstration Script (Recording Teleprompter)

**Project:** Hospital Appointment Platform — Query Regression Detector  
**Total Duration:** 3:00 (180 Seconds)  
**Tone:** Confident, professional, clear, clinical-engineering focused.  
**Roles:** Primary presenter operating as Database / Platform Administrator.

---

### [0:00 – 0:20] 1. PROBLEM

- **TIME:** `0:00 – 0:20` (20 seconds)
- **SCREEN:** Dashboard Home (`http://localhost:5000/dashboard`)
- **ACTION:** Keep mouse pointer steady over the top KPI banner *"Hospital Query Regression Detector"*.
- **NARRATION:**  
  > "Hospital appointment systems cannot tolerate double booking or unpredictable query slowdowns. The existing reactive monitoring workaround may detect problems only after users are affected. This prototype detects query regressions before simulated user impact."

---

### [0:20 – 0:45] 2. BASELINE

- **TIME:** `0:20 – 0:45` (25 seconds)
- **SCREEN:** Dashboard Core Success Metric Banner / Pre-Impact Section
- **ACTION:** Hover smoothly over the three metric cards: Baseline Workaround (0.0%), Target Goal (90.0%), and Measured Detector Result (96.8%).
- **NARRATION:**  
  > "The prototype compares a synthetic legacy reactive-monitoring baseline with a pre-release regression detector.  
  > In this synthetic experiment, the legacy baseline caught zero percent of regressions before simulated impact, waiting for live traffic to trigger alerts. In contrast, our pre-release detector caught 96.8 percent, comfortably exceeding our 90 percent target."

---

### [0:45 – 1:15] 3. FIND THE REGRESSION

- **TIME:** `0:45 – 1:15` (30 seconds)
- **SCREEN:** Interactive Demo Scenarios & Recent Regressions Table on Dashboard
- **ACTION:** Scroll down to the Interactive Scenarios section. Highlight Scenario 2 (`QRY-004`), click **▶ Run Scenario Demo**, then click on `QRY-004` in the Recent Regressions table below.
- **NARRATION:**  
  > "Here the detector identifies a high-priority regression before simulated clinical traffic reaches the affected query.  
  > Notice Query QRY-004, which verifies whether an appointment slot is already booked. The detector flags this as CRITICAL with a priority score of 105, showing that execution time spiked by over eleven hundred percent."

---

### [1:15 – 1:45] 4. WHY DID IT REGRESS?

- **TIME:** `1:15 – 1:45` (30 seconds)
- **SCREEN:** Query Forensics Detail Page (`http://localhost:5000/query/QRY-004`)
- **ACTION:** Scroll down to the glowing card titled **"WHAT CHANGED? (Root Cause Summary)"**, then hover over the Before/After Quantitative comparison bars.
- **NARRATION:**  
  > "The system does not simply say that the query became slow. It provides evidence explaining what changed.  
  > The execution plan changed, the index context changed, and the release history provides the surrounding change context.  
  > Specifically, during release v1.1, the supporting composite index was accidentally dropped, forcing the database engine into a full table scan across 50,000 appointments."

---

### [1:45 – 2:05] 5. EVIDENCE + REVIEW

- **TIME:** `1:45 – 2:05` (20 seconds)
- **SCREEN:** Query Forensics — Review & Governance Decision Section (Lower Page)
- **ACTION:** Scroll down to the Governance Review form. Type a brief note: `"Index drop confirmed in v1.1 canary"` and click **⚠️ Confirm Regression** (or **👁️ Acknowledge / Under Review**). Show the status update in the audit trail.
- **NARRATION:**  
  > "Every high-priority result is backed by structured evidence. An authorised reviewer can inspect the evidence and record a review decision.  
  > Here, as an administrator, I confirm the regression and record our remediation plan directly into the immutable audit trail, blocking the faulty release from deployment."

---

### [2:05 – 2:30] 6. MEASURABLE RESULT

- **TIME:** `2:05 – 2:30` (25 seconds)
- **SCREEN:** Evaluation & Benchmark Analysis Page (`http://localhost:5000/evaluation`)
- **ACTION:** Navigate to the Evaluation tab in the top navigation bar. Highlight the 2x2 Contingency Table and the Core Success Metric banner.
- **NARRATION:**  
  > "The evaluation uses ground-truth synthetic scenarios rather than a manually selected accuracy number.  
  > Out of 251 true regressions in our benchmark, 243 were detected before simulated user impact, giving 96.8 percent.  
  > Our target was 90.0 percent, and the average detection lead time was 13.1 minutes in the synthetic experiment."

---

### [2:30 – 2:45] 7. ERROR ANALYSIS

- **TIME:** `2:30 – 2:45` (15 seconds)
- **SCREEN:** Evaluation Page — False Positive / False Negative Breakdown
- **ACTION:** Scroll down to the Error Analysis & Threshold Sensitivity tables.
- **NARRATION:**  
  > "The prototype also inspects errors instead of hiding them. False positives and false negatives are explicitly reported so threshold trade-offs can be evaluated.  
  > Our eight false negatives occurred only on tiny sub-millisecond queries, while false positives primarily reflect temporary concurrency surges where query plans stayed healthy."

---

### [2:45 – 3:00] 8. PRIVACY + CONCLUSION

- **TIME:** `2:45 – 3:00` (15 seconds)
- **SCREEN:** Navigation Footer / Privacy Assumptions Note
- **ACTION:** Point cursor to the Zero-PII privacy indicator in the footer or top navigation.
- **NARRATION:**  
  > "The prototype uses synthetic or anonymised data and does not use real patient records. The measured result is from a controlled synthetic experiment.  
  > The result is an end-to-end working query-regression detection prototype that identifies slow-query regressions before simulated user impact, with configurable rules, evidence-backed investigation, role-based access and measurable evaluation."

---

**[STOP RECORDING AT 3:00]**
