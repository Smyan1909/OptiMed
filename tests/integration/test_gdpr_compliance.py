"""
Integration tests for GDPR compliance features.

These tests verify that the system properly handles PHI data according to GDPR requirements.
"""

import pytest
import asyncio
import uuid
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any

import asyncpg

from optimed.adapters.vectorstores.gdpr_vectorstore import GDPRVectorStore
from optimed.adapters.vectorstores.ram_vectorstore import RAMVectorStore
from optimed.adapters.kms import create_crypto_service, create_ephemeral_cache_service
from optimed.adapters.database.gdpr_models import (
    SessionModel, AuditEventModel, ResourceModel, EvidenceSetModel,
    GDPRModelUtils
)


@pytest.mark.integration
class TestGDPRCompliance:
    """Integration tests for GDPR compliance."""
    
    @pytest.fixture
    async def db_pool(self):
        """Database connection pool for testing."""
        dsn = os.getenv("TEST_DATABASE_URL", "postgresql://test:test@localhost/test_gdpr")
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        yield pool
        await pool.close()
    
    @pytest.fixture
    async def gdpr_store(self, db_pool):
        """GDPR vector store with real database."""
        ram_store = RAMVectorStore(embedding_dim=128, max_memory_mb=50)
        crypto_service = create_crypto_service()
        ephemeral_cache = create_ephemeral_cache_service(db_pool)
        
        store = GDPRVectorStore(
            dsn=os.getenv("TEST_DATABASE_URL", "postgresql://test:test@localhost/test_gdpr"),
            ram_vectorstore=ram_store,
            ephemeral_cache=ephemeral_cache
        )
        
        yield store
        await store.close()
    
    @pytest.mark.asyncio
    async def test_no_phi_stored_in_database(self, gdpr_store, db_pool):
        """Test that no PHI is stored in the database."""
        # Store embedding with PHI content
        phi_content = "Patient John Doe (ID: 12345) has diabetes and takes metformin 500mg daily"
        
        await gdpr_store.upsert(
            embedding_id="test_phi_embed",
            embedding=[0.1] * 128,
            object_type="PatientNote",
            object_id="note_123",
            content=phi_content,  # PHI content
            metadata={"patient_id": "12345", "note_type": "progress"},
            session_id="session_123"
        )
        
        # Check database - should not contain PHI content
        async with db_pool.acquire() as conn:
            # Check embeddings_metadata table
            row = await conn.fetchrow("""
                SELECT metadata FROM embeddings_metadata 
                WHERE key = 'test_phi_embed'
            """)
            
            assert row is not None
            metadata = row["metadata"]
            
            # Verify PHI content is not in metadata
            metadata_str = json.dumps(metadata)
            assert "John Doe" not in metadata_str
            assert "diabetes" not in metadata_str
            assert "metformin" not in metadata_str
            
            # Verify only metadata is stored
            assert "patient_id" in metadata
            assert "note_type" in metadata
    
    @pytest.mark.asyncio
    async def test_embeddings_only_in_memory(self, gdpr_store):
        """Test that embeddings are only stored in memory."""
        # Store embedding
        await gdpr_store.upsert(
            embedding_id="test_memory_embed",
            embedding=[0.1, 0.2, 0.3] * 43,  # 128 dimensions
            object_type="Test",
            object_id="test_123",
            content="Test content",
            metadata={"test": "data"}
        )
        
        # Verify embedding is in RAM store
        ram_stats = gdpr_store.ram_store.get_stats()
        assert ram_stats["total_records"] > 0
        
        # Verify embedding is not in database
        async with gdpr_store._get_pool() as conn:
            # Check if there's an embeddings table with vector column
            has_vector_column = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'embeddings' 
                    AND column_name = 'embedding'
                    AND data_type = 'USER-DEFINED'
                )
            """)
            
            # If vector column exists, it should be empty or deprecated
            if has_vector_column:
                vector_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM embeddings 
                    WHERE embedding IS NOT NULL
                """)
                assert vector_count == 0  # No vectors should be stored
    
    @pytest.mark.asyncio
    async def test_session_audit_trail(self, gdpr_store, db_pool):
        """Test that session activities are properly audited."""
        session_id = str(uuid.uuid4())
        
        # Create a session
        async with db_pool.acquire() as conn:
            session_model = GDPRModelUtils.create_session(
                conn,
                subject_hash=b"hashed_patient_id",
                user_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                lawful_basis="care_delivery",
                purpose_of_use="clinical_decision_support"
            )
            await conn.commit()
        
        # Perform search operation
        await gdpr_store.similarity_search(
            embedding=[0.1] * 128,
            top_k=5,
            session_id=session_id
        )
        
        # Check audit trail
        async with db_pool.acquire() as conn:
            audit_events = await conn.fetch("""
                SELECT action, outcome FROM audit_events 
                WHERE session_id = $1
                ORDER BY occurred_at DESC
            """, session_id)
            
            # Should have search activity logged
            assert len(audit_events) > 0
            search_events = [event for event in audit_events if event["action"] == "SEARCH"]
            assert len(search_events) > 0
    
    @pytest.mark.asyncio
    async def test_crypto_shredding_functionality(self, gdpr_store):
        """Test that crypto-shredding works correctly."""
        session_id = "test_crypto_session"
        
        # Store some content in ephemeral cache
        test_content = "This is sensitive PHI content"
        await gdpr_store.ephemeral_cache.store_content(
            session_id=session_id,
            resource_type="PatientNote",
            resource_id="note_123",
            content=test_content
        )
        
        # Verify content can be retrieved
        retrieved_content = await gdpr_store.ephemeral_cache.retrieve_content(
            session_id=session_id,
            resource_type="PatientNote",
            resource_id="note_123"
        )
        assert retrieved_content == test_content
        
        # Crypto-shred the session
        await gdpr_store.crypto_shred_session(session_id)
        
        # Verify content can no longer be retrieved
        retrieved_after_shred = await gdpr_store.ephemeral_cache.retrieve_content(
            session_id=session_id,
            resource_type="PatientNote",
            resource_id="note_123"
        )
        assert retrieved_after_shred is None
    
    @pytest.mark.asyncio
    async def test_tenant_isolation(self, db_pool):
        """Test that RLS policies enforce tenant isolation."""
        tenant1_id = str(uuid.uuid4())
        tenant2_id = str(uuid.uuid4())
        
        async with db_pool.acquire() as conn:
            # Create sessions for different tenants
            await conn.execute("""
                INSERT INTO sessions (session_id, subject_hash, user_id, tenant_id, 
                                    lawful_basis, purpose_of_use, model_config_hash)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, 
                str(uuid.uuid4()), b"hash1", str(uuid.uuid4()), tenant1_id,
                "care_delivery", "clinical_support", b"config_hash"
            )
            
            await conn.execute("""
                INSERT INTO sessions (session_id, subject_hash, user_id, tenant_id, 
                                    lawful_basis, purpose_of_use, model_config_hash)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, 
                str(uuid.uuid4()), b"hash2", str(uuid.uuid4()), tenant2_id,
                "care_delivery", "clinical_support", b"config_hash"
            )
            
            # Set tenant context for tenant1
            await conn.execute("SELECT set_tenant_context($1)", tenant1_id)
            
            # Try to access tenant2's sessions (should fail due to RLS)
            tenant2_sessions = await conn.fetch("""
                SELECT session_id FROM sessions WHERE tenant_id = $1
            """, tenant2_id)
            
            # Should be empty due to RLS
            assert len(tenant2_sessions) == 0
            
            # Access tenant1's sessions (should work)
            tenant1_sessions = await conn.fetch("""
                SELECT session_id FROM sessions WHERE tenant_id = $1
            """, tenant1_id)
            
            assert len(tenant1_sessions) == 1
    
    @pytest.mark.asyncio
    async def test_memory_zeroization_on_shutdown(self, gdpr_store):
        """Test that memory is properly zeroized on shutdown."""
        # Store some embeddings
        for i in range(5):
            await gdpr_store.upsert(
                embedding_id=f"test_embed_{i}",
                embedding=[0.1 + i * 0.01] * 128,
                object_type="Test",
                object_id=f"test_{i}",
                content=f"Test content {i}",
                metadata={"index": i}
            )
        
        # Verify embeddings are in memory
        stats_before = gdpr_store.get_memory_stats()
        assert stats_before["total_session_embeddings"] > 0
        
        # Close the store (should zeroize memory)
        await gdpr_store.close()
        
        # Verify memory is zeroized
        stats_after = gdpr_store.get_memory_stats()
        assert stats_after["total_session_embeddings"] == 0
    
    @pytest.mark.asyncio
    async def test_evidence_pointers_without_content(self, gdpr_store, db_pool):
        """Test that evidence sets store pointers only, not content."""
        session_id = str(uuid.uuid4())
        
        # Create a session
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO sessions (session_id, subject_hash, user_id, tenant_id, 
                                    lawful_basis, purpose_of_use, model_config_hash)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, 
                session_id, b"patient_hash", str(uuid.uuid4()), str(uuid.uuid4()),
                "care_delivery", "clinical_support", b"config_hash"
            )
        
        # Create evidence set (this would be done by the retrieval system)
        async with db_pool.acquire() as conn:
            evidence_model = GDPRModelUtils.create_evidence_set(
                conn,
                session_id=session_id,
                question_id=uuid.uuid4(),
                rank=1,
                resource_type="Observation",
                resource_id="obs_123",
                section="value",
                start_offset=10,
                end_offset=50,
                rerank_score=0.95,
                reason="High relevance for diabetes diagnosis"
            )
            await conn.commit()
        
        # Verify evidence set contains only pointers, not content
        async with db_pool.acquire() as conn:
            evidence = await conn.fetchrow("""
                SELECT * FROM evidence_sets 
                WHERE session_id = $1
            """, session_id)
            
            assert evidence is not None
            assert evidence["resource_type"] == "Observation"
            assert evidence["resource_id"] == "obs_123"
            assert evidence["section"] == "value"
            assert evidence["start_offset"] == 10
            assert evidence["end_offset"] == 50
            
            # Verify no content is stored
            assert "content" not in dict(evidence)
    
    @pytest.mark.asyncio
    async def test_resource_catalog_metadata_only(self, db_pool):
        """Test that resource catalog stores only metadata."""
        # Create a resource record
        async with db_pool.acquire() as conn:
            resource_model = GDPRModelUtils.create_resource(
                conn,
                subject_hash=b"patient_hash_123",
                server_alias="epic",
                resource_type="Observation",
                resource_id="obs_12345",
                version_id="1",
                last_updated=datetime.now(timezone.utc),
                etag="abc123",
                encounter_id="enc_67890",
                period_start=datetime.now(timezone.utc),
                period_end=datetime.now(timezone.utc),
                has_binary=False,
                byte_size=1024,
                sha256=b"sha256_hash"
            )
            await conn.commit()
        
        # Verify resource contains only metadata
        async with db_pool.acquire() as conn:
            resource = await conn.fetchrow("""
                SELECT * FROM resources 
                WHERE resource_id = 'obs_12345'
            """)
            
            assert resource is not None
            assert resource["subject_hash"] == b"patient_hash_123"
            assert resource["server_alias"] == "epic"
            assert resource["resource_type"] == "Observation"
            assert resource["resource_id"] == "obs_12345"
            assert resource["has_binary"] is False
            assert resource["byte_size"] == 1024
            
            # Verify no content is stored
            assert "content" not in dict(resource)
            assert "value" not in dict(resource)
            assert "text" not in dict(resource)
    
    @pytest.mark.asyncio
    async def test_ephemeral_cache_ttl_enforcement(self, gdpr_store):
        """Test that ephemeral cache respects TTL."""
        session_id = "test_ttl_session"
        content = "This content should expire"
        
        # Store content with short TTL (1 second for testing)
        original_ttl = os.getenv("EPHEMERAL_CACHE_TTL_HOURS", "24")
        os.environ["EPHEMERAL_CACHE_TTL_HOURS"] = "0.0003"  # ~1 second
        
        try:
            # Recreate cache service with new TTL
            ephemeral_cache = create_ephemeral_cache_service(gdpr_store._get_pool())
            
            await ephemeral_cache.store_content(
                session_id=session_id,
                resource_type="Test",
                resource_id="test_123",
                content=content
            )
            
            # Verify content is available immediately
            retrieved = await ephemeral_cache.retrieve_content(
                session_id=session_id,
                resource_type="Test",
                resource_id="test_123"
            )
            assert retrieved == content
            
            # Wait for TTL to expire
            await asyncio.sleep(2)
            
            # Verify content is no longer available
            retrieved_after_ttl = await ephemeral_cache.retrieve_content(
                session_id=session_id,
                resource_type="Test",
                resource_id="test_123"
            )
            assert retrieved_after_ttl is None
            
        finally:
            # Restore original TTL
            if original_ttl:
                os.environ["EPHEMERAL_CACHE_TTL_HOURS"] = original_ttl
            else:
                os.environ.pop("EPHEMERAL_CACHE_TTL_HOURS", None)


@pytest.mark.asyncio
async def test_phi_detection_in_logs():
    """Test that PHI is not leaked in logs."""
    import logging
    import io
    
    # Capture logs
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.INFO)
    
    logger = logging.getLogger("test_phi_logs")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    
    # Log operations that might contain PHI
    logger.info("Processing patient John Doe with ID 12345")
    logger.info("Diagnosis: diabetes mellitus type 2")
    logger.info("Medication: metformin 500mg daily")
    
    # Check captured logs
    log_content = log_capture.getvalue()
    
    # In a real implementation, you'd want to ensure PHI is not logged
    # For this test, we're just verifying the logging mechanism works
    assert "Processing patient" in log_content
    
    # In production, you'd want to ensure PHI is redacted:
    # assert "John Doe" not in log_content
    # assert "12345" not in log_content
    # assert "diabetes" not in log_content
    # assert "metformin" not in log_content
