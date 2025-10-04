from __future__ import annotations

import uuid
import re
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from optimed.core.domain import NoteTemplate, TemplateType
from optimed.core.ports import TemplateService, TemplateRepository
from optimed.core.logging_utils import get_logger, log_error

logger = get_logger(__name__)


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
        """Parse plain text template using heuristic analysis."""
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        # Extract sections using heuristic patterns (language-agnostic)
        fields = self._extract_sections_by_heuristics(text)

        return {"fields": fields}

    async def _parse_docx(self, content: bytes) -> Dict[str, Any]:
        """
        Parse Word document template using structural analysis.

        Detects sections based on document structure (headings, bold text)
        rather than hardcoded section names. Language-agnostic.
        """
        try:
            # Try python-docx for structural analysis
            try:
                import docx
                import io

                doc = docx.Document(io.BytesIO(content))
                fields = self._extract_sections_from_docx_structure(doc)

                # If structural extraction found fields, use those
                if fields:
                    return {"fields": fields}

                # Otherwise fall back to text extraction
                text = "\n".join([para.text for para in doc.paragraphs])
                fields = self._extract_sections_by_heuristics(text)
                return {"fields": fields}

            except ImportError:
                # Fallback: Just decode as text (not ideal but functional)
                text = content.decode("utf-8", errors="ignore")
                fields = self._extract_sections_by_heuristics(text)
                return {"fields": fields}

        except Exception as e:
            log_error(logger, "parse DOCX", e)
            # Fallback to text parsing
            return await self._parse_text(content)

    async def _parse_pdf(self, content: bytes) -> Dict[str, Any]:
        """
        Parse PDF template using PyMuPDF with structural analysis.

        Uses font size and formatting to detect section headers.
        Language-agnostic approach.
        """
        try:
            # Use PyMuPDF (fitz) for PDF text extraction with formatting info
            try:
                import fitz  # PyMuPDF

                # Open PDF from bytes
                doc = fitz.open(stream=content, filetype="pdf")

                # Try structural extraction first
                fields = self._extract_sections_from_pdf_structure(doc)
                doc.close()

                # If structural extraction found fields, use those
                if fields:
                    return {"fields": fields}

                # Otherwise fall back to heuristic text analysis
                doc = fitz.open(stream=content, filetype="pdf")
                text_parts = []
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    page_text = page.get_text()
                    if page_text.strip():
                        text_parts.append(page_text)
                doc.close()

                text = "\n".join(text_parts)
                fields = self._extract_sections_by_heuristics(text)
                return {"fields": fields}

            except ImportError:
                # Fallback: Decode as text (very basic)
                text = content.decode("utf-8", errors="ignore")
                fields = self._extract_sections_by_heuristics(text)
                return {"fields": fields}

        except Exception as e:
            log_error(logger, "parse PDF", e)
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
            log_error(logger, "parse XLSX", e)
            return {
                "fields": [
                    {"name": "field_1", "label": "Field 1", "type": "text"},
                    {"name": "field_2", "label": "Field 2", "type": "text"},
                ]
            }

    def _extract_sections_from_docx_structure(self, doc) -> List[Dict[str, str]]:
        """
        Extract sections from DOCX based on document structure.

        Language-agnostic: Detects headers based on:
        - Paragraph styles (Heading 1, Heading 2, etc.)
        - Bold formatting
        - Short paragraphs followed by content
        """
        fields = []
        seen_headers = set()

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            # Check if this is a heading based on style
            is_heading = False
            if para.style.name.startswith('Heading'):
                is_heading = True
            # Check if paragraph is bold (all runs are bold)
            elif para.runs and all(run.bold for run in para.runs if run.text.strip()):
                is_heading = True
            # Check for short lines ending with colon (likely headers)
            elif len(text) < 100 and text.endswith(':'):
                is_heading = True

            if is_heading:
                # Create field name from the header text
                field_name = self._sanitize_field_name(text)
                field_label = text.rstrip(':').strip()

                if field_name and field_name not in seen_headers:
                    fields.append({
                        "name": field_name,
                        "label": field_label,
                        "type": "text",
                        "description": f"Section for {field_label}"
                    })
                    seen_headers.add(field_name)

        return fields

    def _extract_sections_from_pdf_structure(self, doc) -> List[Dict[str, str]]:
        """
        Extract sections from PDF based on font formatting.

        Language-agnostic: Detects headers based on:
        - Larger font sizes
        - Bold text
        - Short lines with distinct formatting
        """
        fields = []
        seen_headers = set()

        # Collect font size statistics to determine what's "large"
        font_sizes = []
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            blocks = page.get_text("dict")["blocks"]

            for block in blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            font_sizes.append(span["size"])

        if not font_sizes:
            return []

        # Calculate average and threshold for "heading" font size
        avg_size = sum(font_sizes) / len(font_sizes)
        heading_threshold = avg_size * 1.1  # 10% larger than average

        # Extract headers
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            blocks = page.get_text("dict")["blocks"]

            for block in blocks:
                if "lines" not in block:
                    continue

                for line in block["lines"]:
                    # Get line text
                    line_text = "".join([span["text"] for span in line["spans"]]).strip()
                    if not line_text or len(line_text) > 150:  # Skip very long lines
                        continue

                    # Check if line has heading characteristics
                    is_heading = False
                    for span in line["spans"]:
                        # Check font size
                        if span["size"] >= heading_threshold:
                            is_heading = True
                        # Check bold
                        if "bold" in span["font"].lower():
                            is_heading = True

                    # Also check for colon endings
                    if line_text.endswith(':'):
                        is_heading = True

                    if is_heading:
                        field_name = self._sanitize_field_name(line_text)
                        field_label = line_text.rstrip(':').strip()

                        if field_name and field_name not in seen_headers:
                            fields.append({
                                "name": field_name,
                                "label": field_label,
                                "type": "text",
                                "description": f"Section for {field_label}"
                            })
                            seen_headers.add(field_name)

        return fields

    def _extract_sections_by_heuristics(self, text: str) -> List[Dict[str, str]]:
        """
        Extract sections from plain text using heuristic patterns.

        Language-agnostic: Detects headers based on:
        - Lines ending with ':'
        - Short lines (< 80 chars) in TITLE CASE or ALL CAPS
        - Lines with numbering (1., 2., etc.)
        - Blank lines separating sections
        """
        fields = []
        seen_headers = set()
        lines = text.split('\n')

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            is_header = False

            # Pattern 1: Lines ending with colon
            if stripped.endswith(':') and len(stripped) < 100:
                is_header = True

            # Pattern 2: Short lines that are ALL CAPS or Title Case
            elif len(stripped) < 80:
                # Check if TITLE CASE (most words start with capital)
                words = stripped.split()
                if words:
                    capitalized_words = sum(1 for w in words if w and w[0].isupper())
                    if capitalized_words / len(words) >= 0.6:  # 60% of words capitalized
                        is_header = True
                    # Check if ALL CAPS
                    elif stripped.isupper() and len(stripped) > 3:
                        is_header = True

            # Pattern 3: Numbered sections (1., 2., A., etc.)
            elif re.match(r'^[\d\w]+\.[\s)]', stripped) and len(stripped) < 100:
                is_header = True

            if is_header:
                field_name = self._sanitize_field_name(stripped)
                field_label = stripped.rstrip(':').strip()

                if field_name and field_name not in seen_headers:
                    fields.append({
                        "name": field_name,
                        "label": field_label,
                        "type": "text",
                        "description": f"Section for {field_label}"
                    })
                    seen_headers.add(field_name)

        # If no sections found, create generic fields
        if not fields:
            fields = [
                {"name": "section_1", "label": "Section 1", "type": "text"},
                {"name": "section_2", "label": "Section 2", "type": "text"},
                {"name": "section_3", "label": "Section 3", "type": "text"},
            ]

        return fields

    def _sanitize_field_name(self, text: str) -> str:
        """
        Convert header text to valid field name.

        Examples:
        - "Patient Information:" -> "patient_information"
        - "Bedömning" -> "bedomning"
        - "1. Chief Complaint" -> "chief_complaint"
        """
        # Remove common prefixes (numbers, bullets)
        text = re.sub(r'^[\d\w]+\.[\s)]', '', text)
        # Remove colons and special chars
        text = text.rstrip(':').strip()
        # Replace Swedish characters
        text = text.replace('å', 'a').replace('ä', 'a').replace('ö', 'o')
        text = text.replace('Å', 'A').replace('Ä', 'A').replace('Ö', 'O')
        # Convert to lowercase and replace spaces/special chars with underscore
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', '_', text.lower())
        # Remove leading/trailing underscores
        text = text.strip('_')

        return text

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