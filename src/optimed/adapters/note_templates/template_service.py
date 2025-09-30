from __future__ import annotations

import uuid
import re
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from optimed.core.domain import NoteTemplate, TemplateType
from optimed.core.ports import TemplateService, TemplateRepository


class TemplateServiceAdapter:
    """Service for template management and parsing."""

    def __init__(self, template_repo: TemplateRepository):
        self._repo = template_repo

    async def parse_uploaded_file(
        self, file_content: bytes, filename: str, file_type: str
    ) -> Dict[str, Any]:
        """
        Parse uploaded template file to structured format.

        For MVP: Extracts text and identifies sections by common patterns.
        Future enhancement: Full DOCX/PDF/XLSX parsing with python-docx, pdfplumber, openpyxl.
        """
        # Determine file type from content_type or filename
        file_ext = filename.lower().split(".")[-1] if "." in filename else ""

        if file_type in ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"] or file_ext == "docx":
            return await self._parse_docx(file_content)
        elif file_type in ["application/pdf", "pdf"] or file_ext == "pdf":
            return await self._parse_pdf(file_content)
        elif file_type in ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"] or file_ext == "xlsx":
            return await self._parse_xlsx(file_content)
        elif file_type in ["text/plain", "txt"] or file_ext == "txt":
            return await self._parse_text(file_content)
        else:
            # Default: try text parsing
            return await self._parse_text(file_content)

    async def _parse_text(self, content: bytes) -> Dict[str, Any]:
        """Parse plain text template."""
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        # Extract sections based on common patterns
        fields = self._extract_sections_from_text(text)

        return {"fields": fields}

    async def _parse_docx(self, content: bytes) -> Dict[str, Any]:
        """
        Parse Word document template.

        Future: Use python-docx for proper parsing.
        For now: Convert to text and extract sections.
        """
        try:
            # Try basic python-docx if available
            try:
                import docx
                import io

                doc = docx.Document(io.BytesIO(content))
                text = "\n".join([para.text for para in doc.paragraphs])
            except ImportError:
                # Fallback: Just decode as text (not ideal but functional)
                text = content.decode("utf-8", errors="ignore")

            fields = self._extract_sections_from_text(text)
            return {"fields": fields}

        except Exception as e:
            print(f"[TemplateService] Error parsing DOCX: {e}")
            # Fallback to text parsing
            return await self._parse_text(content)

    async def _parse_pdf(self, content: bytes) -> Dict[str, Any]:
        """
        Parse PDF template.

        Future: Use pdfplumber for proper extraction.
        For now: Basic text extraction.
        """
        try:
            # Try pdfplumber if available
            try:
                import pdfplumber
                import io

                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    text = "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
            except ImportError:
                # Fallback: Decode as text (very basic)
                text = content.decode("utf-8", errors="ignore")

            fields = self._extract_sections_from_text(text)
            return {"fields": fields}

        except Exception as e:
            print(f"[TemplateService] Error parsing PDF: {e}")
            return await self._parse_text(content)

    async def _parse_xlsx(self, content: bytes) -> Dict[str, Any]:
        """
        Parse Excel template.

        Future: Use openpyxl for proper parsing.
        For now: Basic structure.
        """
        try:
            # Try openpyxl if available
            try:
                import openpyxl
                import io

                wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
                ws = wb.active

                fields = []
                for row in ws.iter_rows(values_only=True):
                    if row and row[0]:  # If first column has value
                        field_name = str(row[0]).lower().replace(" ", "_")
                        field_label = str(row[0])
                        fields.append({
                            "name": field_name,
                            "label": field_label,
                            "type": "text"
                        })

                if not fields:
                    # Fallback to generic fields
                    fields = [
                        {"name": "field_1", "label": "Field 1", "type": "text"},
                        {"name": "field_2", "label": "Field 2", "type": "text"},
                    ]

                return {"fields": fields}

            except ImportError:
                # Fallback: Generic structure
                return {
                    "fields": [
                        {"name": "section_1", "label": "Section 1", "type": "text"},
                        {"name": "section_2", "label": "Section 2", "type": "text"},
                    ]
                }

        except Exception as e:
            print(f"[TemplateService] Error parsing XLSX: {e}")
            return {
                "fields": [
                    {"name": "field_1", "label": "Field 1", "type": "text"},
                    {"name": "field_2", "label": "Field 2", "type": "text"},
                ]
            }

    def _extract_sections_from_text(self, text: str) -> List[Dict[str, str]]:
        """Extract sections from text based on common medical note patterns."""
        fields = []

        # Common patterns for section headers (case insensitive)
        patterns = [
            # SOAP
            (r"^Subjective[:|\s]", "subjective", "Subjective"),
            (r"^Objective[:|\s]", "objective", "Objective"),
            (r"^Assessment[:|\s]", "assessment", "Assessment"),
            (r"^Plan[:|\s]", "plan", "Plan"),
            # Swedish
            (r"^Anamnes[:|\s]", "anamnes", "Anamnes"),
            (r"^Status[:|\s]", "status", "Status"),
            (r"^Bedömning[:|\s]", "bedomning", "Bedömning"),
            (r"^Åtgärd[:|\s]", "atgard", "Åtgärd"),
            # SBAR
            (r"^Situation[:|\s]", "situation", "Situation"),
            (r"^Background[:|\s]", "background", "Background"),
            (r"^Bakgrund[:|\s]", "bakgrund", "Bakgrund"),
            # Generic
            (r"^History[:|\s]", "history", "History"),
            (r"^Findings[:|\s]", "findings", "Findings"),
            (r"^Recommendations[:|\s]", "recommendations", "Recommendations"),
        ]

        found_sections = set()
        for pattern, field_name, field_label in patterns:
            if re.search(pattern, text, re.MULTILINE | re.IGNORECASE):
                if field_name not in found_sections:
                    fields.append({
                        "name": field_name,
                        "label": field_label,
                        "type": "text",
                        "description": f"Section for {field_label}"
                    })
                    found_sections.add(field_name)

        # If no sections found, create generic fields
        if not fields:
            fields = [
                {"name": "section_1", "label": "Section 1", "type": "text"},
                {"name": "section_2", "label": "Section 2", "type": "text"},
                {"name": "section_3", "label": "Section 3", "type": "text"},
            ]

        return fields

    async def validate_template_structure(self, structure: Dict[str, Any]) -> bool:
        """Validate template structure format."""
        if not isinstance(structure, dict):
            return False

        if "fields" not in structure:
            return False

        fields = structure["fields"]
        if not isinstance(fields, list):
            return False

        for field in fields:
            if not isinstance(field, dict):
                return False
            if "name" not in field or "label" not in field:
                return False

        return True

    async def get_system_templates(
        self, language: Optional[str] = None
    ) -> List[NoteTemplate]:
        """Get pre-defined system templates."""
        # Use repository to fetch system templates
        # Pass a dummy user_id since system templates are accessible to all
        return await self._repo.list_templates(
            user_id="00000000-0000-0000-0000-000000000000",
            include_system=True,
            language=language,
        )

    async def create_template_from_upload(
        self,
        user_id: str,
        name: str,
        language: str,
        template_type: TemplateType,
        file_content: bytes,
        filename: str,
    ) -> NoteTemplate:
        """Parse uploaded file and create template."""
        # Determine file type
        file_ext = filename.lower().split(".")[-1] if "." in filename else "txt"

        # Parse file
        structure = await self.parse_uploaded_file(
            file_content, filename, file_ext
        )

        # Validate structure
        if not await self.validate_template_structure(structure):
            raise ValueError("Invalid template structure")

        # Create template object
        template = NoteTemplate(
            template_id=str(uuid.uuid4()),
            user_id=user_id,
            name=name,
            language=language,
            template_type=template_type,
            template_structure=structure,
            is_system_template=False,
            file_format=file_ext,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Save to repository
        return await self._repo.create_template(template)