---
title: "Setup Guide"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Developers"]
---

## Executive Summary
Steps to run CLARA locally: configure environment, start backend and web, seed DB, and test endpoints.

## Prerequisites
- Python 3.11+, Node 18+, PostgreSQL 15+ with pgvector
- OpenAI API key, optional Tavily and StabilityAI keys

## Quickstart
1. Copy `.env.example` to `.env` and set DSNs and API keys.
2. Create DB and enable pgvector.
3. Start API gateway: `uvicorn optimed.apps.api_gateway.main:app --reload`.
4. Start web app in `src/optimed/apps/web`: `npm install && npm run dev`.

## Dev Tasks
- Linting: follow repo tooling (ESLint/TypeScript; Python linters as configured).
- Tests: add unit/integration tests per module.

Troubleshooting
- DB connection errors: verify DSN, network, and pgvector extension.
- Missing env: ensure `OPENAI_API_KEY`, `PGVECTOR_DSN` present.

TODO
- Add Makefile and seed scripts.
- Add docker-compose for DB and services.


