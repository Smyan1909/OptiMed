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
    explanation: Optional[str] = None
    created_by_user_id: Optional[str] = None
    reviewed_by_user_id: Optional[str] = None
    is_ai_generated: bool = True 

class TreatmentPlan(FrozenModel):
    plan_id: str
    patient_id: str
    diagnosis_id: str
    plan_details: str
    created_by_user_id: str
    approved_by_user_id: Optional[str] = None
    status: str = "draft"  # e.g., draft, approved, rejected

