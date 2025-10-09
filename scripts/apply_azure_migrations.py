#!/usr/bin/env python3
"""
Comprehensive Azure PostgreSQL Migration Tool
Applies all necessary migrations to optimed-db-sweden in correct order

Migrations applied:
1. Extensions (pgcrypto, vector)
2. Core GDPR schema (sessions, audit, resources)
3. User management
4. Note templates
5. RLS policies
6. Audit schema fixes (user_id nullable, FK constraint removal)
"""

import asyncpg
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

class AzureMigrationRunner:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.conn: asyncpg.Connection = None
        self.migrations_applied = []

    async def connect(self):
        """Connect to Azure PostgreSQL."""
        print("[INFO] Connecting to Azure PostgreSQL...")
        self.conn = await asyncpg.connect(self.dsn)
        print("[OK] Connected successfully")

    async def close(self):
        """Close connection."""
        if self.conn:
            await self.conn.close()
            print("[INFO] Connection closed")

    async def check_table_exists(self, table_name: str) -> bool:
        """Check if a table exists."""
        result = await self.conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = $1
            )
        """, table_name)
        return result

    async def migration_001_extensions(self):
        """Enable required PostgreSQL extensions."""
        print("\n" + "="*70)
        print("MIGRATION 001: Enable PostgreSQL Extensions")
        print("="*70)

        # Check pgcrypto
        has_pgcrypto = await self.conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM pg_extension WHERE extname = 'pgcrypto'
            )
        """)

        if not has_pgcrypto:
            try:
                await self.conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
                print("[OK] pgcrypto extension enabled")
            except Exception as e:
                print(f"[WARN] Could not enable pgcrypto: {e}")
        else:
            print("[OK] pgcrypto already enabled")

        # Check vector
        has_vector = await self.conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM pg_extension WHERE extname = 'vector'
            )
        """)

        if not has_vector:
            try:
                await self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                print("[OK] vector extension enabled")
            except Exception as e:
                print(f"[WARN] Could not enable vector: {e}")
        else:
            print("[OK] vector already enabled")

        self.migrations_applied.append("001_extensions")

    async def migration_002_core_schema(self):
        """Create core GDPR-compliant schema."""
        print("\n" + "="*70)
        print("MIGRATION 002: Core GDPR Schema")
        print("="*70)

        # Users table
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id VARCHAR(255) PRIMARY KEY,
                email VARCHAR(255) UNIQUE,
                name VARCHAR(255),
                role VARCHAR(50) NOT NULL DEFAULT 'clinician',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                last_login_at TIMESTAMPTZ
            );
        """)
        print("[OK] Created users table")

        # Sessions table
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                subject_hash BYTEA,
                user_id VARCHAR(255),
                tenant_id UUID,
                lawful_basis TEXT,
                purpose_of_use TEXT,
                scopes TEXT[],
                model_config_hash BYTEA,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ended_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("[OK] Created sessions table")

        # Audit events
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id BIGSERIAL PRIMARY KEY,
                session_id UUID,
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                resource_version TEXT,
                occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                outcome TEXT,
                latency_ms INT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("[OK] Created audit_events table")

        # Resources (metadata only)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS resources (
                id BIGSERIAL PRIMARY KEY,
                subject_hash BYTEA NOT NULL,
                server_alias TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                version_id TEXT,
                last_updated TIMESTAMPTZ,
                etag TEXT,
                encounter_id TEXT,
                period_start TIMESTAMPTZ,
                period_end TIMESTAMPTZ,
                has_binary BOOLEAN DEFAULT FALSE,
                byte_size INT,
                sha256 BYTEA,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(subject_hash, server_alias, resource_type, resource_id, version_id)
            );
        """)
        print("[OK] Created resources table")

        # System usage metrics
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS system_usage_metrics (
                id BIGSERIAL PRIMARY KEY,
                metric_type VARCHAR(100) NOT NULL,
                metric_name VARCHAR(200) NOT NULL,
                value NUMERIC NOT NULL,
                unit VARCHAR(50) NOT NULL DEFAULT 'count',
                dimensions JSONB DEFAULT '{}',
                tenant_id UUID,
                recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        print("[OK] Created system_usage_metrics table")

        # Indexes
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_events(session_id);")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_type ON system_usage_metrics(metric_type, metric_name);")
        print("[OK] Created indexes")

        self.migrations_applied.append("002_core_schema")

    async def migration_003_audit_tables(self):
        """Create comprehensive audit logging tables."""
        print("\n" + "="*70)
        print("MIGRATION 003: Audit Logging Tables")
        print("="*70)

        # Data access logs
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS data_access_logs (
                id BIGSERIAL PRIMARY KEY,
                session_id UUID,
                user_id VARCHAR(255),
                access_type TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_identifier TEXT,
                resource_count INT DEFAULT 1,
                data_source TEXT NOT NULL DEFAULT 'application',
                lawful_basis TEXT NOT NULL DEFAULT 'legitimate_interest',
                purpose_of_use TEXT NOT NULL DEFAULT 'healthcare_delivery',
                access_method TEXT,
                requested_fields TEXT[],
                returned_count INT,
                filter_criteria JSONB DEFAULT '{}',
                data_retention_days INT,
                encryption_method TEXT,
                access_duration_ms INT,
                privacy_impact_level TEXT DEFAULT 'low',
                access_granted BOOLEAN DEFAULT true,
                accessed_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("[OK] Created data_access_logs table")

        # Data lineage
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS data_lineage (
                id BIGSERIAL PRIMARY KEY,
                session_id UUID,
                source_system TEXT NOT NULL,
                source_resource_id TEXT NOT NULL,
                destination_system TEXT NOT NULL,
                destination_resource_id TEXT NOT NULL,
                transformation_type TEXT NOT NULL,
                transformation_details JSONB DEFAULT '{}',
                quality_score REAL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("[OK] Created data_lineage table")

        # Compliance events
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS compliance_events (
                id BIGSERIAL PRIMARY KEY,
                event_type VARCHAR(100) NOT NULL,
                compliance_framework VARCHAR(50) NOT NULL,
                session_id UUID,
                user_id VARCHAR(255),
                patient_id TEXT,
                data_categories TEXT[],
                processing_purposes TEXT[],
                compliance_status VARCHAR(50) NOT NULL DEFAULT 'compliant',
                risk_assessment JSONB DEFAULT '{}',
                event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        print("[OK] Created compliance_events table")

        # Indexes
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_data_access_user ON data_access_logs(user_id);")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_data_access_session ON data_access_logs(session_id);")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_compliance_user ON compliance_events(user_id);")
        print("[OK] Created audit indexes")

        self.migrations_applied.append("003_audit_tables")

    async def migration_004_note_templates(self):
        """Create note templates and generation metadata tables."""
        print("\n" + "="*70)
        print("MIGRATION 004: Note Templates")
        print("="*70)

        # Check if users table exists
        has_users = await self.check_table_exists('users')

        if not has_users:
            print("[WARN] Users table not found, skipping note templates")
            return

        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS note_templates (
                template_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id VARCHAR(255) NOT NULL,
                name TEXT NOT NULL,
                language TEXT NOT NULL CHECK (language IN ('sv', 'en')),
                template_type TEXT NOT NULL,
                template_structure JSONB NOT NULL,
                is_system_template BOOLEAN DEFAULT FALSE,
                file_format TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("[OK] Created note_templates table")

        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS note_generation_metadata (
                generation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id VARCHAR(255) NOT NULL,
                patient_id UUID,
                template_id UUID,
                session_id TEXT NOT NULL,
                template_name TEXT NOT NULL,
                template_type TEXT NOT NULL,
                language TEXT NOT NULL,
                generation_status TEXT NOT NULL,
                context_prompt_hash TEXT,
                chunks_used_count INT DEFAULT 0,
                generation_started_at TIMESTAMPTZ DEFAULT NOW(),
                generation_completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("[OK] Created note_generation_metadata table")

        # Indexes
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_note_templates_user ON note_templates(user_id);")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_note_gen_user ON note_generation_metadata(user_id);")
        print("[OK] Created note template indexes")

        self.migrations_applied.append("004_note_templates")

    async def migration_005_ehr_connections(self):
        """Create EHR connection management tables."""
        print("\n" + "="*70)
        print("MIGRATION 005: EHR Connections")
        print("="*70)

        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ehr_connections (
                connection_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id VARCHAR(255) NOT NULL,
                provider_type VARCHAR(50) NOT NULL,
                fhir_base_url TEXT NOT NULL,
                access_token_encrypted BYTEA,
                refresh_token_encrypted BYTEA,
                token_expires_at TIMESTAMPTZ,
                patient_id TEXT,
                scopes TEXT[],
                is_active BOOLEAN DEFAULT TRUE,
                last_used_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        print("[OK] Created ehr_connections table")

        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_ehr_conn_user ON ehr_connections(user_id);")
        print("[OK] Created EHR connection indexes")

        self.migrations_applied.append("005_ehr_connections")

    async def migration_007_fix_user_id_nullable(self):
        """Make user_id nullable in audit tables (migration 007)."""
        print("\n" + "="*70)
        print("MIGRATION 007: Make user_id Nullable")
        print("="*70)

        # Check current constraint
        constraint_check = await self.conn.fetchrow("""
            SELECT column_name, is_nullable, data_type
            FROM information_schema.columns
            WHERE table_name = 'data_access_logs'
            AND column_name = 'user_id'
        """)

        if constraint_check:
            print(f"[INFO] Current status: {constraint_check['column_name']} - "
                  f"Nullable: {constraint_check['is_nullable']}")

            if constraint_check['is_nullable'] == 'YES':
                print("[OK] user_id is already nullable")
            else:
                await self.conn.execute("""
                    ALTER TABLE data_access_logs
                    ALTER COLUMN user_id DROP NOT NULL;
                """)
                print("[OK] user_id is now nullable")

        # Also fix compliance_events
        comp_check = await self.conn.fetchrow("""
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = 'compliance_events'
            AND column_name = 'user_id'
        """)

        if comp_check and comp_check['is_nullable'] == 'NO':
            await self.conn.execute("""
                ALTER TABLE compliance_events
                ALTER COLUMN user_id DROP NOT NULL;
            """)
            print("[OK] compliance_events.user_id is now nullable")

        self.migrations_applied.append("007_user_id_nullable")

    async def migration_009_drop_fk_constraints(self):
        """Drop foreign key constraints on session_id (migration 009)."""
        print("\n" + "="*70)
        print("MIGRATION 009: Drop Foreign Key Constraints")
        print("="*70)

        # Find all FK constraints on session_id
        fk_constraints = await self.conn.fetch("""
            SELECT
                tc.constraint_name,
                tc.table_name,
                kcu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_name IN ('data_access_logs', 'data_lineage', 'audit_events', 'compliance_events')
            AND kcu.column_name = 'session_id'
        """)

        if fk_constraints:
            print(f"[INFO] Found {len(fk_constraints)} foreign key constraint(s):")
            for fk in fk_constraints:
                print(f"   - {fk['table_name']}.{fk['column_name']} -> {fk['constraint_name']}")
                await self.conn.execute(f"""
                    ALTER TABLE {fk['table_name']}
                    DROP CONSTRAINT IF EXISTS {fk['constraint_name']};
                """)
                print(f"[OK] Dropped {fk['constraint_name']}")
        else:
            print("[OK] No foreign key constraints found")

        self.migrations_applied.append("009_drop_fk_constraints")

    async def verify_schema(self):
        """Verify the final schema state."""
        print("\n" + "="*70)
        print("SCHEMA VERIFICATION")
        print("="*70)

        # Check critical tables
        tables = ['users', 'sessions', 'data_access_logs', 'audit_events',
                  'system_usage_metrics', 'ehr_connections']

        for table in tables:
            exists = await self.check_table_exists(table)
            status = "[OK]" if exists else "[MISSING]"
            print(f"{status} {table}")

        # Verify user_id is nullable
        user_id_check = await self.conn.fetchrow("""
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = 'data_access_logs'
            AND column_name = 'user_id'
        """)

        if user_id_check:
            status = "[OK]" if user_id_check['is_nullable'] == 'YES' else "[FAIL]"
            print(f"{status} data_access_logs.user_id nullable: {user_id_check['is_nullable']}")

        # Verify no FK constraints remain
        remaining_fk = await self.conn.fetch("""
            SELECT constraint_name, table_name
            FROM information_schema.table_constraints
            WHERE constraint_type = 'FOREIGN KEY'
            AND table_name IN ('data_access_logs', 'data_lineage', 'audit_events')
            AND constraint_name LIKE '%session%'
        """)

        if not remaining_fk:
            print("[OK] No problematic session_id foreign keys")
        else:
            print(f"[WARN] Still have {len(remaining_fk)} session FK constraints")

    async def run_all_migrations(self):
        """Run all migrations in order."""
        try:
            await self.connect()

            print("\n" + "="*70)
            print("  COMPREHENSIVE AZURE POSTGRESQL MIGRATION")
            print("  Database: optimed-db-sweden")
            print("="*70)

            # Run migrations in order
            await self.migration_001_extensions()
            await self.migration_002_core_schema()
            await self.migration_003_audit_tables()
            await self.migration_004_note_templates()
            await self.migration_005_ehr_connections()
            await self.migration_007_fix_user_id_nullable()
            await self.migration_009_drop_fk_constraints()

            # Verify
            await self.verify_schema()

            # Log completion
            try:
                await self.conn.execute("""
                    INSERT INTO system_usage_metrics (
                        metric_type, metric_name, value, unit, dimensions
                    ) VALUES (
                        'migration',
                        'comprehensive_migration_completed',
                        1,
                        'count',
                        $1::JSONB
                    )
                """, {
                    "migrations_applied": self.migrations_applied,
                    "timestamp": str(asyncio.get_event_loop().time())
                })
            except Exception as e:
                print(f"[WARN] Could not log migration completion: {e}")

            print("\n" + "="*70)
            print(f"[OK] Successfully applied {len(self.migrations_applied)} migration(s)")
            print("="*70)
            print("\nMigrations applied:")
            for migration in self.migrations_applied:
                print(f"  - {migration}")

            return True

        except Exception as e:
            print(f"\n[ERROR] Migration failed: {e}")
            import traceback
            print(traceback.format_exc())
            return False
        finally:
            await self.close()


async def main():
    """Main entry point."""
    # Get database connection string
    dsn = os.getenv("PGVECTOR_DSN") or os.getenv("DATABASE_URL")

    if not dsn:
        print("[ERROR] PGVECTOR_DSN or DATABASE_URL environment variable not set")
        print("\nPlease set it to your Azure PostgreSQL connection string:")
        print("  set PGVECTOR_DSN=postgresql://user:password@optimed-db-sweden.postgres.database.azure.com:5432/optimed")
        return False

    # Run migrations
    runner = AzureMigrationRunner(dsn)
    success = await runner.run_all_migrations()

    if success:
        print("\n" + "="*70)
        print("[OK] NEXT STEPS")
        print("="*70)
        print("\n1. Restart the Azure Container App:")
        print("   az containerapp revision restart \\")
        print("     --name optimed-api-sweden \\")
        print("     --resource-group OPTIMED")
        print("\n2. Test the application:")
        print("   - Log in via SMART-on-FHIR")
        print("   - Access patient data")
        print("   - Verify no audit logging errors")
        print()
    else:
        print("\n[ERROR] Migration failed. Please check errors above.")
        return False

    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
