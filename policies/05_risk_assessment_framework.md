# Risk Assessment Framework
**Version:** 1.8  
**Effective Date:** 1 January 2025  
**Owner:** MLRO  
**Review Cycle:** Annual

---

## 1. Purpose

This framework defines how the platform calculates a client's risk score at onboarding and reassesses it during periodic reviews. The risk score determines the applicable CDD tier, the intensity of Source of Wealth verification, the frequency of sanctions and PEP screening, and the review cycle.

The risk score is not a substitute for human judgement. A reviewing officer who identifies material concerns about a client must escalate regardless of the numerical score. The score is a floor, not a ceiling.

---

## 2. Risk Bands

All clients are assigned to one of three risk bands based on their composite risk score:

| Risk Band | Score Range | CDD Tier | Review Frequency |
|-----------|-------------|----------|-----------------|
| Low | 0 – 30 | Simplified Due Diligence (SDD) | Every 24 months |
| Medium | 31 – 60 | Standard CDD | Every 12 months |
| High | 61 – 100 | Enhanced Due Diligence (EDD) | Every 6 months |

A client scoring 31–60 may be manually escalated to High by the reviewing officer or the MLRO if qualitative factors warrant it. Manual escalations must be documented with a written rationale.

---

## 3. Risk Scoring Methodology

The composite risk score is the sum of scores across four risk dimensions. Each dimension has a defined scoring range and set of indicators.

### 3.1 Country Risk (0–30 points)

Country risk reflects the risk associated with the client's country of residence, country of nationality, and — for entities — the jurisdiction of incorporation and principal place of business.

| Indicator | Points |
|-----------|--------|
| Residence or nationality in a FATF grey-listed jurisdiction | 20 |
| Residence or nationality in a FATF blacklisted jurisdiction | 30 |
| Residence or nationality in an EU high-risk third country | 25 |
| Residence or nationality in a jurisdiction with weak AML enforcement (non-FATF listed) | 15 |
| Residence or nationality in the UK, EU/EEA, US, Canada, Australia, New Zealand, Japan, Singapore | 0 |
| All other jurisdictions not listed above | 10 |

Where a client has connections to multiple jurisdictions (e.g., dual nationality, offshore holding company), the **highest-scoring jurisdiction** determines the country risk score.

### 3.2 Client Type Risk (0–30 points)

Client type risk reflects inherent characteristics of the client that are associated with elevated money laundering exposure.

| Indicator | Points |
|-----------|--------|
| Politically Exposed Person (any tier, see Policy 03) | 30 |
| Close associate or family member of a PEP | 20 |
| Cash-intensive business owner or operator | 25 |
| Trust, foundation, or complex legal arrangement | 20 |
| Non-face-to-face customer (remote onboarding) | 10 |
| High-net-worth individual with assets above £5 million | 10 |
| Standard individual with no elevated characteristics | 0 |

Where a client matches more than one indicator, all applicable points are **added together**, subject to the maximum of 30 for this dimension. The dimension score is capped at 30.

### 3.3 Product and Service Risk (0–20 points)

Product risk reflects the risk associated with the specific service being provided by the regulated firm.

| Indicator | Points |
|-----------|--------|
| Discretionary investment management or wealth structuring | 20 |
| Legal services involving real estate transactions | 15 |
| Legal services involving company formation or trust administration | 15 |
| Conveyancing | 15 |
| AML/KYC compliance services only (no asset management) | 5 |
| Standard legal advisory (no asset handling) | 5 |

### 3.4 Delivery Channel Risk (0–20 points)

Delivery channel risk reflects how the business relationship is being established and managed.

| Indicator | Points |
|-----------|--------|
| Fully remote onboarding with no prior relationship | 15 |
| Introduced by an unregulated third party | 20 |
| Introduced by a regulated third party in a high-risk jurisdiction | 15 |
| Introduced by a regulated third party in a low-risk jurisdiction | 5 |
| Existing client with established relationship and clean history | 0 |
| Face-to-face onboarding | 0 |

---

## 4. Automatic High-Risk Overrides

Certain client characteristics automatically assign the High risk band and trigger EDD, **regardless of the composite score**. These are:

- **PEP status** (any tier): always High, always EDD
- **Confirmed nexus to a sanctioned entity or jurisdiction**: always High, always EDD
- **Complex ownership structure** where full beneficial ownership cannot be established: always High, EDD until resolved
- **Adverse media** indicating financial crime, fraud, or corruption: always High, MLRO review required
- **Prior SAR filing** associated with the client or a closely connected party: always High, MLRO review required

These overrides cannot be manually removed by a reviewing officer. Only the MLRO can approve a downgrade from an automatic High override, and the reasoning must be documented in full.

---

## 5. Enhanced Due Diligence Requirements

Where a client is assigned to the High risk band (whether by score or by automatic override), the following EDD requirements apply in addition to Standard CDD:

- **Source of Wealth**: minimum two independent corroborating sources (see Policy 02)
- **Senior management approval**: a named senior manager must approve the relationship before it commences. Approval must be in writing and stored on the client file.
- **Transaction monitoring**: set to the elevated monitoring threshold for the client type and service
- **Periodic review**: every six months, or immediately upon a trigger event (see CDD Policy, Section 7)
- **Documented rationale**: the file must contain a written explanation of why the firm has assessed the relationship as appropriate to accept despite the elevated risk

If EDD cannot be completed to the required standard, the relationship must not be established. If it arises mid-relationship, the relationship must be suspended and the MLRO notified.

---

## 6. Risk Score Reassessment

The risk score is reassessed at each scheduled periodic review and must also be reassessed immediately when:

- The client reports a change of address, nationality, or beneficial ownership
- A new sanctions, PEP, or adverse media alert is generated
- The client requests a new or materially different service
- A transaction pattern inconsistent with the client's profile is identified

Following reassessment, if the client's risk band changes, the file must be updated and the CDD tier adjusted accordingly. A downgrade in risk band must be approved by the MLRO and documented.

---

## 7. Record Keeping

The risk score for each client must be recorded at every assessment point, including:

- The component scores for each of the four dimensions
- The total composite score and resulting risk band
- Any automatic override applied, with the triggering indicator
- Any manual escalation, with written rationale and approving officer name
- The date of assessment and the reviewing officer's name

All historical risk scores must be retained on the client file. The risk score history is part of the audit trail and must not be deleted or overwritten.
