---
title: "Database Schema"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Stakeholders", "Developers"]
---

## Executive Summary
PostgreSQL with pgvector backs chat sessions, history, embeddings, user accounts, and generated images metadata. This doc provides an ER scaffold and notes on migrations and PII minimization.

## Storage Choices
- PostgreSQL + pgvector: vector search and relational data
- Object storage: raw DICOM files and rendered PNGs

## ER Diagram (scaffold)
```mermaid
erDiagram
  USER ||--o{ SESSION : has
  USER }o--o{ ORGANIZATION : belongs_to
  USER ||--o{ AUDIT_LOG : generates
  ORGANIZATION ||--o{ FEATURE_FLAG : enables
  PATIENT_LINK ||--o{ SESSION : referenced_by
  EMBEDDING }o--|| PATIENT_LINK : vectors_for
```

Assumptions
- Vector rows store `embedding vector`, `object_type`, `object_id`, `metadata` JSONB.
- Sessions track participants and message counts.

Migrations
- Use Alembic or SQL migrations; require approvals in CI/CD.

PII Minimization
- Store only necessary identifiers; prefer hashed or pseudonymized IDs for logs.
- Encrypt at rest; restrict access with least privilege.

Stakeholder Notes
- Ensure DPIA reflects purposes for each table containing PHI.


