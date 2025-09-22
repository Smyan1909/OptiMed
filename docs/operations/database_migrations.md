---
title: "Database Migration Scripts"
version: "1.0.0"
last_updated: "2025-01-15"
owner: "OptiMed AI"
audiences: ["Developers", "SRE"]
---

## Overview

OptiMed uses a hybrid approach for database schema management:
1. **Backend Repositories** create core application tables automatically
2. **Migration Scripts** add GDPR compliance, audit logging, and enhancements

## Migration Strategy

### Recommended Execution Order

```bash
# 1. Start backend to create core tables
python -m uvicorn optimed.apps.api_gateway.main:app --host 0.0.0.0 --port 8000

# 2. Stop backend (Ctrl+C) after tables are created

# 3. Run migration scripts
python scripts/run_migrations.py

# 4. Restart backend for normal operation
python -m uvicorn optimed.apps.api_gateway.main:app --host 0.0.0.0 --port 8000
```

### Why This Approach?

- **Separation of Concerns**: Repositories handle operational tables, migrations handle compliance
- **No Circular Dependencies**: Backend creates base tables that migrations reference
- **Flexible**: Can run migrations multiple times safely
- **Azure Compatible**: Handles extension restrictions gracefully

## Migration Scripts

### Location
All migration scripts are in `/migrations/` directory

### Script Descriptions

#### `002_create_gdpr_safe_schema.sql`
**Purpose**: Core GDPR-compliant schema with all application tables

**Key Features**:
- Conditional extension loading (pgcrypto, vector)
- GDPR-compliant session tracking
- Core user management tables
- Application-specific tables (images, EHR connections)
- Comprehensive audit and analytics tables

**Tables Created**:
```sql
-- Core GDPR Compliance
sessions                    -- GDPR session tracking
audit_events               -- Action audit trail
resources                  -- FHIR resource metadata
resource_codes            -- Medical terminology
evidence_sets             -- Evidence pointers (no content)
model_registry            -- Model configurations
retrieval_config          -- Retrieval settings
temp_content              -- Ephemeral encrypted cache

-- User Management (matches backend expectations)
users                     -- User accounts
user_sessions            -- Session management
user_actions             -- User action audit

-- Analytics & Monitoring
system_usage_metrics     -- System-wide usage analytics
session_analytics        -- Session-specific metrics
data_access_logs         -- GDPR data access logging
performance_metrics      -- Application performance
encryption_audit_log     -- Encryption operations audit
compliance_events        -- Regulatory compliance events
gdpr_requests           -- Data subject rights requests
system_health_metrics   -- System health monitoring
data_lineage            -- Data flow tracking

-- Application Tables
generated_images         -- AI-generated images with GDPR compliance
dicom_images            -- Medical images metadata
ehr_login_sessions      -- EHR OAuth sessions
user_ehr_connections    -- EHR system connections
```

#### `003_create_rls_policies.sql`
**Purpose**: Row Level Security policies for multi-tenant data isolation

**Features**:
- Tenant-based data isolation
- User-based access control
- Session-scoped data access
- Currently disabled for backend compatibility (can be enabled when needed)

#### `004_cleanup_phi_tables.sql`
**Purpose**: PHI data cleanup and pseudonymization

**Features**:
- Conditional table processing (only if tables exist)
- PHI pseudonymization functions
- Safe migration from legacy schemas
- GDPR-safe table creation

#### `005_enhanced_audit_logging.sql`
**Purpose**: Enhanced audit logging and metrics (if not already created in 002)

**Features**:
- Additional audit table creation
- Enhanced logging capabilities
- Compliance event tracking

## Extension Handling

### Azure PostgreSQL Compatibility

Migration scripts handle Azure PostgreSQL extension restrictions:

```sql
DO $$
BEGIN
    -- Try to create pgcrypto extension
    BEGIN
        CREATE EXTENSION IF NOT EXISTS "pgcrypto";
        RAISE NOTICE 'pgcrypto extension enabled successfully';
    EXCEPTION
        WHEN OTHERS THEN
            RAISE WARNING 'pgcrypto extension not available. Error: %', SQLERRM;
    END;

    -- Try to create vector extension
    BEGIN
        CREATE EXTENSION IF NOT EXISTS "vector";
        RAISE NOTICE 'vector extension enabled successfully';
    EXCEPTION
        WHEN OTHERS THEN
            RAISE WARNING 'vector extension not available. Error: %', SQLERRM;
    END;
END $$;
```

### Required Extensions

Before running migrations, enable extensions via Azure CLI:

```bash
az postgres flexible-server parameter set \
  --resource-group $RG \
  --server-name optimed-db-sweden \
  --name azure.extensions \
  --value "pgcrypto,vector"
```

## UUID Handling

### Azure Compatibility Fix

OptiMed uses PostgreSQL built-in UUID functions instead of `uuid-ossp` extension:

```sql
-- Instead of uuid_generate_v4()
session_id UUID PRIMARY KEY DEFAULT gen_random_uuid()
```

This avoids Azure PostgreSQL extension restrictions while maintaining functionality.

## Running Migrations

### Migration Runner Script

**Location**: `scripts/run_migrations.py`

**Features**:
- Runs migrations in order
- Handles extension failures gracefully
- Provides detailed logging
- Verifies schema after completion

### Manual Execution

```bash
# Run all migrations
python scripts/run_migrations.py
```

### Expected Output

```
🚀 OptiMed Database Setup
==================================================
🗄️ Running OptiMed Database Migrations...
🔌 Connecting to database...
🔒 Ensuring GDPR compliance: Removing legacy embeddings...
✅ No legacy embeddings found (GDPR compliance)
📋 Found 0 existing tables
📄 Running migrations/002_create_gdpr_safe_schema.sql - GDPR-safe schema...
✅ migrations/002_create_gdpr_safe_schema.sql completed successfully
📄 Running migrations/003_create_rls_policies.sql - Row Level Security policies...
✅ migrations/003_create_rls_policies.sql completed successfully
📄 Running migrations/004_cleanup_phi_tables.sql - PHI cleanup...
✅ migrations/004_cleanup_phi_tables.sql completed successfully
📄 Running migrations/005_enhanced_audit_logging.sql - Enhanced audit logging and metrics...
✅ migrations/005_enhanced_audit_logging.sql completed successfully

🔍 Verifying database schema...
📊 Database schema verification:
  ✅ Core tables (4): sessions, users, user_sessions, user_actions
  📈 Audit/Analytics tables (9): system_usage_metrics, session_analytics, data_access_logs, performance_metrics, encryption_audit_log, compliance_events, gdpr_requests, system_health_metrics, data_lineage
  📋 Other tables (8): generated_images, dicom_images, ehr_login_sessions, user_ehr_connections, audit_events, resources, resource_codes, evidence_sets

🔧 Installed extensions (3):
  - plpgsql
  - pgcrypto
  - vector
  ✅ pgvector extension is available for embeddings

🎉 All migrations completed successfully!
🔒 Your database is now GDPR-compliant with enhanced audit logging!
📊 Enhanced usage analytics and encryption monitoring enabled!

🧪 Testing database connection...
✅ Connected to: PostgreSQL 17.5 on x86_64-pc-linux-gnu, compiled by gcc (GCC) 11.2.0, 64-bit
✅ pgvector extension version: 0.5.1
✅ user_actions table accessible: 0 records

🎯 Setup completed successfully!
🔐 Your OptiMed system is now ready with end-to-end encryption!
```

## Troubleshooting

### Common Issues

#### Extension Not Available
**Error**: `extension "pgcrypto" is not allow-listed`

**Solution**:
1. Enable extensions via Azure CLI
2. Wait for server parameter update
3. Re-run migrations

#### Table Dependencies
**Error**: `relation "sessions" does not exist`

**Solution**:
1. Run backend first to create base tables
2. Then run migrations
3. Order matters for foreign key relationships

#### Migration Already Run
**Behavior**: Migrations are idempotent and can be run multiple times

**Expected**: Tables already exist warnings are normal

### Debugging

#### Check Extension Status
```sql
-- List installed extensions
SELECT extname, extversion FROM pg_extension;

-- Check azure.extensions parameter
SHOW azure.extensions;
```

#### Verify Table Creation
```sql
-- List all tables
SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;

-- Check table structure
\d+ table_name
```

#### Monitor Migration Progress
Watch the migration script output for:
- Extension loading status
- Table creation success/warnings
- Final schema verification

## GDPR Compliance Features

### Data Minimization
- PHI pseudonymization using salted hashes
- Ephemeral content storage with crypto-shredding
- Minimal data retention policies

### Audit Trail
- All data access logged with lawful basis
- User actions tracked with metadata
- Compliance events for regulatory reporting

### Data Subject Rights
- GDPR request tracking and fulfillment
- Automated data export capabilities
- Secure data deletion procedures

### Encryption
- End-to-end encryption for sensitive data
- Encrypted audit logs
- Key management integration

## Maintenance

### Regular Tasks

1. **Monitor Migration Logs**: Check for warnings or errors
2. **Verify Compliance**: Ensure audit tables are populated
3. **Performance Review**: Monitor table sizes and query performance
4. **Backup Verification**: Test restore procedures

### Schema Updates

When adding new features:
1. **Create new migration file** (e.g., `006_new_feature.sql`)
2. **Update migration runner** to include new script
3. **Test on development environment** first
4. **Document changes** in this file

### Best Practices

- Always test migrations on development first
- Keep migrations idempotent (can run multiple times)
- Include rollback procedures where possible
- Document all schema changes
- Follow GDPR principles in new table designs