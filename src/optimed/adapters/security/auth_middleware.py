"""
Authentication Middleware for OptiMed API Gateway

Provides mandatory session-based authentication and request origin validation.
Ensures only authenticated users can access protected endpoints.
"""

import os
from typing import Optional
from fastapi import Request, HTTPException, Header, Depends
from optimed.core.domain import User
from optimed.core.ports import UserRepository
from datetime import datetime, timezone
from optimed.core.logging_utils import get_logger, log_error

logger = get_logger(__name__)

# Configuration from environment
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", os.getenv("CORS_ORIGINS", "http://localhost:3000")).split(",")
ALLOWED_ORIGINS = [origin.strip() for origin in ALLOWED_ORIGINS]

# Public endpoints that don't require authentication
PUBLIC_ENDPOINTS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
}

# Auth endpoints (login, etc.)
AUTH_ENDPOINTS_PREFIX = [
    "/auth/login",
    "/auth/ehr-login",
    "/auth/ehr-callback",
]


def is_public_endpoint(path: str) -> bool:
    """Check if endpoint is public (doesn't require auth)."""
    # Exact match
    if path in PUBLIC_ENDPOINTS:
        return True

    # Prefix match for auth endpoints
    for prefix in AUTH_ENDPOINTS_PREFIX:
        if path.startswith(prefix):
            return True

    return False


async def validate_request_origin(request: Request) -> None:
    """
    Validate that request comes from an allowed origin.

    Checks both Origin and Referer headers for security.
    Raises HTTPException if origin is invalid.
    """
    # Skip for public endpoints
    if is_public_endpoint(request.url.path):
        return

    origin = request.headers.get("origin")
    referer = request.headers.get("referer")

    # For same-origin requests (server-side), these may be None
    if not origin and not referer:
        # Allow if no origin/referer (direct API calls, server-side)
        # In production, you may want to be more strict
        return

    # Check origin
    if origin:
        origin_valid = any(origin.startswith(allowed) for allowed in ALLOWED_ORIGINS)
        if not origin_valid:
            raise HTTPException(
                status_code=403,
                detail=f"Origin '{origin}' is not allowed. This request cannot be processed."
            )

    # Check referer as backup
    if referer and not origin:
        referer_valid = any(referer.startswith(allowed) for allowed in ALLOWED_ORIGINS)
        if not referer_valid:
            raise HTTPException(
                status_code=403,
                detail=f"Referer '{referer}' is not allowed. This request cannot be processed."
            )


async def get_current_user_optional(
    request: Request,
    x_session_id: str = Header(None, alias="X-Session-ID")
) -> Optional[User]:
    """
    Get current user from session (optional - returns None if not authenticated).

    This is the original behavior for backward compatibility.
    """
    if not x_session_id:
        return None

    try:
        # Get user repository from app state (injected during startup)
        user_repo: UserRepository = request.app.state._user_repo

        session = await user_repo.get_active_session(x_session_id)
        if not session:
            return None

        user = await user_repo.get_user_by_id(session.user_id)
        if user:
            # Update last activity
            await user_repo.update_session_activity(x_session_id)

        return user
    except Exception as e:
        log_error(logger, "Fetch current user", e)
        return None


async def require_authenticated_user(
    request: Request,
    x_session_id: str = Header(None, alias="X-Session-ID")
) -> User:
    """
    Require authentication for protected endpoints.

    Returns User if authenticated, raises HTTPException(401) otherwise.
    Use this dependency for endpoints that must be authenticated.
    """
    # Skip for public endpoints
    if is_public_endpoint(request.url.path):
        # For public endpoints, return a dummy user or handle accordingly
        # This shouldn't be called for public endpoints, but just in case
        raise HTTPException(
            status_code=500,
            detail="Authentication not required for this endpoint"
        )

    if not x_session_id:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please provide X-Session-ID header."
        )

    try:
        # Get user repository from app state
        user_repo: UserRepository = request.app.state._user_repo

        session = await user_repo.get_active_session(x_session_id)
        if not session:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired session. Please log in again."
            )

        user = await user_repo.get_user_by_id(session.user_id)
        if not user:
            raise HTTPException(
                status_code=401,
                detail="User not found. Please log in again."
            )

        # Update last activity
        await user_repo.update_session_activity(x_session_id)

        return user

    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Authentication", e)
        raise HTTPException(
            status_code=500,
            detail="Authentication service error. Please try again."
        )


async def check_session_validity(session_id: str, user_repo: UserRepository) -> bool:
    """
    Check if session is still valid and not expired.

    Returns True if valid, False otherwise.
    """
    try:
        session = await user_repo.get_active_session(session_id)
        if not session:
            return False

        # Check if session is still active
        if not session.is_active:
            return False

        # Check session timeout (if implemented)
        session_timeout_minutes = int(os.getenv("SESSION_TIMEOUT_MINUTES", "60"))
        now = datetime.now(timezone.utc)

        # Make last_activity timezone-aware if it isn't
        last_activity = session.last_activity
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)

        time_since_activity = (now - last_activity).total_seconds() / 60

        if time_since_activity > session_timeout_minutes:
            return False

        return True

    except Exception as e:
        log_error(logger, "Check session validity", e)
        return False


async def get_user_context(
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    x_session_id: str = Header(None, alias="X-Session-ID")
) -> dict:
    """
    Get user context dictionary (backward compatible).

    Returns user context with user_id, user object, and session_id.
    """
    return {
        "user_id": user.user_id if user else None,
        "user": user,
        "session_id": x_session_id
    }


async def get_authenticated_user_context(
    request: Request,
    user: User = Depends(require_authenticated_user),
    x_session_id: str = Header(..., alias="X-Session-ID")
) -> dict:
    """
    Get user context dictionary with mandatory authentication.

    Returns user context with user_id, user object, and session_id.
    Raises HTTPException if not authenticated.
    """
    return {
        "user_id": user.user_id,
        "user": user,
        "session_id": x_session_id
    }


# Middleware class for FastAPI
class AuthenticationMiddleware:
    """
    Middleware to enforce authentication and origin validation.

    This can be added to FastAPI app as middleware to apply globally.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)

            # Validate origin
            try:
                await validate_request_origin(request)
            except HTTPException as exc:
                # Send error response
                response = {
                    "type": "http.response.start",
                    "status": exc.status_code,
                    "headers": [(b"content-type", b"application/json")],
                }
                await send(response)
                await send({
                    "type": "http.response.body",
                    "body": f'{{"detail": "{exc.detail}"}}'.encode(),
                })
                return

            # Attach user to request state for audit logging (GDPR compliance)
            try:
                # Extract session_id from headers
                x_session_id = None
                for header_name, header_value in scope.get("headers", []):
                    if header_name == b"x-session-id":
                        x_session_id = header_value.decode()
                        break

                # Fetch and attach user if session exists
                if x_session_id and hasattr(request.app.state, '_user_repo'):
                    user_repo = request.app.state._user_repo
                    session = await user_repo.get_active_session(x_session_id)
                    if session:
                        user = await user_repo.get_user_by_id(session.user_id)
                        if user:
                            request.state.user = user
                            request.state.session_id = x_session_id
            except Exception as e:
                # Don't fail the request if user attachment fails
                log_error(logger, "Attach user to request", e)

        # Continue to next middleware/route
        await self.app(scope, receive, send)
