"""
Row-Level Security (RLS) Context Middleware for OptiMed

Sets PostgreSQL session variables for RLS policies to enforce multi-tenant isolation.
Ensures that database queries automatically filter data by tenant/user.
"""

import uuid
from typing import Optional
from fastapi import Request
import asyncpg
from optimed.core.logging_utils import get_logger, sanitize_user_id, sanitize_session_id, log_error

logger = get_logger(__name__)


async def set_rls_context_for_connection(
    conn: asyncpg.Connection,
    user_id: Optional[str] = None,
    tenant_id: Optional[uuid.UUID] = None,
    session_id: Optional[str] = None
) -> None:
    """
    Set RLS context variables on a PostgreSQL connection.

    These variables are used by RLS policies to filter data.

    Args:
        conn: PostgreSQL connection
        user_id: Current user ID
        tenant_id: Current tenant ID (organization)
        session_id: Current session ID
    """
    try:
        # Set user_id context
        if user_id:
            await conn.execute(
                "SELECT set_config('app.user_id', $1, false)",
                user_id
            )

        # Set tenant_id context
        if tenant_id:
            await conn.execute(
                "SELECT set_config('app.current_tenant_id', $1, false)",
                str(tenant_id)
            )

        # Set session_id context (optional, for audit)
        if session_id:
            await conn.execute(
                "SELECT set_config('app.session_id', $1, false)",
                session_id
            )

    except Exception as e:
        log_error(logger, "Set RLS context", e)
        # Don't fail the request if RLS context setting fails
        # This allows the system to work even if RLS is not fully configured


async def clear_rls_context(conn: asyncpg.Connection) -> None:
    """
    Clear RLS context variables from a PostgreSQL connection.

    Useful for connection pooling to ensure clean state.
    """
    try:
        await conn.execute("SELECT set_config('app.user_id', '', false)")
        await conn.execute("SELECT set_config('app.current_tenant_id', '', false)")
        await conn.execute("SELECT set_config('app.session_id', '', false)")
    except Exception as e:
        log_error(logger, "Clear RLS context", e)


async def get_current_rls_context(conn: asyncpg.Connection) -> dict:
    """
    Get current RLS context variables from connection.

    Returns:
        Dictionary with user_id, tenant_id, session_id
    """
    try:
        user_id = await conn.fetchval("SELECT current_setting('app.user_id', true)")
        tenant_id = await conn.fetchval("SELECT current_setting('app.current_tenant_id', true)")
        session_id = await conn.fetchval("SELECT current_setting('app.session_id', true)")

        return {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "session_id": session_id,
        }
    except Exception as e:
        log_error(logger, "Get RLS context", e)
        return {}


class RLSContextManager:
    """
    Manager for RLS context in connection pools.

    Ensures that RLS context is properly set/cleared for pooled connections.
    """

    @staticmethod
    async def acquire_with_context(
        pool: asyncpg.Pool,
        user_id: Optional[str] = None,
        tenant_id: Optional[uuid.UUID] = None,
        session_id: Optional[str] = None
    ) -> asyncpg.Connection:
        """
        Acquire a connection from pool and set RLS context.

        Args:
            pool: Connection pool
            user_id: User ID for RLS
            tenant_id: Tenant ID for RLS
            session_id: Session ID for RLS

        Returns:
            Connection with RLS context set
        """
        conn = await pool.acquire()
        await set_rls_context_for_connection(conn, user_id, tenant_id, session_id)
        return conn

    @staticmethod
    async def release_with_cleanup(pool: asyncpg.Pool, conn: asyncpg.Connection) -> None:
        """
        Clear RLS context and release connection back to pool.

        Args:
            pool: Connection pool
            conn: Connection to release
        """
        await clear_rls_context(conn)
        await pool.release(conn)


class RLSMiddleware:
    """
    FastAPI middleware to set RLS context for each request.

    Extracts user/tenant/session from request and sets PostgreSQL context variables.
    This ensures RLS policies automatically filter data.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)

            # Extract user context from request state (set by auth middleware)
            user_id = None
            tenant_id = None
            session_id = None

            # Get session ID from header
            session_id = request.headers.get("x-session-id")

            # Get user from request state (if available)
            if hasattr(request.state, "user") and request.state.user:
                user = request.state.user
                user_id = user.user_id

                # Determine tenant_id
                # For now, we'll use a default tenant or derive from user
                # In a real multi-tenant system, this would come from user profile
                # You can extend User model to include tenant_id
                # For now, we'll generate a deterministic tenant ID based on user
                if hasattr(user, 'tenant_id') and user.tenant_id:
                    tenant_id = user.tenant_id
                else:
                    # Default: use a hash of user_id as tenant_id (single-tenant mode)
                    # In production, replace with actual tenant resolution
                    tenant_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"optimed.{user_id}")

            # Store RLS context in request state for repositories to use
            request.state.rls_context = {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "session_id": session_id,
            }

        # Continue to next middleware/route
        await self.app(scope, receive, send)


# Helper functions for repositories to use

def get_rls_context_from_request(request: Request) -> dict:
    """
    Get RLS context from request state.

    Use this in repository methods to get context for setting RLS.

    Returns:
        Dictionary with user_id, tenant_id, session_id
    """
    if hasattr(request.state, "rls_context"):
        return request.state.rls_context
    return {"user_id": None, "tenant_id": None, "session_id": None}


async def with_rls_context(conn: asyncpg.Connection, request: Request) -> asyncpg.Connection:
    """
    Set RLS context on a connection from request.

    Usage in repositories:
        conn = await pool.acquire()
        conn = await with_rls_context(conn, request)
        # Now execute queries with RLS applied
        result = await conn.fetch(...)

    Args:
        conn: Database connection
        request: FastAPI request object

    Returns:
        Connection with RLS context set
    """
    context = get_rls_context_from_request(request)
    await set_rls_context_for_connection(
        conn,
        user_id=context.get("user_id"),
        tenant_id=context.get("tenant_id"),
        session_id=context.get("session_id")
    )
    return conn
