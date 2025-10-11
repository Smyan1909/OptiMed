from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Optional, Sequence

import asyncpg

from optimed.core.domain import UserEHRConnection
from optimed.core.ports import UserEHRConnectionRepository
from optimed.core.logging_utils import get_logger, log_error
from optimed.adapters.security.database_encryption import get_database_encryption

logger = get_logger(__name__)

class PGUserEHRConnectionRepository(UserEHRConnectionRepository):
    """PostgreSQL implementation of UserEHRConnectionRepository."""
    
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None
        self._tables_created = False
        self._db_encryption = get_database_encryption()
    
    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create connection pool."""
        if self._pool is None:
            # Create pool without init function to avoid the recursive issue
            self._pool = await asyncpg.create_pool(self._dsn)
            
            # Create tables once after pool is created
            if not self._tables_created:
                await self._ensure_tables_once()
                self._tables_created = True
                
        return self._pool
    
    async def _ensure_tables_once(self):
        """Create tables once, safely."""
        if self._pool is None:
            return
            
        async with self._pool.acquire() as conn:
            try:
                # Check if tables exist first
                tables_exist = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'ehr_login_sessions'
                    )
                """)
                
                if not tables_exist:
                    # Create temporary EHR login sessions table
                    await conn.execute("""
                        CREATE TABLE ehr_login_sessions (
                            session_id VARCHAR(255) PRIMARY KEY,
                            connection_id VARCHAR(255) UNIQUE NOT NULL,
                            fhir_server_url TEXT NOT NULL,
                            client_id VARCHAR(255) NOT NULL,
                            scope TEXT NOT NULL,
                            state VARCHAR(255) NOT NULL,
                            redirect_uri TEXT NOT NULL,
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                            expires_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '1 hour')
                        )
                    """)
                
                # Check if user_ehr_connections table exists
                connections_exist = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'user_ehr_connections'
                    )
                """)
                
                if not connections_exist:
                    # Create user_ehr_connections table
                    await conn.execute("""
                        CREATE TABLE user_ehr_connections (
                            connection_id VARCHAR(255) PRIMARY KEY,
                            user_id VARCHAR(255) NOT NULL,
                            provider_type VARCHAR(100) NOT NULL,
                            fhir_server_url TEXT NOT NULL,
                            client_id VARCHAR(255) NOT NULL,
                            credentials JSONB DEFAULT '{}',
                            access_token TEXT,
                            refresh_token TEXT,
                            token_expires_at TIMESTAMP WITH TIME ZONE,
                            scope TEXT,
                            -- patient_context removed for GDPR compliance
                            is_active BOOLEAN DEFAULT TRUE,
                            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                            expires_at TIMESTAMP WITH TIME ZONE
                        )
                    """)
                
                # Create indexes if they don't exist
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_ehr_connections_user_id ON user_ehr_connections(user_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_ehr_connections_provider_type ON user_ehr_connections(provider_type)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_ehr_connections_active ON user_ehr_connections(is_active)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_ehr_login_sessions_expires ON ehr_login_sessions(expires_at)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_ehr_login_sessions_connection ON ehr_login_sessions(connection_id)")
                
            except Exception as e:
                log_error(logger, "Error creating tables", e)
                # Continue anyway - tables might already exist
                pass
    
    async def create_ehr_login_session(self, session_data: dict) -> str:
        """Create a temporary EHR login session."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            session_id = session_data["session_id"]
            await conn.execute("""
                INSERT INTO ehr_login_sessions (
                    session_id, connection_id, fhir_server_url, client_id,
                    scope, state, redirect_uri, created_at, expires_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """, 
                session_id,
                session_data["connection_id"],
                session_data["fhir_server_url"],
                session_data["client_id"],
                session_data["scope"],
                session_data["state"],
                session_data["redirect_uri"],
                session_data["created_at"],
                session_data["expires_at"]
            )
            return session_id
    
    async def get_ehr_login_session(self, connection_id: str) -> Optional[dict]:
        """Get EHR login session by connection ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT session_id, connection_id, fhir_server_url, client_id,
                       scope, state, redirect_uri, created_at, expires_at
                FROM ehr_login_sessions 
                WHERE connection_id = $1 AND expires_at > NOW()
            """, connection_id)
            
            if not row:
                return None
            
            return {
                "session_id": row["session_id"],
                "connection_id": row["connection_id"],
                "fhir_server_url": row["fhir_server_url"],
                "client_id": row["client_id"],
                "scope": row["scope"],
                "state": row["state"],
                "redirect_uri": row["redirect_uri"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"]
            }
    
    async def delete_ehr_login_session(self, connection_id: str) -> bool:
        """Delete EHR login session."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM ehr_login_sessions WHERE connection_id = $1
            """, connection_id)
            return result == "DELETE 1"
    
    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired EHR login sessions."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM ehr_login_sessions WHERE expires_at <= NOW()
            """)
            return int(result.split()[-1]) if result else 0
    
    async def create_connection(self, connection: UserEHRConnection) -> UserEHRConnection:
        """Create a new EHR connection with encrypted tokens and hashed user_id."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Encrypt sensitive fields
            access_enc, refresh_enc, creds_enc = await self._db_encryption.encrypt_connection_tokens(
                conn,
                connection.access_token,
                connection.refresh_token,
                json.dumps(connection.credentials) if connection.credentials else None
            )

            # Hash user_id for GDPR compliance
            user_id_hash = self._db_encryption.hash_value(connection.user_id)

            await conn.execute("""
                INSERT INTO user_ehr_connections (
                    connection_id, user_id, user_id_hash, provider_type, fhir_server_url, client_id,
                    credentials, credentials_encrypted,
                    access_token, access_token_encrypted,
                    refresh_token, refresh_token_encrypted,
                    token_expires_at, scope, is_active,
                    created_at, updated_at, expires_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
            """,
                connection.connection_id, connection.user_id, user_id_hash, connection.provider_type,
                connection.fhir_server_url, connection.client_id,
                '{}', creds_enc,  # Store empty object, encrypted in separate column
                '[ENCRYPTED]', access_enc,  # Placeholder, encrypted in separate column
                '[ENCRYPTED]', refresh_enc,  # Placeholder, encrypted in separate column
                connection.token_expires_at, connection.scope, connection.is_active,
                connection.created_at, connection.updated_at, connection.expires_at
            )
            return connection
    
    async def get_connection_by_id(self, connection_id: str) -> Optional[UserEHRConnection]:
        """Get connection by ID and decrypt tokens."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT connection_id, user_id, provider_type, fhir_server_url, client_id,
                       credentials, credentials_encrypted,
                       access_token, access_token_encrypted,
                       refresh_token, refresh_token_encrypted,
                       token_expires_at, scope, patient_context,
                       is_active, created_at, updated_at, expires_at
                FROM user_ehr_connections
                WHERE connection_id = $1
            """, connection_id)

            if not row:
                return None

            # Decrypt tokens
            access_token, refresh_token, creds_json = await self._db_encryption.decrypt_connection_tokens(
                conn,
                row["access_token_encrypted"],
                row["refresh_token_encrypted"],
                row["credentials_encrypted"]
            )

            # Fallback to plaintext if encrypted columns are NULL (backward compatibility)
            if not access_token and row["access_token"] and row["access_token"] != '[ENCRYPTED]':
                access_token = row["access_token"]
            if not refresh_token and row["refresh_token"] and row["refresh_token"] != '[ENCRYPTED]':
                refresh_token = row["refresh_token"]
            if not creds_json and row["credentials"]:
                creds_json = row["credentials"]

            return UserEHRConnection(
                connection_id=row["connection_id"],
                user_id=row["user_id"],
                provider_type=row["provider_type"],
                fhir_server_url=row["fhir_server_url"],
                client_id=row["client_id"],
                credentials=json.loads(creds_json) if creds_json else {},
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=row["token_expires_at"],
                scope=row["scope"],
                patient_context=row["patient_context"],
                is_active=row["is_active"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                expires_at=row["expires_at"]
            )
    
    async def get_connections_by_user(self, user_id: str, provider_type: Optional[str] = None) -> Sequence[UserEHRConnection]:
        """Get all connections for a user with decryption, optionally filtered by provider type."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if provider_type:
                rows = await conn.fetch("""
                    SELECT connection_id, user_id, provider_type, fhir_server_url, client_id,
                           credentials, credentials_encrypted,
                           access_token, access_token_encrypted,
                           refresh_token, refresh_token_encrypted,
                           token_expires_at, scope, patient_context,
                           is_active, created_at, updated_at, expires_at
                    FROM user_ehr_connections
                    WHERE user_id = $1 AND provider_type = $2
                    ORDER BY created_at DESC
                """, user_id, provider_type)
            else:
                rows = await conn.fetch("""
                    SELECT connection_id, user_id, provider_type, fhir_server_url, client_id,
                           credentials, credentials_encrypted,
                           access_token, access_token_encrypted,
                           refresh_token, refresh_token_encrypted,
                           token_expires_at, scope, patient_context,
                           is_active, created_at, updated_at, expires_at
                    FROM user_ehr_connections
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                """, user_id)

            connections = []
            for row in rows:
                # Decrypt tokens for this connection
                access_token, refresh_token, creds_json = await self._db_encryption.decrypt_connection_tokens(
                    conn,
                    row["access_token_encrypted"],
                    row["refresh_token_encrypted"],
                    row["credentials_encrypted"]
                )

                # Fallback to plaintext if encrypted columns are NULL (backward compatibility)
                if not access_token and row["access_token"] and row["access_token"] != '[ENCRYPTED]':
                    access_token = row["access_token"]
                if not refresh_token and row["refresh_token"] and row["refresh_token"] != '[ENCRYPTED]':
                    refresh_token = row["refresh_token"]
                if not creds_json and row["credentials"]:
                    creds_json = row["credentials"]

                connections.append(UserEHRConnection(
                    connection_id=row["connection_id"],
                    user_id=row["user_id"],
                    provider_type=row["provider_type"],
                    fhir_server_url=row["fhir_server_url"],
                    client_id=row["client_id"],
                    credentials=json.loads(creds_json) if creds_json else {},
                    access_token=access_token,
                    refresh_token=refresh_token,
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
        """Update an existing connection with encryption and hashed user_id."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Encrypt sensitive fields
            access_enc, refresh_enc, creds_enc = await self._db_encryption.encrypt_connection_tokens(
                conn,
                connection.access_token,
                connection.refresh_token,
                json.dumps(connection.credentials) if connection.credentials else None
            )

            # Hash user_id for GDPR compliance
            user_id_hash = self._db_encryption.hash_value(connection.user_id)

            await conn.execute("""
                UPDATE user_ehr_connections SET
                    user_id = $2, user_id_hash = $3, provider_type = $4, fhir_server_url = $5, client_id = $6,
                    credentials = $7, credentials_encrypted = $8,
                    access_token = $9, access_token_encrypted = $10,
                    refresh_token = $11, refresh_token_encrypted = $12,
                    token_expires_at = $13, scope = $14, patient_context = $15,
                    is_active = $16, updated_at = $17, expires_at = $18
                WHERE connection_id = $1
            """,
                connection.connection_id, connection.user_id, user_id_hash, connection.provider_type, connection.fhir_server_url,
                connection.client_id,
                '{}', creds_enc,  # Store empty object, encrypted in separate column
                '[ENCRYPTED]', access_enc,  # Placeholder, encrypted in separate column
                '[ENCRYPTED]', refresh_enc,  # Placeholder, encrypted in separate column
                connection.token_expires_at, connection.scope, connection.patient_context,
                connection.is_active, datetime.now(timezone.utc), connection.expires_at
            )
            return connection
    
    async def delete_connection(self, connection_id: str) -> bool:
        """Delete a connection."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM user_ehr_connections WHERE connection_id = $1
            """, connection_id)
            
            return result == "DELETE 1"
    
    async def get_active_connection_by_user(self, user_id: str, provider_type: str) -> Optional[UserEHRConnection]:
        """Get the active connection for a user and provider type."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
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