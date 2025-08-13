---
title: "Component Details"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Stakeholders", "Developers"]
---

## Executive Summary
This document catalogs core modules, their purposes, inputs/outputs, and key interfaces.

### API Gateway (`src/optimed/apps/api_gateway/main.py`)
- Purpose: HTTP surface for patients, chat/diagnose, journal, DICOM, search, image generation.
- Inputs: JSON requests, multipart upload; headers `X-Session-ID` where required.
- Outputs: JSON responses and SSE streams.
- Notes: Uses dependency factory for repos and engines.

### Orchestrators (`src/optimed/apps/orchestrator/*`)
- Diagnostic/Information Engines: coordinate FHIR, LLM, vector store; support streaming.
- Image Analysis Engine: coordinates DICOM pixel/metadata and vision LLM.

### Ports (`src/optimed/core/ports.py`)
- FHIRRepository, LLMClient, VectorStore, ImageService, UserRepository, etc.
- Explicit async Protocols; adapters implement these.

### Adapters
- FHIR: `HAPIFHIRRepository`, `SMARTFHIRRepository`.
- LLM: `OpenAIGPT4oClient`.
- VectorStore: `PGVectorAdapter`.
- DICOM: `PyDICOMProcessor`, `FileSystemImageStorage`, `PostgreSQLImageRepository`.
- Web Search: `TavilyWebSearchService`.
- Image Generation: `StabilityAIClient`, `PostgresGeneratedImageRepository`.

Performance & Trade-offs
- GPT-4o used for balance of latency and multimodal; JSON-mode where needed.
- pgvector similarity enables quick retrieval; requires careful indexing and filtering.
- Streaming SSE reduces perceived latency; requires buffering control.

Stakeholder Notes
- All user-visible outputs must be reviewed by clinicians; system assists, does not decide.


