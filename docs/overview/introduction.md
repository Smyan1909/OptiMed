---
title: "Introduction"
version: "2.0.0"
last_updated: "2025-01-27"
owner: "OptiMed AI"
audiences: ["Stakeholders", "Developers", "Compliance Officers"]
---

## Executive Summary

**CLARA (OptiMed AI)** is an advanced clinical information assistant deployed in **Azure Sweden Central** with **Azure AI Foundry (Data Zone Europe)** for GDPR-compliant medical information retrieval. The system implements **RAM-only processing** with zero PHI persistence, ensuring absolute patient privacy while delivering sub-second clinical summaries.

**Key Innovation**: All patient data and embeddings exist only in volatile memory, automatically zeroized on session end, making "right to erasure" instant and complete.

### How to Read This Documentation

1. **[System Architecture](../architecture/system_architecture.md)** - Understand Azure deployment and data flows
2. **[Intelligent Retrieval Pipeline](../algorithms/intelligent_retrieve_chunks.md)** - 9-stage RAM-only retrieval
3. **[Specialized Flows](../algorithms/specialized_flows.md)** - SBAR, Summary, Timeline, Notes
4. **[Azure AI Foundry Setup](../operations/azure_ai_foundry_setup.md)** - LLM configuration
5. **[Deployment Process](../operations/deployment_process.md)** - Azure Container Apps deployment
6. **[GDPR Compliance](../architecture/gdpr_compliant_architecture.md)** - Privacy-preserving architecture

---

## Purpose and Scope

### Mission
Provide healthcare professionals with **instant, accurate, privacy-preserving** access to clinical information through advanced AI while maintaining absolute GDPR compliance via RAM-only processing.

### Scope
- **Backend Services**: FastAPI on Azure Container Apps
- **Orchestration**: LangGraph state machines for clinical workflows
- **AI Processing**: Azure AI Foundry (Data Zone Europe) - GPT-4o
- **Data Access**: FHIR (HAPI + SMART-on-FHIR)
- **Retrieval**: 9-stage RAM-only pipeline with multilingual support
- **Frontend**: Next.js web application
- **Deployment**: Azure Container Apps (Sweden Central)
- **Compliance**: Full GDPR compliance with EU data residency

---

## Value Proposition

### For Clinicians
- ⚡ **Sub-second responses**: 300-800ms clinical information retrieval
- 🎯 **Specialized flows**: SBAR handoffs, comprehensive summaries, timelines
- 🌍 **Multilingual**: 100+ language support with cross-encoder
- 📱 **Modern UX**: Streaming responses, EHR source links, real-time updates

### For Healthcare Organizations
- 🔒 **Absolute Privacy**: Zero PHI persistence - all data in RAM only
- ✅ **GDPR Compliant**: EU data residency (Sweden Central), Data Zone Europe
- 📊 **Complete Audit**: Full data lineage tracking without PHI storage
- 💰 **Cost Effective**: No vector database costs, efficient Azure scaling

### For IT/Compliance
- 🇪🇺 **EU Residency**: All processing in Sweden Central + Data Zone Europe
- 🛡️ **E2E Encryption**: AES-256-GCM with session keys
- 📋 **Instant Erasure**: Right to erasure via memory zeroization
- 🔍 **Audit Ready**: 7-year compliant audit logs (metadata only)

---

## Target Users

### Primary Users
- **Clinicians**: Physicians, nurse practitioners, physician assistants
- **Nurses**: Floor nurses, ICU nurses, emergency department staff
- **Care Teams**: Multidisciplinary teams requiring patient information
- **Documentation Staff**: Medical scribes, documentation specialists

### Secondary Users
- **IT Teams**: System integration, deployment, monitoring
- **Compliance Officers**: GDPR compliance, privacy impact assessments
- **Security Teams**: Penetration testing, security audits
- **Healthcare Administrators**: System oversight, policy enforcement

---

## High-Level Capabilities

### Clinical Information Retrieval
- **Standard Queries**: Fast lookup of patient data with intelligent context
- **SBAR Handoffs**: Structured clinical communication (300-500ms)
- **Comprehensive Summaries**: 8-component patient overview (500-800ms)
- **Timeline Visualization**: Chronological patient journey with events
- **Clinical Notes**: Template-driven SOAP, Progress, Admission, Discharge notes

### Advanced Retrieval Features
- **9-Stage Pipeline**: Bi-encoder → Cross-encoder → MMR → Gating → Refinement
- **Query Classification**: Zero-shot intent detection for optimized routing
- **Multilingual Support**: Cross-encoder reranking for 100+ languages
- **Agentic Refinement**: Automatic query refinement (up to 2 retries)
- **Web Search Integration**: Evidence-based guidelines via Tavily

### EHR Integration
- **HAPI FHIR**: Institutional EHR access
- **SMART-on-FHIR**: Per-user authenticated access with OAuth2/OIDC
- **FHIR Resources**: Patient, Observation, Condition, Medication, Procedure, etc.
- **Source Attribution**: EHR links preserved in responses

### AI & ML Capabilities
- **LLM**: Azure AI Foundry GPT-4o (Data Zone Europe)
- **Embeddings**: sentence-transformers/all-MiniLM-L6-v2 (384-dim)
- **Cross-Encoder**: ms-marco-MiniLM-L-6-v2 (multilingual)
- **Zero-Shot Classifier**: Query intent classification
- **Streaming**: Real-time response generation

### Privacy & Security
- **RAM-Only Processing**: Zero PHI persistence
- **E2E Encryption**: AES-256-GCM with RSA-2048 key exchange
- **Crypto-Shredding**: Automatic on session end
- **Audit Logging**: Complete data lineage (metadata only)
- **Row-Level Security**: Multi-tenant data isolation

---

## Deployment Architecture

### Azure Infrastructure (Sweden Central, EU)

```
┌─────────────────────────────────────────────────────────┐
│              Azure Sweden Central (EU)                  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Azure Container Apps Environment                       │
│  ├─ optimed-api-sweden (Backend)                       │
│  ├─ optimed-web-sweden (Frontend)                      │
│  └─ Auto-scaling: 1-5 replicas                         │
│                                                         │
│  Azure AI Foundry - Data Zone Europe                   │
│  └─ GPT-4o deployment (50K TPM)                        │
│                                                         │
│  Azure PostgreSQL Flexible Server                      │
│  └─ optimed-db-sweden (metadata only, no PHI)          │
│                                                         │
│  Azure Monitor + Application Insights                  │
│  └─ Logs, metrics, alerts, dashboards                  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Key Components**:
- **Region**: Sweden Central (EU data residency)
- **LLM**: Azure AI Foundry - Data Zone Europe
- **Compute**: Azure Container Apps (serverless)
- **Database**: Azure PostgreSQL Flexible Server (metadata only)
- **Monitoring**: Azure Monitor + Application Insights

---

## Non-Goals

### What CLARA Does NOT Do
- ❌ **Replace Clinical Judgment**: Not a medical device, not for diagnosis
- ❌ **Persist PHI**: No patient data or embeddings saved to disk/database
- ❌ **Offline Operation**: Requires internet connection to Azure services
- ❌ **Direct Treatment**: No prescription generation or treatment automation
- ❌ **Regulatory Approval**: Not FDA/CE-marked as medical device
- ❌ **Long-Term PHI Storage**: Session data zeroized on end

### Intentional Limitations
- **Session-Based**: Data exists only during active session
- **Assistant Role**: Information retrieval, not decision-making
- **EU Deployment Only**: Optimized for Sweden Central region
- **Requires EHR**: Depends on FHIR-enabled EHR system

---

## Success Metrics (KPIs)

### Performance Metrics
- **Time to First Token**: <1 second for all flows
- **End-to-End Latency**: 300-800ms for standard retrieval
- **Availability**: 99.9% uptime SLA
- **Error Rate**: <1% failed requests

### Clinical Metrics
- **Task Completion**: >90% successful information retrievals
- **User Satisfaction**: >4.5/5 clinician rating
- **Time Saved**: >2 minutes per clinical query vs manual EHR navigation

### Privacy & Compliance Metrics
- **PHI Persistence**: 0 (zero) - all RAM-only
- **Audit Findings**: 0 critical GDPR violations
- **Data Breach Rate**: 0 incidents
- **Right to Erasure**: <1 second fulfillment (instant memory wipe)

### Technical Metrics
- **Concurrent Sessions**: 100+ per replica
- **Memory per Session**: 1-2 MB
- **Token Consumption**: <10K tokens per query average
- **Retrieval Accuracy**: >85% precision@10

---

## Technology Stack

### Backend
- **Language**: Python 3.12
- **Framework**: FastAPI
- **Orchestration**: LangGraph (state machines)
- **AI**: Azure OpenAI SDK
- **Database**: asyncpg (PostgreSQL)
- **Embeddings**: sentence-transformers
- **ML**: transformers, scikit-learn

### Frontend
- **Framework**: Next.js 15 (React)
- **Language**: TypeScript
- **UI**: Tailwind CSS, Radix UI
- **Streaming**: Server-Sent Events
- **Encryption**: Web Crypto API

### Infrastructure
- **Cloud**: Azure (Sweden Central)
- **Compute**: Azure Container Apps
- **Database**: Azure PostgreSQL Flexible Server
- **AI**: Azure AI Foundry (Data Zone Europe)
- **Registry**: Azure Container Registry
- **Monitoring**: Azure Monitor, Application Insights

### ML/AI
- **LLM**: GPT-4o via Azure AI Foundry
- **Embeddings**: all-MiniLM-L6-v2 (384-dim)
- **Cross-Encoder**: ms-marco-MiniLM-L-6-v2
- **Classifier**: Zero-shot classifier for intent detection

---

## Compliance & Regulatory

### GDPR Compliance
- ✅ Data Minimization: Only metadata persisted
- ✅ Purpose Limitation: Session-specific processing
- ✅ Storage Limitation: Automatic deletion on session end
- ✅ Data Subject Rights: Instant erasure via crypto-shredding
- ✅ Security: E2E encryption, audit logging
- ✅ Accountability: Complete data lineage tracking
- ✅ Data Protection Impact Assessment: Completed
- ✅ EU Data Residency: Sweden Central + Data Zone Europe

### Standards Compliance
- **FHIR R4**: EHR interoperability
- **OAuth2/OIDC**: Authentication standards
- **SMART-on-FHIR**: EHR integration standard
- **HL7**: Healthcare data standards
- **ISO 27001**: Information security (Azure certified)

---

## Stakeholder Notes

### For Clinical Leadership
- CLARA assists but does not replace clinical decision-making
- All information retrieval includes EHR source links for verification
- System maintains complete audit trail for medical-legal compliance
- GDPR compliance ensures patient privacy protection

### For IT Leadership
- Deployment entirely on Azure in Sweden Central (EU)
- Auto-scaling from 1-5 replicas based on load
- Zero infrastructure for vector database (RAM-only)
- Comprehensive monitoring via Azure Monitor

### For Compliance Officers
- **Zero PHI Persistence**: Instant GDPR "right to erasure" compliance
- **EU Data Residency**: All processing within EU boundaries
- **Complete Audit Trail**: 7-year retention of metadata logs
- **Data Lineage**: Full tracking of all transformations

### For Security Teams
- E2E encryption for all sessions (AES-256-GCM)
- Managed identity for Azure service authentication
- Private endpoints for database (no public internet)
- Regular security audits and penetration testing

---

## Quick Links

### Getting Started
- [Setup Guide](../operations/setup_guide.md) - Local development
- [Deployment Process](../operations/deployment_process.md) - Azure deployment
- [Azure AI Foundry Setup](../operations/azure_ai_foundry_setup.md) - LLM configuration

### Architecture
- [System Architecture](../architecture/system_architecture.md) - High-level design
- [Data Flow](../architecture/data_flow.md) - RAM-only processing
- [GDPR Architecture](../architecture/gdpr_compliant_architecture.md) - Privacy design

### Algorithms
- [Intelligent Retrieval](../algorithms/intelligent_retrieve_chunks.md) - 9-stage pipeline
- [Info Flow](../algorithms/info_flow_langgraph.md) - LangGraph orchestration
- [Specialized Flows](../algorithms/specialized_flows.md) - SBAR, Summary, Timeline

### Operations
- [Monitoring](../operations/monitoring.md) - Azure Monitor setup
- [Troubleshooting](../maintenance/troubleshooting.md) - Common issues
- [GDPR Operations](../operations/gdpr_operational_guide.md) - Compliance procedures

---

**Version**: 2.0.0 (RAM-Only Architecture)
**Last Updated**: 2025-01-27
**Deployment**: Azure Sweden Central (EU)
**LLM Provider**: Azure AI Foundry - Data Zone Europe


