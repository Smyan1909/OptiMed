import asyncpg
from typing import Sequence
from optimed.core.ports import VectorStore

class PGVectorAdapter(VectorStore):
    def __init__(self, dsn: str, min_size: int = 10, max_size: int = 20):
        """Initialize the PGVectorAdapter with a PostgreSQL DSN and connection pool settings."""
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self._pool = None

    async def _get_pool(self):
        """Get or create the connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=self.min_size,
                max_size=self.max_size
            )
        return self._pool

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
    
    async def upsert(
        self,
        embedding_id: str,
        embedding: Sequence[float],
        metadata: dict[str, str] | None = None,
    ) -> None:
        metadata = metadata or {}
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO embeddings (id, embedding, metadata)
                VALUES ($1, $2, $3)
                ON CONFLICT (id) DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata;
                """,
                embedding_id,
                embedding,
                metadata
            )
    
    async def similarity_search(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        filter_: dict[str, str] | None = None,
    ) -> Sequence[tuple[str, float]]:
        filter_ = filter_ or {}
        where_clauses = []
        values = [embedding]

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
                SELECT id, embedding <#> $1 AS distance
                FROM embeddings
                {where_sql}
                ORDER BY distance
                LIMIT {top_k}
                """,
                *values
            )
            return [(row['id'], row['distance']) for row in rows]

    async def delete(self, embedding_ids: Sequence[str]) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM embeddings WHERE id = ANY($1)",
                embedding_ids
            )

    async def update(
        self,
        embedding_id: str,
        embedding: Sequence[float] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        if not embedding and not metadata:
            return

        set_clauses = []
        values = [embedding_id]

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

        

        