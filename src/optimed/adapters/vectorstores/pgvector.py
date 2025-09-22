import asyncpg # type: ignore
from pgvector.asyncpg import register_vector # type: ignore
from typing import Sequence, Any, Dict, Optional
from optimed.core.ports import VectorStore
from optimed.core.domain import ChatSession, SessionParticipant
from datetime import datetime, timezone
import uuid
import json
import os
import faiss
import numpy as np
from optimed.adapters.kms.crypto_service import EnvelopeEncryption, EphemeralCacheService, KMSConfig

class PGVectorAdapter(VectorStore):
    def __init__(self, dsn: str, min_size: int = 10, max_size: int = 20, embedding_dim: int = 1024):
        """Initialize the PGVectorAdapter with GDPR-compliant RAM-only embeddings."""
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self._pool = None
        
        # GDPR compliance features
        self.embedding_dim = embedding_dim
        self.persist_phi = os.getenv("PERSIST_PHI", "false").lower() == "true"
        self.ephemeral_cache_enabled = os.getenv("EPHEMERAL_CACHE_ENABLED", "false").lower() == "true"
        
        # RAM-only vector storage (session-scoped)
        self._ram_stores: Dict[str, Dict] = {}  # session_id -> {index, id_map, metadata_map}
        
        # KMS for ephemeral cache
        if self.ephemeral_cache_enabled:
            kms_config = KMSConfig(kek_id="optimed-kek")
            self.envelope_encryption = EnvelopeEncryption(kms_config)
            # Initialize ephemeral cache after pool is created
            self.ephemeral_cache: Optional[EphemeralCacheService] = None
        else:
            self.envelope_encryption: Optional[EnvelopeEncryption] = None
            self.ephemeral_cache: Optional[EphemeralCacheService] = None

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
            
            # Initialize ephemeral cache after pool is created
            if self.ephemeral_cache_enabled and self.envelope_encryption and self.ephemeral_cache is None:
                self.ephemeral_cache = EphemeralCacheService(self.envelope_encryption, self._pool)
                
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
        """GDPR-compliant upsert: stores embeddings in RAM only, metadata in DB."""
        metadata = metadata or {}
        
        # Extract session_id from metadata for RAM storage
        session_id = metadata.get("session_id")
        if not session_id:
            # Generate a default session if none provided (for backward compatibility)
            session_id = "default_session"
            metadata["session_id"] = session_id
        
        # Ensure RAM store exists for this session
        if session_id not in self._ram_stores:
            self._ram_stores[session_id] = {
                "index": faiss.IndexFlatIP(self.embedding_dim),
                "id_map": {},  # external_id -> internal_id
                "metadata_map": {},  # internal_id -> metadata
                "content_map": {},  # internal_id -> content
                "next_internal_id": 0
            }
        
        ram_store = self._ram_stores[session_id]
        
        # Add to FAISS index
        vec = np.array(embedding).astype('float32').reshape(1, -1)
        if vec.shape[1] != self.embedding_dim:
            raise ValueError(f"Embedding dimension mismatch: expected {self.embedding_dim}, got {vec.shape[1]}")
        
        # Get or create internal ID
        if embedding_id not in ram_store["id_map"]:
            internal_id = ram_store["next_internal_id"]
            ram_store["next_internal_id"] += 1
            ram_store["id_map"][embedding_id] = internal_id
        else:
            internal_id = ram_store["id_map"][embedding_id]
        
        # Add to FAISS index (replace if exists)
        if internal_id < ram_store["index"].ntotal:
            # Update existing vector
            ram_store["index"].reconstruct(internal_id, vec[0])
        else:
            # Add new vector
            ram_store["index"].add(vec)
        
        # Store metadata and content in RAM
        ram_store["metadata_map"][internal_id] = {**metadata, "object_type": object_type, "object_id": object_id}
        ram_store["content_map"][internal_id] = content
        
        # Optional: Store in ephemeral cache if enabled
        if self.ephemeral_cache_enabled and self.ephemeral_cache:
            await self._store_in_ephemeral_cache(session_id, object_type, object_id, content)
        
        # Store metadata only in database (no PHI) - only if persist_phi is enabled
        if self.persist_phi:
            await self._store_legacy_embedding(embedding_id, object_type, object_id, content, embedding, metadata)
        else:
            await self._store_metadata_only(embedding_id, object_type, object_id, metadata)
        
        return embedding_id
    
    async def _store_in_ephemeral_cache(self, session_id: str, object_type: str, object_id: str, content: str | dict):
        """Store content in ephemeral cache with crypto-shredding."""
        if not self.ephemeral_cache:
            return
        try:
            # Use the ephemeral cache service to store content
            await self.ephemeral_cache.store_content(
                session_id=session_id,
                resource_type=object_type,
                resource_id=object_id,
                content=json.dumps(content) if isinstance(content, dict) else content
            )
            
        except Exception as e:
            print(f"Warning: Failed to store in ephemeral cache: {e}")
    
    async def _store_metadata_only(self, embedding_id: str, object_type: str, object_id: str, metadata: dict):
        """Store only metadata in database, no PHI content."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                # Store in resources table (metadata only)
                await conn.execute("""
                    INSERT INTO resources (server_alias, resource_type, resource_id, last_updated)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (server_alias, resource_type, resource_id) DO NOTHING
                """, "local", object_type, object_id, datetime.now(timezone.utc))
        except Exception as e:
            print(f"Warning: Failed to store metadata: {e}")
    
    async def _store_legacy_embedding(self, embedding_id: str, object_type: str, object_id: str, content: str | dict, embedding: Sequence[float], metadata: dict):
        """Store in legacy embeddings table (for backward compatibility when persist_phi=true)."""
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
    
    async def similarity_search(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        filter_: dict[str, str] | None = None,
    ) -> Sequence[tuple[str, float, str]]:
        """GDPR-compliant similarity search using RAM-only storage."""
        filter_ = filter_ or {}
        
        # Get session_id from filter for RAM search
        session_id = filter_.get("session_id", "default_session")
        
        # Search in RAM store if available
        if session_id in self._ram_stores:
            return self._search_ram_store(session_id, embedding, top_k, filter_)
        
        # Fallback to database search if persist_phi is enabled
        if self.persist_phi:
            return await self._search_database(embedding, top_k, filter_)
        
        # No data available (GDPR mode, no RAM store for this session)
        return []
    
    def _search_ram_store(self, session_id: str, embedding: Sequence[float], top_k: int, filter_: dict) -> Sequence[tuple[str, float, str]]:
        """Search in RAM-only FAISS store."""
        ram_store = self._ram_stores[session_id]
        
        if ram_store["index"].ntotal == 0:
            return []
        
        # Convert query to numpy array
        query_vec = np.array(embedding).astype('float32').reshape(1, -1)
        if query_vec.shape[1] != self.embedding_dim:
            raise ValueError(f"Query embedding dimension mismatch: expected {self.embedding_dim}, got {query_vec.shape[1]}")
        
        # Search FAISS index
        distances, internal_ids = ram_store["index"].search(query_vec, min(top_k, ram_store["index"].ntotal))
        
        results = []
        for dist, internal_id in zip(distances[0], internal_ids[0]):
            if internal_id == -1:  # No more results
                continue
            
            # Get external ID
            external_id = next((k for k, v in ram_store["id_map"].items() if v == internal_id), None)
            if external_id is None:
                continue
            
            # Get metadata and content
            metadata = ram_store["metadata_map"].get(internal_id, {})
            content = ram_store["content_map"].get(internal_id, "")
            
            # Apply filter if present
            if filter_:
                if not all(metadata.get(k) == v for k, v in filter_.items() if k != "session_id"):
                    continue
            
            # Convert distance to similarity (1 - distance for inner product)
            similarity = float(1 - dist)
            results.append((external_id, similarity, content))
        
        # Sort by similarity in descending order
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]
    
    async def _search_database(self, embedding: Sequence[float], top_k: int, filter_: dict) -> Sequence[tuple[str, float, str]]:
        """Fallback database search when persist_phi is enabled."""
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
                SELECT id,
                       embedding <=> $1 AS distance,
                       1 - (embedding <=> $1) AS similarity,
                       content
                FROM embeddings
                {where_sql}
                ORDER BY distance
                LIMIT {top_k}
                """,
                *values
            )
            # Return (id, similarity, content) for clearer semantics upstream
            return [(row['id'], float(row['similarity']), row['content']) for row in rows]

    async def delete(self, embedding_ids: Sequence[str]) -> None:
        """Delete embeddings from RAM stores and optionally from database."""
        # Delete from all RAM stores
        for session_id, ram_store in self._ram_stores.items():
            for embedding_id in embedding_ids:
                if embedding_id in ram_store["id_map"]:
                    internal_id = ram_store["id_map"][embedding_id]
                    del ram_store["id_map"][embedding_id]
                    ram_store["metadata_map"].pop(internal_id, None)
                    ram_store["content_map"].pop(internal_id, None)
        
        # Delete from database if persist_phi is enabled
        if self.persist_phi:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM embeddings WHERE id = ANY($1)",
                    embedding_ids
                )
    
    async def clear_session(self, session_id: str) -> None:
        """Clear all data for a specific session (GDPR compliance)."""
        if session_id in self._ram_stores:
            # Clear RAM store
            del self._ram_stores[session_id]
            
            # Clear ephemeral cache if enabled
            if self.ephemeral_cache_enabled and self.ephemeral_cache:
                await self._clear_ephemeral_cache(session_id)
    
    async def _clear_ephemeral_cache(self, session_id: str) -> None:
        """Clear ephemeral cache for a session and delete DEKs."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                # Get all entries for this session
                rows = await conn.fetch(
                    "SELECT resource_type, resource_id FROM temp_content WHERE session_id = $1",
                    uuid.UUID(session_id)
                )
                
                # Delete content from ephemeral cache
                if self.ephemeral_cache:
                    for row in rows:
                        await self.ephemeral_cache.delete_content(
                            session_id=session_id,
                            resource_type=row["resource_type"],
                            resource_id=row["resource_id"]
                        )
                
                # Delete from temp_content table
                await conn.execute(
                    "DELETE FROM temp_content WHERE session_id = $1",
                    uuid.UUID(session_id)
                )
        except Exception as e:
            print(f"Warning: Failed to clear ephemeral cache for session {session_id}: {e}")
    
    def get_session_memory_usage(self, session_id: str) -> dict:
        """Get memory usage statistics for a session."""
        if session_id not in self._ram_stores:
            return {"vectors": 0, "metadata_entries": 0, "content_entries": 0, "memory_mb": 0}
        
        ram_store = self._ram_stores[session_id]
        vectors = ram_store["index"].ntotal
        metadata_entries = len(ram_store["metadata_map"])
        content_entries = len(ram_store["content_map"])
        
        # Estimate memory usage (rough calculation)
        memory_mb = (vectors * self.embedding_dim * 4) / (1024 * 1024)  # 4 bytes per float32
        
        return {
            "vectors": vectors,
            "metadata_entries": metadata_entries,
            "content_entries": content_entries,
            "memory_mb": round(memory_mb, 2)
        }

    async def get_chat_history(self, patient_id: str, session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """GDPR-compliant chat history: returns empty list to prevent PHI storage."""
        # GDPR Compliance: Chat history with PHI must not be stored or retrieved
        # This prevents any PHI from being persisted in the database
        print(f"[GDPR] Chat history access blocked for patient_id={patient_id}, session_id={session_id}")
        
        # Return empty list to maintain API compatibility
        return []

    async def clear_chat_history(self, patient_id: str) -> None:
        """GDPR-compliant: No chat history to clear since it's not stored."""
        # GDPR Compliance: Chat history with PHI is not stored, so nothing to clear
        print(f"[GDPR] Chat history clear requested for patient_id={patient_id} - no action needed (not stored)")

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
    
    async def store_dicom_embedding(
        self,
        image_id: str,
        embedding: Sequence[float],
        metadata: dict[str, Any]
    ) -> str:
        """Store DICOM image embedding."""
            
        embedding_id = f"dicom_{image_id}_{uuid.uuid4()}"
        
        if self._pool is None:
            self._pool = await self._get_pool()

        if self._pool is None:
            raise RuntimeError("Connection pool is not initialized")

        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO embeddings (id, embedding, metadata, created_at)
                VALUES ($1, $2, $3, $4)
            """, embedding_id, embedding, json.dumps(metadata), datetime.now(timezone.utc))
        
        return embedding_id
    
    async def search_similar_dicom(
        self,
        query_embedding: Sequence[float],
        limit: int = 5,
        similarity_threshold: float = 0.7
    ) -> list[dict[str, Any]]:
        """Search for similar DICOM images by embedding."""
        
        if self._pool is None:
            self._pool = await self._get_pool()

        if self._pool is None:
            return []

        async with self._pool.acquire() as conn:
            results = await conn.fetch("""
                SELECT id, metadata, 1 - (embedding <=> $1) as similarity
                FROM embeddings 
                WHERE metadata->>'type' = 'dicom'
                AND 1 - (embedding <=> $1) > $2
                ORDER BY embedding <=> $1
                LIMIT $3
            """, query_embedding, similarity_threshold, limit)
            
            return [
                {
                    'embedding_id': row['id'],
                    'metadata': json.loads(row['metadata']),
                    'similarity': float(row['similarity'])
                }
                for row in results
            ]
    
    async def get_sessions_for_patient(
        self, 
        patient_id: str | None = None,
        limit: int = 50,
        include_general: bool = False
    ) -> list[ChatSession]:
        """Get all chat sessions for a patient (regardless of user)."""
        
        # Build query conditions
        where_conditions = ["metadata->>'namespace' = 'session_info'"]
        params: list[Any] = []
        
        if patient_id:
            where_conditions.append(f"metadata->>'patient_id' = ${len(params) + 1}")
            params.append(patient_id)
        elif not include_general:
            where_conditions.append("metadata->>'patient_id' != 'general_chat'")
        
        where_clause = " AND ".join(where_conditions)
        
        query = f"""
            SELECT content, metadata, created_at
            FROM embeddings 
            WHERE {where_clause}
            ORDER BY (metadata->>'last_message_at')::bigint DESC
            LIMIT {limit}
        """
        
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        
        return self._parse_session_rows(rows)
    
    async def get_user_sessions_for_patient(
        self, 
        user_id: str, 
        patient_id: str | None = None,
        limit: int = 50
    ) -> list[ChatSession]:
        """Get sessions where user has participated for a specific patient."""
        
        # Build query conditions - user must be creator OR participant
        where_conditions = [
            "metadata->>'namespace' = 'session_info'",
            "(metadata->>'created_by_user_id' = $1 OR content::jsonb->'participants' ? $1)"
        ]
        params = [user_id]
        
        if patient_id:
            where_conditions.append(f"metadata->>'patient_id' = ${len(params) + 1}")
            params.append(patient_id)
        else:
            where_conditions.append("metadata->>'patient_id' = 'general_chat'")
        
        where_clause = " AND ".join(where_conditions)
        
        query = f"""
            SELECT content, metadata, created_at
            FROM embeddings 
            WHERE {where_clause}
            ORDER BY (metadata->>'last_message_at')::bigint DESC
            LIMIT {limit}
        """
        
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        
        return self._parse_session_rows(rows)
    
    async def add_user_to_session(
        self,
        session_id: str,
        user_id: str
    ) -> bool:
        """Add a user as a participant to an existing session."""
        
        
        # First check if user is already a participant
        check_query = """
            SELECT content::jsonb->'participants' ? $2 as is_participant
            FROM embeddings 
            WHERE metadata->>'namespace' = 'session_info' 
            AND metadata->>'session_id' = $1
        """
        
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            check_result = await conn.fetchval(check_query, session_id, user_id)
            
            if check_result:  # User is already a participant
                return False
            
            # Add user to participants array
            update_query = """
                UPDATE embeddings 
                SET 
                    content = jsonb_set(
                        content::jsonb, 
                        '{participants}', 
                        COALESCE(content::jsonb->'participants', '[]'::jsonb) || to_jsonb($2::text)
                    ),
                    metadata = jsonb_set(
                        metadata::jsonb, 
                        '{last_participant_id}', 
                        to_jsonb($3::text)
                    )
                WHERE metadata->>'namespace' = 'session_info' 
                AND metadata->>'session_id' = $1
            """
            
            result = await conn.execute(update_query, session_id, user_id, user_id)
            return result != "UPDATE 0"
    
    async def get_session_participants(
        self,
        session_id: str
    ) -> list[SessionParticipant]:
        """Get all participants of a session."""
        
        # Get session info first
        session_query = """
            SELECT content, metadata
            FROM embeddings 
            WHERE metadata->>'namespace' = 'session_info'
            AND metadata->>'session_id' = $1
            LIMIT 1
        """
        
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            session_row = await conn.fetchrow(session_query, session_id)
        
        if not session_row:
            return []
        
        try:
            content_data = json.loads(session_row["content"]) if isinstance(session_row["content"], str) else session_row["content"]
            participants_ids = content_data.get("participants", [])
            
            # Get participation details from chat history
            participants = []
            for user_id in participants_ids:
                # Get user's first and last message in this session
                participation_query = """
                    SELECT 
                        MIN((metadata->>'timestamp')::bigint) as first_message,
                        MAX((metadata->>'timestamp')::bigint) as last_message,
                        COUNT(*) as message_count
                    FROM embeddings 
                    WHERE metadata->>'namespace' = 'chat_history'
                    AND metadata->>'session_id' = $1
                    AND metadata->>'user_id' = $2
                """
                
                async with pool.acquire() as conn:
                    participation_row = await conn.fetchrow(participation_query, session_id, user_id)
                
                if participation_row and participation_row["message_count"] > 0:
                    participants.append(SessionParticipant(
                        user_id=user_id,
                        session_id=session_id,
                        first_joined_at=datetime.fromtimestamp(int(participation_row["first_message"]) / 1000),
                        last_active_at=datetime.fromtimestamp(int(participation_row["last_message"]) / 1000),
                        message_count=int(participation_row["message_count"])
                    ))
                    
            return participants
            
        except Exception as e:
            print(f"Error parsing session participants: {e}")
            return []
    
    async def create_chat_session(
        self,
        user_id: str,
        patient_id: str | None,
        mode: str,
        session_title: str | None = None
    ) -> str:
        """Create a new chat session and return session_id."""
        
        session_id = f"{mode}_{patient_id or 'general'}_{user_id}_{int(datetime.now().timestamp() * 1000)}"
        current_timestamp = str(int(datetime.now().timestamp() * 1000))
        
        if not session_title:
            session_title = f"{mode.title()} Session - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        session_data = {
            "session_id": session_id,
            "created_at": current_timestamp,
            "session_title": session_title,
            "message_count": 0,
            "mode": mode,
            "is_active": True,
            "participants": [user_id]  # Creator is first participant
        }
        
        # Store session info in vector store using upsert
        await self.upsert(
            embedding_id=f"session_{session_id}",
            embedding=[0.0] * 1024,  # Use correct dimensions for your database
            object_type="session_info",
            object_id=session_id,
            content=session_data,
            metadata={
                "namespace": "session_info",
                "session_id": session_id,
                "created_by_user_id": user_id,
                "patient_id": patient_id or "general_chat",
                "created_at": current_timestamp,
                "last_message_at": current_timestamp,
                "last_participant_id": user_id,
                "mode": mode
            }
        )
        
        return session_id
    
    async def update_session_activity(
        self,
        session_id: str,
        user_id: str,
        message_count_increment: int = 1
    ) -> None:
        """Update session's last activity and user participation."""
        
        current_timestamp = str(int(datetime.now().timestamp() * 1000))
        
        # First, ensure user is in participants list
        await self.add_user_to_session(session_id, user_id)
        
        # Then update session activity
        query = """
            UPDATE embeddings 
            SET 
                content = jsonb_set(
                    jsonb_set(content::jsonb, '{message_count}', 
                        to_jsonb(((content->>'message_count')::int + $2)::text)),
                    '{last_message_at}', to_jsonb($3::text)
                ),
                metadata = jsonb_set(
                    jsonb_set(metadata::jsonb, '{last_message_at}', to_jsonb($3::text)),
                    '{last_participant_id}', to_jsonb($4::text)
                )
            WHERE metadata->>'namespace' = 'session_info' 
            AND metadata->>'session_id' = $1
        """
        
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(query, session_id, message_count_increment, current_timestamp, user_id)
    

    async def get_session_info(self, session_id: str) -> ChatSession | None:
        """Get session information by session_id."""
        
        query = """
            SELECT content, metadata
            FROM embeddings 
            WHERE metadata->>'namespace' = 'session_info'
            AND metadata->>'session_id' = $1
            LIMIT 1
        """
        
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, session_id)
        
        if not row:
            return None
            
        try:
            content_data = json.loads(row["content"]) if isinstance(row["content"], str) else row["content"]
            metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
            
            return ChatSession(
                session_id=session_id,
                patient_id=metadata.get("patient_id") if metadata.get("patient_id") != "general_chat" else None,
                created_by_user_id=metadata.get("created_by_user_id"),
                participants=content_data.get("participants", []),
                created_at=datetime.fromtimestamp(int(content_data.get("created_at", 0)) / 1000),
                last_message_at=datetime.fromtimestamp(int(metadata.get("last_message_at", 0)) / 1000),
                session_title=content_data.get("session_title", "Untitled Session"),
                message_count=int(content_data.get("message_count", 0)),
                mode=content_data.get("mode", "chat"),
                is_active=content_data.get("is_active", True),
                last_participant_id=metadata.get("last_participant_id")
            )
        except Exception as e:
            print(f"Error parsing session info: {e}")
            return None
    
    async def get_session_messages(
        self,
        session_id: str,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get all messages for a specific session."""
        
        query = """
            SELECT content, metadata
            FROM embeddings 
            WHERE metadata->>'namespace' = 'chat_history'
            AND metadata->>'session_id' = $1
            ORDER BY 
                CASE WHEN metadata->>'timestamp' ~ '^[0-9]+$' 
                    THEN (metadata->>'timestamp')::bigint 
                    ELSE 0 
                END ASC
            LIMIT $2
        """
        
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, session_id, limit)
        
        result = []
        for row in rows:
            try:
                raw_content = row["content"]
                metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
                
                if isinstance(raw_content, str):
                    try:
                        content_data = json.loads(raw_content)
                    except json.JSONDecodeError:
                        content_data = {"content": raw_content, "role": "user"}
                else:
                    content_data = raw_content
                
                message_content = content_data.get("content", "")
                message_role = content_data.get("role", "user")
                
                # Fix timestamp handling
                timestamp_value = metadata.get("timestamp")
                if timestamp_value:
                    try:
                        # If it's a string of digits (milliseconds), convert it
                        if isinstance(timestamp_value, str) and timestamp_value.isdigit():
                            timestamp_ms = int(timestamp_value)
                            timestamp_iso = datetime.fromtimestamp(timestamp_ms / 1000).isoformat()
                        # If it's already a proper timestamp format, use it
                        elif isinstance(timestamp_value, str):
                            timestamp_iso = timestamp_value
                        else:
                            timestamp_iso = str(timestamp_value)
                    except Exception:
                        timestamp_iso = datetime.now().isoformat()
                else:
                    timestamp_iso = datetime.now().isoformat()
                
                result.append({
                    "content": message_content,
                    "role": message_role,
                    "timestamp": timestamp_iso,
                    "metadata": metadata
                })
                
            except Exception as e:
                print(f"Error parsing message row: {e}")
                continue
        
        return result
    

    def _parse_session_rows(self, rows) -> list[ChatSession]:
        """Helper method to parse session rows into ChatSession objects."""
        sessions = []
        for row in rows:
            try:
                content_data = json.loads(row["content"]) if isinstance(row["content"], str) else row["content"]
                metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
                
                session = ChatSession(
                    session_id=content_data.get("session_id"),
                    patient_id=metadata.get("patient_id") if metadata.get("patient_id") != "general_chat" else None,
                    created_by_user_id=metadata.get("created_by_user_id"),
                    participants=content_data.get("participants", []),
                    created_at=datetime.fromtimestamp(int(content_data.get("created_at", 0)) / 1000),
                    last_message_at=datetime.fromtimestamp(int(metadata.get("last_message_at", 0)) / 1000),
                    session_title=content_data.get("session_title", "Untitled Session"),
                    message_count=int(content_data.get("message_count", 0)),
                    mode=content_data.get("mode", "chat"),
                    is_active=content_data.get("is_active", True),
                    last_participant_id=metadata.get("last_participant_id")
                )
                sessions.append(session)
            except Exception as e:
                print(f"Error parsing session row: {e}")
                continue
                
        return sessions
    

        

        