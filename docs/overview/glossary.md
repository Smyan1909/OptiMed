---
title: "Glossary"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Stakeholders", "Developers"]
---

| Term | Definition | Stakeholder Notes |
|---|---|---|
| FHIR | Fast Healthcare Interoperability Resources standard for healthcare data exchange | Used for EHR integration and patient context retrieval |
| SMART-on-FHIR | OAuth2/OIDC profile for launching apps within EHR context | Enables user/EHR-scoped access and consent |
| EHR | Electronic Health Record | Source of truth for clinical data; CLARA does not replace EHR |
| PHI/PII | Protected Health Information/Personally Identifiable Information | GDPR compliance: minimization, lawful basis, DSR handling |
| RBAC/ABAC | Role-/Attribute-Based Access Control | Enforced at API and data layers, aligned to least privilege |
| CI/CD | Continuous Integration/Continuous Delivery | GitHub Actions pipelines for build/test/deploy |
| SLO/SLA | Service Level Objective/Agreement | Track latency, uptime, error budgets |
| DPIA | Data Protection Impact Assessment | Required for high-risk processing under GDPR |
| OpenTelemetry | Unified tracing/metrics/logging standard | Used for observability with Prometheus/Grafana |
| pgvector | PostgreSQL extension for vector similarity | Used for chat history, embeddings, and DICOM similarity |
| DICOM | Digital Imaging and Communications in Medicine | Medical imaging files and metadata |
| ADR | Architecture Decision Record | Used for major design decisions and trade-offs |


