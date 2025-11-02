"""
Background task utilities for non-blocking database operations.

Provides safe wrappers for executing analytics and audit logging tasks
in the background without impacting request latency.
"""
import asyncio
import logging
from typing import Coroutine, Any

logger = logging.getLogger(__name__)


async def safe_background_task(
    coro: Coroutine[Any, Any, Any],
    task_name: str,
    session_id: str | None = None,
    user_id: str | None = None
) -> None:
    """
    Execute a coroutine as a background task with error handling.

    This wrapper ensures that failures in analytics/audit logging don't
    propagate to user-facing operations. All errors are logged but suppressed.

    Args:
        coro: The coroutine to execute
        task_name: Human-readable name for logging
        session_id: Optional session ID for context
        user_id: Optional user ID for context

    Usage:
        asyncio.create_task(
            safe_background_task(
                audit_repo.log_audit_event(...),
                "log_audit_event",
                session_id=session_id
            )
        )
    """
    try:
        await coro
    except Exception as e:
        context = []
        if session_id:
            context.append(f"session_id={session_id}")
        if user_id:
            context.append(f"user_id={user_id}")

        context_str = f" ({', '.join(context)})" if context else ""
        logger.error(
            f"Background task '{task_name}' failed{context_str}: {e}",
            exc_info=True,
            extra={
                "task_name": task_name,
                "session_id": session_id,
                "user_id": user_id,
                "error_type": type(e).__name__
            }
        )


def create_background_task(
    coro: Coroutine[Any, Any, Any],
    task_name: str,
    session_id: str | None = None,
    user_id: str | None = None
) -> asyncio.Task:
    """
    Convenience wrapper to create and return a background task.

    Args:
        coro: The coroutine to execute
        task_name: Human-readable name for logging
        session_id: Optional session ID for context
        user_id: Optional user ID for context

    Returns:
        The created asyncio.Task

    Usage:
        task = create_background_task(
            audit_repo.log_audit_event(...),
            "log_audit_event",
            session_id=session_id
        )
    """
    return asyncio.create_task(
        safe_background_task(coro, task_name, session_id, user_id)
    )
