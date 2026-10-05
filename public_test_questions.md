# Public Test Questions
## Compliance Document Intelligence — Candidate Verification Set

These 5 questions are provided so you can verify your system is working correctly. For each question, the expected answer is included so you can check your system's output against it.

Your system does not need to reproduce the expected answer word-for-word — the substance and accuracy of the answer matters, and it must be grounded in the provided policy documents with correct citations.

---

### Q1 — Simple Lookup

**Question:** What documents are required to verify Source of Wealth where a client's wealth comes from employment income?

**Expected Answer:**

Three documents are required:
1. Payslips for the most recent three consecutive months, showing gross and net pay
2. A letter from the employer confirming the client's role, salary, and length of employment (on headed paper, signed by HR or a director)
3. Bank statements for the most recent three months, showing salary credits matching the payslips

A single payslip or verbal confirmation of employment is not sufficient. All three documents must be present and consistent with each other.

**Primary source:** Policy 02 — Source of Wealth Verification Guidelines, Section 3.1

---

### Q2 — Simple Lookup

**Question:** How frequently must sanctions screening be repeated for existing medium-risk clients?

**Expected Answer:**

Medium-risk clients (those with a risk score between 31 and 60) must be screened quarterly.

Additionally, regardless of the scheduled frequency, any update to a sanctions list triggers an immediate re-screen of all active clients within 24 hours of the list update being published.

**Primary source:** Policy 03 — Sanctions and PEP Screening Procedure, Section 4

---

### Q3 — Multi-Document Reasoning

**Question:** A client has been identified as a foreign PEP and also scores 72 on the risk assessment. What requirements apply?

**Expected Answer:**

Two separate triggers apply in this case, both leading to the same outcome:

1. **PEP status** is an automatic High-risk override — EDD is triggered regardless of the risk score (Policy 05, Section 4; Policy 03, Section 6)
2. **Risk score of 72** independently places the client in the High risk band (score 61–100), also requiring EDD (Policy 05, Section 2)

The combined EDD requirements are:
- Source of Wealth verification with a minimum of two independent corroborating sources
- Senior management approval in writing before the relationship is established or continued
- A documented rationale explaining why the relationship is appropriate despite elevated risk
- Ongoing transaction monitoring at an elevated threshold
- Periodic review every six months (not annually)

**Primary sources:** Policy 05 — Risk Assessment Framework, Sections 2, 4, and 5; Policy 03 — Sanctions and PEP Screening Procedure, Section 6; Policy 01 — CDD Policy, Section 5

---

### Q4 — Nuanced Lookup

**Question:** A client submits a passport that expired 4 months ago. Is this acceptable as a primary identity document?

**Expected Answer:**

Yes, this is acceptable. The Document Verification Standards allow passports that are expired within the last 6 months to be used as a primary identity document. A passport expired 4 months ago falls within this window.

However, one additional rule must still be checked: the passport must have been issued within the last 10 years. A passport expired 4 months ago that was issued more than 10 years ago would not be acceptable regardless of its expiry date.

**Primary source:** Policy 04 — Document Verification Standards, Sections 2 and 3

---

### Q5 — Hallucination Guard Test

**Question:** What is the procedure for verifying Source of Wealth where a client's wealth originates entirely from cryptocurrency trading?

**Expected Answer:**

The provided policy documents do not cover cryptocurrency trading as a Source of Wealth category.

Policy 02 (Source of Wealth Verification Guidelines) defines five recognised wealth categories: Employment/Salary, Business Ownership or Sale, Inheritance, Investment Portfolio, and Property/Real Estate. Cryptocurrency trading does not fall within any of these categories as documented.

The policy states that where a client's wealth does not fit any recognised category, the case must be escalated to the MLRO before the file progresses. The MLRO will determine whether the wealth source is sufficiently explained and documented.

**A correct system response should:** identify that this specific scenario is not covered in the provided documents, cite the escalation requirement, and explicitly flag that it cannot provide a complete procedure from the available sources — rather than fabricating one.

**Primary source:** Policy 02 — Source of Wealth Verification Guidelines, Section 2
