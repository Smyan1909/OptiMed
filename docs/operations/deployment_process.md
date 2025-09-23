---
title: "Deployment Process"
version: "0.2.0"
last_updated: "2025-01-15"
owner: "OptiMed AI"
audiences: ["Developers", "SRE"]
---

## Executive Summary
OptiMed deployment leverages Azure Container Apps in EU regions for GDPR compliance. Current production deployment runs in Sweden Central with Azure PostgreSQL Flexible Server and end-to-end encryption.

## Current Production Environment

**Region**: Sweden Central
**Infrastructure**: Azure Container Apps + Azure PostgreSQL Flexible Server
**Compliance**: GDPR-compliant with E2E encryption and audit logging

### Active Deployments
- **Backend**: `optimed-api-sweden` - https://optimed-api-sweden.agreeablecoast-ffcd3664.swedencentral.azurecontainerapps.io
- **Frontend**: `optimed-web-sweden` - https://clara.optimedai.com
- **Database**: `optimed-db-sweden.postgres.database.azure.com`
- **Environment**: `optimed-env-sweden`

## Deployment Architecture

### Container Registry
- **Registry**: `optimedacr123.azurecr.io`
- **Images**:
  - `optimed-api-sweden:latest` (Backend)
  - `optimed-web-sweden:latest` (Frontend)

### Environment Variables Setup
```bash
export RG=your-resource-group-name
export ACR=optimedacr123
```

## Database Setup (Azure PostgreSQL Flexible Server)

### Prerequisites
Before running application deployments, ensure database is configured:

#### 1. Enable Required Extensions
```bash
# Enable pgcrypto and vector extensions
az postgres flexible-server parameter set \
  --resource-group $RG \
  --server-name optimed-db-sweden \
  --name azure.extensions \
  --value "pgcrypto,vector"
```

#### 2. Database Initialization Strategy
**Recommended Approach**: Let backend create base tables first, then run migrations

```bash
# Step 1: Start backend to create core application tables
python -m uvicorn optimed.apps.api_gateway.main:app --host 0.0.0.0 --port 8000

# Step 2: Stop backend (Ctrl+C) and run GDPR compliance migrations
python scripts/run_migrations.py

# Step 3: Restart backend for normal operation
python -m uvicorn optimed.apps.api_gateway.main:app --host 0.0.0.0 --port 8000
```

### Migration Scripts
Located in `/migrations/` directory:
- `002_create_gdpr_safe_schema.sql` - Core tables + GDPR compliance
- `003_create_rls_policies.sql` - Row Level Security policies
- `004_cleanup_phi_tables.sql` - PHI data cleanup
- `005_enhanced_audit_logging.sql` - Enhanced audit logging

**Key Features:**
- Conditional extension loading (handles Azure restrictions)
- GDPR-compliant session tracking
- Comprehensive audit logging
- End-to-end encryption support

## Backend Deployment

### Build and Deploy Backend
```bash
# Build backend container
az acr build --registry $ACR \
  --image optimed-api-sweden:latest \
  --file Dockerfile.backend \
  .

# Deploy to Container Apps
az containerapp create \
  --name optimed-api-sweden \
  --resource-group $RG \
  --environment optimed-env-sweden \
  --image $ACR.azurecr.io/optimed-api-sweden:latest \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 5 \
  --cpu 1.0 \
  --memory 2Gi \
  --set-env-vars \
    PGVECTOR_DSN="postgresql://optimed_admin:clara_passkey@optimed-db-sweden.postgres.database.azure.com:5432/optimed?sslmode=require" \
    DATABASE_URL="postgresql://optimed_admin:clara_passkey@optimed-db-sweden.postgres.database.azure.com:5432/optimed?sslmode=require" \
    API_BASE_URL="https://optimed-api-sweden.agreeablecoast-ffcd3664.swedencentral.azurecontainerapps.io" \
    FRONTEND_URL="https://clara.optimedai.com" \
    CORS_ORIGINS="https://clara.optimedai.com"
```

## Frontend Deployment

### Build and Deploy Frontend
```bash
# Navigate to frontend directory
cd src/optimed/apps/web

# Build with environment variables baked in at build time
az acr build --registry $ACR \
  --image optimed-web-sweden:latest \
  --build-arg NEXT_PUBLIC_API_BASE_URL="https://optimed-api-sweden.agreeablecoast-ffcd3664.swedencentral.azurecontainerapps.io" \
  --build-arg NEXT_PUBLIC_DEFAULT_FHIR_SERVER="https://smart-launcher.mangocoast-b1d65dd2.northeurope.azurecontainerapps.io/v/r4/sim/eyJqIjoiMSIsImIiOiJmMmY5NDRkNi05Y2E2LTQ5MDAtOGE1NC0xMzBlMmNkZTYwOGQifQ/fhir" \
  --build-arg NEXT_PUBLIC_INFO_MODE="true" \
  --build-arg FRONTEND_URL="https://clara.optimedai.com" \
  .

# Deploy to Container Apps
az containerapp create \
  --name optimed-web-sweden \
  --resource-group $RG \
  --environment optimed-env-sweden \
  --image $ACR.azurecr.io/optimed-web-sweden:latest \
  --target-port 3000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 0.5 \
  --memory 1Gi
```

## Secrets Management
- Database credentials: Configured in Container Apps environment variables
- API keys: Managed via Azure Key Vault integration
- Encryption keys: Set via environment variables (`ENCRYPTION_MASTER_KEY`, `HASH_SALT`)

## Rollbacks
- **Container Images**: Use previous image tags for instant rollback
- **Database**: Run migration rollback scripts (if available)
- **DNS**: Update custom domain mappings if needed

## Monitoring and Health Checks
- Container Apps built-in health probes
- Application logs via Azure Log Analytics
- Performance metrics tracked in database (`performance_metrics` table)
- GDPR compliance events logged (`compliance_events` table)

## Stakeholder Notes
- All deployments maintain GDPR compliance with data residency in EU (Sweden Central)
- Audit trails preserved for regulatory requirements
- End-to-end encryption enabled for all PHI data


