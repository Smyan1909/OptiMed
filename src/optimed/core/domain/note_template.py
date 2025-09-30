from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from pydantic import Field

from .enums import TemplateType, NoteGenerationStatus, NoteExportMethod
from .mixins import FrozenModel

"""Domain models for clinical note templates and generation."""


class NoteTemplate(FrozenModel):
    """
    Template for generating clinical notes.
    Contains structure only, no PHI.
    """
    template_id: str
    user_id: str
    name: str
    language: str  # 'sv' or 'en'
    template_type: TemplateType
    template_structure: Dict[str, Any]  # Field definitions and placeholders
    is_system_template: bool = Field(default=False)
    file_format: str  # 'docx', 'pdf', 'xlsx', 'json'
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def display_name(self) -> str:
        """Returns display name with language indicator."""
        lang_badge = "🇸🇪" if self.language == "sv" else "🇬🇧"
        return f"{lang_badge} {self.name}"

    @property
    def is_user_template(self) -> bool:
        """Returns True if this is a user-created template."""
        return not self.is_system_template


class NoteGenerationRequest(FrozenModel):
    """Request to generate a clinical note."""
    template_id: str
    session_id: str
    patient_id: Optional[str] = None
    context_prompt: Optional[str] = None
    include_conversation_history: bool = Field(default=True)
    user_id: str


class GeneratedNote(FrozenModel):
    """
    Generated note content (ephemeral, never persisted).
    ⚠️ This object must never be stored in database.
    """
    generation_id: str
    content: str  # Full note content
    sections: Dict[str, str]  # Content organized by section
    template_name: str
    template_type: TemplateType
    language: str
    sources: List[str] = Field(default_factory=list)  # EHR source links preserved
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def word_count(self) -> int:
        """Returns approximate word count of generated content."""
        return len(self.content.split())

    @property
    def has_sources(self) -> bool:
        """Returns True if note includes EHR source citations."""
        return len(self.sources) > 0


class NoteGenerationMetadata(FrozenModel):
    """
    GDPR-safe metadata about note generation.
    NO CONTENT stored, only analytics and audit trail.
    """
    generation_id: str
    user_id: str
    patient_id: Optional[str] = None  # Reference only
    template_id: str
    session_id: str
    template_name: str
    template_type: TemplateType
    language: str
    status: NoteGenerationStatus
    context_prompt_hash: Optional[str] = None  # SHA256 hash for analytics
    chunks_used_count: int = Field(default=0)
    conversation_turns_included: int = Field(default=0)
    export_method: Optional[NoteExportMethod] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        """Returns generation duration in seconds if completed."""
        if self.completed_at:
            return (self.completed_at - self.created_at).total_seconds()
        return None

    @property
    def is_completed(self) -> bool:
        """Returns True if generation completed successfully."""
        return self.status == NoteGenerationStatus.COMPLETED