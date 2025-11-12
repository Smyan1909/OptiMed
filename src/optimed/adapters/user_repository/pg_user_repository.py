from __future__ import annotations
import asyncpg
import json
from typing import Optional, Sequence
from datetime import datetime, timezone, timedelta
from optimed.core.domain import User, UserSession, UserAction, UserRole, UserStatus
from optimed.core.ports import UserRepository
import hashlib
import uuid
from optimed.core.logging_utils import get_logger, log_error
from optimed.adapters.security.database_encryption import get_database_encryption

logger = get_logger(__name__)

class PGUserRepository(UserRepository):

    def __init__(self, dsn: str, min_size: int = 5, max_size: int = 20):
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self._pool: Optional[asyncpg.Pool] = None
        self._db_encryption = get_database_encryption()

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create the connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=self.min_size,
                max_size=self.max_size,
                init=self._init_connection
            )
        return self._pool
    
    async def _init_connection(self, conn: asyncpg.Connection):
        """Initialize database connection with required extensions and schemas."""
        # Ensure tables exist
        await self._ensure_tables(conn)

    async def _ensure_tables(self, conn: asyncpg.Connection):
        """Create tables if they don't exist."""
        
        # Create users table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id VARCHAR(255) PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                first_name VARCHAR(255) NOT NULL,
                last_name VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL,
                status VARCHAR(50) NOT NULL DEFAULT 'active',
                department VARCHAR(255),
                license_number VARCHAR(255),
                phone VARCHAR(50),
                hsa_id VARCHAR(255) UNIQUE,
                siths_metadata JSONB DEFAULT '{}',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        # Create user_sessions table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                login_time TIMESTAMP WITH TIME ZONE NOT NULL,
                last_activity TIMESTAMP WITH TIME ZONE NOT NULL,
                ip_address INET,
                user_agent TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
        
        # Create user_actions table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_actions (
                action_id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                action_type VARCHAR(100) NOT NULL,
                resource_type VARCHAR(100),
                resource_id VARCHAR(255),
                description TEXT NOT NULL,
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_hsa_id ON users(hsa_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON user_sessions(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_active ON user_sessions(is_active)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_user_id ON user_actions(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_type ON user_actions(action_type)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_created_at ON user_actions(created_at)")

    async def get_user_metrics(self, user_id: str, days: int = 30) -> dict:
        """Get GDPR-safe user metrics for analytics."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Calculate date range
            from_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            # Get prompt metrics
            prompt_metrics = await conn.fetch("""
                SELECT 
                    metadata->>'prompt_category' as category,
                    COUNT(*) as count,
                    AVG((metadata->>'prompt_length')::int) as avg_length
                FROM user_actions 
                WHERE user_id = $1 
                AND action_type = 'chat_message'
                AND created_at >= $2
                GROUP BY metadata->>'prompt_category'
            """, user_id, from_date)
            
            # Get response metrics
            response_metrics = await conn.fetch("""
                SELECT 
                    COUNT(*) as total_responses,
                    AVG((metadata->>'response_length')::int) as avg_response_length,
                    COUNT(CASE WHEN (metadata->>'has_web_search')::boolean THEN 1 END) as web_search_count,
                    COUNT(CASE WHEN (metadata->>'has_patient_id')::boolean THEN 1 END) as patient_context_count
                FROM user_actions 
                WHERE user_id = $1 
                AND action_type = 'assistant_response'
                AND created_at >= $2
            """, user_id, from_date)
            
            # Process results
            prompt_categories = {}
            total_prompts = 0
            total_prompt_length = 0
            
            for row in prompt_metrics:
                category = row['category'] or 'General'
                count = row['count']
                avg_length = row['avg_length'] or 0
                
                prompt_categories[category] = {
                    'count': count,
                    'average_length': round(avg_length, 2)
                }
                total_prompts += count
                total_prompt_length += count * avg_length
            
            avg_prompt_length = round(total_prompt_length / total_prompts, 2) if total_prompts > 0 else 0
            
            # Process response metrics
            response_data = response_metrics[0] if response_metrics else None
            if response_data:
                total_responses = response_data['total_responses']
                avg_response_length = round(response_data['avg_response_length'] or 0, 2)
                web_search_count = response_data['web_search_count']
                patient_context_count = response_data['patient_context_count']
            else:
                total_responses = 0
                avg_response_length = 0
                web_search_count = 0
                patient_context_count = 0
            
            return {
                "total_prompts": total_prompts,
                "prompt_categories": prompt_categories,
                "average_prompt_length": avg_prompt_length,
                "total_responses": total_responses,
                "average_response_length": avg_response_length,
                "web_search_usage": web_search_count,
                "patient_context_usage": patient_context_count,
                "days_analyzed": days,
                "analysis_period": {
                    "from": from_date.isoformat(),
                    "to": datetime.now(timezone.utc).isoformat()
                }
            }

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1",
                user_id
            )
            return self._row_to_user(row) if row else None

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE username = $1",
                username
            )
            return self._row_to_user(row) if row else None

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE email = $1",
                email
            )
            return self._row_to_user(row) if row else None

    async def get_user_by_hsa_id(self, hsa_id: str) -> Optional[User]:
        """Get user by HSA ID (for SITHS authentication)."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE hsa_id = $1",
                hsa_id
            )
            return self._row_to_user(row) if row else None
        
    async def create_user(self, user: User) -> User:
        """Create a new user with hashed PII."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Hash PII fields
            email_hash, phone_hash, name_hash = self._db_encryption.hash_user_pii(
                user.email, user.phone, user.first_name, user.last_name
            )

            await conn.execute("""
                INSERT INTO users (
                    user_id, username, email, first_name, last_name,
                    email_hash, phone_hash, name_hash,
                    role, status, department, license_number, hsa_id, siths_metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            """,
                user.user_id, user.username, user.email, user.first_name,
                user.last_name, email_hash, phone_hash, name_hash,
                user.role.value, user.status.value,
                user.department, user.license_number, user.hsa_id,
                json.dumps(user.siths_metadata)
            )
            return user

    async def update_user(self, user: User) -> User:
        """Update an existing user with hashed PII."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Hash PII fields
            email_hash, phone_hash, name_hash = self._db_encryption.hash_user_pii(
                user.email, user.phone, user.first_name, user.last_name
            )

            await conn.execute("""
                UPDATE users SET
                    username = $2, email = $3, first_name = $4, last_name = $5,
                    email_hash = $6, phone_hash = $7, name_hash = $8,
                    role = $9, status = $10, department = $11, license_number = $12,
                    phone = $13, hsa_id = $14, siths_metadata = $15, updated_at = NOW()
                WHERE user_id = $1
            """,
                user.user_id, user.username, user.email, user.first_name,
                user.last_name, email_hash, phone_hash, name_hash,
                user.role.value, user.status.value,
                user.department, user.license_number, user.phone,
                user.hsa_id, json.dumps(user.siths_metadata)
            )
            return user

    async def delete_user(self, user_id: str) -> None:
        """Delete a user by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE user_id = $1", user_id)


    async def list_users_by_role(self, role: str) -> Sequence[User]:
        """List users by role."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM users WHERE role = $1 ORDER BY last_name, first_name",
                role
            )
            return [self._row_to_user(row) for row in rows]

    async def create_session(self, session: UserSession) -> UserSession:
        """Create a new user session with GDPR-compliant tracking."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Create session in user_sessions table
            await conn.execute("""
                INSERT INTO user_sessions (
                    session_id, user_id, login_time, last_activity,
                    ip_address, user_agent, is_active, grandid_sessionid
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
                session.session_id, session.user_id, session.login_time,
                session.last_activity, session.ip_address, session.user_agent,
                session.is_active, session.grandid_sessionid
            )

            # Create GDPR-compliant session record
            await self._create_gdpr_session(session.user_id, session.session_id)

            # Initialize session analytics tracking
            try:
                await self.initialize_session_analytics(session.session_id, session.user_id)
                logger.info(f"Session analytics initialized for session {session.session_id}")
            except Exception as e:
                log_error(logger, "Failed to initialize session analytics", e)
                # Continue even if analytics initialization fails

            return session
    
    async def _create_gdpr_session(self, user_id: str, session_id: str) -> None:
        """
        Create a GDPR-compliant session record in sessions table.
        Only creates if BOTH session_id AND user_id are valid UUIDs.
        SITHS/EHR sessions (with VARCHAR user_ids) are tracked in user_sessions table only.
        """
        try:
            # Only create GDPR session if session_id is a valid UUID
            try:
                session_uuid = uuid.UUID(session_id)
            except ValueError:
                logger.debug(f"Skipping GDPR session creation for non-UUID session_id: {session_id}")
                return

            # Also check if user_id is a valid UUID (sessions table requires UUID user_id)
            # SITHS users have VARCHAR user_ids like "siths_c1653fc552ad"
            # EHR users have VARCHAR user_ids like "ehr_user_abc-123..."
            try:
                user_uuid = uuid.UUID(user_id)
            except ValueError:
                logger.debug(f"Skipping GDPR session creation for non-UUID user_id: {user_id} (SITHS/EHR user)")
                return

            pool = await self._get_pool()
            async with pool.acquire() as conn:
                # Generate pseudonymized subject hash (placeholder - should be actual patient ID)
                subject_hash = hashlib.sha256(f"user_{user_id}_session_{session_id}".encode()).digest()

                # Generate model config hash
                model_config = {"version": "1.0", "model": "gpt-4"}
                model_config_hash = hashlib.sha256(json.dumps(model_config, sort_keys=True).encode()).digest()

                await conn.execute("""
                    INSERT INTO sessions (
                        session_id, subject_hash, user_id, tenant_id,
                        lawful_basis, purpose_of_use, scopes, model_config_hash
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (session_id) DO UPDATE SET
                        started_at = NOW(),
                        is_active = TRUE,
                        ended_at = NULL
                """,
                    session_uuid, subject_hash, user_uuid,  # Both UUIDs now
                    uuid.uuid4(),  # Default tenant_id - should be set properly
                    "care_delivery", "diagnosis", ["patient/read", "observation/read"],
                    model_config_hash
                )
                logger.debug(f"Created GDPR session record for session {session_id}, user {user_id}")
        except Exception as e:
            log_error(logger, "Failed to create GDPR session record", e)

    async def get_active_session(self, session_id: str) -> Optional[UserSession]:
        """Get an active user session by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM user_sessions 
                WHERE session_id = $1 AND is_active = TRUE
            """, session_id)
            return self._row_to_session(row) if row else None
        
    async def update_session_activity(self, session_id: str) -> None:
        """Update last activity timestamp for a session."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_sessions 
                SET last_activity = NOW()
                WHERE session_id = $1
            """, session_id)

    async def deactivate_session(self, session_id: str) -> None:
        """Deactivate a user session."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_sessions 
                SET is_active = FALSE
                WHERE session_id = $1
            """, session_id)

    async def log_action(self, action: UserAction) -> UserAction:
        """Log a user action."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_actions (
                    action_id, user_id, action_type, resource_type,
                    resource_id, description, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
                action.action_id, action.user_id, action.action_type,
                action.resource_type, action.resource_id, action.description,
                json.dumps(action.metadata)
            )
            return action

    async def create_user_action(self, action: UserAction) -> UserAction:
        """Create a user action (alias for log_action for backward compatibility)."""
        return await self.log_action(action)

    async def log_system_usage_metric(self, metric_type: str, metric_name: str, value: int,
                                     unit: str = "count", dimensions: Optional[dict] = None,
                                     tenant_id: Optional[str] = None) -> None:
        """Log system usage metric for analytics."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO system_usage_metrics (
                    metric_type, metric_name, value, unit, dimensions, tenant_id
                ) VALUES ($1, $2, $3, $4, $5, $6)
            """, metric_type, metric_name, value, unit,
                json.dumps(dimensions or {}),
                uuid.UUID(tenant_id) if tenant_id else None)

    async def log_data_access(self, user_id: str, access_type: str, resource_type: str,
                             resource_identifier: str, data_source: str,
                             lawful_basis: str = "care_delivery",
                             purpose_of_use: str = "clinical_decision_support",
                             session_id: Optional[str] = None, **kwargs) -> None:
        """Log data access for GDPR compliance."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO data_access_logs (
                    session_id, user_id, access_type, resource_type, resource_identifier,
                    data_source, lawful_basis, purpose_of_use, access_method,
                    requested_fields, returned_count, filter_criteria,
                    data_retention_days, encryption_method, access_duration_ms
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            """,
                uuid.UUID(session_id) if session_id else None,
                user_id, access_type, resource_type, resource_identifier,  # user_id is VARCHAR
                data_source, lawful_basis, purpose_of_use,
                kwargs.get('access_method'), kwargs.get('requested_fields'),
                kwargs.get('returned_count'), json.dumps(kwargs.get('filter_criteria', {})),
                kwargs.get('data_retention_days'), kwargs.get('encryption_method'),
                kwargs.get('access_duration_ms'))

    async def log_performance_metric(self, metric_category: str, metric_name: str,
                                   value: float, unit: str, endpoint: Optional[str] = None,
                                   user_id: Optional[str] = None, session_id: Optional[str] = None,
                                   **kwargs) -> None:
        """Log performance metric for monitoring."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO performance_metrics (
                    metric_category, metric_name, value, unit, endpoint,
                    user_id, session_id, patient_context_size, model_used,
                    processing_stage, additional_context
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
                metric_category, metric_name, value, unit, endpoint,
                user_id,  # VARCHAR, not UUID
                uuid.UUID(session_id) if session_id else None,
                kwargs.get('patient_context_size'), kwargs.get('model_used'),
                kwargs.get('processing_stage'), json.dumps(kwargs.get('additional_context', {})))

    async def log_encryption_operation(self, operation_type: str, data_type: str,
                                     encryption_algorithm: str, key_type: str,
                                     success: bool = True, session_id: Optional[str] = None,
                                     user_id: Optional[str] = None, **kwargs) -> None:
        """Log encryption operation for security auditing."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO encryption_audit_log (
                    session_id, user_id, operation_type, data_type, encryption_algorithm,
                    key_type, key_identifier, data_size_bytes, operation_duration_ms,
                    success, error_details, client_info, compliance_context
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            """,
                uuid.UUID(session_id) if session_id else None,
                user_id,  # VARCHAR, not UUID
                operation_type, data_type, encryption_algorithm, key_type,
                kwargs.get('key_identifier'), kwargs.get('data_size_bytes'),
                kwargs.get('operation_duration_ms'), success, kwargs.get('error_details'),
                json.dumps(kwargs.get('client_info', {})),
                json.dumps(kwargs.get('compliance_context', {})))

    async def log_compliance_event(self, event_type: str, compliance_framework: str,
                                 user_id: str, lawful_basis: Optional[str] = None,
                                 session_id: Optional[str] = None, patient_id: Optional[str] = None,
                                 **kwargs) -> None:
        """Log compliance event for regulatory tracking."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO compliance_events (
                    event_type, compliance_framework, session_id, user_id, patient_id,
                    lawful_basis, consent_status, data_categories, processing_purposes,
                    retention_period_days, data_minimization_applied, anonymization_method,
                    cross_border_transfer, transfer_safeguards, individual_rights_exercised,
                    compliance_status, risk_assessment, mitigation_measures
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
            """,
                event_type, compliance_framework,
                uuid.UUID(session_id) if session_id else None,
                user_id, patient_id, lawful_basis,  # user_id is VARCHAR
                kwargs.get('consent_status'), kwargs.get('data_categories'),
                kwargs.get('processing_purposes'), kwargs.get('retention_period_days'),
                kwargs.get('data_minimization_applied', True), kwargs.get('anonymization_method'),
                kwargs.get('cross_border_transfer', False), kwargs.get('transfer_safeguards'),
                kwargs.get('individual_rights_exercised'), kwargs.get('compliance_status', 'compliant'),
                json.dumps(kwargs.get('risk_assessment', {})), kwargs.get('mitigation_measures'))

    async def update_session_analytics(self, session_id: str, **metrics) -> None:
        """
        Update session analytics with new metrics.

        NOTE: Numeric values are INCREMENTED, not set.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Build dynamic update query based on provided metrics
            updates = []
            values = []
            param_count = 1

            metric_mappings = {
                'requests': 'total_requests',
                'responses': 'total_responses',
                'patients_accessed': 'patient_contexts_accessed',
                'web_searches': 'web_searches_performed',
                'diagnostic_requests': 'diagnostic_requests',
                'chat_requests': 'chat_requests',
                'image_uploads': 'image_uploads',
                'journal_generations': 'journal_generations',
                'errors': 'error_count'
            }

            for key, value in metrics.items():
                if key in metric_mappings:
                    # INCREMENT values instead of setting them
                    column = metric_mappings[key]
                    updates.append(f"{column} = COALESCE({column}, 0) + ${param_count}")
                    values.append(value)
                    param_count += 1
                elif key == 'performance_metrics':
                    updates.append(f"performance_metrics = ${param_count}")
                    values.append(json.dumps(value))
                    param_count += 1
                elif key == 'data_sources_accessed':
                    updates.append(f"data_sources_accessed = ${param_count}")
                    values.append(value)
                    param_count += 1

            if updates:
                updates.append("last_updated = NOW()")
                query = f"""
                    UPDATE session_analytics
                    SET {', '.join(updates)}
                    WHERE session_id = ${param_count}
                """

                # session_id is now VARCHAR, no UUID conversion needed
                values.append(session_id)
                result = await conn.execute(query, *values)

                # Log if no rows were updated (session_analytics doesn't exist)
                if result == "UPDATE 0":
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Session analytics not found for session_id: {session_id}. Call initialize_session_analytics() first.")

    async def initialize_session_analytics(self, session_id: str, user_id: str) -> None:
        """
        Initialize session analytics row when session starts.

        Args:
            session_id: Session ID (VARCHAR - supports both UUID and chat session formats)
            user_id: User ID (VARCHAR)
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO session_analytics (
                    session_id, user_id, total_requests, total_responses,
                    patient_contexts_accessed, web_searches_performed,
                    diagnostic_requests, chat_requests, image_uploads,
                    journal_generations, error_count, session_duration_minutes,
                    performance_metrics, data_sources_accessed
                ) VALUES ($1, $2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, '{}', '{}')
                ON CONFLICT (session_id) DO NOTHING
            """,
                session_id,  # Direct string, no UUID conversion
                user_id      # Direct string, no UUID conversion
            )

    async def finalize_session_analytics(self, session_id: str) -> None:
        """
        Finalize session analytics by calculating duration and updating both sessions and user_sessions tables.

        Call this when a session ends (user logout, timeout, or app shutdown).

        Args:
            session_id: Session ID (VARCHAR - supports both UUID and chat session formats)
        """
        import logging
        logger = logging.getLogger(__name__)

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            session_info = None
            duration_minutes = None

            # Try to convert to UUID for sessions table lookup (only for GDPR auth sessions)
            # Chat sessions don't have entries in sessions table
            try:
                session_uuid = uuid.UUID(session_id)
                logger.debug(f"[finalize_session_analytics] Processing UUID session: {session_id}")

                # Try updating sessions table (GDPR-safe sessions)
                try:
                    session_info = await conn.fetchrow("""
                        UPDATE sessions
                        SET ended_at = NOW(), is_active = FALSE
                        WHERE session_id = $1 AND ended_at IS NULL
                        RETURNING started_at, ended_at
                    """, session_uuid)

                    if session_info:
                        logger.debug(f"[finalize_session_analytics] Updated sessions table")
                        started_at = session_info['started_at']
                        ended_at = session_info['ended_at']
                        duration_minutes = (ended_at - started_at).total_seconds() / 60.0
                except Exception as e:
                    logger.warning(f"[finalize_session_analytics] Could not update sessions table: {e}")
                    # Continue - might be in user_sessions instead

                # Also try updating user_sessions table (SITHS/EHR/manual login sessions)
                # This is where SITHS sessions are stored
                try:
                    user_session_info = await conn.fetchrow("""
                        UPDATE user_sessions
                        SET is_active = FALSE
                        WHERE session_id = $1 AND is_active = TRUE
                        RETURNING login_time, NOW() as ended_at
                    """, session_id)  # Use string session_id for VARCHAR column

                    if user_session_info:
                        logger.debug(f"[finalize_session_analytics] Updated user_sessions table")
                        # Use user_sessions timing if sessions table didn't have it
                        if not session_info:
                            started_at = user_session_info['login_time']
                            ended_at = user_session_info['ended_at']
                            duration_minutes = (ended_at - started_at).total_seconds() / 60.0
                except Exception as e:
                    logger.warning(f"[finalize_session_analytics] Could not update user_sessions table: {e}")

                # Update session_analytics with calculated duration
                if duration_minutes is not None:
                    try:
                        await conn.execute("""
                            UPDATE session_analytics
                            SET session_duration_minutes = $1,
                                last_updated = NOW()
                            WHERE session_id = $2
                        """,
                            duration_minutes,
                            session_id  # VARCHAR, no conversion needed
                        )
                        logger.debug(f"[finalize_session_analytics] Updated session_analytics with duration: {duration_minutes:.2f} min")
                    except Exception as e:
                        logger.error(f"[finalize_session_analytics] Error updating session_analytics: {e}")
            except ValueError:
                # Not a UUID session (chat session), skip sessions table update
                # Chat sessions track analytics but don't have entries in sessions table
                logger.debug(f"[finalize_session_analytics] Skipping table updates for non-UUID session: {session_id}")
            except Exception as e:
                logger.error(f"[finalize_session_analytics] Unexpected error for session {session_id}: {e}")
                raise

    async def expire_old_sessions(self, max_session_hours: int = 8) -> tuple[int, list[str]]:
        """
        Expire sessions older than max_session_hours and finalize their analytics.
        Checks BOTH sessions table (GDPR sessions) AND user_sessions table (SITHS/EHR/manual login).

        Args:
            max_session_hours: Maximum session duration in hours (default: 8)

        Returns:
            Tuple of (number of sessions expired, list of expired session IDs)
        """
        import logging
        logger = logging.getLogger(__name__)

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Find expired sessions from BOTH tables
            all_expired_sessions = []

            # 1. Find expired sessions from sessions table (GDPR sessions)
            try:
                gdpr_sessions = await conn.fetch("""
                    SELECT session_id::TEXT as session_id FROM sessions
                    WHERE is_active = TRUE
                    AND ended_at IS NULL
                    AND started_at < NOW() - INTERVAL '{} hours'
                """.format(max_session_hours))
                all_expired_sessions.extend([row['session_id'] for row in gdpr_sessions])
                logger.debug(f"Found {len(gdpr_sessions)} expired GDPR sessions")
            except Exception as e:
                logger.error(f"Error finding expired GDPR sessions: {e}")

            # 2. Find expired sessions from user_sessions table (SITHS/EHR/manual login)
            try:
                user_sessions = await conn.fetch("""
                    SELECT session_id FROM user_sessions
                    WHERE is_active = TRUE
                    AND login_time < NOW() - INTERVAL '{} hours'
                """.format(max_session_hours))
                all_expired_sessions.extend([row['session_id'] for row in user_sessions])
                logger.debug(f"Found {len(user_sessions)} expired user sessions (SITHS/EHR/manual)")
            except Exception as e:
                logger.error(f"Error finding expired user sessions: {e}")

            # Finalize all expired sessions
            expired_count = 0
            expired_session_ids = []
            for session_id in all_expired_sessions:
                try:
                    await self.finalize_session_analytics(session_id)
                    expired_count += 1
                    expired_session_ids.append(session_id)
                    logger.info(f"Expired session: {session_id}")
                except Exception as e:
                    logger.error(f"Failed to expire session {session_id}: {e}")

            return expired_count, expired_session_ids

    async def check_session_timeout(self, session_id: str, max_session_hours: int = 8) -> bool:
        """
        Check if a session has exceeded the maximum duration and expire it if so.

        Args:
            session_id: Session ID to check
            max_session_hours: Maximum session duration in hours (default: 8)

        Returns:
            True if session is still valid, False if expired
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Try to convert to UUID, skip check for non-UUID sessions
            # (chat sessions use non-UUID session IDs like chat_general_xxx)
            try:
                session_uuid = uuid.UUID(session_id)
            except ValueError:
                # Not a UUID session, skip timeout check (chat sessions don't timeout)
                return True

            # Check both sessions table (GDPR-safe) and user_sessions table (SITHS/EHR login)
            # First, try the sessions table (UUID primary key)
            session = await conn.fetchrow("""
                SELECT started_at, ended_at, is_active FROM sessions
                WHERE session_id = $1
            """, session_uuid)

            # If not found in sessions table, check user_sessions table (VARCHAR primary key)
            if not session:
                user_session = await conn.fetchrow("""
                    SELECT login_time, NULL as ended_at, is_active FROM user_sessions
                    WHERE session_id = $1
                """, session_id)  # Use string session_id for VARCHAR column

                if not user_session:
                    return False  # Session doesn't exist in either table

                # Map user_sessions columns to sessions table format
                session = {
                    'started_at': user_session['login_time'],
                    'ended_at': user_session['ended_at'],
                    'is_active': user_session['is_active']
                }

            # Check if session is explicitly inactive or ended
            # Treat NULL is_active as active (for backward compatibility)
            if session['is_active'] is False or session['ended_at'] is not None:
                return False  # Session ended or marked inactive

            # Check if session has exceeded max duration
            from datetime import datetime, timezone, timedelta
            started_at = session['started_at']
            max_age = timedelta(hours=max_session_hours)

            if datetime.now(timezone.utc) - started_at > max_age:
                # Session has expired - finalize it
                await self.finalize_session_analytics(session_id)
                return False

            return True

    async def get_enhanced_user_metrics(self, user_id: str, days: int = 30) -> dict:
        """Get comprehensive user metrics including new tracking data."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            from_date = datetime.now(timezone.utc) - timedelta(days=days)

            # Get basic user metrics (existing functionality)
            basic_metrics = await self.get_user_metrics(user_id, days)

            # Get session analytics
            # Note: session_analytics.session_id is VARCHAR (supports both UUID auth sessions and chat sessions)
            #       sessions.session_id is UUID (only auth sessions have entries in sessions table)
            # We LEFT JOIN to include both auth sessions and chat sessions in the stats
            session_stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total_sessions,
                    AVG(session_duration_minutes) as avg_session_duration,
                    SUM(total_requests) as total_requests,
                    SUM(patient_contexts_accessed) as patients_accessed,
                    SUM(web_searches_performed) as web_searches,
                    SUM(diagnostic_requests) as diagnostic_requests,
                    SUM(chat_requests) as chat_requests,
                    SUM(error_count) as total_errors
                FROM session_analytics sa
                LEFT JOIN sessions s ON (
                    sa.session_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    AND sa.session_id::UUID = s.session_id
                )
                WHERE (s.user_id = $1 OR sa.user_id = $1) AND sa.started_at >= $2
            """, user_id, from_date)  # user_id is VARCHAR

            # Get performance metrics
            performance_stats = await conn.fetch("""
                SELECT
                    metric_category,
                    metric_name,
                    AVG(value) as avg_value,
                    MIN(value) as min_value,
                    MAX(value) as max_value,
                    COUNT(*) as measurement_count
                FROM performance_metrics
                WHERE user_id = $1 AND measured_at >= $2
                GROUP BY metric_category, metric_name
                ORDER BY metric_category, metric_name
            """, user_id, from_date)  # user_id is VARCHAR

            # Get data access summary
            data_access_stats = await conn.fetch("""
                SELECT
                    data_source,
                    resource_type,
                    COUNT(*) as access_count,
                    AVG(access_duration_ms) as avg_duration_ms
                FROM data_access_logs
                WHERE user_id = $1 AND accessed_at >= $2
                GROUP BY data_source, resource_type
                ORDER BY access_count DESC
            """, user_id, from_date)  # user_id is VARCHAR

            # Format enhanced metrics
            enhanced_metrics = {
                **basic_metrics,
                "session_analytics": {
                    "total_sessions": session_stats['total_sessions'] if session_stats else 0,
                    "average_session_duration_minutes": round(session_stats['avg_session_duration'] or 0, 2) if session_stats else 0,
                    "total_requests": session_stats['total_requests'] if session_stats else 0,
                    "patients_accessed": session_stats['patients_accessed'] if session_stats else 0,
                    "web_searches_performed": session_stats['web_searches'] if session_stats else 0,
                    "diagnostic_requests": session_stats['diagnostic_requests'] if session_stats else 0,
                    "chat_requests": session_stats['chat_requests'] if session_stats else 0,
                    "total_errors": session_stats['total_errors'] if session_stats else 0
                },
                "performance_metrics": {
                    row['metric_category']: {
                        row['metric_name']: {
                            "average": round(row['avg_value'], 2),
                            "minimum": round(row['min_value'], 2),
                            "maximum": round(row['max_value'], 2),
                            "count": row['measurement_count']
                        }
                    } for row in performance_stats
                },
                "data_access_patterns": [
                    {
                        "data_source": row['data_source'],
                        "resource_type": row['resource_type'],
                        "access_count": row['access_count'],
                        "average_duration_ms": round(row['avg_duration_ms'] or 0, 2)
                    } for row in data_access_stats
                ]
            }

            return enhanced_metrics
        
    async def get_user_actions(self, user_id: str, limit: int = 100) -> Sequence[UserAction]:
        """Get user actions for audit trail."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM user_actions 
                WHERE user_id = $1 
                ORDER BY created_at DESC 
                LIMIT $2
            """, user_id, limit)
            return [self._row_to_action(row) for row in rows]

    def _row_to_user(self, row) -> User:
        """Convert database row to User domain object."""
        # Parse siths_metadata from JSON if it's a string, otherwise use as-is
        siths_metadata = row.get('siths_metadata', {})
        if isinstance(siths_metadata, str):
            try:
                siths_metadata = json.loads(siths_metadata) if siths_metadata else {}
            except (json.JSONDecodeError, TypeError):
                siths_metadata = {}

        return User(
            user_id=row['user_id'],
            username=row['username'],
            email=row['email'],
            first_name=row['first_name'],
            last_name=row['last_name'],
            role=UserRole(row['role']),
            status=UserStatus(row['status']),
            department=row['department'],
            license_number=row['license_number'],
            phone=row['phone'],
            hsa_id=row.get('hsa_id'),  # May be NULL for non-SITHS users
            siths_metadata=siths_metadata  # Properly parsed JSON dict
            # Note: last_login is tracked in user_sessions table for GDPR compliance
        )

    def _row_to_session(self, row) -> UserSession:
        """Convert database row to UserSession domain object."""
        return UserSession(
            session_id=row['session_id'],
            user_id=row['user_id'],
            login_time=row['login_time'],
            last_activity=row['last_activity'],
            ip_address=str(row['ip_address']) if row['ip_address'] else None,
            user_agent=row['user_agent'],
            is_active=row['is_active'],
            grandid_sessionid=row.get('grandid_sessionid')  # Use .get() for backward compatibility
        )
    
    def _row_to_action(self, row) -> UserAction:
        """Convert database row to UserAction domain object."""
        return UserAction(
            action_id=row['action_id'],
            user_id=row['user_id'],
            action_type=row['action_type'],
            resource_type=row['resource_type'],
            resource_id=row['resource_id'],
            description=row['description'],
            metadata=row['metadata'] if row['metadata'] else {},
        )

    async def log_gdpr_compliant_data_access(self, user_id: str, access_type: str,
                                           resource_type: str, resource_count: int = 1,
                                           data_source: str = 'application',
                                           lawful_basis: str = 'legitimate_interest',
                                           purpose_of_use: str = 'healthcare_delivery',
                                           session_id: Optional[str] = None,
                                           privacy_impact_level: str = 'low') -> None:
        """Log data access in GDPR-compliant manner (no PHI stored)."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Check if table exists before logging
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'data_access_logs'
                )
            """)

            if table_exists:
                await conn.execute("""
                    INSERT INTO data_access_logs (
                        session_id, user_id, access_type, resource_type, resource_count,
                        data_source, lawful_basis, purpose_of_use, privacy_impact_level,
                        access_granted, accessed_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, true, NOW())
                """,
                uuid.UUID(session_id) if session_id else None,
                user_id,  # VARCHAR
                access_type,
                resource_type,
                resource_count,
                data_source,
                lawful_basis,
                purpose_of_use,
                privacy_impact_level
                )