from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from pydantic import Field

from .mixins import FrozenModel


class Chunk(FrozenModel):
    """Privacy-preserving unit of text for embedding and retrieval.

    This entity must not contain direct PII/PHI. It uses pseudonymous
    references for patient and encounter.
    """

    id: str
    patient_ref: Optional[str] = None
    text: str
    resource_type: str
    key: Optional[str] = None
    code: Optional[str] = None
    system: Optional[str] = None
    units: Optional[str] = None
    value_type: Optional[str] = None
    timestamp: Optional[datetime] = None
    time_bucket: Optional[str] = None  # e.g., "2025-09"
    encounter_ref: Optional[str] = None
    strategy_id: str
    strategy_version: str
    span: Optional[tuple[int, int]] = None  # token start,end within parent
    meta: Dict[str, Any] = Field(default_factory=dict)

    # Privacy invariant marker (always False for allowed PHI)
    has_phi: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Record(FrozenModel):
    """Normalized input record for strategies.

    Derived from PatientContext or extracted from Documents.
    """

    patient_ref: Optional[str] = None
    encounter_ref: Optional[str] = None
    resource_type: str  # e.g., "vital", "lab", "medication", "narrative"
    key: Optional[str] = None
    value: Optional[str] = None
    text: Optional[str] = None  # long text for narrative
    code: Optional[str] = None
    system: Optional[str] = None
    units: Optional[str] = None
    value_type: Optional[str] = None
    timestamp: Optional[datetime] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class ChunkPolicy(FrozenModel):
    """Chunking policy parameters per strategy.

    max_tokens: target chunk size window.
    overlap: fraction (0..1) of overlap between consecutive chunks.
    boundary_rules: hints for sentence/paragraph/semantic boundaries.
    grouping_rules: hints for bundling (e.g., by encounter or month).
    """

    name: str
    max_tokens: int
    overlap: float = 0.0
    boundary_rules: Dict[str, Any] = Field(default_factory=dict)
    grouping_rules: Dict[str, Any] = Field(default_factory=dict)


class PolicySet(FrozenModel):
    """Named presets to drive strategies.

    Strategy key -> ChunkPolicy
    Examples: "atomic_default", "narrative_default", "bundle_default".
    """

    presets: Mapping[str, ChunkPolicy]

    def get(self, name: str) -> ChunkPolicy:
        policy = self.presets.get(name)
        if policy is None:
            raise KeyError(f"Policy preset not found: {name}")
        return policy


