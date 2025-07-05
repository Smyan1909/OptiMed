from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional, Any
from pydantic import Field
from .mixins import FrozenModel


class WebSearchInfo(FrozenModel):
    """Information about web search performed during diagnosis."""
    web_search_performed: bool = False
    sources_consulted: List[str] = Field(default_factory=list)
    sources_cited_in_response: List[str] = Field(default_factory=list)
    search_summary: str = ""
    source_count: int = 0
    citations_included: bool = False


class CrossSessionHistoryInfo(FrozenModel):
    """Information about cross-session history search."""
    cross_session_search_performed: bool = False
    historical_sessions_consulted: int = 0
    historical_messages_found: int = 0
    oldest_reference: Optional[str] = None


class GeneratedImageInfo(FrozenModel):
    """Information about generated educational image."""
    image_generated: bool = False
    image_id: Optional[str] = None
    image_prompt: Optional[str] = None
    generation_metadata: dict[str, Any] = Field(default_factory=dict)
    model_info: dict[str, Any] = Field(default_factory=dict)


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

    # New fields for enhanced functionality
    session_id: Optional[str] = None
    web_search_info: WebSearchInfo = Field(default_factory=WebSearchInfo)
    cross_session_history_info: CrossSessionHistoryInfo = Field(default_factory=CrossSessionHistoryInfo)
    generated_image: GeneratedImageInfo = Field(default_factory=GeneratedImageInfo)
    
    # Additional metadata
    retrieved_chunks: List[str] = Field(default_factory=list)
    retrieval_reasoning: Optional[str] = None
    timestamp: Optional[str] = None

class TreatmentPlan(FrozenModel):
    plan_id: str
    patient_id: str
    diagnosis_id: str
    plan_details: str
    created_by_user_id: str
    approved_by_user_id: Optional[str] = None
    status: str = "draft"  # e.g., draft, approved, rejected

