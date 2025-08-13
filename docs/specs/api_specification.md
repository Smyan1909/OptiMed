---
title: "API Specification"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Stakeholders", "Developers"]
---

## Executive Summary
This document summarizes public API endpoints exposed by the FastAPI gateway, including auth, patients, chat/diagnose, DICOM, journal, lookup, and images. OAuth2/OIDC is used for user authentication; SMART-on-FHIR enables EHR-scoped access.

## Overview
- Base URL: / (FastAPI)
- Auth: OAuth2/OIDC sessions; `X-Session-ID` header for stateful session tracking
- Versioning: path- or header-based in the future (v1); current draft is unversioned
- Rate limiting: recommended at ingress (e.g., per user/session)
- Pagination: standard `limit`/`offset` or endpoint-specific query params

## Authentication
- `/auth/ehr-login` (POST): initiates SMART login
- `/auth/ehr-callback` (GET): completes SMART login and redirects to frontend
- `/auth/login` (POST): developer login for local testing
- `/auth/me` (GET): current user
- `/auth/logout` (POST): invalidate session (TBD)

## Key Endpoints (selection)
- `/patients` (GET): search
- `/patients/{id}` (GET): details
- `/chat` (POST), `/chat/stream` (POST)
- `/diagnose` (POST), `/diagnose/stream` (POST)
- `/chat-history` (POST)
- `/patients/{id}/journal` (GET, POST); `/patients/{id}/journal/{entry_id}` (PUT, DELETE)
- `/dicom/upload` (POST); `/dicom/images` (GET); `/dicom/images/{id}` (GET); `/dicom/images/{id}/pixel-data` (GET); `/dicom/images/{id}/analyze` (POST); `/dicom/images/{id}/similar` (GET)
- `/images/generate` (POST); `/images/generated/{id}` (GET); `/images/user/{user_id}` (GET); `/images/service/status` (GET)
- `/lookup` (POST)

## Error Model
```json
{
  "error": {
    "code": "string",
    "message": "human readable",
    "details": {"...": "..."}
  }
}
```

## Idempotency
- Client should retry only safe GETs; POSTs should use client-generated ids where supported (e.g., sessions) and be retried with backoff.

## Mini OpenAPI Snippet
```yaml
openapi: 3.0.3
info:
  title: OptiMed API
  version: 0.1.0
paths:
  /patients:
    get:
      summary: Search patients
      parameters:
        - in: query
          name: q
          schema: { type: string }
      responses:
        '200': { description: OK }
  /chat:
    post:
      summary: General chat
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                patient_id: { type: string, nullable: true }
                user_prompt: { type: string }
      responses:
        '200': { description: OK }
  /diagnose:
    post:
      summary: Diagnostic reasoning
      responses:
        '200': { description: OK }
```

For full spec, see `../../openapi/openapi.yaml`.

Stakeholder Notes
- OAuth/OIDC + SMART flows govern data access; session header required for imaging APIs.


