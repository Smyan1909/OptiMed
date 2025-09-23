import fitz  # PyMuPDF
from typing import Dict, Any
from datetime import datetime

from optimed.core.ports import PDFProcessor
from optimed.core.domain.pdf_document import PDFMetadata


class PyMuPDFProcessor(PDFProcessor):
    """PDF processor implementation using PyMuPDF."""

    async def extract_text(self, file_content: bytes) -> str:
        """Extract text content from a PDF file."""
        try:
            # Open PDF from bytes
            doc = fitz.open(stream=file_content, filetype="pdf")

            text_content = []
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text()
                if text.strip():  # Only add non-empty pages
                    text_content.append(f"--- Page {page_num + 1} ---\n{text}")

            doc.close()
            return "\n\n".join(text_content)

        except Exception as e:
            raise ValueError(f"Failed to extract text from PDF: {str(e)}")

    async def extract_metadata(self, file_content: bytes) -> Dict[str, Any]:
        """Extract metadata from a PDF file."""
        try:
            doc = fitz.open(stream=file_content, filetype="pdf")

            # Get PDF metadata
            pdf_metadata = doc.metadata

            # Convert to our domain metadata
            metadata = {
                "title": pdf_metadata.get("title"),
                "author": pdf_metadata.get("author"),
                "subject": pdf_metadata.get("subject"),
                "creator": pdf_metadata.get("creator"),
                "producer": pdf_metadata.get("producer"),
                "page_count": len(doc),
                "file_size": len(file_content)
            }

            # Parse dates if available
            creation_date = pdf_metadata.get("creationDate")
            if creation_date:
                try:
                    # PyMuPDF date format: D:YYYYMMDDHHmmSSOHH'mm'
                    if creation_date.startswith("D:"):
                        date_str = creation_date[2:16]  # Extract YYYYMMDDHHMMSS
                        metadata["creation_date"] = datetime.strptime(date_str, "%Y%m%d%H%M%S")
                except (ValueError, IndexError):
                    pass  # Skip invalid dates

            modification_date = pdf_metadata.get("modDate")
            if modification_date:
                try:
                    if modification_date.startswith("D:"):
                        date_str = modification_date[2:16]
                        metadata["modification_date"] = datetime.strptime(date_str, "%Y%m%d%H%M%S")
                except (ValueError, IndexError):
                    pass

            doc.close()
            return metadata

        except Exception as e:
            raise ValueError(f"Failed to extract metadata from PDF: {str(e)}")

    async def validate_pdf_file(self, file_content: bytes) -> bool:
        """Validate if the file content is a valid PDF file."""
        try:
            doc = fitz.open(stream=file_content, filetype="pdf")
            is_valid = len(doc) > 0  # Valid if it has at least one page
            doc.close()
            return is_valid
        except Exception:
            return False