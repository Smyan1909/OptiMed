from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import Field

from .mixins import FrozenModel



class DiagnosisResult(FrozenModel):
    patient_id: str
    primary_icd: str
    differential: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    explaination: Optional[str] = None