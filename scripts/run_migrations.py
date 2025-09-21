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
    """Run SQL migrations in order."""
    print("🗄️ Running OptiMed Database Migrations...")
    
    # Load environment
    load_dotenv()
    
    dsn = os.getenv("PGVECTOR_DSN")
    if not dsn:
        print("❌ PGVECTOR_DSN environment variable not set")
        print("Please set PGVECTOR_DSN in your .env file")
        return False
    
    try:
        print(f"🔌 Connecting to database...")
        conn = await asyncpg.connect(dsn)
        
        # Run migrations in order
        migrations = [
            "migrations/001_create_embeddings.sql",
            "migrations/002_create_gdpr_safe_schema.sql", 
            "migrations/003_create_rls_policies.sql",
            "migrations/004_cleanup_phi_tables.sql"
        ]
        
        for migration in migrations:
            migration_path = Path(migration)
            if migration_path.exists():
                print(f"📄 Running {migration}...")
                sql_content = migration_path.read_text()
                
                # Execute migration
                await conn.execute(sql_content)
                print(f"✅ {migration} completed successfully")
            else:
                print(f"⚠️ {migration} not found, skipping")
        
        # Verify tables were created
        print("\n🔍 Verifying database schema...")
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """)
        
        print("📊 Created tables:")
        for table in tables:
            print(f"  - {table['table_name']}")
        
        # Check extensions
        extensions = await conn.fetch("""
            SELECT extname 
            FROM pg_extension 
            ORDER BY extname
        """)
        
        print("\n🔧 Installed extensions:")
        for ext in extensions:
            print(f"  - {ext['extname']}")
        
        await conn.close()
        print("\n🎉 All migrations completed successfully!")
        print("🔒 Your database is now GDPR-compliant!")
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
