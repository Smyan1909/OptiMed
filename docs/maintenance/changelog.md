---
title: "Changelog"
version: "2.0.0"
last_updated: "2025-01-27"
owner: "OptiMed AI"
audiences: ["Stakeholders", "Developers"]
---

All notable changes to this project are documented in this file.

## [2.0.0] - 2025-01-27 - RAM-Only Architecture

### Major Changes
- **RAM-Only Processing**: Complete migration to zero-PHI-persistence architecture
- **Azure AI Foundry**: Migrated from generic OpenAI to Azure AI Foundry (Data Zone Europe)
- **Information Flow**: New primary orchestration flow replacing patient flow
- **Specialized Flows**: Added SBAR, General Summary, Timeline, Note Generation

### Added
- 9-stage intelligent retrieval pipeline with agentic refinement
- Multilingual cross-encoder reranking (100+ languages)
- Zero-shot query classification for flow routing
- Dynamic-N selection based on query complexity
- MMR diversification for result variety
- Binary gating with adaptive thresholds
- Crypto-shredding for session memory
- Complete data lineage tracking
- Azure Monitor integration
- Azure Container Apps deployment

### Changed
- **Deployment**: Kubernetes → Azure Container Apps (Sweden Central)
- **LLM**: OpenAI GPT-4 → Azure AI Foundry GPT-4o (Data Zone Europe)
- **Vector Store**: PostgreSQL pgvector → RAM-only embeddings
- **Session Storage**: Database-backed → Encrypted RAM-only
- **Monitoring**: Prometheus/Grafana → Azure Monitor/Application Insights
- **Retrieval**: Basic vector search → 9-stage pipeline

### Deprecated
- `patient_flow.py` - Legacy diagnostic flow (use `info_flow_ram.py`)
- Database vector storage (embeddings now RAM-only)
- Persistent PHI storage (all data ephemeral)

### Removed
- PHI persistence in database
- Vector database dependency
- ICD parsing from core flow (moved to optional service)
- Cross-session vector search (GDPR non-compliant)

### Security
- Zero PHI persistence (instant GDPR "right to erasure")
- E2E encryption with AES-256-GCM
- Managed identity for Azure services
- Private endpoints for database
- Complete audit logging (metadata only)

### Performance
- Retrieval latency: 1-2s → 300-800ms
- Specialized flows: SBAR 300-500ms, Summary 500-800ms
- Parallel execution for multi-component flows
- Optimized cross-encoder operations

### Compliance
- Full GDPR compliance via RAM-only processing
- EU data residency (Sweden Central + Data Zone Europe)
- Complete data lineage tracking
- 7-year audit retention
- Data Protection Impact Assessment completed

---

## [1.5.0] - 2024-12-15 - Azure Migration

### Added
- Azure Container Apps deployment
- Azure PostgreSQL Flexible Server integration
- Sweden Central region deployment
- Azure-specific deployment documentation

### Changed
- Migrated from generic cloud to Azure
- Updated deployment scripts for Azure CLI
- Azure Monitor for observability

---

## [1.0.0] - 2024-09-01 - Production Release

### Added
- Information flow orchestration (LangGraph)
- FHIR integration (HAPI + SMART-on-FHIR)
- Vector store with PostgreSQL pgvector
- Web search integration (Tavily)
- E2E encryption
- GDPR compliance features
- Next.js frontend

### Changed
- Migrated to production-ready architecture
- Enhanced security and compliance
- Added comprehensive documentation

---

## [0.5.0] - 2024-06-01 - Beta Release

### Added
- Patient flow orchestration
- Diagnostic mode
- ICD code parsing
- Differential diagnosis
- Journal generation

---

## [0.1.0] - 2024-01-15 - Alpha Release

### Added
- Initial documentation set
- System architecture
- Hexagonal architecture implementation
- Basic API specification
- Development environment setup

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
| **2.0.0** | 2025-01-27 | RAM-Only Architecture, Azure AI Foundry |
| 1.5.0 | 2024-12-15 | Azure Migration |
| 1.0.0 | 2024-09-01 | Production Release |
| 0.5.0 | 2024-06-01 | Beta Release |
| 0.1.0 | 2024-01-15 | Alpha Release |

---

## Upgrade Guides

### Upgrading from 1.x to 2.0

**Breaking Changes**:
1. `patient_flow.py` deprecated → use `info_flow_ram.py`
2. Vector database removed → embeddings now RAM-only
3. Environment variable changes:
   - Add: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`
   - Add: `PERSISTENCE_ENABLED="false"`
   - Remove: `OPENAI_API_KEY` (use Azure version)

**Migration Steps**:
1. Update code to use `LangGraphRAMInformationEngine`
2. Configure Azure AI Foundry environment variables
3. Remove vector database dependencies
4. Update deployment to Azure Container Apps
5. Run database cleanup migration (`004_cleanup_phi_tables.sql`)

**See**: [Migration Guide](../algorithms/patient_flow_langgraph.md#migration-guide)

---

## Future Roadmap

### v2.1.0 (Q2 2025)
- Enhanced specialized flows (differential diagnosis, treatment planning)
- GPU acceleration for cross-encoder
- Hybrid search (dense + sparse)
- Multi-hop retrieval

### v2.2.0 (Q3 2025)
- Federated retrieval across institutions
- Advanced clinical decision support
- Learned reranking models
- Adaptive MMR parameters

### v3.0.0 (Q4 2025)
- Complete removal of deprecated patient flow
- Advanced agentic capabilities
- Multi-model ensemble
- Real-time collaborative features

---

**Current Version**: 2.0.0
**Release Date**: 2025-01-27
**Status**: Production
**Deployment**: Azure Sweden Central
