from __future__ import annotations

import asyncpg
import json
from typing import Optional, List
from datetime import datetime, timezone

from optimed.core.domain import (
    NoteTemplate,
    NoteGenerationMetadata,
    TemplateType,
    NoteGenerationStatus,
    NoteExportMethod,
)
from optimed.core.ports import TemplateRepository


class PGTemplateRepository(TemplateRepository):
    """PostgreSQL implementation of TemplateRepository."""

    def __init__(self, dsn: str, min_size: int = 5, max_size: int = 20):
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create the connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=self.min_size,
                max_size=self.max_size,
            )
        return self._pool

    async def create_template(self, template: NoteTemplate) -> NoteTemplate:
        """Create a new template."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO note_templates
                (template_id, user_id, name, language, template_type,
                 template_structure, is_system_template, file_format,
                 created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                template.template_id,
                template.user_id,
                template.name,
                template.language,
                template.template_type.value,
                json.dumps(template.template_structure),
                template.is_system_template,
                template.file_format,
                template.created_at,
                template.updated_at,
            )
        return template

    async def get_template_by_id(self, template_id: str) -> Optional[NoteTemplate]:
        """Get template by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT template_id, user_id, name, language, template_type,
                       template_structure, is_system_template, file_format,
                       created_at, updated_at
                FROM note_templates
                WHERE template_id = $1
                """,
                template_id,
            )

            if not row:
                return None

            # Convert types from database
            template_structure = row["template_structure"]
            if isinstance(template_structure, str):
                template_structure = json.loads(template_structure)

            return NoteTemplate(
                template_id=str(row["template_id"]),
                user_id=row["user_id"],
                name=row["name"],
                language=row["language"],
                template_type=TemplateType(row["template_type"]),
                template_structure=template_structure,
                is_system_template=row["is_system_template"],
                file_format=row["file_format"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def list_templates(
        self,
        user_id: str,
        include_system: bool = True,
        language: Optional[str] = None,
        template_type: Optional[str] = None,
    ) -> List[NoteTemplate]:
        """List templates available to user."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Build query dynamically based on filters
            query = """
                SELECT template_id, user_id, name, language, template_type,
                       template_structure, is_system_template, file_format,
                       created_at, updated_at
                FROM note_templates
                WHERE (user_id = $1 OR (is_system_template = TRUE AND $2 = TRUE))
            """
            params = [user_id, include_system]
            param_idx = 3

            if language:
                query += f" AND language = ${param_idx}"
                params.append(language)
                param_idx += 1

            if template_type:
                query += f" AND template_type = ${param_idx}"
                params.append(template_type)
                param_idx += 1

            query += " ORDER BY is_system_template DESC, name ASC"

            rows = await conn.fetch(query, *params)

            templates = []
            for row in rows:
                # Convert types from database
                template_structure = row["template_structure"]
                if isinstance(template_structure, str):
                    template_structure = json.loads(template_structure)

                templates.append(
                    NoteTemplate(
                        template_id=str(row["template_id"]),
                        user_id=row["user_id"],
                        name=row["name"],
                        language=row["language"],
                        template_type=TemplateType(row["template_type"]),
                        template_structure=template_structure,
                        is_system_template=row["is_system_template"],
                        file_format=row["file_format"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                )
            return templates

    async def update_template(self, template: NoteTemplate) -> NoteTemplate:
        """Update existing template."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE note_templates
                SET name = $1, language = $2, template_type = $3,
                    template_structure = $4, file_format = $5, updated_at = $6
                WHERE template_id = $7
                """,
                template.name,
                template.language,
                template.template_type.value,
                json.dumps(template.template_structure),
                template.file_format,
                datetime.now(timezone.utc),
                template.template_id,
            )
        return template

    async def delete_template(self, template_id: str) -> bool:
        """Delete template (user templates only)."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM note_templates
                WHERE template_id = $1 AND is_system_template = FALSE
                """,
                template_id,
            )
            # Returns "DELETE N" where N is number of rows deleted
            return result.split()[-1] == "1"

    async def save_generation_metadata(
        self, metadata: NoteGenerationMetadata
    ) -> None:
        """Save generation metadata (GDPR-safe, no content)."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO note_generation_metadata
                (generation_id, user_id, patient_id, template_id, session_id,
                 template_name, template_type, language, generation_status,
                 context_prompt_hash, chunks_used_count, conversation_turns_included,
                 export_method, error_message, created_at, completed_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                """,
                metadata.generation_id,
                metadata.user_id,
                metadata.patient_id,
                metadata.template_id,
                metadata.session_id,
                metadata.template_name,
                metadata.template_type.value,
                metadata.language,
                metadata.status.value,
                metadata.context_prompt_hash,
                metadata.chunks_used_count,
                metadata.conversation_turns_included,
                metadata.export_method.value if metadata.export_method else None,
                metadata.error_message,
                metadata.created_at,
                metadata.completed_at,
            )

    async def update_generation_metadata(
        self,
        generation_id: str,
        status: NoteGenerationStatus,
        export_method: Optional[NoteExportMethod] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update generation metadata status."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE note_generation_metadata
                SET generation_status = $1,
                    export_method = $2,
                    error_message = $3,
                    completed_at = $4
                WHERE generation_id = $5
                """,
                status.value,
                export_method.value if export_method else None,
                error_message,
                datetime.now(timezone.utc) if status in [NoteGenerationStatus.COMPLETED, NoteGenerationStatus.ERROR, NoteGenerationStatus.CANCELLED] else None,
                generation_id,
            )

    async def get_generation_history(
        self,
        user_id: str,
        patient_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[NoteGenerationMetadata]:
        """Get metadata history (no actual note content)."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if patient_id:
                rows = await conn.fetch(
                    """
                    SELECT generation_id, user_id, patient_id, template_id, session_id,
                           template_name, template_type, language, generation_status,
                           context_prompt_hash, chunks_used_count, conversation_turns_included,
                           export_method, error_message, created_at, completed_at
                    FROM note_generation_metadata
                    WHERE user_id = $1 AND patient_id = $2
                    ORDER BY created_at DESC
                    LIMIT $3
                    """,
                    user_id,
                    patient_id,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT generation_id, user_id, patient_id, template_id, session_id,
                           template_name, template_type, language, generation_status,
                           context_prompt_hash, chunks_used_count, conversation_turns_included,
                           export_method, error_message, created_at, completed_at
                    FROM note_generation_metadata
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    user_id,
                    limit,
                )

            metadata_list = []
            for row in rows:
                # Convert UUIDs to strings
                metadata_list.append(
                    NoteGenerationMetadata(
                        generation_id=str(row["generation_id"]),
                        user_id=row["user_id"],
                        patient_id=str(row["patient_id"]) if row["patient_id"] else None,
                        template_id=str(row["template_id"]),
                        session_id=row["session_id"],
                        template_name=row["template_name"],
                        template_type=TemplateType(row["template_type"]),
                        language=row["language"],
                        status=NoteGenerationStatus(row["generation_status"]),
                        context_prompt_hash=row["context_prompt_hash"],
                        chunks_used_count=row["chunks_used_count"],
                        conversation_turns_included=row["conversation_turns_included"],
                        export_method=NoteExportMethod(row["export_method"]) if row["export_method"] else None,
                        error_message=row["error_message"],
                        created_at=row["created_at"],
                        completed_at=row["completed_at"],
                    )
                )
            return metadata_list

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()