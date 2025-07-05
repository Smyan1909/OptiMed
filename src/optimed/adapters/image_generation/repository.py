from __future__ import annotations

import json
import asyncpg
from typing import Optional, Any
from optimed.core.domain import GeneratedImage
from optimed.core.ports import GeneratedImageRepository


class PostgresGeneratedImageRepository(GeneratedImageRepository):
    """PostgreSQL implementation for generated image storage."""
    
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None
        self._tables_created = False
    
    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn)
            
            # Create tables once after pool is created
            if not self._tables_created:
                await self._ensure_tables_once()
                self._tables_created = True
                
        return self._pool
    
    async def _ensure_tables_once(self):
        """Create tables once, safely with better error handling."""
        if self._pool is None:
            return
            
        try:
            async with self._pool.acquire() as conn:
                # Check if table exists first
                table_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'generated_images'
                    );
                """)
                
                if not table_exists:
                    print("[DB] Creating generated_images table...")
                    await conn.execute("""
                        CREATE TABLE generated_images (
                            generation_id UUID PRIMARY KEY,
                            image_data BYTEA NOT NULL,
                            image_format VARCHAR(10) NOT NULL DEFAULT 'png',
                            metadata JSONB NOT NULL DEFAULT '{}',
                            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                            prompt TEXT NOT NULL,
                            model_info JSONB NOT NULL DEFAULT '{}',
                            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                        )
                    """)
                    
                    # Create indexes for common queries
                    await conn.execute("CREATE INDEX IF NOT EXISTS idx_generated_images_user_id ON generated_images USING GIN ((metadata->>'user_id'))")
                    await conn.execute("CREATE INDEX IF NOT EXISTS idx_generated_images_patient_id ON generated_images USING GIN ((metadata->>'patient_id'))")
                    await conn.execute("CREATE INDEX IF NOT EXISTS idx_generated_images_session_id ON generated_images USING GIN ((metadata->>'session_id'))")
                    await conn.execute("CREATE INDEX IF NOT EXISTS idx_generated_images_created_at ON generated_images (created_at)")
                    
                    # Fixed: Use proper GIN index with tsvector for full-text search
                    await conn.execute("CREATE INDEX IF NOT EXISTS idx_generated_images_prompt_fts ON generated_images USING GIN (to_tsvector('english', prompt))")
                    
                    print("[DB] ✅ generated_images table created successfully")
                else:
                    print("[DB] generated_images table already exists")
                    
        except Exception as e:
            print(f"[ERROR] Failed to create generated_images table: {e}")
            # Don't raise here, let the app continue
    
    async def store_generated_image(self, image: GeneratedImage) -> str:
        """Store generated image and return its ID."""
        pool = await self._get_pool()
        
        async with pool.acquire() as conn:
            try:
                query = """
                INSERT INTO generated_images (
                    generation_id, image_data, image_format, metadata, 
                    created_at, prompt, model_info
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING generation_id
                """
                
                result = await conn.fetchrow(
                    query,
                    image.generation_id,
                    image.image_data,
                    image.image_format,
                    json.dumps(image.metadata),
                    image.created_at,
                    image.prompt,
                    json.dumps(image.model_info)
                )
                
                print(f"[DB] ✅ Stored generated image {image.generation_id}")
                return result['generation_id']
                
            except Exception as e:
                print(f"[ERROR] Failed to store generated image {image.generation_id}: {e}")
                raise
    
    async def get_generated_image(self, image_id: str) -> Optional[GeneratedImage]:
        """Retrieve a generated image by ID."""
        pool = await self._get_pool()
        
        async with pool.acquire() as conn:
            try:
                query = """
                SELECT generation_id, image_data, image_format, metadata,
                       created_at, prompt, model_info
                FROM generated_images 
                WHERE generation_id = $1
                """
                
                row = await conn.fetchrow(query, image_id)
                if not row:
                    return None
                
                return GeneratedImage(
                    generation_id=str(row['generation_id']),  # Convert UUID to string
                    image_data=row['image_data'],
                    image_format=row['image_format'],
                    metadata=json.loads(row['metadata']),
                    created_at=row['created_at'],
                    prompt=row['prompt'],
                    model_info=json.loads(row['model_info'])
                )
                
            except Exception as e:
                print(f"[ERROR] Failed to retrieve generated image {image_id}: {e}")
                return None

    async def get_user_generated_images(
        self, 
        user_id: str, 
        limit: int = 10
    ) -> list[GeneratedImage]:
        """Get generated images for a user."""
        pool = await self._get_pool()
        
        async with pool.acquire() as conn:
            try:
                query = """
                SELECT generation_id, image_data, image_format, metadata,
                       created_at, prompt, model_info
                FROM generated_images 
                WHERE metadata->>'user_id' = $1
                ORDER BY created_at DESC
                LIMIT $2
                """
                
                rows = await conn.fetch(query, user_id, limit)
                
                return [
                    GeneratedImage(
                        generation_id=str(row['generation_id']),  # Convert UUID to string
                        image_data=row['image_data'],
                        image_format=row['image_format'],
                        metadata=json.loads(row['metadata']),
                        created_at=row['created_at'],
                        prompt=row['prompt'],
                        model_info=json.loads(row['model_info'])
                    )
                    for row in rows
                ]
                
            except Exception as e:
                print(f"[ERROR] Failed to retrieve generated images for user {user_id}: {e}")
                return []

    async def search_generated_images_by_prompt(
        self, 
        search_query: str, 
        user_id: Optional[str] = None,
        limit: int = 10
    ) -> list[GeneratedImage]:
        """Search generated images by prompt text using full-text search."""
        pool = await self._get_pool()
        
        async with pool.acquire() as conn:
            try:
                base_query = """
                SELECT generation_id, image_data, image_format, metadata,
                       created_at, prompt, model_info,
                       ts_rank(to_tsvector('english', prompt), plainto_tsquery('english', $1)) as rank
                FROM generated_images 
                WHERE to_tsvector('english', prompt) @@ plainto_tsquery('english', $1)
                """
                
                params: list[Any] = [search_query]
                
                if user_id:
                    base_query += " AND metadata->>'user_id' = $2"
                    params.append(user_id)
                    base_query += " ORDER BY rank DESC, created_at DESC LIMIT $3"
                    params.append(limit)
                else:
                    base_query += " ORDER BY rank DESC, created_at DESC LIMIT $2"
                    params.append(limit)
                
                rows = await conn.fetch(base_query, *params)
                
                return [
                    GeneratedImage(
                        generation_id=str(row['generation_id']),  # Convert UUID to string
                        image_data=row['image_data'],
                        image_format=row['image_format'],
                        metadata=json.loads(row['metadata']),
                        created_at=row['created_at'],
                        prompt=row['prompt'],
                        model_info=json.loads(row['model_info'])
                    )
                    for row in rows
                ]
                
            except Exception as e:
                print(f"[ERROR] Failed to search generated images: {e}")
                return []
    
    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()