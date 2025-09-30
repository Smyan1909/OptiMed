"""Note templates adapter for template management and note generation."""

from .pg_template_repository import PGTemplateRepository
from .template_service import TemplateServiceAdapter
from .note_generator import NoteGeneratorAdapter

__all__ = ["PGTemplateRepository", "TemplateServiceAdapter", "NoteGeneratorAdapter"]