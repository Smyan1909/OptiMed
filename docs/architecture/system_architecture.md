---
title: "System Architecture"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Stakeholders", "Developers"]
---

## Executive Summary
CLARA’s architecture uses ports-and-adapters. A FastAPI gateway fronts orchestrators that coordinate LLMs, FHIR repositories (HAPI or SMART), pgvector, DICOM services, and optional web/image generation services. The web app is Next.js. Security and privacy are first-class, targeting EU data residency and GDPR.

## Context Diagram
Context: High-level interactions among users, external dependencies, and core services.

```mermaid
flowchart LR
  Clinician((Clinician))
  EHR[(EHR System)]
  Auth[(OIDC Provider)]
  subgraph CLARA Platform
    API[API Gateway (FastAPI)]
    ORCH[Orchestrator]
    DB[(PostgreSQL + pgvector)]
    LOG[(AuditLog)]
    IMG[(DICOM Services)]
    LLM[(OpenAI GPT-4o)]
    WEB[(Web App - Next.js)]
  end
  Clinician -->|Query| WEB --> API
  API --> Auth
  API --> ORCH
  ORCH --> EHR
  ORCH --> DB
  ORCH --> LLM
  ORCH --> IMG
  API --> LOG
```

Assumptions
- EHR connectivity via HAPI FHIR by default; SMART-on-FHIR per-user when authenticated.
- Vector store uses PostgreSQL DSN and pgvector extension.
- GPT-4o as default LLM; configurable via env.

Update instructions
- Edit the Mermaid code block and re-render via MkDocs/Material preview.

## Components and Boundaries
- API Gateway (`src/optimed/apps/api_gateway/main.py`): FastAPI endpoints (/patients, /chat, /diagnose, /dicom, /journal, auth flows).
- Orchestrators (`src/optimed/apps/orchestrator/*`): diagnostic, information, and image analysis engines.
- Core Ports (`src/optimed/core/ports.py`): FHIRRepository, LLMClient, VectorStore, ImageService, UserRepository, etc.
- Adapters:
  - FHIR: `HAPIFHIRRepository`, `SMARTFHIRRepository`.
  - Vector store: `PGVectorAdapter`.
  - Users/EHR connections: `PGUserRepository`, `PGUserEHRConnectionRepository`.
  - DICOM: `PyDICOMProcessor`, `FileSystemImageStorage`, `PostgreSQLImageRepository`.
  - LLM: `OpenAIGPT4oClient`.
  - Web search: `TavilyWebSearchService`.
  - Image generation (optional): `StabilityAIClient`, repo `PostgresGeneratedImageRepository`.

## Cross-cutting Concerns
- Security & Privacy: OAuth2/OIDC, per-user SMART connections, least-privilege DB roles, input validation, audit logs.
- Logging & Observability: OpenTelemetry spans around critical flows; metrics for latency/error rate; structured logs.
- i18n: Language detection and prompt localization for journal/chat.
- Error Handling: Defensive try/except in API, consistent HTTP errors, partial degradation with defaults.

Stakeholder Notes
- Patient data is transiently processed to assist clinicians; storage follows configured retention.
- EU residency: deploy data plane in EU regions; ensure vendor sub-processors comply with GDPR.


