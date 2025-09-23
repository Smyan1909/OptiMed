---
title: "Azure PostgreSQL Setup and Management"
version: "1.0.0"
last_updated: "2025-01-15"
owner: "OptiMed AI"
audiences: ["Developers", "SRE", "DevOps"]
---

## Overview

OptiMed uses Azure Database for PostgreSQL Flexible Server in Sweden Central for GDPR compliance. This document covers setup, configuration, and management procedures.

## Current Production Setup

**Server**: `optimed-db-sweden.postgres.database.azure.com`
**Region**: Sweden Central
**SKU**: Flexible Server
**PostgreSQL Version**: 17.5

## Prerequisites

### Required Azure CLI Extensions
```bash
# Install PostgreSQL extension if not already installed
az extension add --name db-up
```

### Environment Variables
```bash
export RG=your-resource-group-name
export DB_SERVER=optimed-db-sweden
export DB_NAME=optimed
export DB_ADMIN=optimed_admin
```

## Database Server Configuration

### 1. Extension Management

Azure PostgreSQL requires extensions to be explicitly allow-listed before use.

#### Enable Required Extensions
```bash
# Enable pgcrypto and vector extensions
az postgres flexible-server parameter set \
  --resource-group $RG \
  --server-name $DB_SERVER \
  --name azure.extensions \
  --value "pgcrypto,vector"
```

#### Verify Extensions
```bash
# Check current allowed extensions
az postgres flexible-server parameter show \
  --resource-group $RG \
  --server-name $DB_SERVER \
  --name azure.extensions
```

#### Available Extensions
Key extensions available in Azure PostgreSQL Flexible Server:
- `pgcrypto` - Cryptographic functions (required for OptiMed)
- `vector` - Vector similarity search (required for embeddings)
- `pg_stat_statements` - Query performance monitoring
- `pg_trgm` - Text similarity and fuzzy matching
- `uuid-ossp` - UUID generation (available but OptiMed uses built-in functions)

### 2. Connection Configuration

#### Connection String Format
```
postgresql://username:password@hostname:5432/database?sslmode=require
```

#### Current Production Connection
```bash
# Primary connection (used by backend)
PGVECTOR_DSN="postgresql://optimed_admin:clara_passkey@optimed-db-sweden.postgres.database.azure.com:5432/optimed?sslmode=require"

# Backup connection (same as primary for now)
DATABASE_URL="postgresql://optimed_admin:clara_passkey@optimed-db-sweden.postgres.database.azure.com:5432/optimed?sslmode=require"
```

### 3. Security Configuration

#### SSL/TLS Requirements
- SSL connections are enforced (`sslmode=require`)
- Azure PostgreSQL automatically provides SSL certificates
- All connections are encrypted in transit

#### Network Access
```bash
# Allow Azure services access (required for Container Apps)
az postgres flexible-server firewall-rule create \
  --resource-group $RG \
  --name $DB_SERVER \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

## Database Initialization

### Initial Database Creation

The `optimed` database is created automatically during server setup, but can be manually created if needed:

```bash
# Create database (if not exists)
az postgres flexible-server db create \
  --resource-group $RG \
  --server-name $DB_SERVER \
  --database-name $DB_NAME
```

### Schema Initialization Strategy

**Recommended approach**: Backend tables first, then migrations

1. **Start Backend** - Creates core application tables via repository `_ensure_tables_once()` methods
2. **Run Migrations** - Adds GDPR compliance and audit tables
3. **Restart Backend** - Normal operation with full schema

#### Manual Database Reset (if needed)
```bash
# Connect to PostgreSQL and reset database
python -c "
import asyncio
import asyncpg

async def reset_database():
    # Connect to postgres database to drop and recreate optimed
    dsn = 'postgresql://optimed_admin:clara_passkey@optimed-db-sweden.postgres.database.azure.com:5432/postgres?sslmode=require'

    try:
        conn = await asyncpg.connect(dsn)
        print('Connected to PostgreSQL server')

        # Drop database (removes all tables)
        await conn.execute('DROP DATABASE IF EXISTS optimed')
        print('Dropped optimed database')

        # Create clean database
        await conn.execute('CREATE DATABASE optimed')
        print('Created clean optimed database')

        await conn.close()

    except Exception as e:
        print(f'Error: {e}')

asyncio.run(reset_database())
"
```

## Migration Management

### Migration Scripts Location
All migration scripts are located in `/migrations/` directory:

- `002_create_gdpr_safe_schema.sql` - Core tables + GDPR compliance
- `003_create_rls_policies.sql` - Row Level Security policies
- `004_cleanup_phi_tables.sql` - PHI data cleanup
- `005_enhanced_audit_logging.sql` - Enhanced audit logging

### Running Migrations
```bash
# Run all migrations
python scripts/run_migrations.py
```

### Migration Features

#### Extension Handling
Migrations include conditional extension loading:
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
END $$;
```

#### UUID Generation
Uses PostgreSQL built-in `gen_random_uuid()` instead of `uuid-ossp` extension:
```sql
session_id UUID PRIMARY KEY DEFAULT gen_random_uuid()
```

### Key Tables Created

#### Core Application Tables
- `users` - User accounts with GDPR-safe structure
- `user_sessions` - Session management
- `user_actions` - Action audit trail
- `sessions` - GDPR-compliant session tracking

#### Application-Specific Tables
- `generated_images` - AI-generated images with PHI redaction
- `dicom_images` - Medical images metadata (GDPR-safe)
- `ehr_login_sessions` - EHR OAuth sessions
- `user_ehr_connections` - EHR system connections

#### Compliance & Audit Tables
- `system_usage_metrics` - System analytics
- `session_analytics` - Session performance metrics
- `data_access_logs` - GDPR data access logging
- `performance_metrics` - Application performance
- `encryption_audit_log` - Encryption operations audit
- `compliance_events` - Regulatory compliance events
- `gdpr_requests` - Data subject rights requests
- `system_health_metrics` - Infrastructure monitoring
- `data_lineage` - Data flow tracking

## Monitoring and Maintenance

### Performance Monitoring
```bash
# Check server metrics
az postgres flexible-server show \
  --resource-group $RG \
  --name $DB_SERVER

# View server logs
az postgres flexible-server logs list \
  --resource-group $RG \
  --name $DB_SERVER
```

### Backup Configuration
Azure PostgreSQL Flexible Server automatically:
- Takes daily backups
- Retains backups for 7 days (configurable up to 35 days)
- Supports point-in-time restore (PITR)

### Manual Backup
```bash
# Create manual backup
az postgres flexible-server backup create \
  --resource-group $RG \
  --name $DB_SERVER \
  --backup-name manual-backup-$(date +%Y%m%d)
```

## Troubleshooting

### Common Issues

#### Extension Not Available
**Error**: `extension "pgcrypto" is not allow-listed`
**Solution**: Enable extension via azure.extensions parameter

#### Connection Timeouts
**Symptoms**: Intermittent connection failures
**Solutions**:
1. Check firewall rules
2. Verify SSL configuration
3. Check Container Apps networking

#### Migration Failures
**Error**: `relation "sessions" does not exist`
**Solution**: Run backend first to create base tables, then migrations

### Useful Queries

#### Check Extensions
```sql
-- List installed extensions
SELECT * FROM pg_extension;

-- Check available extensions
SELECT * FROM pg_available_extensions WHERE name LIKE '%vector%';
```

#### Monitor Performance
```sql
-- Check active connections
SELECT * FROM pg_stat_activity;

-- Database size
SELECT pg_size_pretty(pg_database_size('optimed'));
```

## Security Best Practices

1. **Network Security**: Use Azure private endpoints for production
2. **Access Control**: Implement least-privilege database users
3. **Encryption**: Ensure all connections use SSL/TLS
4. **Monitoring**: Enable query logging for audit trails
5. **Backup**: Test restore procedures regularly

## GDPR Compliance Features

### Data Minimization
- PHI is pseudonymized using salted hashes
- Sensitive data encrypted at rest and in transit
- Automatic data retention policies

### Audit Requirements
- All data access logged in `data_access_logs`
- User actions tracked in `user_actions`
- Compliance events recorded in `compliance_events`

### Data Subject Rights
- GDPR requests tracked in `gdpr_requests` table
- Automated data export capabilities
- Secure data deletion procedures

## Contact Information

For database issues:
- **Primary**: Development Team
- **Escalation**: Azure Support (for infrastructure issues)
- **Emergency**: Follow incident response procedures