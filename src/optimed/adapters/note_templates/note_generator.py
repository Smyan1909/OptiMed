from __future__ import annotations

import hashlib
import json
import uuid
from typing import AsyncGenerator, Dict, Any, Optional, List
from datetime import datetime, timezone

from optimed.core.ports import NoteGenerator, TemplateRepository
from optimed.core.domain import (
    NoteGenerationRequest,
    GeneratedNote,
    NoteGenerationMetadata,
    NoteTemplate,
    PatientContext,
    ChatMessage,
    User,
    NoteGenerationStatus,
    NoteExportMethod,
)


class NoteGeneratorAdapter:
    """
    Adapter implementing NoteGenerator protocol.
    Integrates with LangGraph orchestrator for note generation.
    """

    def __init__(
        self,
        template_repo: TemplateRepository,
    ):
        self._template_repo = template_repo

    async def generate_note_streaming(
        self,
        request: NoteGenerationRequest,
        patient_context: Optional[PatientContext],
        conversation_history: List[ChatMessage],
        template: NoteTemplate,
        user: User,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Generate note using LangGraph orchestrator.
        Streams progress and returns ephemeral content.

        Note: The actual generation logic is handled by info_flow_ram.py
        This adapter manages metadata and streaming coordination.
        """
        generation_id = str(uuid.uuid4())

        try:
            # Create initial metadata
            context_hash = None
            if request.context_prompt:
                context_hash = hashlib.sha256(
                    request.context_prompt.encode()
                ).hexdigest()

            metadata = NoteGenerationMetadata(
                generation_id=generation_id,
                user_id=request.user_id,
                patient_id=request.patient_id,
                template_id=request.template_id,
                session_id=request.session_id,
                template_name=template.name,
                template_type=template.template_type,
                language=template.language,
                status=NoteGenerationStatus.STARTED,
                context_prompt_hash=context_hash,
                created_at=datetime.now(timezone.utc),
            )
            await self._template_repo.save_generation_metadata(metadata)

            yield {
                "type": "start",
                "generation_id": generation_id,
                "template_name": template.name,
            }

            # The orchestrator (info_flow_ram.py) will handle the actual generation
            # and yield events. This is coordinated through the API layer.
            # This method serves as the protocol implementation and metadata manager.

            yield {
                "type": "metadata_saved",
                "generation_id": generation_id,
            }

        except Exception as e:
            yield {"type": "error", "message": str(e)}
            await self._template_repo.update_generation_metadata(
                generation_id=generation_id,
                status=NoteGenerationStatus.ERROR,
                error_message=str(e),
            )

    async def start_generation_metadata(
        self, request: NoteGenerationRequest, template: NoteTemplate
    ) -> str:
        """
        Start generation and create metadata record.
        Returns generation_id.
        """
        generation_id = str(uuid.uuid4())

        context_hash = None
        if request.context_prompt:
            context_hash = hashlib.sha256(request.context_prompt.encode()).hexdigest()

        metadata = NoteGenerationMetadata(
            generation_id=generation_id,
            user_id=request.user_id,
            patient_id=request.patient_id,
            template_id=request.template_id,
            session_id=request.session_id,
            template_name=template.name,
            template_type=template.template_type,
            language=template.language,
            status=NoteGenerationStatus.STARTED,
            context_prompt_hash=context_hash,
            created_at=datetime.now(timezone.utc),
        )

        await self._template_repo.save_generation_metadata(metadata)
        return generation_id

    async def complete_generation_metadata(
        self,
        generation_id: str,
        status: NoteGenerationStatus,
        export_method: Optional[NoteExportMethod] = None,
        chunks_count: int = 0,
        conversation_turns: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        """Complete generation metadata (no content saved)."""
        # First, get the current metadata to update it properly
        # We need to update with chunks and conversation counts
        await self._template_repo.update_generation_metadata(
            generation_id=generation_id,
            status=status,
            export_method=export_method,
            error_message=error_message,
        )

        # Note: chunk counts and conversation turns would need a separate update method
        # or we need to extend the update_generation_metadata signature
        # For now, they're set during the initial save in info_flow_ram.py