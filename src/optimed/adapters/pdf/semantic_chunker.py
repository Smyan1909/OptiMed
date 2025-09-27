"""
Fully language-agnostic semantic PDF chunking for medical documents based on 2025 best practices.

Implements advanced chunking strategies optimized for healthcare RAG systems:
- Semantic coherence preservation using structural patterns
- Context-aware overlapping for better continuity
- Universal medical document structure detection (any language)
- Hierarchical chunking for complex documents
- Language-agnostic pattern matching using document structure
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import re


@dataclass
class ChunkMetadata:
    """Metadata for a semantic chunk."""
    chunk_id: str
    document_id: str
    start_page: int
    end_page: int
    section_title: Optional[str] = None
    chunk_type: str = "content"  # content, header, table, list, conclusion
    semantic_context: Optional[str] = None
    overlap_with: List[str] = None

    def __post_init__(self):
        if self.overlap_with is None:
            self.overlap_with = []


@dataclass
class SemanticChunk:
    """A semantically coherent chunk of text from a PDF."""
    text: str
    metadata: ChunkMetadata
    embedding: Optional[List[float]] = None

    @property
    def token_count(self) -> int:
        """Estimate token count (rough approximation)."""
        return len(self.text.split()) * 1.3  # ~1.3 tokens per word for English


class SemanticPDFChunker:
    """
    Fully language-agnostic semantic chunker optimized for medical PDFs.

    Based on 2025 best practices for healthcare RAG systems.
    Uses structural patterns instead of language-specific keywords to work
    with medical documents in any language (English, Swedish, German, French, etc.).
    """

    def __init__(
        self,
        target_chunk_size: int = 800,  # tokens
        overlap_ratio: float = 0.15,   # 15% overlap
        min_chunk_size: int = 100,     # minimum chunk size
        max_chunk_size: int = 1200,    # maximum chunk size
        preserve_medical_context: bool = True
    ):
        self.target_chunk_size = target_chunk_size
        self.overlap_ratio = overlap_ratio
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.preserve_medical_context = preserve_medical_context

        # Fully language-agnostic structural patterns for medical documents
        # Using semantic structure patterns instead of language-specific keywords
        self.medical_section_patterns = [
            # Headers ending with colon (universal medical format)
            r"^[^\s:]{3,50}:\s*$",
            # Numbered sections (1., 2., etc.)
            r"^\d+\.\s*\S",
            # Roman numerals (I., II., III.)
            r"^[IVX]+\.\s*\S",
            # Letter sections (A., B., C.)
            r"^[A-Z]\.\s*\S",
            # Indented subsections (1.1, 2.3, etc.)
            r"^\s{2,}\d+\.\d+\s*\S",
            # Headers with underlines (followed by === or ---)
            r"^.+\n[=\-]{3,}$",
            # Date/time patterns (common in medical docs)
            r"^\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}",
            # Time stamps
            r"^\d{1,2}:\d{2}(?::\d{2})?",
            # Bold/emphasized text (markdown style)
            r"^\*\*.+\*\*$|^__.+__$",
            # Line separators
            r"^[\-=_]{3,}$",
        ]

        # Fully language-agnostic sentence boundary patterns
        self.sentence_boundaries = [
            r'\.(?=\s+\S)',     # Period followed by space and non-whitespace
            r'[.!?](?=\s*\n)',  # End punctuation at line end
            r'\.(?=\s*\d+\.)',  # Period before numbered list
        ]

        # Fully language-agnostic paragraph boundary patterns
        self.paragraph_boundaries = [
            r'\n\s*\n',         # Double newline
            r'\n(?=\s*[^\s:]{3,}:)',  # New section header (any text ending with colon)
            r'\n(?=\s*\d+\.)',  # Numbered list item
            r'\n(?=\s*[•\-\*])', # Bullet point
            r'\n(?=\s*[A-Z]\.\s)', # Letter sections
        ]

    def chunk_pdf_text(
        self,
        text: str,
        document_id: str,
        metadata: Dict[str, Any] = None
    ) -> List[SemanticChunk]:
        """
        Chunk PDF text using semantic awareness for medical documents.

        Args:
            text: Extracted PDF text
            document_id: Unique document identifier
            metadata: Additional document metadata

        Returns:
            List of semantic chunks optimized for medical RAG
        """
        if not text or not text.strip():
            return []

        # Step 1: Detect document structure
        sections = self._detect_document_structure(text)

        # Step 2: Create semantic chunks with context preservation
        chunks = []
        previous_context = ""

        for i, section in enumerate(sections):
            section_chunks = self._chunk_section(
                section,
                document_id,
                previous_context,
                metadata or {}
            )
            chunks.extend(section_chunks)

            # Update context for next section (last 100 chars for continuity)
            if section_chunks:
                previous_context = section_chunks[-1].text[-100:] if len(section_chunks[-1].text) > 100 else section_chunks[-1].text

        # Step 3: Add overlapping context between chunks
        if len(chunks) > 1:
            chunks = self._add_overlapping_context(chunks)

        # Step 4: Validate and optimize chunk sizes
        chunks = self._optimize_chunk_sizes(chunks)

        return chunks

    def _detect_document_structure(self, text: str) -> List[Dict[str, Any]]:
        """Detect sections and structure in medical documents."""
        sections = []
        current_section = {"title": None, "content": "", "start_pos": 0, "type": "content"}

        lines = text.split('\n')
        current_pos = 0

        for line in lines:
            line_stripped = line.strip()

            # Check if this line is a medical section header
            is_header = False
            header_type = None

            for pattern in self.medical_section_patterns:
                if re.match(pattern, line_stripped):
                    is_header = True
                    header_type = "medical_section"
                    break

            # Check for other structural elements
            if not is_header:
                if re.match(r'^\s*\d+\.', line_stripped):  # Numbered list
                    header_type = "numbered_list"
                elif re.match(r'^\s*[•\-\*]', line_stripped):  # Bullet point
                    header_type = "bullet_list"
                elif (len(line_stripped) > 2 and
                      len(line_stripped) < 50 and
                      self._is_structural_header(line_stripped)):
                    is_header = True
                    header_type = "section_header"

            if is_header and current_section["content"].strip():
                # Save current section and start new one
                current_section["end_pos"] = current_pos
                sections.append(current_section)
                current_section = {
                    "title": line_stripped,
                    "content": "",
                    "start_pos": current_pos,
                    "type": header_type
                }
            else:
                current_section["content"] += line + '\n'

            current_pos += len(line) + 1

        # Add final section
        if current_section["content"].strip():
            current_section["end_pos"] = current_pos
            sections.append(current_section)

        return sections

    def _chunk_section(
        self,
        section: Dict[str, Any],
        document_id: str,
        previous_context: str,
        metadata: Dict[str, Any]
    ) -> List[SemanticChunk]:
        """Chunk a single section with semantic awareness."""
        content = section["content"].strip()
        if not content:
            return []

        chunks = []

        # For medical sections, try to preserve semantic boundaries
        if section.get("type") == "medical_section":
            chunks = self._chunk_medical_section(content, section, document_id, previous_context, metadata)
        else:
            chunks = self._chunk_general_content(content, section, document_id, previous_context, metadata)

        return chunks

    def _chunk_medical_section(
        self,
        content: str,
        section: Dict[str, Any],
        document_id: str,
        previous_context: str,
        metadata: Dict[str, Any]
    ) -> List[SemanticChunk]:
        """Chunk medical section content with context preservation."""
        chunks = []

        # Split by paragraphs first to maintain medical context
        paragraphs = re.split(r'\n\s*\n', content)
        current_chunk = ""

        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue

            # Check if adding this paragraph exceeds target size
            potential_chunk = current_chunk + "\n\n" + paragraph if current_chunk else paragraph
            potential_size = len(potential_chunk.split()) * 1.3

            if potential_size <= self.target_chunk_size or not current_chunk:
                current_chunk = potential_chunk
            else:
                # Create chunk from current content
                if current_chunk:
                    chunk_metadata = ChunkMetadata(
                        chunk_id=f"{document_id}_chunk_{len(chunks)}",
                        document_id=document_id,
                        start_page=1,  # TODO: Track actual page numbers
                        end_page=1,
                        section_title=section.get("title"),
                        chunk_type=section.get("type", "content"),
                        semantic_context=previous_context if chunks == 0 and previous_context else None
                    )

                    chunks.append(SemanticChunk(
                        text=current_chunk,
                        metadata=chunk_metadata
                    ))

                # Start new chunk with current paragraph
                current_chunk = paragraph

        # Add final chunk
        if current_chunk:
            chunk_metadata = ChunkMetadata(
                chunk_id=f"{document_id}_chunk_{len(chunks)}",
                document_id=document_id,
                start_page=1,
                end_page=1,
                section_title=section.get("title"),
                chunk_type=section.get("type", "content"),
                semantic_context=previous_context if len(chunks) == 0 and previous_context else None
            )

            chunks.append(SemanticChunk(
                text=current_chunk,
                metadata=chunk_metadata
            ))

        return chunks

    def _chunk_general_content(
        self,
        content: str,
        section: Dict[str, Any],
        document_id: str,
        previous_context: str,
        metadata: Dict[str, Any]
    ) -> List[SemanticChunk]:
        """Chunk general content with sentence-aware splitting."""
        chunks = []

        # Split into sentences for better semantic coherence
        sentences = re.split(r'(?<=[.!?])\s+', content)
        current_chunk = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            potential_chunk = current_chunk + " " + sentence if current_chunk else sentence
            potential_size = len(potential_chunk.split()) * 1.3

            if potential_size <= self.target_chunk_size or not current_chunk:
                current_chunk = potential_chunk
            else:
                # Create chunk
                if current_chunk:
                    chunk_metadata = ChunkMetadata(
                        chunk_id=f"{document_id}_chunk_{len(chunks)}",
                        document_id=document_id,
                        start_page=1,
                        end_page=1,
                        section_title=section.get("title"),
                        chunk_type=section.get("type", "content"),
                        semantic_context=previous_context if len(chunks) == 0 and previous_context else None
                    )

                    chunks.append(SemanticChunk(
                        text=current_chunk,
                        metadata=chunk_metadata
                    ))

                current_chunk = sentence

        # Add final chunk
        if current_chunk:
            chunk_metadata = ChunkMetadata(
                chunk_id=f"{document_id}_chunk_{len(chunks)}",
                document_id=document_id,
                start_page=1,
                end_page=1,
                section_title=section.get("title"),
                chunk_type=section.get("type", "content"),
                semantic_context=previous_context if len(chunks) == 0 and previous_context else None
            )

            chunks.append(SemanticChunk(
                text=current_chunk,
                metadata=chunk_metadata
            ))

        return chunks

    def _add_overlapping_context(self, chunks: List[SemanticChunk]) -> List[SemanticChunk]:
        """Add overlapping context between chunks for better continuity."""
        if not chunks or len(chunks) < 2:
            return chunks

        for i in range(len(chunks) - 1):
            current_chunk = chunks[i]
            next_chunk = chunks[i + 1]

            # Calculate overlap size
            overlap_chars = int(len(current_chunk.text) * self.overlap_ratio)
            if overlap_chars > 0:
                # Take the last part of current chunk as context for next
                overlap_text = current_chunk.text[-overlap_chars:]

                # Prepend to next chunk with separator
                next_chunk.text = f"{overlap_text}\n---\n{next_chunk.text}"
                next_chunk.metadata.overlap_with.append(current_chunk.metadata.chunk_id)

        return chunks

    def _optimize_chunk_sizes(self, chunks: List[SemanticChunk]) -> List[SemanticChunk]:
        """Optimize chunk sizes and merge small chunks."""
        optimized_chunks = []
        i = 0

        while i < len(chunks):
            current_chunk = chunks[i]

            # Check if chunk is too small
            if (current_chunk.token_count < self.min_chunk_size and
                i < len(chunks) - 1 and
                chunks[i + 1].token_count < self.target_chunk_size):

                # Merge with next chunk
                next_chunk = chunks[i + 1]
                merged_text = f"{current_chunk.text}\n\n{next_chunk.text}"

                merged_metadata = ChunkMetadata(
                    chunk_id=current_chunk.metadata.chunk_id,
                    document_id=current_chunk.metadata.document_id,
                    start_page=current_chunk.metadata.start_page,
                    end_page=next_chunk.metadata.end_page,
                    section_title=current_chunk.metadata.section_title,
                    chunk_type="merged",
                    semantic_context=current_chunk.metadata.semantic_context,
                    overlap_with=current_chunk.metadata.overlap_with + next_chunk.metadata.overlap_with
                )

                merged_chunk = SemanticChunk(
                    text=merged_text,
                    metadata=merged_metadata
                )

                optimized_chunks.append(merged_chunk)
                i += 2  # Skip next chunk as it's merged
            else:
                optimized_chunks.append(current_chunk)
                i += 1

        return optimized_chunks

    def _is_structural_header(self, text: str) -> bool:
        """Check if text is a structural header using language-agnostic patterns."""
        # Remove common punctuation and whitespace for analysis
        cleaned_text = re.sub(r'[:\s\-_\.]+', '', text)
        if not cleaned_text:
            return False

        # Language-agnostic structural indicators
        structural_indicators = [
            # Mostly uppercase (any language)
            lambda t: sum(1 for c in t if c.isupper()) / len([c for c in t if c.isalpha()]) > 0.8 if any(c.isalpha() for c in t) else False,
            # Short line with specific formatting patterns
            lambda t: bool(re.match(r'^[^a-z]*[A-Z]', text)) and len(text.strip()) < 30,
            # Contains numbers/special structure
            lambda t: bool(re.search(r'\d+\.|\([a-zA-Z]\)|[IVX]+\.', text)),
            # All caps words (universal pattern)
            lambda t: len(text.split()) <= 5 and all(word.isupper() or not word.isalpha() for word in text.split()),
            # Ends with colon (section header pattern)
            lambda t: text.strip().endswith(':'),
        ]

        return any(indicator(cleaned_text) for indicator in structural_indicators)