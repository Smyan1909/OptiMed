from __future__ import annotations

from abc import abstractmethod
from typing import AsyncGenerator, Protocol, Sequence, Any, Union

from optimed.core.domain import PatientContext, KPIEvent, ChatMessage, DiagnosisResult

# core/ports.py
#
# Hexagonal “ports” that your adapters (Issue #8 Claude, #9 FHIR, #10 pgvector)
# will implement.  Nothing here should import concrete infrastructure libs.


class FHIRRepository(Protocol):
    """Read-only access to EHR data expoised as FHIR / SMART-onFHIR APIs."""

    @abstractmethod
    async def get_patient(self, patient_id: str) -> PatientContext:
        """Get patient context by ID."""
        ...

    @abstractmethod
    async def search_patients(self, query: str) -> Sequence[PatientContext]:
        """Simple convenience search"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close any resources like HTTP clients."""
        ...

    @abstractmethod
    async def _get_patient_resource(self, pid: str) -> PatientContext:
        """Fetch a single Patient resource by ID."""
        ...
    
    @abstractmethod
    async def _get_observations(
        self, pid: str, *, category: str, count: int = 10
    ) -> list[Any]:
        """Fetch observations of a specific category for a patient."""
        ...



class KPIEventSink(Protocol):

    @abstractmethod
    async def record(self, event: KPIEvent) -> None:
        """Record a KPI event."""
        ...
    
    @abstractmethod
    async def flush(self) -> None:
        """Flush any buffered events."""
        ...


class LLMClient(Protocol):

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
    async def similarity_search(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        filter_: dict[str, str] | None = None, 
    ) -> Sequence[tuple[str, float, str]]:
        """Find top-k most similar embeddings."""
        ...

    @abstractmethod
    async def delete(self, embedding_ids: Sequence[str]) -> None:
        """Delete an embedding vector by ID."""
        ...
    
    @abstractmethod
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

    @abstractmethod
    async def run(self, patient: PatientContext | None = None, user_prompt: str | None = None, chat_mode: bool = False) -> Union[DiagnosisResult,  dict]:
        """Return the top diagnosis (v0) or ranked list (v1)."""
        ...

    @abstractmethod
    async def run_stream(self, patient: PatientContext, user_prompt: str | None = None):
        """Run the diagnostic engine with streaming support."""
        ...