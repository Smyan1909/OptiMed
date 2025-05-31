from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from typing import Iterable, Protocol, Sequence

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
    async def search_patients(self, mrn_or_name: str) -> Sequence[PatientContext]:
        """Simple convenience search"""
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
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Upsert an embedding vector with optional metadata."""
        ...

    @abstractmethod
    async def similarity_search(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        filter_: dict[str, str] | None = None, 
    ) -> Sequence[tuple[str, float]]:
        """Find top-k most similar embeddings."""
        ...


class DiagnosticEngine(Protocol):
    """Pure-domain service used by LangGraph; orchestrates everything."""

    @abstractmethod
    async def run(self, patient: PatientContext) -> DiagnosisResult:
        """Return the top diagnosis (v0) or ranked list (v1)."""
        ...