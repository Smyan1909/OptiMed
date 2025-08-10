import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter
import uuid

@pytest.fixture
def adapter():
    return PGVectorAdapter("postgresql://user:pass@localhost/db", min_size=5, max_size=10)


@pytest.fixture
def mock_connection():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock()
    return conn


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    pool.close = AsyncMock()
    return pool


class AsyncContextManagerMock:
    """A mock that properly implements async context manager protocol"""
    def __init__(self, return_value):
        self.return_value = return_value
        self.enter_called = False
        self.exit_called = False
    
    async def __aenter__(self):
        self.enter_called = True
        return self.return_value
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.exit_called = True
        return None


@pytest.mark.asyncio
class TestPGVectorAdapter:
    
    async def test_init(self):
        dsn = "postgresql://user:pass@localhost/db"
        adapter = PGVectorAdapter(dsn, min_size=5, max_size=15)
        assert adapter.dsn == dsn
        assert adapter.min_size == 5
        assert adapter.max_size == 15
        assert adapter._pool is None

    async def test_init_default_pool_sizes(self):
        dsn = "postgresql://user:pass@localhost/db"
        adapter = PGVectorAdapter(dsn)
        assert adapter.min_size == 10
        assert adapter.max_size == 20

    @patch('optimed.adapters.vectorstores.pgvector.asyncpg.create_pool')
    async def test_get_pool_creates_new_pool(self, mock_create_pool, adapter):
        mock_pool = AsyncMock()
        # Make create_pool return a coroutine that resolves to the mock pool
        async def create_pool_coro(*args, **kwargs):
            return mock_pool
        mock_create_pool.side_effect = create_pool_coro
        
        result = await adapter._get_pool()
        
        # Check that create_pool was called with the expected arguments
        mock_create_pool.assert_called_once()
        call_args, call_kwargs = mock_create_pool.call_args
        
        # Verify the expected keyword arguments
        assert call_kwargs['dsn'] == adapter.dsn
        assert call_kwargs['min_size'] == adapter.min_size
        assert call_kwargs['max_size'] == adapter.max_size
        assert 'init' in call_kwargs  # Verify init function is passed
        assert callable(call_kwargs['init'])  # Verify it's a callable
        
        assert result == mock_pool
        assert adapter._pool == mock_pool

    @patch('optimed.adapters.vectorstores.pgvector.asyncpg.create_pool')
    async def test_get_pool_reuses_existing_pool(self, mock_create_pool, adapter):
        mock_pool = AsyncMock()
        adapter._pool = mock_pool
        
        result = await adapter._get_pool()
        
        mock_create_pool.assert_not_called()
        assert result == mock_pool

    async def test_close_pool(self, adapter):
        mock_pool = AsyncMock()
        adapter._pool = mock_pool
        
        await adapter.close()
        
        mock_pool.close.assert_called_once()
        assert adapter._pool is None

    async def test_close_no_pool(self, adapter):
        # Should not raise an error when no pool exists
        await adapter.close()

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_upsert_with_metadata(self, mock_get_pool, adapter, mock_connection):
        mock_pool = MagicMock()
        # Create a proper async context manager
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        
        embedding_id = "test_id"
        embedding = [0.1, 0.2, 0.3]
        object_type = "document"
        object_id = "doc_123"
        content = "This is test content"
        metadata = {"key": "value"}
        
        await adapter.upsert(embedding_id, embedding, object_type, object_id, content, metadata)
        
        mock_get_pool.assert_called_once()
        mock_pool.acquire.assert_called_once()
        mock_connection.execute.assert_called_once()
        call_args = mock_connection.execute.call_args
        assert "INSERT INTO embeddings" in call_args[0][0]
        assert "ON CONFLICT (key) DO UPDATE" in call_args[0][0]
        assert isinstance(call_args[0][1], uuid.UUID)
        assert call_args[0][2] == embedding_id  # Fixed: embedding_id is now at position 2
        assert call_args[0][3] == object_type   # Fixed: object_type is now at position 3
        assert call_args[0][4] == object_id     # Fixed: object_id is now at position 4
        assert call_args[0][5] == content       # Fixed: content is now at position 5
        assert call_args[0][6] == embedding     # Fixed: embedding is now at position 6
        assert call_args[0][7] == '{"key": "value"}'  # metadata remains at position 7

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_upsert_without_metadata(self, mock_get_pool, adapter, mock_connection):
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        
        embedding_id = "test_id"
        embedding = [0.1, 0.2, 0.3]
        object_type = "document"
        object_id = "doc_123"
        content = "This is test content"
        
        await adapter.upsert(embedding_id, embedding, object_type, object_id, content)
        
        mock_connection.execute.assert_called_once()
        call_args = mock_connection.execute.call_args
        assert call_args[0][7] == '{}'

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_similarity_search_without_filter(self, mock_get_pool, adapter, mock_connection):
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        mock_connection.fetch.return_value = [
            {'id': 'id1', 'distance': 0.1, 'similarity': 0.9, 'content': 'First document content'},
            {'id': 'id2', 'distance': 0.2, 'similarity': 0.8, 'content': 'Second document content'}
        ]
        
        embedding = [0.1, 0.2, 0.3]
        result = await adapter.similarity_search(embedding, top_k=2)
        
        assert result == [('id1', 0.9, 'First document content'), ('id2', 0.8, 'Second document content')]
        mock_connection.fetch.assert_called_once()
        call_args = mock_connection.fetch.call_args
        query = call_args[0][0]
        assert "ORDER BY distance" in query
        assert "LIMIT 2" in query

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_similarity_search_with_filter(self, mock_get_pool, adapter, mock_connection):
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        mock_connection.fetch.return_value = [{'id': 'id1', 'distance': 0.1, 'similarity': 0.9, 'content': 'Medical document content'}]
        
        embedding = [0.1, 0.2, 0.3]
        filter_ = {"category": "medical"}
        
        result = await adapter.similarity_search(embedding, top_k=5, filter_=filter_)
        
        assert result == [('id1', 0.9, 'Medical document content')]
        call_args = mock_connection.fetch.call_args
        query = call_args[0][0]
        assert "WHERE metadata ->> 'category' = $2" in query
        assert call_args[0][1] == embedding
        assert call_args[0][2] == "medical"

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_similarity_search_with_multiple_filters(self, mock_get_pool, adapter, mock_connection):
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        mock_connection.fetch.return_value = []
        
        embedding = [0.1, 0.2, 0.3]
        filter_ = {"category": "medical", "type": "diagnosis"}
        
        await adapter.similarity_search(embedding, top_k=5, filter_=filter_)
        
        call_args = mock_connection.fetch.call_args
        query = call_args[0][0]
        # Check that both filters are in the query
        assert "metadata ->> 'category'" in query
        assert "metadata ->> 'type'" in query
        assert "WHERE" in query and "AND" in query
        assert call_args[0][1] == embedding

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_delete(self, mock_get_pool, adapter, mock_connection):
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        
        embedding_ids = ["id1", "id2", "id3"]
        
        await adapter.delete(embedding_ids)
        
        mock_connection.execute.assert_called_once_with(
            "DELETE FROM embeddings WHERE id = ANY($1)",
            embedding_ids
        )

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_update_embedding_only(self, mock_get_pool, adapter, mock_connection):
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        
        embedding_id = "test_id"
        embedding = [0.1, 0.2, 0.3]
        
        await adapter.update(embedding_id, embedding=embedding)
        
        call_args = mock_connection.execute.call_args
        assert "UPDATE embeddings SET embedding = $2 WHERE id = $1" in call_args[0][0]
        assert call_args[0][1] == embedding_id
        assert call_args[0][2] == embedding

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_update_metadata_only(self, mock_get_pool, adapter, mock_connection):
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        
        embedding_id = "test_id"
        metadata = {"key": "value"}
        
        await adapter.update(embedding_id, metadata=metadata)
        
        call_args = mock_connection.execute.call_args
        assert "UPDATE embeddings SET metadata = $2 WHERE id = $1" in call_args[0][0]
        assert call_args[0][1] == embedding_id
        assert call_args[0][2] == metadata

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_update_both_embedding_and_metadata(self, mock_get_pool, adapter, mock_connection):
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        
        embedding_id = "test_id"
        embedding = [0.1, 0.2, 0.3]
        metadata = {"key": "value"}
        
        await adapter.update(embedding_id, embedding=embedding, metadata=metadata)
        
        call_args = mock_connection.execute.call_args
        query = call_args[0][0]
        assert "UPDATE embeddings SET embedding = $2, metadata = $3 WHERE id = $1" in query
        assert call_args[0][1] == embedding_id
        assert call_args[0][2] == embedding
        assert call_args[0][3] == metadata

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_update_no_changes(self, mock_get_pool, adapter, mock_connection):
        embedding_id = "test_id"
        
        await adapter.update(embedding_id)
        
        mock_get_pool.assert_not_called()

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_pool_context_manager_usage(self, mock_get_pool, adapter, mock_connection):
        """Test that pool.acquire() is properly used as a context manager"""
        mock_pool = MagicMock()
        context_manager = AsyncContextManagerMock(mock_connection)
        mock_pool.acquire.return_value = context_manager
        mock_get_pool.return_value = mock_pool
        
        await adapter.delete(["test_id"])
        
        mock_pool.acquire.assert_called_once()
        assert context_manager.enter_called
        assert context_manager.exit_called

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_similarity_search_empty_filters(self, mock_get_pool, adapter, mock_connection):
        """Test similarity search with empty filters"""
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        mock_connection.fetch.return_value = []
        
        embedding = [0.1, 0.2, 0.3]
        result = await adapter.similarity_search(embedding, top_k=5, filter_={})
        
        assert result == []
        call_args = mock_connection.fetch.call_args
        query = call_args[0][0]
        # Should not have WHERE clause when no filters
        assert "WHERE" not in query
        assert call_args[0][1] == embedding

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_error_handling_in_operations(self, mock_get_pool, adapter, mock_connection):
        """Test that exceptions are properly propagated"""
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        
        # Make execute raise an exception
        mock_connection.execute.side_effect = Exception("Database error")
        
        with pytest.raises(Exception):
            await adapter.upsert("test_id", [0.1, 0.2], "document", "doc_123", "test content", {"key": "value"})

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_sql_injection_prevention(self, mock_get_pool, adapter, mock_connection):
        """Test that filter values are properly parameterized"""
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        mock_connection.fetch.return_value = []
        
        embedding = [0.1, 0.2, 0.3]
        # Try a potentially malicious filter value
        filter_ = {"category": "'; DROP TABLE embeddings; --"}
        
        await adapter.similarity_search(embedding, top_k=5, filter_=filter_)
        
        call_args = mock_connection.fetch.call_args
        # The malicious string should be passed as a parameter, not in the query string
        assert "DROP TABLE" not in call_args[0][0]
        assert call_args[0][2] == "'; DROP TABLE embeddings; --"

    @patch.object(PGVectorAdapter, '_get_pool')
    async def test_large_embedding_handling(self, mock_get_pool, adapter, mock_connection):
        """Test handling of large embeddings"""
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = AsyncContextManagerMock(mock_connection)
        mock_get_pool.return_value = mock_pool
        
        embedding_id = "test_large_embedding"
        # Create a large embedding (e.g., 1536 dimensions like OpenAI's embeddings)
        large_embedding = [0.1] * 1536
        object_type = "document"
        object_id = "large_doc_123"
        content = {"text": "Large document content"}
        metadata = {"model": "text-embedding-ada-002"}
        
        await adapter.upsert(embedding_id, large_embedding, object_type, object_id, content, metadata)
        
        call_args = mock_connection.execute.call_args
        assert isinstance(call_args[0][1], uuid.UUID)
        assert call_args[0][2] == embedding_id  # Fixed: embedding_id is now at position 2
        assert call_args[0][3] == object_type   # Fixed: object_type is now at position 3
        assert call_args[0][4] == object_id     # Fixed: object_id is now at position 4
        assert call_args[0][5] == '{"text": "Large document content"}'  # Fixed: content is now at position 5 (JSON serialized)
        assert call_args[0][6] == large_embedding  # Fixed: embedding is now at position 6
        assert len(call_args[0][6]) == 1536