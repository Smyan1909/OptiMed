"""
Rate Limiting Middleware for OptiMed API Gateway

Implements sliding window rate limiting per user/session to prevent abuse.
Tracks usage metrics for analytics and compliance.
"""

import os
import time
from typing import Dict, Tuple, Optional
from collections import defaultdict
from fastapi import Request, HTTPException
from datetime import datetime, timezone
import asyncio
from optimed.core.logging_utils import get_logger, sanitize_user_id, sanitize_session_id, log_error

logger = get_logger(__name__)

# Configuration from environment
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "1000"))
RATE_LIMIT_ENABLED = os.getenv("ENABLE_RATE_LIMITING", "true").lower() == "true"


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter implementation.

    Tracks requests per user/session in memory with automatic cleanup.
    Thread-safe for concurrent requests.
    """

    def __init__(self, per_minute: int = RATE_LIMIT_PER_MINUTE, per_hour: int = RATE_LIMIT_PER_HOUR):
        """
        Initialize rate limiter.

        Args:
            per_minute: Maximum requests per minute per user/session
            per_hour: Maximum requests per hour per user/session
        """
        self.per_minute = per_minute
        self.per_hour = per_hour

        # Store request timestamps: {user_id: [timestamp1, timestamp2, ...]}
        self.request_history: Dict[str, list] = defaultdict(list)

        # Store rate limit violations for tracking
        self.violations: Dict[str, int] = defaultdict(int)

        # Lock for thread safety
        self._lock = asyncio.Lock()

        # Last cleanup time
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # Cleanup every 5 minutes

    async def check_rate_limit(self, identifier: str) -> Tuple[bool, Optional[str]]:
        """
        Check if request should be allowed based on rate limits.

        Args:
            identifier: User ID or session ID

        Returns:
            Tuple of (is_allowed, retry_after_message)
        """
        if not RATE_LIMIT_ENABLED:
            return True, None

        async with self._lock:
            current_time = time.time()

            # Cleanup old entries periodically
            if current_time - self._last_cleanup > self._cleanup_interval:
                await self._cleanup_old_entries(current_time)
                self._last_cleanup = current_time

            # Get request history for this identifier
            timestamps = self.request_history[identifier]

            # Remove timestamps older than 1 hour
            one_hour_ago = current_time - 3600
            timestamps = [ts for ts in timestamps if ts > one_hour_ago]
            self.request_history[identifier] = timestamps

            # Check minute limit
            one_minute_ago = current_time - 60
            requests_last_minute = sum(1 for ts in timestamps if ts > one_minute_ago)

            if requests_last_minute >= self.per_minute:
                self.violations[identifier] += 1
                retry_after = 60 - (current_time - max([ts for ts in timestamps if ts > one_minute_ago]))
                return False, f"Rate limit exceeded. Please retry after {int(retry_after)} seconds."

            # Check hour limit
            requests_last_hour = len(timestamps)

            if requests_last_hour >= self.per_hour:
                self.violations[identifier] += 1
                retry_after = 3600 - (current_time - min(timestamps))
                return False, f"Hourly rate limit exceeded. Please retry after {int(retry_after / 60)} minutes."

            # Allow request and record timestamp
            timestamps.append(current_time)
            self.request_history[identifier] = timestamps

            return True, None

    async def _cleanup_old_entries(self, current_time: float) -> None:
        """
        Cleanup old entries to prevent memory bloat.

        Removes all timestamps older than 1 hour.
        """
        one_hour_ago = current_time - 3600

        # Clean up request history
        identifiers_to_remove = []
        for identifier, timestamps in self.request_history.items():
            # Filter out old timestamps
            recent_timestamps = [ts for ts in timestamps if ts > one_hour_ago]
            if recent_timestamps:
                self.request_history[identifier] = recent_timestamps
            else:
                identifiers_to_remove.append(identifier)

        # Remove empty entries
        for identifier in identifiers_to_remove:
            del self.request_history[identifier]

    async def get_usage_stats(self, identifier: str) -> Dict[str, int]:
        """
        Get usage statistics for an identifier.

        Returns:
            Dictionary with requests_last_minute, requests_last_hour, violations
        """
        async with self._lock:
            timestamps = self.request_history.get(identifier, [])
            current_time = time.time()
            one_minute_ago = current_time - 60

            requests_last_minute = sum(1 for ts in timestamps if ts > one_minute_ago)
            requests_last_hour = len(timestamps)
            violations = self.violations.get(identifier, 0)

            return {
                "requests_last_minute": requests_last_minute,
                "requests_last_hour": requests_last_hour,
                "violations": violations,
                "limit_per_minute": self.per_minute,
                "limit_per_hour": self.per_hour,
            }

    async def reset_limits(self, identifier: str) -> None:
        """Reset rate limits for an identifier (admin function)."""
        async with self._lock:
            if identifier in self.request_history:
                del self.request_history[identifier]
            if identifier in self.violations:
                del self.violations[identifier]


# Global rate limiter instance
_rate_limiter: Optional[SlidingWindowRateLimiter] = None


def get_rate_limiter() -> SlidingWindowRateLimiter:
    """Get global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = SlidingWindowRateLimiter(
            per_minute=RATE_LIMIT_PER_MINUTE,
            per_hour=RATE_LIMIT_PER_HOUR
        )
    return _rate_limiter


async def check_rate_limit_for_request(request: Request) -> None:
    """
    Check rate limit for incoming request.

    Uses user_id or session_id as identifier.
    Raises HTTPException(429) if rate limit exceeded.
    """
    if not RATE_LIMIT_ENABLED:
        return

    # Skip rate limiting for public endpoints
    public_endpoints = {"/health", "/docs", "/redoc", "/openapi.json"}
    if request.url.path in public_endpoints:
        return

    # Get identifier (prefer user_id, fallback to session_id, then IP)
    identifier = None

    # Try to get user from request state (set by auth middleware)
    if hasattr(request.state, "user") and request.state.user:
        identifier = request.state.user.user_id
    elif "x-session-id" in request.headers:
        identifier = request.headers["x-session-id"]
    else:
        # Fallback to IP address
        identifier = request.client.host if request.client else "unknown"

    if not identifier:
        # If no identifier, skip rate limiting (shouldn't happen)
        return

    # Check rate limit
    rate_limiter = get_rate_limiter()
    is_allowed, retry_message = await rate_limiter.check_rate_limit(identifier)

    if not is_allowed:
        # Log rate limit violation
        try:
            if hasattr(request.app.state, "_user_repo"):
                user_repo = request.app.state._user_repo
                await user_repo.log_system_usage_metric(
                    metric_type="rate_limit",
                    metric_name="violation",
                    value=1,
                    dimensions={"identifier": identifier, "path": request.url.path}
                )
        except Exception as e:
            log_error(logger, "Log rate limit violation", e)

        raise HTTPException(
            status_code=429,
            detail=retry_message or "Rate limit exceeded. Please try again later.",
            headers={"Retry-After": "60"}
        )

    # Log successful request for metrics
    try:
        if hasattr(request.app.state, "_user_repo"):
            user_repo = request.app.state._user_repo
            await user_repo.log_system_usage_metric(
                metric_type="rate_limit",
                metric_name="request_allowed",
                value=1,
                dimensions={"identifier": identifier, "path": request.url.path}
            )
    except Exception as e:
        # Don't block request if logging fails
        log_error(logger, "Log rate limit metric", e)


class RateLimitMiddleware:
    """
    FastAPI middleware for rate limiting.

    Applies rate limiting to all requests before they reach route handlers.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)

            # Check rate limit
            try:
                await check_rate_limit_for_request(request)
            except HTTPException as exc:
                # Send rate limit error response
                import json
                response_body = json.dumps({"detail": exc.detail}).encode()

                await send({
                    "type": "http.response.start",
                    "status": exc.status_code,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", b"60"),
                    ],
                })
                await send({
                    "type": "http.response.body",
                    "body": response_body,
                })
                return

        # Continue to next middleware/route
        await self.app(scope, receive, send)
