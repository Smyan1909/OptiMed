from __future__ import annotations
import asyncpg
import json
from typing import Optional, Sequence
from datetime import datetime, timezone, timedelta
from optimed.core.domain import User, UserSession, UserAction, UserRole, UserStatus
from optimed.core.ports import UserRepository
import hashlib
import uuid

class PGUserRepository(UserRepository):

    def __init__(self, dsn: str, min_size: int = 5, max_size: int = 20):
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self._pool: Optional[asyncpg.Pool] = None

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
        
    async def create_user(self, user: User) -> User:
        """Create a new user."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (
                    user_id, username, email, first_name, last_name,
                    role, status, department, license_number, phone
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """, 
                user.user_id, user.username, user.email, user.first_name,
                user.last_name, user.role.value, user.status.value,
                user.department, user.license_number, user.phone
            )
            return user

    async def update_user(self, user: User) -> User:
        """Update an existing user."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE users SET
                    username = $2, email = $3, first_name = $4, last_name = $5,
                    role = $6, status = $7, department = $8, license_number = $9,
                    phone = $10, updated_at = NOW()
                WHERE user_id = $1
            """,
                user.user_id, user.username, user.email, user.first_name,
                user.last_name, user.role.value, user.status.value,
                user.department, user.license_number, user.phone
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
                    ip_address, user_agent, is_active
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
                session.session_id, session.user_id, session.login_time,
                session.last_activity, session.ip_address, session.user_agent,
                session.is_active
            )
            
            # Create GDPR-compliant session record
            await self._create_gdpr_session(session.user_id, session.session_id)
            
            return session
    
    async def _create_gdpr_session(self, user_id: str, session_id: str) -> None:
        """Create a GDPR-compliant session record."""
        try:
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
                    ON CONFLICT (session_id) DO NOTHING
                """,
                    uuid.UUID(session_id), subject_hash, uuid.UUID(user_id),
                    uuid.uuid4(),  # Default tenant_id - should be set properly
                    "care_delivery", "diagnosis", ["patient/read", "observation/read"],
                    model_config_hash
                )
        except Exception as e:
            print(f"Warning: Failed to create GDPR session record: {e}")

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
            # Remove created_at and updated_at since they're not in the User model
            last_login=row.get('last_login')  # Use get() in case this field is nullable
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
            is_active=row['is_active']
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