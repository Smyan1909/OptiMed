from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import Field

from .enums import Channel, EventType, NotificationStatus, ChatRole, UserRole
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
    user_id: Optional[str] = None  # User ID of the sender
    user_role: Optional[UserRole] = None  # Role of the user (e.g., doctor, nurse)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, str] = Field(default_factory=dict)

    @property
    def is_from_staff(self) -> bool:
        """Check if the message is from a staff member (doctor, nurse, etc.)."""
        return self.user_id is not None and self.user_role is not None
    
class WebSearchQuery(FrozenModel):
    """Represents a web search query."""
    query_id: str
    query_text: str
    patient_id: Optional[str] = None
    user_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    search_intent: str = ""  # Medical condition, drug info, treatment guidelines, etc.

class WebSearchResult(FrozenModel):
    """Represents a single web search result."""
    url: str
    title: str
    snippet: str
    relevance_score: float = 0.0
    source_type: str = "general"  # medical_journal, clinical_guideline, drug_database, etc.
    publication_date: Optional[datetime] = None

class WebSearchResponse(FrozenModel):
    """Represents the complete web search response."""
    query: WebSearchQuery
    results: List[WebSearchResult] = Field(default_factory=list)
    total_results: int = 0
    search_time_ms: int = 0
    sources_used: List[str] = Field(default_factory=list)  # URLs that were actually used
    summary: str = ""  # AI-generated summary of findings
    searched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    def get_credible_sources(self, min_score: float = 0.7) -> List[WebSearchResult]:
        """Filter results by relevance score for credible sources."""
        return [result for result in self.results if result.relevance_score >= min_score]