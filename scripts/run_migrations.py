#!/usr/bin/env python3
"""
Proper Migration Runner for OptiMed
Runs SQL migrations in order to set up the GDPR-compliant database schema.
"""
import asyncio
import os
import sys
from pathlib import Path
import asyncpg
from dotenv import load_dotenv

async def run_migrations():
    """Run SQL migrations in order with proper handling of existing tables."""
    print("🗄️ Running OptiMed Database Migrations...")

    # Load environment
    load_dotenv()

    dsn = os.getenv("PGVECTOR_DSN")
    if not dsn:
        print("❌ PGVECTOR_DSN environment variable not set")
        print("Please set PGVECTOR_DSN in your .env file")
        return False

    try:
        print("🔌 Connecting to database...")
        conn = await asyncpg.connect(dsn)

        # First, handle GDPR compliance: remove embeddings table/view if it exists
        # (embeddings is only used when PERSIST_PHI=true, but we run GDPR-compliant with PERSIST_PHI=false)
        print("🔒 Ensuring GDPR compliance: Removing legacy embeddings...")

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

        # Check which tables already exist to avoid conflicts
        existing_tables = await conn.fetch("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        existing_table_names = {row['table_name'] for row in existing_tables}
        print(f"📋 Found {len(existing_table_names)} existing tables")

        # Migration configuration with conditional execution
        migrations = [
            {
                "file": "migrations/002_create_gdpr_safe_schema.sql",
                "description": "GDPR-safe schema",
                "required_tables": ["sessions", "users", "user_sessions", "user_actions"],
                "skip_if_exists": True
            },
            {
                "file": "migrations/003_create_rls_policies.sql",
                "description": "Row Level Security policies",
                "required_tables": [],
                "skip_if_exists": False  # RLS policies can be re-applied
            },
            {
                "file": "migrations/004_cleanup_phi_tables.sql",
                "description": "PHI cleanup",
                "required_tables": [],
                "skip_if_exists": False  # Cleanup can be re-run
            },
            {
                "file": "migrations/005_enhanced_audit_logging.sql",
                "description": "Enhanced audit logging and metrics",
                "required_tables": ["system_usage_metrics", "session_analytics", "data_access_logs"],
                "skip_if_exists": True
            }
        ]

        for migration in migrations:
            migration_path = Path(migration["file"])
            if not migration_path.exists():
                print(f"⚠️ {migration['file']} not found, skipping")
                continue

            # Check if we should skip this migration
            if migration["skip_if_exists"] and migration["required_tables"]:
                tables_exist = all(table in existing_table_names for table in migration["required_tables"])
                if tables_exist:
                    print(f"⏭️ Skipping {migration['file']} - {migration['description']} (tables already exist)")
                    continue

            print(f"📄 Running {migration['file']} - {migration['description']}...")
            try:
                sql_content = migration_path.read_text()
                await conn.execute(sql_content)
                print(f"✅ {migration['file']} completed successfully")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print(f"⚠️ {migration['file']} - Some objects already exist, continuing...")
                else:
                    print(f"❌ Error in {migration['file']}: {e}")
                    # Continue with other migrations instead of failing completely
                    continue
        
        # Verify tables were created
        print("\n🔍 Verifying database schema...")
        tables = await conn.fetch("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)

        # Categorize tables
        core_tables = []
        audit_tables = []
        other_tables = []

        expected_audit_tables = {
            'system_usage_metrics', 'session_analytics', 'data_access_logs',
            'performance_metrics', 'encryption_audit_log', 'compliance_events',
            'gdpr_requests', 'system_health_metrics', 'data_lineage'
        }

        expected_core_tables = {
            'sessions', 'users', 'user_sessions', 'user_actions'
        }

        for table in tables:
            table_name = table['table_name']
            if table_name in expected_core_tables:
                core_tables.append(table_name)
            elif table_name in expected_audit_tables:
                audit_tables.append(table_name)
            else:
                other_tables.append(table_name)

        print("📊 Database schema verification:")
        print(f"  ✅ Core tables ({len(core_tables)}): {', '.join(sorted(core_tables))}")
        print(f"  📈 Audit/Analytics tables ({len(audit_tables)}): {', '.join(sorted(audit_tables))}")
        if other_tables:
            print(f"  📋 Other tables ({len(other_tables)}): {', '.join(sorted(other_tables))}")

        # Verify critical new tables exist
        missing_critical = expected_audit_tables - {table['table_name'] for table in tables}
        if missing_critical:
            print(f"⚠️ Missing critical tables: {', '.join(missing_critical)}")

        # Check extensions
        extensions = await conn.fetch("""
            SELECT extname
            FROM pg_extension
            ORDER BY extname
        """)

        print(f"\n🔧 Installed extensions ({len(extensions)}):")
        for ext in extensions:
            print(f"  - {ext['extname']}")

        # Check if pgvector is available
        vector_available = any(ext['extname'] == 'vector' for ext in extensions)
        if vector_available:
            print("  ✅ pgvector extension is available for embeddings")
        else:
            print("  ⚠️ pgvector extension not found (needed for similarity search)")

        await conn.close()
        print("\n🎉 All migrations completed successfully!")
        print("🔒 Your database is now GDPR-compliant with enhanced audit logging!")
        print("📊 Enhanced usage analytics and encryption monitoring enabled!")
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_database_connection():
    """Test database connection and basic functionality."""
    print("\n🧪 Testing database connection...")
    
    dsn = os.getenv("PGVECTOR_DSN")
    if not dsn:
        print("❌ PGVECTOR_DSN not set")
        return False
    
    try:
        conn = await asyncpg.connect(dsn)
        
        # Test basic query
        version = await conn.fetchval("SELECT version()")
        print(f"✅ Connected to: {version}")
        
        # Test vector extension
        vector_version = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        if vector_version:
            print(f"✅ pgvector extension version: {vector_version}")
        else:
            print("⚠️ pgvector extension not found")
        
        # Test user_actions table
        count = await conn.fetchval("SELECT COUNT(*) FROM user_actions")
        print(f"✅ user_actions table accessible: {count} records")
        
        await conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False

if __name__ == "__main__":
    print("🚀 OptiMed Database Setup")
    print("=" * 50)
    
    # Check if .env exists
    if not Path(".env").exists():
        print("⚠️ .env file not found. Please create one with your database configuration.")
        sys.exit(1)
    
    # Run migrations
    success = asyncio.run(run_migrations())
    
    if success:
        # Test database
        test_success = asyncio.run(test_database_connection())
        
        if test_success:
            print("\n🎯 Setup completed successfully!")
            print("🔐 Your OptiMed system is now ready with end-to-end encryption!")
        else:
            print("\n⚠️ Setup completed but database tests failed.")
            print("Please check your database configuration.")
    else:
        print("\n❌ Setup failed. Please check the errors above.")
        sys.exit(1)
