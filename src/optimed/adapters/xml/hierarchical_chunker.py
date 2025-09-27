"""
Hierarchical XML Chunker for RAG Systems

Implements structure-aware, language-agnostic XML chunking strategies
optimized for medical documents and retrieval-augmented generation.
"""

import lxml.etree as etree
from typing import List, Dict, Any
import re
from dataclasses import dataclass


@dataclass
class XMLChunk:
    """Represents a semantic chunk from XML content."""
    content: str
    metadata: Dict[str, Any]
    xpath: str
    element_type: str
    level: int
    token_estimate: int


class HierarchicalXMLChunker:
    """
    Advanced XML chunker that creates semantic chunks based on document structure.

    Features:
    - Hierarchical chunking (sections → subsections → elements)
    - Structure-aware boundaries
    - Metadata preservation
    - Language-agnostic processing
    - Medical document optimization
    """

    def __init__(self,
                 target_chunk_size: int = 600,
                 min_chunk_size: int = 200,
                 max_chunk_size: int = 1000,
                 preserve_context: bool = True):
        """
        Initialize the hierarchical XML chunker.

        Args:
            target_chunk_size: Target tokens per chunk
            min_chunk_size: Minimum tokens per chunk
            max_chunk_size: Maximum tokens per chunk
            preserve_context: Whether to include parent context in chunks
        """
        self.target_chunk_size = target_chunk_size
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.preserve_context = preserve_context

        # Medical XML patterns for enhanced processing
        self.medical_section_patterns = {
            'patient_info': ['patient', 'demographics', 'personal'],
            'conditions': ['condition', 'diagnosis', 'problem', 'disease'],
            'medications': ['medication', 'drug', 'prescription', 'treatment'],
            'observations': ['observation', 'vital', 'lab', 'test', 'result'],
            'procedures': ['procedure', 'surgery', 'operation', 'intervention'],
            'notes': ['note', 'narrative', 'comment', 'report', 'summary']
        }

    def chunk_xml_document(self, xml_content: str, document_metadata: Dict[str, Any] = None) -> List[XMLChunk]:
        """
        Chunk XML document using hierarchical structure-aware strategy.

        Args:
            xml_content: Raw XML content string
            document_metadata: Optional metadata about the document

        Returns:
            List of XMLChunk objects with semantic content and metadata
        """
        try:
            # Parse XML
            root = etree.fromstring(xml_content.encode('utf-8'))

            # Initialize chunking context
            document_metadata = document_metadata or {}

            # Strategy 1: Major section chunking
            major_chunks = self._chunk_major_sections(root, document_metadata)

            # Strategy 2: Hierarchical subdivision for large sections
            refined_chunks = []
            for chunk in major_chunks:
                if chunk.token_estimate > self.max_chunk_size:
                    # Subdivide large chunks
                    sub_chunks = self._subdivide_large_chunk(chunk, xml_content)
                    refined_chunks.extend(sub_chunks)
                elif chunk.token_estimate < self.min_chunk_size:
                    # Combine small chunks with neighbors
                    refined_chunks.append(chunk)  # Will combine in post-processing
                else:
                    refined_chunks.append(chunk)

            # Strategy 3: Post-process to optimize chunk sizes
            final_chunks = self._post_process_chunks(refined_chunks)

            return final_chunks

        except etree.XMLSyntaxError as e:
            raise ValueError(f"Invalid XML content: {e}")
        except Exception as e:
            raise ValueError(f"XML chunking failed: {e}")

    def _chunk_major_sections(self, root: etree._Element, doc_metadata: Dict[str, Any]) -> List[XMLChunk]:
        """Create chunks for major document sections."""
        chunks = []

        # Document header chunk
        header_content = self._create_document_header(root, doc_metadata)
        if header_content:
            chunks.append(XMLChunk(
                content=header_content,
                metadata={
                    'section_type': 'document_header',
                    'element_name': root.tag,
                    'level': 0,
                    **doc_metadata
                },
                xpath=f'/{root.tag}',
                element_type='document_header',
                level=0,
                token_estimate=self._estimate_tokens(header_content)
            ))

        # Process each major section
        for i, child in enumerate(root):
            section_chunks = self._process_section_element(child, i, doc_metadata, level=1)
            chunks.extend(section_chunks)

        return chunks

    def _process_section_element(self, element: etree._Element, index: int,
                                doc_metadata: Dict[str, Any], level: int) -> List[XMLChunk]:
        """Process a section element and create appropriate chunks."""
        chunks = []
        element_name = self._clean_element_name(element.tag)

        # Determine section type for medical documents
        section_type = self._classify_medical_section(element_name)

        # Create section header
        section_header = self._create_section_header(element, section_type, level)

        # Process content based on section type and size
        if len(list(element)) == 0:
            # Leaf element - create single chunk
            content = section_header + self._extract_element_text(element)
            chunks.append(XMLChunk(
                content=content,
                metadata={
                    'section_type': section_type,
                    'element_name': element_name,
                    'level': level,
                    'index': index,
                    **doc_metadata
                },
                xpath=self._get_xpath(element),
                element_type='leaf_element',
                level=level,
                token_estimate=self._estimate_tokens(content)
            ))
        else:
            # Container element - process children
            if self._should_group_children(element):
                # Group all children into one chunk
                content = section_header + self._extract_grouped_content(element)
                chunks.append(XMLChunk(
                    content=content,
                    metadata={
                        'section_type': section_type,
                        'element_name': element_name,
                        'level': level,
                        'index': index,
                        'child_count': len(list(element)),
                        **doc_metadata
                    },
                    xpath=self._get_xpath(element),
                    element_type='grouped_section',
                    level=level,
                    token_estimate=self._estimate_tokens(content)
                ))
            else:
                # Process children individually
                for j, child in enumerate(element):
                    child_chunks = self._process_section_element(child, j, doc_metadata, level + 1)
                    # Add section context to child chunks
                    for chunk in child_chunks:
                        chunk.content = section_header + chunk.content
                        chunk.metadata['parent_section'] = section_type
                        chunk.metadata['parent_element'] = element_name
                    chunks.extend(child_chunks)

        return chunks

    def _should_group_children(self, element: etree._Element) -> bool:
        """Determine if child elements should be grouped into one chunk."""
        children = list(element)

        # Group if small number of simple children
        if len(children) <= 3:
            return True

        # Group if all children are simple leaf elements
        all_simple = all(len(list(child)) == 0 for child in children)
        if all_simple and len(children) <= 10:
            return True

        # Group if total estimated content is reasonable
        total_text = self._extract_grouped_content(element)
        if self._estimate_tokens(total_text) <= self.target_chunk_size:
            return True

        return False

    def _extract_grouped_content(self, element: etree._Element) -> str:
        """Extract content from element with all children grouped together."""
        content_parts = []

        # Add element's direct text
        if element.text and element.text.strip():
            content_parts.append(element.text.strip())

        # Process children
        for child in element:
            child_content = self._extract_element_with_context(child)
            if child_content.strip():
                content_parts.append(child_content.strip())

        return '\n\n'.join(content_parts)

    def _extract_element_with_context(self, element: etree._Element) -> str:
        """Extract element content with contextual formatting."""
        parts = []
        element_name = self._clean_element_name(element.tag)

        # Add element label for context
        if element_name.lower() not in ['text', 'content', 'value', 'data']:
            parts.append(f"{element_name.replace('_', ' ').title()}:")

        # Extract text content recursively
        text_content = self._extract_element_text(element)
        if text_content.strip():
            parts.append(text_content.strip())

        return ' '.join(parts)

    def _extract_element_text(self, element: etree._Element) -> str:
        """Extract all text content from an element recursively."""
        # Use etree's text extraction but clean it up
        text = etree.tostring(element, method='text', encoding='unicode')

        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n\n', text)

        return text.strip()

    def _create_document_header(self, root: etree._Element, metadata: Dict[str, Any]) -> str:
        """Create a document header chunk with key information."""
        header_parts = []

        # Document type
        doc_type = metadata.get('document_type', 'Unknown')
        filename = metadata.get('filename', 'Unknown')
        header_parts.append(f"Document: {filename} (Type: {doc_type})")

        # Root element info
        root_name = self._clean_element_name(root.tag)
        header_parts.append(f"Root Element: {root_name}")

        # Document structure overview
        section_count = len(list(root))
        header_parts.append(f"Sections: {section_count}")

        # Add any metadata from XML attributes
        if root.attrib:
            for key, value in root.attrib.items():
                header_parts.append(f"{key}: {value}")

        return '\n'.join(header_parts) + '\n\n'

    def _create_section_header(self, element: etree._Element, section_type: str, level: int) -> str:
        """Create a contextual header for a section."""
        element_name = self._clean_element_name(element.tag)

        # Create header with appropriate formatting
        header_prefix = '---' if level == 1 else '>>>'
        header = f"{header_prefix} {element_name.replace('_', ' ').title()}"

        # Add section type context
        if section_type != 'unknown':
            header += f" ({section_type.replace('_', ' ').title()})"

        header += " ---\n\n"

        return header

    def _classify_medical_section(self, element_name: str) -> str:
        """Classify an XML element as a medical section type."""
        element_lower = element_name.lower()

        for section_type, patterns in self.medical_section_patterns.items():
            if any(pattern in element_lower for pattern in patterns):
                return section_type

        return 'unknown'

    def _subdivide_large_chunk(self, large_chunk: XMLChunk, original_xml: str) -> List[XMLChunk]:
        """Subdivide a chunk that's too large into smaller semantic chunks."""
        # For now, use simple text splitting but preserve structure
        content = large_chunk.content
        target_size = self.target_chunk_size

        # Split on double newlines (section boundaries)
        sections = content.split('\n\n')

        chunks = []
        current_chunk = []
        current_size = 0

        for section in sections:
            section_size = self._estimate_tokens(section)

            if current_size + section_size <= target_size:
                current_chunk.append(section)
                current_size += section_size
            else:
                # Finish current chunk
                if current_chunk:
                    chunk_content = '\n\n'.join(current_chunk)
                    chunks.append(XMLChunk(
                        content=chunk_content,
                        metadata={**large_chunk.metadata, 'subdivision': len(chunks)},
                        xpath=large_chunk.xpath,
                        element_type='subdivided_chunk',
                        level=large_chunk.level,
                        token_estimate=current_size
                    ))

                # Start new chunk
                current_chunk = [section]
                current_size = section_size

        # Add final chunk
        if current_chunk:
            chunk_content = '\n\n'.join(current_chunk)
            chunks.append(XMLChunk(
                content=chunk_content,
                metadata={**large_chunk.metadata, 'subdivision': len(chunks)},
                xpath=large_chunk.xpath,
                element_type='subdivided_chunk',
                level=large_chunk.level,
                token_estimate=current_size
            ))

        return chunks if chunks else [large_chunk]

    def chunk_extracted_text(self, extracted_text: str, document_metadata: Dict[str, Any] = None) -> List[XMLChunk]:
        """
        Chunk already-extracted XML text using semantic boundaries.

        This method works with text that has already been extracted from XML,
        rather than parsing raw XML. It uses semantic patterns to create
        meaningful chunks for medical documents.

        Args:
            extracted_text: Already extracted text content from XML
            document_metadata: Optional metadata about the document

        Returns:
            List of XMLChunk objects with semantic content and metadata
        """
        try:
            document_metadata = document_metadata or {}

            # Split extracted text into logical sections
            sections = self._split_extracted_text_by_structure(extracted_text)

            chunks = []
            for i, section in enumerate(sections):
                # Create chunk for each section
                section_type = self._classify_section_from_text(section['content'])

                # Clean content for ML model compatibility
                clean_content = self._clean_text_for_processing(section['content'])

                chunk = XMLChunk(
                    content=clean_content,
                    metadata={
                        'section_type': section_type,
                        'section_title': section.get('title', f'Section {i+1}'),
                        'level': 1,
                        'index': i,
                        **document_metadata
                    },
                    xpath=f"/section[{i+1}]",
                    element_type=section_type,
                    level=1,
                    token_estimate=self._estimate_tokens(clean_content)
                )

                # Check if section is too large and needs subdivision
                if chunk.token_estimate > self.max_chunk_size:
                    sub_chunks = self._subdivide_text_chunk(chunk)
                    chunks.extend(sub_chunks)
                else:
                    chunks.append(chunk)

            # Post-process to optimize chunk sizes
            final_chunks = self._post_process_chunks(chunks)

            return final_chunks

        except Exception as e:
            raise ValueError(f"Text chunking failed: {e}")

    def _split_extracted_text_by_structure(self, text: str) -> List[Dict[str, str]]:
        """Split extracted text into logical sections based on structure markers."""
        sections = []

        # Split on section headers (lines that look like headers)
        lines = text.split('\n')
        current_section = []
        current_title = None

        for line in lines:
            line = line.strip()

            # Check if line looks like a section header
            if self._is_section_header(line):
                # Finish previous section
                if current_section:
                    content = '\n'.join(current_section).strip()
                    if content:
                        sections.append({
                            'title': current_title or 'Section',
                            'content': content
                        })
                    current_section = []

                # Start new section
                current_title = line.replace('---', '').replace('>>>', '').strip()

            else:
                # Add to current section
                if line:  # Skip empty lines
                    current_section.append(line)

        # Add final section
        if current_section:
            content = '\n'.join(current_section).strip()
            if content:
                sections.append({
                    'title': current_title or 'Final Section',
                    'content': content
                })

        # If no sections found, split by double newlines
        if not sections:
            paragraphs = text.split('\n\n')
            for i, paragraph in enumerate(paragraphs):
                paragraph = paragraph.strip()
                if paragraph:
                    sections.append({
                        'title': f'Paragraph {i+1}',
                        'content': paragraph
                    })

        return sections

    def _is_section_header(self, line: str) -> bool:
        """Check if a line looks like a section header."""
        line = line.strip()

        # Common header patterns
        header_patterns = [
            r'^---.*---$',  # --- Header ---
            r'^>>>.*$',     # >>> Header
            r'^[A-Z][A-Z\s]{2,}:?\s*$',  # ALL CAPS headers
            r'^Document\s+Type:',  # Document Type:
            r'^[A-Za-z\s]+Information\s*:?\s*$',  # Patient Information:
            r'^[A-Za-z\s]+(:|：)\s*$',  # Headers ending with colon
        ]

        for pattern in header_patterns:
            if re.match(pattern, line):
                return True

        return False

    def _classify_section_from_text(self, content: str) -> str:
        """Classify a text section based on its content."""
        content_lower = content.lower()

        # Medical section classification based on keywords
        for section_type, patterns in self.medical_section_patterns.items():
            if any(pattern in content_lower for pattern in patterns):
                return section_type

        # Additional classification based on content patterns
        if any(keyword in content_lower for keyword in ['patient', 'name', 'dob', 'gender', 'address']):
            return 'patient_info'
        elif any(keyword in content_lower for keyword in ['mg', 'tablet', 'dose', 'per os', 'x 1', 'x 2']):
            return 'medications'
        elif any(keyword in content_lower for keyword in ['beats/minute', 'breaths/minute', '°c', 'ng/l', 'g/l']):
            return 'observations'
        elif any(keyword in content_lower for keyword in ['anledning', 'anamnes', 'status', 'bedömning', 'plan']):
            return 'notes'

        return 'general_content'

    def _subdivide_text_chunk(self, large_chunk: XMLChunk) -> List[XMLChunk]:
        """Subdivide a text chunk that's too large into smaller chunks."""
        content = large_chunk.content

        # Try to split on paragraph boundaries first
        paragraphs = content.split('\n\n')

        if len(paragraphs) <= 1:
            # No paragraph breaks, split on sentence boundaries
            sentences = re.split(r'[.!?]+\s+', content)
            paragraphs = []
            current_para = []

            for sentence in sentences:
                current_para.append(sentence)
                # Combine sentences into paragraph-sized chunks
                if len(' '.join(current_para)) > 200:
                    paragraphs.append(' '.join(current_para))
                    current_para = []

            if current_para:
                paragraphs.append(' '.join(current_para))

        # Group paragraphs into optimally-sized chunks
        chunks = []
        current_chunk = []
        current_size = 0

        for paragraph in paragraphs:
            para_size = self._estimate_tokens(paragraph)

            if current_size + para_size <= self.target_chunk_size:
                current_chunk.append(paragraph)
                current_size += para_size
            else:
                # Finish current chunk
                if current_chunk:
                    chunk_content = '\n\n'.join(current_chunk)
                    clean_chunk_content = self._clean_text_for_processing(chunk_content)
                    chunks.append(XMLChunk(
                        content=clean_chunk_content,
                        metadata={**large_chunk.metadata, 'subdivision': len(chunks)},
                        xpath=large_chunk.xpath,
                        element_type='subdivided_text_chunk',
                        level=large_chunk.level,
                        token_estimate=self._estimate_tokens(clean_chunk_content)
                    ))

                # Start new chunk
                current_chunk = [paragraph]
                current_size = para_size

        # Add final chunk
        if current_chunk:
            chunk_content = '\n\n'.join(current_chunk)
            clean_chunk_content = self._clean_text_for_processing(chunk_content)
            chunks.append(XMLChunk(
                content=clean_chunk_content,
                metadata={**large_chunk.metadata, 'subdivision': len(chunks)},
                xpath=large_chunk.xpath,
                element_type='subdivided_text_chunk',
                level=large_chunk.level,
                token_estimate=self._estimate_tokens(clean_chunk_content)
            ))

        return chunks if chunks else [large_chunk]

    def _post_process_chunks(self, chunks: List[XMLChunk]) -> List[XMLChunk]:
        """Post-process chunks to optimize sizes and remove duplicates."""
        if not chunks:
            return []

        # Combine very small adjacent chunks
        optimized_chunks = []
        current_group = []
        current_size = 0

        for chunk in chunks:
            if chunk.token_estimate < self.min_chunk_size and current_size + chunk.token_estimate <= self.target_chunk_size:
                current_group.append(chunk)
                current_size += chunk.token_estimate
            else:
                # Finish current group
                if current_group:
                    if len(current_group) == 1:
                        optimized_chunks.append(current_group[0])
                    else:
                        # Combine multiple small chunks
                        combined_content = '\n\n'.join(c.content for c in current_group)
                        clean_combined_content = self._clean_text_for_processing(combined_content)
                        combined_metadata = current_group[0].metadata.copy()
                        combined_metadata['combined_chunks'] = len(current_group)

                        optimized_chunks.append(XMLChunk(
                            content=clean_combined_content,
                            metadata=combined_metadata,
                            xpath=current_group[0].xpath,
                            element_type='combined_chunk',
                            level=min(c.level for c in current_group),
                            token_estimate=self._estimate_tokens(clean_combined_content)
                        ))

                # Start new group
                current_group = [chunk]
                current_size = chunk.token_estimate

        # Handle final group
        if current_group:
            if len(current_group) == 1:
                optimized_chunks.append(current_group[0])
            else:
                combined_content = '\n\n'.join(c.content for c in current_group)
                clean_combined_content = self._clean_text_for_processing(combined_content)
                combined_metadata = current_group[0].metadata.copy()
                combined_metadata['combined_chunks'] = len(current_group)

                optimized_chunks.append(XMLChunk(
                    content=clean_combined_content,
                    metadata=combined_metadata,
                    xpath=current_group[0].xpath,
                    element_type='combined_chunk',
                    level=min(c.level for c in current_group),
                    token_estimate=self._estimate_tokens(clean_combined_content)
                ))

        return optimized_chunks

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text (rough approximation)."""
        # Simple heuristic: ~4 characters per token for most languages
        return max(1, len(text) // 4)

    def _clean_text_for_processing(self, text: str) -> str:
        """Clean text to ensure compatibility with downstream ML models."""
        if not text:
            return ""

        try:
            # Normalize unicode to handle potential encoding issues
            import unicodedata
            text = unicodedata.normalize('NFKC', text)

            # Ensure proper UTF-8 encoding/decoding
            text = text.encode('utf-8', errors='ignore').decode('utf-8')

            # Remove any null bytes or other problematic characters
            text = text.replace('\x00', '').replace('\ufeff', '')

            # Normalize whitespace
            text = re.sub(r'\s+', ' ', text)
            text = re.sub(r'\n\s*\n', '\n\n', text)

            return text.strip()

        except Exception:
            # Fallback: return ASCII-only version if cleaning fails
            return text.encode('ascii', errors='ignore').decode('ascii').strip()

    def _clean_element_name(self, tag: str) -> str:
        """Clean XML element name for display."""
        # Remove namespace if present
        if '}' in tag:
            tag = tag.split('}')[-1]
        return tag

    def _get_xpath(self, element: etree._Element) -> str:
        """Get XPath for an element."""
        try:
            return element.getroottree().getpath(element)
        except Exception:
            return f"//{self._clean_element_name(element.tag)}"