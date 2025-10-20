"""
Document event broadcaster for real-time notifications.
Uses only asyncio - no additional dependencies.
"""

import asyncio
import json
from typing import Dict, Set
from dataclasses import dataclass
from datetime import datetime

from optimed.core.logging_utils import get_logger, sanitize_user_id

logger = get_logger(__name__)


@dataclass
class DocumentEvent:
    """Document event."""
    type: str  # 'uploaded', 'deleted'
    document_id: str
    filename: str
    document_type: str  # 'pdf' or 'xml'
    session_id: str
    patient_id: str | None = None


class DocumentEventBroadcaster:
    """Manages document event subscriptions using asyncio.Queue."""

    def __init__(self) -> None:
        # user_id -> set of queues
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, user_id: str) -> asyncio.Queue:
        """Subscribe to events for a user."""
        async with self._lock:
            queue: asyncio.Queue = asyncio.Queue(maxsize=100)

            if user_id not in self._subscribers:
                self._subscribers[user_id] = set()

            self._subscribers[user_id].add(queue)
            logger.info(f"[DocEvents] User {sanitize_user_id(user_id)} subscribed ({len(self._subscribers[user_id])} connections)")

            return queue

    async def unsubscribe(self, user_id: str, queue: asyncio.Queue):
        """Unsubscribe from events."""
        async with self._lock:
            if user_id in self._subscribers:
                self._subscribers[user_id].discard(queue)

                if not self._subscribers[user_id]:
                    del self._subscribers[user_id]

                logger.info(f"[DocEvents] User {sanitize_user_id(user_id)} unsubscribed")

    async def broadcast(self, user_id: str, event: DocumentEvent):
        """Broadcast event to all user's connections."""
        async with self._lock:
            queues = self._subscribers.get(user_id, set()).copy()

        if not queues:
            return

        logger.info(f"[DocEvents] Broadcasting to {len(queues)} connection(s) for user {sanitize_user_id(user_id)}")

        dead_queues = []
        for queue in queues:
            try:
                await asyncio.wait_for(queue.put(event), timeout=1.0)
            except asyncio.TimeoutError:
                dead_queues.append(queue)
            except Exception as e:
                logger.error(f"[DocEvents] Error broadcasting event: {type(e).__name__}")
                dead_queues.append(queue)

        # Cleanup dead queues
        if dead_queues:
            async with self._lock:
                for queue in dead_queues:
                    self._subscribers.get(user_id, set()).discard(queue)


# Global instance
_broadcaster = DocumentEventBroadcaster()


def get_broadcaster() -> DocumentEventBroadcaster:
    """Get global broadcaster instance."""
    return _broadcaster


def format_sse_event(event: DocumentEvent) -> str:
    """Format event as SSE message."""
    data = {
        "type": event.type,
        "document_id": event.document_id,
        "filename": event.filename,
        "document_type": event.document_type,
        "session_id": event.session_id,
        "patient_id": event.patient_id,
        "timestamp": datetime.now().isoformat()
    }
    return f"data: {json.dumps(data)}\n\n"
