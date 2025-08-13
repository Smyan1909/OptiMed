---
title: "Information Flow – LangGraph Diagram"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Developers"]
---

## Executive Summary
State graph for `info_flow.py` showing major nodes and conditional branches.

```mermaid
flowchart TD
  A[load_user_context] --> B[evaluate_query_complexity]
  B --> C[store_user_message]
  C --> D[load_current_session_history]
  D --> X{requires full processing?}
  X -- no --> O[provide_information]
  X -- yes --> E{check_patient}
  E -- yes --> F[fetch_patient]
  F --> G[store_patient_chunks]
  G --> H[evaluate_cross_session_history_need]
  H --> I{needs_cross_session_search?}
  I -- yes --> J[search_cross_session_history]
  I -- no --> K[intelligent_retrieve_chunks]
  J --> K[intelligent_retrieve_chunks]
  K --> L[evaluate_web_search_need]
  L --> M{needs_web_search?}
  M -- yes --> N[perform_web_search]
  M -- no --> O[provide_information]
  N --> O[provide_information]
  O --> P[store_assistant_response]
```

Notes
- Entry point: `load_user_context`.
- Branches: patient presence, cross-session need, web search need.


