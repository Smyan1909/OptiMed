---
title: "intelligent_retrieve_chunks – Design and Flow"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Developers"]
---

## Executive Summary
This function selects the most relevant patient data “chunks” to answer a query. It combines vector similarity search, recency-aware filtering by data type, and an LLM-based selector with a robust fallback strategy.

## High-level Flow
```mermaid
flowchart TD
  A[Similarity search in vector store] --> B{Any rows?}
  B -- no, has patient_ctx --> C[Use full patient context as fallback]
  B -- no, no patient_ctx --> D[Return empty]
  B -- yes --> E[Recency-aware filtering and scoring]
  E --> F[Prepare candidate chunk list]
  F --> G[LLM analyzes relevance and selects 3-6 chunks]
  G --> H{LLM succeeded?}
  H -- yes --> I[Use selected chunks]
  H -- no --> J[Fallback: top journal + recent vitals/labs/meds + top other]
  I --> K[Set state.retrieved_chunks]
  J --> K[Set state.retrieved_chunks]
```

## Detailed Steps
- Initial search:
  - Build query embedding for `state.user_prompt`.
  - Search `namespace=clinical` filtered by `patient_id`, `top_k=20` to support later filtering.
- Recency-aware filtering by `data_type` with thresholds:
  - vitals: 7 days; labs: 14 days; medications: 90 days; others: always relevant.
  - Skip stale time-sensitive chunks; compute `adjusted_score` with a recency boost for recent items.
- Candidate preparation:
  - Keep metadata like `data_type`, `timestamp`, and `adjusted_score`.
  - Ensure relevance to the current patient via patient_id/name string checks.
- LLM selection:
  - Prompt evaluates each chunk on relevance, clinical importance, and utility.
  - Returns JSON with `selected_chunks`, `reasoning`, and per-chunk scores.
- Fallback if LLM fails:
  - Picks top journal entries, top recent time-sensitive chunks by `adjusted_score`, and top remaining by similarity.

## Figure: Scoring and Selection
```mermaid
flowchart LR
  subgraph Inputs
    Q[user_prompt]
    V[vector rows]
    M[metadata timestamps]
  end
  Q --> S1
  V --> S1[Recency filter per type]
  M --> S1
  S1 --> S2[Compute adjusted_score]
  S2 --> S3[LLM selection]
  S3 -->|ok| OUT[retrieved_chunks]
  S3 -->|error| FBF[Fallback selector]
  FBF --> OUT
```

## Notes
- Returns both `state.retrieved_chunks` and a `state.chunk_analysis` JSON explaining choices.
- Designed to degrade gracefully: multiple fallbacks end in at least demographics or full patient context when available.


