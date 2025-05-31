from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import Field

from .enums import Channel, EventType, NotificationStatus, ChatRole
from .mixins import FrozenModel

class InfoEvent(FrozenModel):
    event_id: str
    patient_id: Optional[str] = None
    type: EventType
    payload_json: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def route_targets(self, policy: Dict[str, List[str]]) -> List[str]:
        """Pure function: choose recipients by event type & policy mapping."""
        return policy.get(self.type, [])


class Notification(FrozenModel):
    notification_id: str
    event_id: str # FK to InfoEvent
    recipient_ids: List[str]   # User IDs of recipients
    channel: Channel
    status: NotificationStatus = NotificationStatus.DELIVERED
    delivered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ack_at: Optional[datetime] = None

    def acknowledge(self, ts: Optional[datetime] = None) -> "Notification":
        """Acknowledge notification delivery."""
        return self.model_copy(update={"status": NotificationStatus.ACK, "ack_at": ts or datetime.now(timezone.utc)})


class CommThread(FrozenModel):
    thread_id: str
    notifications: List[Notification] = Field(default_factory=list)
    owners: List[str] = Field(default_factory=list)  # User IDs of thread owners
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None

    def add_notification(self, n: Notification) -> "CommThread":
        """Add a notification to the thread."""
        return self.model_copy(update={"notifications": self.notifications + [n]})
    
    def is_closed(self) -> bool:
        """Check if thread is closed."""
        return self.closed_at is not None
    

class ChatMessage(FrozenModel):
    role: ChatRole
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, str] = Field(default_factory=dict)