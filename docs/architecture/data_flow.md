---
title: "Data Flows"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Stakeholders", "Developers"]
---

## Executive Summary
This doc details key read/write flows: patient retrieval and summarization, diagnostic reasoning, general chat, DICOM upload/analysis, and journal generation. It also provides sequence diagrams and pseudocode for critical paths.

## Flow A: Patient Query → Retrieval → Reasoning → Response
```mermaid
sequenceDiagram
  participant U as Clinician
  participant WEB as Web App
  participant API as API Gateway
  participant ORCH as Orchestrator
  participant FHIR as FHIR Repo
  participant WS as Web Search
  participant LLM as LLM
  U->>WEB: Request summary
  WEB->>API: POST /diagnose {patient_id, user_prompt}
  API->>FHIR: get_patient(patient_id)
  FHIR-->>API: PatientContext
  API->>ORCH: run(patient, prompt)
  ORCH->>ORCH: evaluate_web_search_need(user_query, patient_context [, chat_history])
  alt needs web search
    ORCH->>WS: search(query, max_results, patient_context, intent, lang)
    WS-->>ORCH: results+summary
  end
  ORCH->>LLM: chat(messages)
  LLM-->>ORCH: response
  ORCH-->>API: result
  API-->>WEB: 200 OK (JSON)
```

Pseudocode
```
patient = fhir_repo.get_patient(pid)
result = engine.run(patient, prompt, user_id, session_id)
return result
```

## Flow B: Chat (with/without patient)
```mermaid
sequenceDiagram
  participant WEB
  participant API
  participant FHIR
  participant ORCH
  participant WS as Web Search
  participant LLM
  WEB->>API: POST /chat {patient_id?, user_prompt}
  alt patient provided
    API->>FHIR: get_patient
    FHIR-->>API: PatientContext
  end
  API->>ORCH: run(patient?, prompt, chat_mode=true)
  ORCH->>ORCH: evaluate_web_search_need(user_query, patient_context [, chat_history])
  alt needs web search
    ORCH->>WS: search(query, max_results, patient_context, intent, lang)
    WS-->>ORCH: results+summary
  end
  ORCH->>LLM: chat
  LLM-->>ORCH: response
  ORCH-->>API: result
  API-->>WEB: 200 OK
```

## Flow C: DICOM Upload → Process → Analyze
```mermaid
sequenceDiagram
  participant WEB
  participant API
  participant IMG as Image Service
  participant STORE as Storage/DB
  participant VLLM as Vision LLM
  WEB->>API: POST /dicom/upload (file)
  API->>IMG: upload_image(file)
  IMG->>STORE: persist file/metadata/pixel
  STORE-->>IMG: OK
  API-->>WEB: 200 OK (image_id)
  WEB->>API: POST /dicom/images/{id}/analyze
  API->>IMG: get_image + pixel_data
  API->>VLLM: analyze_dicom_image(...)
  VLLM-->>API: analysis
  API-->>WEB: 200 OK (analysis)
```

## Flow D: Journal Generation
```mermaid
sequenceDiagram
  participant WEB
  participant API
  participant FHIR
  participant LLM
  WEB->>API: POST /journal/generate {prompt, patient_id?}
  API->>FHIR: get_patient (optional)
  FHIR-->>API: PatientContext
  API->>LLM: chat(JSON-mode prompt)
  LLM-->>API: {title, content}
  API-->>WEB: 200 OK
```

## Flow E: Web Search Decision and Integration (Patient and Info Flows)
```mermaid
sequenceDiagram
  participant ORCH as Orchestrator
  participant WS as Web Search
  participant LLM as LLM
  ORCH->>ORCH: evaluate_web_search_need(user_query, patient_ctx [, chat_history])
  alt result = true
    ORCH->>WS: search(query, max_results=8, patient_context, intent, target_language)
    WS-->>ORCH: WebSearchResponse{results[title,url,snippet], summary}
    ORCH->>LLM: chat(messages + web sources summary)
  else result = false
    ORCH->>LLM: chat(messages)
  end
  LLM-->>ORCH: response (may cite sources)
```

Pseudocode (diagnostic flow)
```
# patient_flow
needs = web_search.evaluate_search_need(user_query, patient_context)
if needs or diagnostic_mode == "research":
    resp = web_search.search(query, max_results=8, patient_context, search_intent="diagnostic_support", target_language=detect_language(user_query))
    state.web_search_response = resp
# proceed to diagnosis with sources included in messages
```

Pseudocode (information flow)
```
# info_flow
needs = web_search.evaluate_search_need(user_query, patient_context, chat_history=last_messages)
if needs:
    resp = web_search.search(query, max_results=8, patient_context, search_intent="clinical_information", target_language=detect_language(user_query))
    state.web_search_response = resp
# LLM crafts answer and may cite URLs from resp.results
```

Stakeholder Notes
- Data minimization: only required fields are retrieved and cached.
- Journal content is user-driven and should be reviewed before storing in EHR.
 - Web results are advisory; clinicians should validate sources. Non-authoritative links should be de-emphasized.

Update instructions
- Update diagrams if endpoints or steps change; keep pseudocode in sync with orchestrator.


