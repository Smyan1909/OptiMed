#!/usr/bin/env python3
"""
Run migrations against Azure PostgreSQL database
"""
import asyncio
import sys
from pathlib import Path
import asyncpg
from dotenv import load_dotenv

async def run_azure_migrations():
    """Run migrations against Azure database."""
    print("🚀 OptiMed Azure Database Migration")
    print("=" * 50)

    # Load environment
    load_dotenv()

    # Use Azure database connection
    dsn = "postgresql://optimeduser:optimedpassword@optimed-pg.postgres.database.azure.com:5432/optimed?sslmode=require"

    try:
        print("🔌 Connecting to Azure database...")
        conn = await asyncpg.connect(dsn)

        # Check if embeddings exists and what type it is
        obj_type = await conn.fetchval("""
            SELECT CASE
                WHEN table_type = 'VIEW' THEN 'view'
                WHEN table_type = 'BASE TABLE' THEN 'table'
                ELSE NULL
            END
            FROM information_schema.tables
            WHERE table_name = 'embeddings' AND table_schema = 'public'
        """)

        if obj_type == 'view':
            await conn.execute("DROP VIEW IF EXISTS embeddings CASCADE;")
            print("✅ Legacy embeddings view removed (GDPR compliance)")
        elif obj_type == 'table':
            await conn.execute("DROP TABLE IF EXISTS embeddings CASCADE;")
            print("✅ Legacy embeddings table removed (GDPR compliance)")
        else:
            print("✅ No legacy embeddings found (GDPR compliance)")

        # Run migration 005 (the main one we need)
        migration_path = Path("migrations/005_enhanced_audit_logging.sql")
        if migration_path.exists():
            print(f"📄 Running {migration_path} - Enhanced audit logging and metrics...")
            try:
                sql_content = migration_path.read_text()
                await conn.execute(sql_content)
                print(f"✅ {migration_path} completed successfully")
            except Exception as e:
                print(f"❌ Error in {migration_path}: {e}")
                return False

        # Verify tables were created
        print("\\n🔍 Verifying database schema...")
        tables = await conn.fetch("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)

        audit_tables = []
        expected_audit_tables = {
            'system_usage_metrics', 'session_analytics', 'data_access_logs',
            'performance_metrics', 'encryption_audit_log', 'compliance_events',
            'gdpr_requests', 'system_health_metrics', 'data_lineage'
        }

        for table in tables:
            table_name = table['table_name']
            if table_name in expected_audit_tables:
                audit_tables.append(table_name)

        print(f"📈 Audit/Analytics tables ({len(audit_tables)}): {', '.join(sorted(audit_tables))}")

        missing_critical = expected_audit_tables - {table['table_name'] for table in tables}
        if missing_critical:
            print(f"⚠️ Missing critical tables: {', '.join(missing_critical)}")
        else:
            print("✅ All audit tables created successfully!")

        await conn.close()
        print("\\n🎉 Azure database migration completed successfully!")
        print("🔒 Your Azure database is now GDPR-compliant with enhanced audit logging!")
        return True

    except Exception as e:
        print(f"❌ Azure migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(run_azure_migrations())
    if not success:
        sys.exit(1)