import fitz  # PyMuPDF
import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from optimed.core.ports import PDFProcessor
from optimed.core.domain.pdf_document import PDFMetadata


@dataclass
class TextSpan:
    """A text span with position information."""
    text: str
    x0: float  # Left x coordinate
    y0: float  # Top y coordinate
    x1: float  # Right x coordinate
    y1: float  # Bottom y coordinate
    page: int


@dataclass 
class PageTextWithCoords:
    """Page text with coordinate information for table parsing."""
    page_number: int
    spans: List[TextSpan]
    raw_text: str


class PyMuPDFProcessor(PDFProcessor):
    """PDF processor implementation using PyMuPDF."""

    def _clean_pdf_text(self, text: str) -> str:
        """
        Clean PDF text by removing common artifacts and noise.

        Args:
            text: Raw text extracted from PDF

        Returns:
            Cleaned text with artifacts removed
        """
        # Remove page markers that were added during extraction
        text = re.sub(r'---\s*Page\s+\d+\s*---', '', text, flags=re.IGNORECASE)

        # Remove common Swedish PDF artifacts
        text = re.sub(r'\btom rad\b', '', text, flags=re.IGNORECASE)  # "empty row"
        text = re.sub(r'\bSida\s+\d+\s+av\s+\d+\b', '', text, flags=re.IGNORECASE)  # "Page X of Y"

        # Remove excessive whitespace and empty lines
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Multiple blank lines → double newline
        text = re.sub(r'[ \t]+', ' ', text)  # Multiple spaces/tabs → single space

        # Remove common header/footer patterns
        text = re.sub(r'\n\s*Journalkopia\s*\n', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'\n\s*Utskrift ur journal\s*\n', '\n', text, flags=re.IGNORECASE)

        # Remove page footer patterns with timestamps
        text = re.sub(r'\n\s*Journalkopia uttagen\s+\d{4}-\d{2}-\d{2}\s+kl\s+\d{2}:\d{2}[^\n]*\n', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'\n\s*Uttagen av[^\n]*\n', '\n', text, flags=re.IGNORECASE)
        # Remove timestamp lines that may have trailing content (e.g., "2025-11-17 kl 15:45	34HD")
        text = re.sub(r'\n\s*\d{4}-\d{2}-\d{2}\s+kl\s+\d{2}:\d{2}[^\n]*\n', '\n', text)
        # Remove patient demographics header (person number + KOPIA + patient info)  
        text = re.sub(r'\n\s*\d{2}\s+\d{6}-\d{4}\s+KOPIA[^\n]*(?:\n[^\n]+)*?\n(?=\n[A-ZÅÄÖ])', '\n', text, flags=re.DOTALL)

        # Trim leading/trailing whitespace
        text = text.strip()

        return text

    async def extract_text(self, file_content: bytes) -> str:
        """Extract and clean text content from a PDF file."""
        try:
            # Open PDF from bytes
            doc = fitz.open(stream=file_content, filetype="pdf")

            text_content = []
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text()

                if text.strip():  # Only add non-empty pages
                    # Clean the text before adding
                    cleaned_text = self._clean_pdf_text(text)
                    if cleaned_text:  # Only add if there's content after cleaning
                        text_content.append(cleaned_text)

            doc.close()

            # Join pages with clear separator (but not the page marker)
            full_text = "\n\n".join(text_content)

            return full_text

        except Exception as e:
            raise ValueError(f"Failed to extract text from PDF: {str(e)}")

    async def extract_metadata(self, file_content: bytes) -> PDFMetadata:
        """Extract metadata from a PDF file."""
        try:
            doc = fitz.open(stream=file_content, filetype="pdf")

            # Get PDF metadata
            pdf_metadata = doc.metadata

            # Parse dates if available
            creation_date = None
            modification_date = None

            creation_date_str = pdf_metadata.get("creationDate")
            if creation_date_str:
                try:
                    # PyMuPDF date format: D:YYYYMMDDHHmmSSOHH'mm'
                    if creation_date_str.startswith("D:"):
                        date_str = creation_date_str[2:16]  # Extract YYYYMMDDHHMMSS
                        creation_date = datetime.strptime(date_str, "%Y%m%d%H%M%S")
                except (ValueError, IndexError):
                    pass  # Skip invalid dates

            modification_date_str = pdf_metadata.get("modDate")
            if modification_date_str:
                try:
                    if modification_date_str.startswith("D:"):
                        date_str = modification_date_str[2:16]
                        modification_date = datetime.strptime(date_str, "%Y%m%d%H%M%S")
                except (ValueError, IndexError):
                    pass

            # Convert to our domain metadata
            metadata = PDFMetadata(
                title=pdf_metadata.get("title"),
                author=pdf_metadata.get("author"),
                subject=pdf_metadata.get("subject"),
                creator=pdf_metadata.get("creator"),
                producer=pdf_metadata.get("producer"),
                creation_date=creation_date,
                modification_date=modification_date,
                page_count=len(doc),
                file_size=len(file_content)
            )

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

    async def extract_text_with_coords(self, file_content: bytes) -> List[PageTextWithCoords]:
        """
        Extract text with coordinate information from a PDF file.
        
        This method extracts text spans with their x,y coordinates, which is useful
        for table parsing where column alignment matters.
        
        Args:
            file_content: PDF file content as bytes
            
        Returns:
            List of PageTextWithCoords, one per page
        """
        try:
            doc = fitz.open(stream=file_content, filetype="pdf")
            pages_data: List[PageTextWithCoords] = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                
                # Get words with coordinates
                # Returns list of (x0, y0, x1, y1, word, block_no, line_no, word_no)
                words = page.get_text("words")
                
                spans: List[TextSpan] = []
                for word_data in words:
                    x0, y0, x1, y1, text, block_no, line_no, word_no = word_data
                    spans.append(TextSpan(
                        text=text,
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                        page=page_num
                    ))
                
                # Also get raw text for this page
                raw_text = page.get_text()
                cleaned_text = self._clean_pdf_text(raw_text)
                
                pages_data.append(PageTextWithCoords(
                    page_number=page_num + 1,  # 1-indexed
                    spans=spans,
                    raw_text=cleaned_text
                ))
            
            doc.close()
            return pages_data
            
        except Exception as e:
            raise ValueError(f"Failed to extract text with coordinates from PDF: {str(e)}")