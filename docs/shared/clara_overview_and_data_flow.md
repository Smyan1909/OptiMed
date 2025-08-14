---
title: "CLARA Overview and Data Flow (Customer Summary)"
version: "1.0"
last_updated: "2025-08-14"
owner: "OptiMed AI"
audiences: ["Customers", "Stakeholders"]
---

### What is CLARA

CLARA is a clinical information assistant designed to help clinicians find and summarize the right patient information quickly and safely. It connects to electronic health records (EHR) via industry standards (FHIR and SMART-on-FHIR), and when appropriate, can enrich answers with trusted external sources. CLARA presents concise, multilingual summaries in an easy-to-use web interface.

### What CLARA Does (Functionality)

- **Patient context summaries**: Retrieves relevant vitals, labs, medications, allergies, history, and notes from the EHR and summarizes them for fast review.
- **Clinician Q&A**: Allows natural-language questions about a patient’s record or clinical topics; answers include links back to the original sources when available.
- **Documentation support**: Assists with generating and refining clinical notes or journals, for clinician review and approval before saving.

### Goals

- **Speed and clarity**: Reduce time-to-information during clinical workflows.
- **Safety and transparency**: Provide clear, sourced summaries that help clinicians verify details.
- **Seamless integration**: Work with existing EHR systems using open standards.
- **Multilingual support**: Help diverse care teams and patient populations.

### High-level Data Flow

1. **Clinician uses the web app** to request a summary or ask a question.
2. **Backend retrieves only the necessary data** from the EHR to answer the request (data minimization).
3. **Optional: trusted web sources** may be queried to enrich answers when appropriate.
4. **AI composes a concise response** and returns it to the clinician, including links back to source data when available.
5. **Clinician reviews and decides** how to use the information (e.g., finalize a note).

### Important Clarifications

- **Not a medical device**: CLARA provides information and drafting assistance. It does not diagnose, treat, or make clinical decisions and must not be used as a substitute for professional judgment.
- **Clinician-in-the-loop**: All outputs are for clinician review and verification prior to use in care.

### Privacy, Security, and Data Residency

- **EU-first deployment**: We plan to deploy CLARA with all data saved within the EU using local Azure cloud services.
- **GDPR principles**: Data minimization, purpose limitation, and appropriate retention policies.
- **Source transparency**: Responses aim to include links back to EHR items or indicate when no link is available.

### Deployment Approach (Summary)

- **Cloud**: Local Azure services in EU regions for application hosting and data storage.
- **Standards-based interoperability**: FHIR/SMART-on-FHIR connections to partner EHRs.
- **Observability and controls**: Role-based access, audit logging, and monitoring aligned with healthcare best practices.

### Limitations and Non-Goals

- **No replacement for clinical decision-making**: CLARA does not provide final diagnoses or treatment recommendations.
- **No long-term storage beyond policy**: Patient data is processed to assist clinicians and stored according to agreed retention policies.


