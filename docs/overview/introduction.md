---
title: "Introduction"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Stakeholders", "Developers"]
---

## Executive Summary
CLARA (OptiMed AI) is a clinical information assistant focused on fast, safe information retrieval. It connects to EHR systems via FHIR/SMART, retrieves and normalizes patient context, enriches answers with trusted web sources when appropriate, and presents concise, multilingual summaries via a modern web UI. This document set provides a concise, version-controlled blueprint for understanding, deploying, and operating CLARA in EU regions with GDPR-first design.

### How to read this doc set
- Start with Architecture to understand system boundaries and data flows.
- See Hexagonal Architecture for domain, ports, adapters, and wiring details.
- Review Specifications for APIs, data schema, and components.
- Use Operations for setup, deployment, and monitoring.
- See Maintenance for troubleshooting, known issues, and changelog.

## Purpose and Scope
- Provide a shared understanding of CLARA’s goals, architecture, and interfaces.
- Serve as a single source of truth for development, integration, and compliance reviews.
- Scope covers backend services (FastAPI), orchestrator (LangGraph-like flows), adapters (FHIR, vector store, LLMs, web search), DICOM imaging, and the Next.js web app.

## Value Proposition
- Faster clinical information retrieval and summarization.
- Streamlined documentation (journals/notes) with language-aware generation.

## Target Users
- Clinicians (primary), care teams, and clinical documentation staff.
- Technical teams integrating with EHRs and infrastructure.
- Compliance and security stakeholders (EU focus).

## High-level Capabilities
- EHR integration via HAPI FHIR and SMART-on-FHIR repositories.
- Information retrieval and summarization backed by OpenAI GPT-4 family.
- Vector store using PostgreSQL/pgvector for chat history and embeddings.
- Journal generation and autocomplete.
- Web search (Tavily) for external-source enrichment.

## Non-Goals
- Replace clinical decision-making; CLARA is an assistant, not a medical device.
- Long-term storage of PHI beyond configured retention policies.
- Offline, on-device operation.

## Success Metrics (KPIs)
- Time-to-first-token and total response latency.
- Task completion rates for common clinician workflows.
- Uptime and error rates for API endpoints.
- Privacy posture: zero critical findings in audits, DPIA resolved actions.

Stakeholder Notes
- System assists clinicians; it does not provide final diagnoses.
- GDPR principles apply: data minimization, purpose limitation, and DSR handling.


