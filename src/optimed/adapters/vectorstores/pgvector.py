import asyncpg # type: ignore
from pgvector.asyncpg import register_vector # type: ignore
from typing import Sequence, Any
from optimed.core.ports import VectorStore
import uuid
import json

class PGVectorAdapter(VectorStore):
    def __init__(self, dsn: str, min_size: int = 10, max_size: int = 20):
        """Initialize the PGVectorAdapter with a PostgreSQL DSN and connection pool settings."""
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self._pool = None

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create the connection pool."""
        if self._pool is None:

            
            async def _init(conn):
                await register_vector(conn)

            self._pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=self.min_size,
                max_size=self.max_size,
                init=_init,
            )
        return self._pool

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
    
    async def upsert(
        self,
        embedding_id: str,
        embedding: Sequence[float],
        object_type: str,
        object_id: str,
        content: str | dict,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        metadata = metadata or {}
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO embeddings
                (id, key, object_type, object_id, content, embedding, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (key) DO UPDATE
                SET embedding = EXCLUDED.embedding,
                    metadata  = EXCLUDED.metadata,
                    updated_at = now();
                """,
                uuid.uuid4(),
                embedding_id,
                object_type,
                object_id,
                json.dumps(content) if isinstance(content, dict) else content,
                embedding,
                json.dumps(metadata)
            )
            return embedding_id
    
    async def similarity_search(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        filter_: dict[str, str] | None = None,
    ) -> Sequence[tuple[str, float, str]]:
        filter_ = filter_ or {}
        where_clauses: list[str] = []
        values: list[Any] = [embedding]

        for i, (k, v) in enumerate(filter_.items(), start=2):
            where_clauses.append(f"metadata ->> '{k}' = ${i}")
            values.append(v)

        where_sql = " AND ".join(where_clauses)
        if where_sql:
            where_sql = "WHERE " + where_sql
        
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, embedding <#> $1 AS distance, content
                FROM embeddings
                {where_sql}
                ORDER BY distance
                LIMIT {top_k}
                """,
                *values
            )
            return [(row['id'], row['distance'], row['content']) for row in rows]

    async def delete(self, embedding_ids: Sequence[str]) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM embeddings WHERE id = ANY($1)",
                embedding_ids
            )

    async def get_chat_history(self, patient_id: str, limit: int = 20) -> list[dict[str, Any]]:
        query = """
            SELECT content, metadata
            FROM embeddings 
            WHERE metadata->>'patient_id' = $1 
            AND metadata->>'namespace' = 'chat_history'
            ORDER BY metadata->>'timestamp' DESC
            LIMIT $2
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, patient_id, limit)

        result = []
        for row in rows:
            try:
                # Parse metadata if it's a JSON string
                metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
                result.append({
                    "content": row["content"], 
                    "metadata": metadata
                })
            except Exception as e:
                print(f"Error parsing row in get_chat_history: {e}")
                continue
        
        return result

    async def clear_chat_history(self, patient_id: str) -> None:
        """Clear chat history for a specific patient."""
        query = """
            DELETE FROM embeddings 
            WHERE metadata->>'patient_id' = $1 
            AND metadata->>'namespace' = 'chat_history'
        """
        
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(query, patient_id)

    async def update(
        self,
        embedding_id: str,
        embedding: Sequence[float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not embedding and not metadata:
            return

        set_clauses: list[str] = []
        values: list[Any] = [embedding_id]

        if embedding:
            set_clauses.append("embedding = $2")
            values.append(embedding)

        if metadata:
            set_clauses.append(f"metadata = ${len(values) + 1}")
            values.append(metadata)

        set_sql = ", ".join(set_clauses)

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE embeddings SET {set_sql} WHERE id = $1", *values
            )

        

        