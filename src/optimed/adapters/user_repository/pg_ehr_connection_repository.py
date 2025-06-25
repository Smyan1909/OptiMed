from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Optional, Sequence

import asyncpg

from optimed.core.domain import UserEHRConnection
from optimed.core.ports import UserEHRConnectionRepository

class PGUserEHRConnectionRepository(UserEHRConnectionRepository):
    """PostgreSQL implementation of UserEHRConnectionRepository."""
    
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None
    
    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn)
        return self._pool
    
    async def _ensure_tables(self, conn: asyncpg.Connection):
        """Create tables if they don't exist."""
        
        # Create user_ehr_connections table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_ehr_connections (
                connection_id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                provider_type VARCHAR(100) NOT NULL,
                fhir_server_url TEXT NOT NULL,
                client_id VARCHAR(255) NOT NULL,
                credentials JSONB DEFAULT '{}',
                access_token TEXT,
                refresh_token TEXT,
                token_expires_at TIMESTAMP WITH TIME ZONE,
                scope TEXT,
                patient_context VARCHAR(255),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                expires_at TIMESTAMP WITH TIME ZONE
            )
        """)
        
        # Create indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_ehr_connections_user_id ON user_ehr_connections(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_ehr_connections_provider_type ON user_ehr_connections(provider_type)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_ehr_connections_active ON user_ehr_connections(is_active)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_ehr_connections_user_provider ON user_ehr_connections(user_id, provider_type)")
    
    async def create_connection(self, connection: UserEHRConnection) -> UserEHRConnection:
        """Create a new EHR connection."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await self._ensure_tables(conn)
            
            await conn.execute("""
                INSERT INTO user_ehr_connections (
                    connection_id, user_id, provider_type, fhir_server_url, client_id,
                    credentials, access_token, refresh_token, token_expires_at,
                    scope, patient_context, is_active, created_at, updated_at, expires_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            """, 
                connection.connection_id, connection.user_id, connection.provider_type,
                connection.fhir_server_url, connection.client_id,
                json.dumps(connection.credentials), connection.access_token,
                connection.refresh_token, connection.token_expires_at,
                connection.scope, connection.patient_context, connection.is_active,
                connection.created_at, connection.updated_at, connection.expires_at
            )
            return connection
    
    async def get_connection_by_id(self, connection_id: str) -> Optional[UserEHRConnection]:
        """Get connection by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await self._ensure_tables(conn)
            
            row = await conn.fetchrow("""
                SELECT connection_id, user_id, provider_type, fhir_server_url, client_id,
                       credentials, access_token, refresh_token, token_expires_at,
                       scope, patient_context, is_active, created_at, updated_at, expires_at
                FROM user_ehr_connections 
                WHERE connection_id = $1
            """, connection_id)
            
            if not row:
                return None
            
            return UserEHRConnection(
                connection_id=row["connection_id"],
                user_id=row["user_id"],
                provider_type=row["provider_type"],
                fhir_server_url=row["fhir_server_url"],
                client_id=row["client_id"],
                credentials=json.loads(row["credentials"]) if row["credentials"] else {},
                access_token=row["access_token"],
                refresh_token=row["refresh_token"],
                token_expires_at=row["token_expires_at"],
                scope=row["scope"],
                patient_context=row["patient_context"],
                is_active=row["is_active"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                expires_at=row["expires_at"]
            )
    
    async def get_connections_by_user(self, user_id: str, provider_type: Optional[str] = None) -> Sequence[UserEHRConnection]:
        """Get all connections for a user, optionally filtered by provider type."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await self._ensure_tables(conn)
            
            if provider_type:
                rows = await conn.fetch("""
                    SELECT connection_id, user_id, provider_type, fhir_server_url, client_id,
                           credentials, access_token, refresh_token, token_expires_at,
                           scope, patient_context, is_active, created_at, updated_at, expires_at
                    FROM user_ehr_connections 
                    WHERE user_id = $1 AND provider_type = $2
                    ORDER BY created_at DESC
                """, user_id, provider_type)
            else:
                rows = await conn.fetch("""
                    SELECT connection_id, user_id, provider_type, fhir_server_url, client_id,
                           credentials, access_token, refresh_token, token_expires_at,
                           scope, patient_context, is_active, created_at, updated_at, expires_at
                    FROM user_ehr_connections 
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                """, user_id)
            
            connections = []
            for row in rows:
                connections.append(UserEHRConnection(
                    connection_id=row["connection_id"],
                    user_id=row["user_id"],
                    provider_type=row["provider_type"],
                    fhir_server_url=row["fhir_server_url"],
                    client_id=row["client_id"],
                    credentials=json.loads(row["credentials"]) if row["credentials"] else {},
                    access_token=row["access_token"],
                    refresh_token=row["refresh_token"],
                    token_expires_at=row["token_expires_at"],
                    scope=row["scope"],
                    patient_context=row["patient_context"],
                    is_active=row["is_active"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    expires_at=row["expires_at"]
                ))
            
            return connections
    
    async def update_connection(self, connection: UserEHRConnection) -> UserEHRConnection:
        """Update an existing connection."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await self._ensure_tables(conn)
            
            await conn.execute("""
                UPDATE user_ehr_connections SET
                    provider_type = $2, fhir_server_url = $3, client_id = $4,
                    credentials = $5, access_token = $6, refresh_token = $7,
                    token_expires_at = $8, scope = $9, patient_context = $10,
                    is_active = $11, updated_at = $12, expires_at = $13
                WHERE connection_id = $1
            """, 
                connection.connection_id, connection.provider_type, connection.fhir_server_url,
                connection.client_id, json.dumps(connection.credentials), connection.access_token,
                connection.refresh_token, connection.token_expires_at, connection.scope,
                connection.patient_context, connection.is_active, 
                datetime.now(timezone.utc), connection.expires_at
            )
            return connection
    
    async def delete_connection(self, connection_id: str) -> bool:
        """Delete a connection."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await self._ensure_tables(conn)
            
            result = await conn.execute("""
                DELETE FROM user_ehr_connections WHERE connection_id = $1
            """, connection_id)
            
            return result == "DELETE 1"
    
    async def get_active_connection_by_user(self, user_id: str, provider_type: str) -> Optional[UserEHRConnection]:
        """Get the active connection for a user and provider type."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await self._ensure_tables(conn)
            
            row = await conn.fetchrow("""
                SELECT connection_id, user_id, provider_type, fhir_server_url, client_id,
                       credentials, access_token, refresh_token, token_expires_at,
                       scope, patient_context, is_active, created_at, updated_at, expires_at
                FROM user_ehr_connections 
                WHERE user_id = $1 AND provider_type = $2 AND is_active = TRUE
                ORDER BY created_at DESC
                LIMIT 1
            """, user_id, provider_type)
            
            if not row:
                return None
            
            return UserEHRConnection(
                connection_id=row["connection_id"],
                user_id=row["user_id"],
                provider_type=row["provider_type"],
                fhir_server_url=row["fhir_server_url"],
                client_id=row["client_id"],
                credentials=json.loads(row["credentials"]) if row["credentials"] else {},
                access_token=row["access_token"],
                refresh_token=row["refresh_token"],
                token_expires_at=row["token_expires_at"],
                scope=row["scope"],
                patient_context=row["patient_context"],
                is_active=row["is_active"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                expires_at=row["expires_at"]
            )
    
    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()