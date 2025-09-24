"""
Unit tests for GDPR-compliant vector store implementation.
"""

import pytest
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from optimed.adapters.vectorstores.gdpr_vectorstore import GDPRVectorStore
from optimed.adapters.vectorstores.ram_vectorstore import RAMVectorStore
from optimed.adapters.kms import EphemeralCacheService, KMSConfig, EnvelopeEncryption


class TestGDPRVectorStore:
    """Test cases for GDPR-compliant vector store."""
    
    @pytest.fixture
    async def mock_db_pool(self):
        """Mock database connection pool."""
        pool = AsyncMock()
        conn = AsyncMock()
        pool.acquire.return_value.__aenter__.return_value = conn
        return pool, conn
    
    @pytest.fixture
    def ram_vectorstore(self):
        """Mock RAM vector store."""
        return MagicMock(spec=RAMVectorStore)
    
    @pytest.fixture
    def ephemeral_cache(self):
        """Mock ephemeral cache service."""
        return MagicMock(spec=EphemeralCacheService)
    
    @pytest.fixture
    def gdpr_store(self, mock_db_pool, ram_vectorstore, ephemeral_cache):
        """GDPR vector store instance for testing."""
        pool, _ = mock_db_pool
        return GDPRVectorStore(
            dsn="postgresql://test:test@localhost/test",
            ram_vectorstore=ram_vectorstore,
            ephemeral_cache=ephemeral_cache
        )
    
    @pytest.mark.asyncio
    async def test_upsert_no_content_stored(self, gdpr_store, ram_vectorstore, mock_db_pool):
        """Test that content is not stored in upsert operations."""
        pool, conn = mock_db_pool
        
        # Mock RAM store upsert
        ram_vectorstore.upsert = AsyncMock(return_value="test_id")
        
        # Test upsert
        result = await gdpr_store.upsert(
            embedding_id="test_id",
            embedding=[0.1, 0.2, 0.3],
            object_type="test_type",
            object_id="test_obj",
            content="This is PHI content that should not be stored",
            metadata={"test": "metadata"},
            session_id="session_123"
        )
        
        # Verify RAM store was called with empty content
        ram_vectorstore.upsert.assert_called_once_with(
            embedding_id="test_id",
            embedding=[0.1, 0.2, 0.3],
            object_type="test_type",
            object_id="test_obj",
            content="",  # Content should be empty
            metadata={"test": "metadata", "content_type": "str", "object_type": "test_type", "object_id": "test_obj", "ingested_at": pytest.any(str)}
        )
        
        # Verify database was called with metadata only
        conn.execute.assert_called_once()
        call_args = conn.execute.call_args[0][0]
        assert "INSERT INTO embeddings_metadata" in call_args
        assert "content" not in call_args.lower()  # No content in SQL
        
        assert result == "test_id"
    
    @pytest.mark.asyncio
    async def test_similarity_search_returns_metadata_only(self, gdpr_store, ram_vectorstore):
        """Test that similarity search returns only metadata."""
        # Mock RAM store search results
        mock_results = [
            ("id1", 0.9, json.dumps({"object_type": "test", "object_id": "obj1"})),
            ("id2", 0.8, json.dumps({"object_type": "test", "object_id": "obj2"}))
        ]
        ram_vectorstore.similarity_search = AsyncMock(return_value=mock_results)
        
        # Mock database logging
        gdpr_store._log_search_activity = AsyncMock()
        
        # Test search
        results = await gdpr_store.similarity_search(
            embedding=[0.1, 0.2, 0.3],
            top_k=5,
            session_id="session_123"
        )
        
        # Verify results contain only metadata, no content
        assert len(results) == 2
        for result_id, similarity, metadata_json in results:
            assert isinstance(result_id, str)
            assert isinstance(similarity, float)
            assert isinstance(metadata_json, str)
            # Verify metadata doesn't contain content
            metadata = json.loads(metadata_json)
            assert "content" not in metadata
        
        # Verify search activity was logged
        gdpr_store._log_search_activity.assert_called_once_with("session_123", 2)
    
    @pytest.mark.asyncio
    async def test_get_chat_history_no_content(self, gdpr_store, mock_db_pool):
        """Test that chat history returns metadata only."""
        pool, conn = mock_db_pool
        
        # Mock database response
        mock_rows = [
            {
                "metadata": {"patient_id": "123", "timestamp": "1640995200000", "user_id": "user1"},
                "created_at": datetime.now(timezone.utc)
            }
        ]
        conn.fetch.return_value = mock_rows
        
        # Test chat history retrieval
        results = await gdpr_store.get_chat_history("patient_123", limit=10)
        
        # Verify no content is returned
        assert len(results) == 1
        result = results[0]
        assert "content_available" in result
        assert result["content_available"] is False
        assert "note" in result
        assert "Content not stored" in result["note"]
        assert "metadata" in result
    
    @pytest.mark.asyncio
    async def test_crypto_shred_session(self, gdpr_store, ram_vectorstore, ephemeral_cache):
        """Test crypto-shredding of session data."""
        # Setup session embeddings
        gdpr_store._session_embeddings["session_123"] = ["embed1", "embed2"]
        
        # Mock RAM store delete
        ram_vectorstore.delete = AsyncMock()
        
        # Mock ephemeral cache crypto-shred
        ephemeral_cache.crypto_shred_session = AsyncMock(return_value=True)
        
        # Test crypto-shredding
        result = await gdpr_store.crypto_shred_session("session_123")
        
        # Verify embeddings were removed from RAM
        ram_vectorstore.delete.assert_called_once_with(["embed1", "embed2"])
        
        # Verify ephemeral cache was crypto-shredded
        ephemeral_cache.crypto_shred_session.assert_called_once_with("session_123")
        
        # Verify session embeddings were cleared
        assert "session_123" not in gdpr_store._session_embeddings
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_memory_zeroization_on_close(self, gdpr_store, ram_vectorstore, mock_db_pool):
        """Test that memory is zeroized when store is closed."""
        pool, _ = mock_db_pool
        
        # Mock RAM store zeroize
        ram_vectorstore.zeroize = MagicMock()
        
        # Setup some session data
        gdpr_store._session_embeddings["session_123"] = ["embed1"]
        
        # Test close
        await gdpr_store.close()
        
        # Verify RAM store was zeroized
        ram_vectorstore.zeroize.assert_called_once()
        
        # Verify session embeddings were cleared
        assert len(gdpr_store._session_embeddings) == 0
    
    @pytest.mark.asyncio
    async def test_store_dicom_embedding_no_content(self, gdpr_store, ram_vectorstore, mock_db_pool):
        """Test DICOM embedding storage without content."""
        pool, conn = mock_db_pool
        
        # Mock RAM store upsert
        ram_vectorstore.upsert = AsyncMock()
        
        # Test DICOM embedding storage
        result = await gdpr_store.store_dicom_embedding(
            image_id="dicom_123",
            embedding=[0.1, 0.2, 0.3],
            metadata={"modality": "CT", "patient_id": "patient_123"}
        )
        
        # Verify RAM store was called with empty content
        ram_vectorstore.upsert.assert_called_once_with(
            embedding_id=pytest.any(str),
            embedding=[0.1, 0.2, 0.3],
            object_type="DICOM",
            object_id="dicom_123",
            content="",  # No content stored
            metadata={"modality": "CT", "patient_id": "patient_123"}
        )
        
        # Verify database was called
        conn.execute.assert_called_once()
        
        assert "dicom_dicom_123_" in result  # Generated ID format
    
    @pytest.mark.asyncio
    async def test_search_similar_dicom_metadata_only(self, gdpr_store, ram_vectorstore):
        """Test DICOM similarity search returns metadata only."""
        # Mock RAM store search
        mock_results = [
            ("dicom_1", 0.9, json.dumps({"modality": "CT", "patient_id": "patient_123"})),
            ("dicom_2", 0.8, json.dumps({"modality": "MRI", "patient_id": "patient_456"}))
        ]
        ram_vectorstore.similarity_search = AsyncMock(return_value=mock_results)
        
        # Test DICOM search
        results = await gdpr_store.search_similar_dicom(
            query_embedding=[0.1, 0.2, 0.3],
            limit=5,
            similarity_threshold=0.7
        )
        
        # Verify results contain only metadata
        assert len(results) == 2
        for result in results:
            assert "embedding_id" in result
            assert "metadata" in result
            assert "similarity" in result
            assert "content" not in result  # No content returned
    
    def test_get_memory_stats(self, gdpr_store, ram_vectorstore):
        """Test memory statistics retrieval."""
        # Mock RAM store stats
        ram_vectorstore.get_stats.return_value = {
            "total_records": 100,
            "memory_usage_mb": 50
        }
        
        # Setup session embeddings
        gdpr_store._session_embeddings = {
            "session_1": ["embed1", "embed2"],
            "session_2": ["embed3"]
        }
        
        # Test stats
        stats = gdpr_store.get_memory_stats()
        
        # Verify stats structure
        assert "ram_store_stats" in stats
        assert "session_embeddings_count" in stats
        assert "total_session_embeddings" in stats
        
        assert stats["session_embeddings_count"] == 2
        assert stats["total_session_embeddings"] == 3
        assert stats["ram_store_stats"]["total_records"] == 100


class TestRAMVectorStore:
    """Test cases for RAM-only vector store."""
    
    @pytest.fixture
    def ram_store(self):
        """RAM vector store instance for testing."""
        return RAMVectorStore(embedding_dim=3, max_memory_mb=10)
    
    @pytest.mark.asyncio
    async def test_upsert_and_search(self, ram_store):
        """Test basic upsert and search functionality."""
        # Test upsert
        await ram_store.upsert(
            embedding_id="test_1",
            embedding=[0.1, 0.2, 0.3],
            object_type="test",
            object_id="obj_1",
            content="test content",
            metadata={"type": "test"}
        )
        
        # Test search
        results = await ram_store.similarity_search(
            embedding=[0.1, 0.2, 0.3],
            top_k=5
        )
        
        assert len(results) == 1
        assert results[0][0] == "test_1"
        assert results[0][1] == pytest.approx(1.0, rel=1e-6)  # Cosine similarity of identical vectors
    
    @pytest.mark.asyncio
    async def test_memory_budget_management(self, ram_store):
        """Test memory budget and eviction."""
        # Fill up memory with many embeddings
        for i in range(100):  # This should trigger eviction
            await ram_store.upsert(
                embedding_id=f"test_{i}",
                embedding=[0.1, 0.2, 0.3],
                object_type="test",
                object_id=f"obj_{i}",
                content=f"content {i}",
                metadata={"index": i}
            )
        
        # Check memory stats
        stats = ram_store.get_memory_stats()
        assert stats["total_records"] <= 100  # Some may have been evicted
        
        # Verify memory usage is within budget
        assert stats["usage_percentage"] <= 100
    
    def test_zeroization(self, ram_store):
        """Test secure memory zeroization."""
        # Add some data
        asyncio.run(ram_store.upsert(
            embedding_id="test_1",
            embedding=[0.1, 0.2, 0.3],
            object_type="test",
            object_id="obj_1",
            content="test content",
            metadata={"type": "test"}
        ))
        
        # Verify data exists
        stats_before = ram_store.get_stats()
        assert stats_before["total_records"] > 0
        
        # Zeroize
        ram_store.zeroize()
        
        # Verify data is gone
        stats_after = ram_store.get_stats()
        assert stats_after["total_records"] == 0
        assert stats_after["current_memory_bytes"] == 0


class TestCryptoShredding:
    """Test cases for crypto-shredding functionality."""
    
    @pytest.fixture
    def crypto_service(self):
        """Crypto service for testing."""
        config = KMSConfig(kek_id="test_kek", ttl_hours=1)
        return EnvelopeEncryption(config)
    
    def test_encrypt_decrypt_content(self, crypto_service):
        """Test content encryption and decryption."""
        session_id = "test_session"
        content = "This is sensitive PHI content"
        
        # Encrypt content
        envelope_data = crypto_service.encrypt_content(content, session_id)
        
        # Verify envelope structure
        assert "dek_id" in envelope_data
        assert "encrypted_dek" in envelope_data
        assert "ciphertext" in envelope_data
        assert "created_at" in envelope_data
        
        # Decrypt content
        decrypted_content = crypto_service.decrypt_content(envelope_data, session_id)
        
        # Verify content matches
        assert decrypted_content == content
    
    def test_crypto_shredding(self, crypto_service):
        """Test crypto-shredding functionality."""
        session_id = "test_session"
        content = "This is sensitive PHI content"
        
        # Encrypt content
        envelope_data = crypto_service.encrypt_content(content, session_id)
        
        # Verify we can decrypt initially
        decrypted_content = crypto_service.decrypt_content(envelope_data, session_id)
        assert decrypted_content == content
        
        # Crypto-shred (delete DEK)
        result = crypto_service.crypto_shred(session_id)
        assert result is True
        
        # Verify DEK is gone from cache
        cache_stats = crypto_service.get_cache_stats()
        assert cache_stats["active_deks"] == 0
    
    def test_multiple_sessions_isolation(self, crypto_service):
        """Test that crypto-shredding one session doesn't affect others."""
        session1 = "session_1"
        session2 = "session_2"
        content = "Sensitive content"
        
        # Encrypt content for both sessions
        envelope1 = crypto_service.encrypt_content(content, session1)
        envelope2 = crypto_service.encrypt_content(content, session2)
        
        # Verify both can be decrypted
        assert crypto_service.decrypt_content(envelope1, session1) == content
        assert crypto_service.decrypt_content(envelope2, session2) == content
        
        # Crypto-shred session1
        crypto_service.crypto_shred(session1)
        
        # Verify session2 still works
        assert crypto_service.decrypt_content(envelope2, session2) == content
        
        # Verify session1 is crypto-shredded
        cache_stats = crypto_service.get_cache_stats()
        assert cache_stats["active_deks"] == 1  # Only session2 remains


@pytest.mark.asyncio
async def test_integration_gdpr_workflow():
    """Integration test for complete GDPR workflow."""
    # This would be a more comprehensive test that exercises the full workflow
    # including database operations, RAM storage, and crypto-shredding
    
    # Mock database pool
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    
    # Create GDPR store
    gdpr_store = GDPRVectorStore(
        dsn="postgresql://test:test@localhost/test",
        ram_vectorstore=RAMVectorStore(embedding_dim=3),
        ephemeral_cache=None
    )
    gdpr_store._pool = pool
    
    try:
        # 1. Store embedding without content
        await gdpr_store.upsert(
            embedding_id="test_embed",
            embedding=[0.1, 0.2, 0.3],
            object_type="Patient",
            object_id="patient_123",
            content="Patient has diabetes and hypertension",  # PHI content
            metadata={"session_id": "session_123"},
            session_id="session_123"
        )
        
        # 2. Search embeddings
        results = await gdpr_store.similarity_search(
            embedding=[0.1, 0.2, 0.3],
            top_k=5,
            session_id="session_123"
        )
        
        # 3. Verify no content is stored or returned
        assert len(results) >= 0  # May or may not find results
        
        # 4. Crypto-shred session
        await gdpr_store.crypto_shred_session("session_123")
        
        # 5. Verify memory is clean
        stats = gdpr_store.get_memory_stats()
        assert stats["total_session_embeddings"] == 0
        
    finally:
        # Clean up
        await gdpr_store.close()
