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
  participant LLM as LLM
  U->>WEB: Request summary
  WEB->>API: POST /diagnose {patient_id, user_prompt}
  API->>FHIR: get_patient(patient_id)
  FHIR-->>API: PatientContext
  API->>ORCH: run(patient, prompt)
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
  participant LLM
  WEB->>API: POST /chat {patient_id?, user_prompt}
  alt patient provided
    API->>FHIR: get_patient
    FHIR-->>API: PatientContext
  end
  API->>ORCH: run(patient?, prompt, chat_mode=true)
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

Stakeholder Notes
- Data minimization: only required fields are retrieved and cached.
- Journal content is user-driven and should be reviewed before storing in EHR.

Update instructions
- Update diagrams if endpoints or steps change; keep pseudocode in sync with orchestrator.


