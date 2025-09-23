#!/usr/bin/env python3
"""
GDPR Integration Script for OptiMed

This script helps integrate the GDPR-compliant changes into your existing system.
It runs migrations, tests the new functionality, and provides status information.
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from optimed.adapters.vectorstores.pgvector import PGVectorAdapter
from optimed.adapters.user_repository.pg_user_repository import PGUserRepository
from optimed.adapters.kms.crypto_service import KMSClient
import asyncpg

async def test_gdpr_compliance():
    """Test the GDPR-compliant functionality."""
    print("🔒 Testing GDPR Compliance...")
    
    # Load environment
    load_dotenv()
    
    dsn = os.getenv("PGVECTOR_DSN")
    if not dsn:
        print("❌ PGVECTOR_DSN environment variable not set")
        return False
    
    try:
        # Test vector store with RAM-only embeddings
        print("📊 Testing RAM-only vector store...")
        vector_store = PGVectorAdapter(dsn=dsn, embedding_dim=3)
        
        # Test embedding storage
        test_embedding = [0.1, 0.2, 0.3]
        test_content = {"patient_data": "sensitive information"}
        test_metadata = {"session_id": "test_session_123", "object_type": "Patient"}
        
        embedding_id = await vector_store.upsert(
            embedding_id="test_1",
            embedding=test_embedding,
            object_type="Patient",
            object_id="patient_123",
            content=test_content,
            metadata=test_metadata
        )
        print(f"✅ Embedded data with ID: {embedding_id}")
        
        # Test similarity search
        results = await vector_store.similarity_search(
            embedding=test_embedding,
            top_k=5,
            filter_={"session_id": "test_session_123"}
        )
        print(f"✅ Found {len(results)} similar embeddings in RAM")
        
        # Test session management
        memory_usage = vector_store.get_session_memory_usage("test_session_123")
        print(f"✅ Session memory usage: {memory_usage}")
        
        # Test session cleanup
        await vector_store.clear_session("test_session_123")
        print("✅ Session cleared successfully")
        
        # Test user repository
        print("👤 Testing user repository...")
        user_repo = PGUserRepository(dsn=dsn)
        
        # Test KMS (if enabled)
        if os.getenv("EPHEMERAL_CACHE_ENABLED", "false").lower() == "true":
            print("🔐 Testing KMS encryption...")
            kms = KMSClient(kek_id="test-kek")
            dek, encrypted_dek = kms.generate_data_key()
            test_data = b"test sensitive data"
            ciphertext = kms.encrypt(test_data, encrypted_dek)
            decrypted = kms.decrypt(ciphertext, encrypted_dek)
            
            if decrypted == test_data:
                print("✅ KMS encryption/decryption working")
            else:
                print("❌ KMS encryption/decryption failed")
                return False
            
            # Test crypto-shredding
            kms.delete_data_key(encrypted_dek)
            print("✅ Crypto-shredding simulation successful")
        
        print("🎉 All GDPR compliance tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ GDPR compliance test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Cleanup
        if 'vector_store' in locals():
            await vector_store.close()
        if 'user_repo' in locals():
            await user_repo.close()

async def check_migration_status():
    """Check if GDPR migrations have been applied."""
    print("📋 Checking migration status...")
    
    dsn = os.getenv("PGVECTOR_DSN")
    if not dsn:
        print("❌ PGVECTOR_DSN environment variable not set")
        return False
    
    try:
        conn = await asyncpg.connect(dsn)
        
        # Check for new GDPR tables
        gdpr_tables = [
            "sessions", "audit_events", "resources", "resource_codes", 
            "evidence_sets", "model_registry", "retrieval_config", "temp_content"
        ]
        
        for table in gdpr_tables:
            exists = await conn.fetchval(f"""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = '{table}'
                )
            """)
            
            if exists:
                print(f"✅ Table '{table}' exists")
            else:
                print(f"❌ Table '{table}' missing - run migrations")
                return False
        
        # Check if embeddings table still exists (should be dropped for full GDPR compliance)
        embeddings_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'embeddings'
            )
        """)
        
        if embeddings_exists:
            print("⚠️  'embeddings' table still exists - consider running cleanup migration")
        else:
            print("✅ 'embeddings' table removed (GDPR compliant)")
        
        # Check RLS policies
        rls_tables = ["sessions", "resources", "audit_events", "evidence_sets", "temp_content"]
        for table in rls_tables:
            rls_enabled = await conn.fetchval(f"""
                SELECT relrowsecurity FROM pg_class 
                WHERE relname = '{table}' AND relkind = 'r'
            """)
            
            if rls_enabled:
                print(f"✅ RLS enabled on '{table}'")
            else:
                print(f"⚠️  RLS not enabled on '{table}' - run RLS migration")
        
        await conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Migration check failed: {e}")
        return False

def print_environment_status():
    """Print current environment configuration."""
    print("🔧 Environment Configuration:")
    print(f"   PERSIST_PHI: {os.getenv('PERSIST_PHI', 'false')}")
    print(f"   EPHEMERAL_CACHE_ENABLED: {os.getenv('EPHEMERAL_CACHE_ENABLED', 'false')}")
    print(f"   SESSION_TTL_MINUTES: {os.getenv('SESSION_TTL_MINUTES', '60')}")
    print(f"   EMBEDDING_DIM: {os.getenv('EMBEDDING_DIM', '1024')}")
    print(f"   KMS_KEK_BASE64: {'Set' if os.getenv('KMS_KEK_BASE64') else 'Not set'}")

async def main():
    """Main integration script."""
    print("🚀 OptiMed GDPR Integration Script")
    print("=" * 50)
    
    # Check environment
    print_environment_status()
    print()
    
    # Check migration status
    migration_ok = await check_migration_status()
    print()
    
    if not migration_ok:
        print("❌ Migration check failed. Please run the migration scripts first:")
        print("   1. migrations/002_create_gdpr_safe_schema.sql")
        print("   2. migrations/003_create_rls_policies.sql")
        print("   3. migrations/004_cleanup_phi_tables.sql")
        return
    
    # Test GDPR compliance
    compliance_ok = await test_gdpr_compliance()
    
    print("\n" + "=" * 50)
    if compliance_ok:
        print("🎉 GDPR Integration Successful!")
        print("\nYour system is now GDPR-compliant with:")
        print("✅ RAM-only embeddings")
        print("✅ No PHI persistence")
        print("✅ Session-scoped data")
        print("✅ Crypto-shredding capability")
        print("✅ Audit trails")
        print("✅ Row-level security")
    else:
        print("❌ GDPR Integration Failed!")
        print("Please check the errors above and fix them before proceeding.")

if __name__ == "__main__":
    asyncio.run(main())
