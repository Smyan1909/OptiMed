from __future__ import annotations

from typing import AsyncGenerator, Protocol, Sequence, Any, Union, Optional

from optimed.core.domain import PatientContext, KPIEvent, ChatMessage, DiagnosisResult, User, UserSession, UserAction

# core/ports.py
#
# Hexagonal “ports” that your adapters (Issue #8 Claude, #9 FHIR, #10 pgvector)
# will implement.  Nothing here should import concrete infrastructure libs.


class FHIRRepository(Protocol):
    """Read-only access to EHR data expoised as FHIR / SMART-onFHIR APIs."""

    async def get_patient(self, patient_id: str) -> PatientContext:
        """Get patient context by ID."""
        ...

    async def search_patients(self, query: str) -> Sequence[PatientContext]:
        """Simple convenience search"""
        ...

    async def close(self) -> None:
        """Close any resources like HTTP clients."""
        ...

    async def _get_patient_resource(self, pid: str) -> PatientContext:
        """Fetch a single Patient resource by ID."""
        ...
    
    async def _get_observations(
        self, pid: str, *, category: str, count: int = 10
    ) -> list[Any]:
        """Fetch observations of a specific category for a patient."""
        ...



class KPIEventSink(Protocol):

    async def record(self, event: KPIEvent) -> None:
        """Record a KPI event."""
        ...
    
    async def flush(self) -> None:
        """Flush any buffered events."""
        ...


class LLMClient(Protocol):

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatMessage:
        """Send a chat message sequence to the LLM and get a response."""
        ...

class VectorStore(Protocol):

    """pgvector / Pinecone / FAISS – whatever backs similarity search."""

    async def upsert(
        self,
        embedding_id: str,
        embedding: Sequence[float],
        object_type: str,
        object_id: str,
        content: str | dict,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Upsert an embedding vector with optional metadata."""
        ...

    async def similarity_search(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        filter_: dict[str, str] | None = None, 
    ) -> Sequence[tuple[str, float, str]]:
        """Find top-k most similar embeddings."""
        ...

    async def delete(self, embedding_ids: Sequence[str]) -> None:
        """Delete an embedding vector by ID."""
        ...

    async def get_chat_history(self, patient_id: str, session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Get chat history for a patient."""
        ...

    async def clear_chat_history(self, patient_id: str) -> None:
        """Clear chat history for a patient."""
        ...

    async def update(
        self,
        embedding_id: str,
        embedding: Sequence[float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update an existing embedding vector's metadata or embedding."""
        ...


class DiagnosticEngine(Protocol):
    """Pure-domain service used by LangGraph; orchestrates everything."""

    async def run(self, patient: PatientContext | None = None, user_prompt: str | None = None, chat_mode: bool = False, user_id: str | None = None, session_id: str | None = None) -> Union[DiagnosisResult,  dict]:
        """Return the top diagnosis (v0) or ranked list (v1)."""
        ...

    def run_stream(self, patient: PatientContext, user_prompt: str | None = None) -> AsyncGenerator[dict[str, Any], None]:
        """Run the diagnostic engine with streaming support."""
        ...


class UserRepository(Protocol):
    """User management and session handling."""

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        ...

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        ...

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        ...

    async def create_user(self, user: User) -> User:
        """Create a new user."""
        ...
    
    async def update_user(self, user: User) -> User:
        """Update an existing user."""
        ... 

    async def delete_user(self, user_id: str) -> None:
        """Delete a user by ID."""
        ...
    
    async def list_users_by_role(self, role: str) -> Sequence[User]:
        """List users by role."""
        ...

    async def create_session(self, session: UserSession) -> UserSession:
        """Create a new user session."""
        ...

    async def update_session_activity(self, session_id: str) -> None:
        """Update the last activity timestamp of a user session."""
        ...

    async def get_active_session(self, session_id: str) -> Optional[UserSession]:
        """Get an active user session by ID."""
        ...
    
    async def log_action(self, action: UserAction) -> UserAction:
        """Log a user action."""
        ...