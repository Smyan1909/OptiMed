"""
XML Semantic Chunker for Medical Documents

Implements advanced chunking strategies optimized for XML-based healthcare RAG systems:
- Structure-aware chunking that respects XML hierarchy
- Medical document type-specific chunking (HL7 CDA, FHIR)
- Context-aware overlapping for better continuity
- Hierarchical chunking for complex nested structures
- Namespace-aware processing for multi-format support
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import lxml.etree as etree
import re


@dataclass
class XMLChunkMetadata:
    """Metadata for an XML semantic chunk."""
    chunk_id: str
    document_id: str
    xml_path: str  # XPath to the source element
    element_type: str  # Type of XML element (section, entry, text, etc.)
    namespace: Optional[str] = None
    parent_element: Optional[str] = None
    section_title: Optional[str] = None
    chunk_type: str = "content"  # content, header, section, entry, narrative
    semantic_context: Optional[str] = None
    overlap_with: Optional[List[str]] = None
    attributes: Optional[Dict[str, str]] = None

    def __post_init__(self):
        if self.overlap_with is None:
            self.overlap_with = []
        if self.attributes is None:
            self.attributes = {}


@dataclass
class XMLSemanticChunk:
    """A semantically coherent chunk of content from an XML document."""
    text: str
    metadata: XMLChunkMetadata
    structured_data: Optional[Dict[str, Any]] = None  # Original XML structure
    embedding: Optional[List[float]] = None

    @property
    def token_count(self) -> int:
        """Estimate token count (rough approximation)."""
        return int(len(self.text.split()) * 1.3)  # ~1.3 tokens per word


class XMLSemanticChunker:
    """
    Structure-aware semantic chunker optimized for XML medical documents.

    Supports multiple medical document formats:
    - HL7 Clinical Document Architecture (CDA)

    Provides backwards compatibility methods for RAG integration.
    """

    def chunk_xml_text(
        self,
        extracted_text: str,
        document_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Backwards compatibility method for RAG system integration.
        Converts extracted text into chunks compatible with RAG processing.

        Args:
            extracted_text: Already extracted text content
            document_id: Document identifier
            metadata: Document metadata

        Returns:
            List of dictionaries with 'content' key for compatibility
        """
        # Create simple text-based chunks for RAG compatibility
        chunks = []

        # Split by sections (marked with "--- Section:")
        sections = re.split(r'\n\n--- Section[:\s]', extracted_text)

        for i, section in enumerate(sections):
            if not section.strip():
                continue

            # Create chunk dict for RAG compatibility
            chunk_dict = {
                "content": section.strip(),
                "section_index": i,
                "document_id": document_id,
                "metadata": metadata or {}
            }
            chunks.append(chunk_dict)

        # If no sections found, create single chunk
        if not chunks and extracted_text.strip():
            chunks.append({
                "content": extracted_text.strip(),
                "section_index": 0,
                "document_id": document_id,
                "metadata": metadata or {}
            })

        return chunks

    def __init__(
        self,
        target_chunk_size: int = 800,  # tokens
        overlap_ratio: float = 0.15,   # 15% overlap
        min_chunk_size: int = 100,     # minimum chunk size
        max_chunk_size: int = 1200,    # maximum chunk size
        preserve_structure: bool = True,
        preserve_medical_context: bool = True
    ):
        self.target_chunk_size = target_chunk_size
        self.overlap_ratio = overlap_ratio
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.preserve_structure = preserve_structure
        self.preserve_medical_context = preserve_medical_context

        # Medical document structure patterns
        self.medical_elements = {
            'hl7_cda': {
                'sections': ['{urn:hl7-org:v3}section'],
                'entries': ['{urn:hl7-org:v3}entry'],
                'narratives': ['{urn:hl7-org:v3}text'],
                'observations': ['{urn:hl7-org:v3}observation'],
                'headers': ['{urn:hl7-org:v3}title', '{urn:hl7-org:v3}code']
            },
            'fhir': {
                'resources': ['{http://hl7.org/fhir}entry'],
                'narratives': ['{http://hl7.org/fhir}text'],
                'values': ['{http://hl7.org/fhir}value'],
                'codes': ['{http://hl7.org/fhir}code']
            },
            'generic': {
                'sections': ['section', 'chapter', 'part', 'division'],
                'headers': ['title', 'header', 'heading', 'name'],
                'content': ['content', 'text', 'description', 'note']
            }
        }

    def chunk_xml_document(
        self,
        xml_content: bytes,
        document_id: str,
        document_type: str = 'generic-xml',
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[XMLSemanticChunk]:
        """
        Chunk XML document using structure-aware semantic analysis.

        Args:
            xml_content: Raw XML content as bytes
            document_id: Unique document identifier
            document_type: Type of document (hl7-cda, fhir, generic-xml)
            metadata: Additional document metadata

        Returns:
            List of semantic chunks optimized for medical RAG
        """
        if not xml_content or len(xml_content.strip()) == 0:
            return []

        try:
            # Parse XML document
            doc = etree.fromstring(xml_content)

            # Choose chunking strategy based on document type
            if 'cda' in document_type.lower() or 'hl7' in document_type.lower():
                chunks = self._chunk_cda_document(doc, document_id, metadata or {})
            elif 'fhir' in document_type.lower():
                chunks = self._chunk_fhir_document(doc, document_id, metadata or {})
            else:
                chunks = self._chunk_generic_xml(doc, document_id, metadata or {})

            # Post-process chunks
            if len(chunks) > 1:
                chunks = self._add_overlapping_context(chunks)

            chunks = self._optimize_chunk_sizes(chunks)
            return chunks

        except Exception:
            # Fallback to text-based chunking if XML parsing fails
            text_content = xml_content.decode('utf-8', errors='ignore')
            return self._chunk_text_content(text_content, document_id, metadata or {})

    def _chunk_cda_document(
        self,
        doc: etree._Element,
        document_id: str,
        metadata: Dict[str, Any]
    ) -> List[XMLSemanticChunk]:
        """Chunk HL7 CDA document using medical structure awareness."""
        chunks = []

        # Extract document header as first chunk
        header_chunk = self._extract_cda_header(doc, document_id, metadata)
        if header_chunk:
            chunks.append(header_chunk)

        # Process sections
        sections = doc.findall('.//{urn:hl7-org:v3}section')
        for i, section in enumerate(sections):
            section_chunks = self._chunk_cda_section(section, document_id, i, metadata)
            chunks.extend(section_chunks)

        return chunks

    def _extract_cda_header(
        self,
        doc: etree._Element,
        document_id: str,
        metadata: Dict[str, Any]
    ) -> Optional[XMLSemanticChunk]:
        """Extract and chunk CDA document header."""
        header_parts = []

        # Document title
        title = doc.find('.//{urn:hl7-org:v3}title')
        if title is not None and title.text:
            header_parts.append(f"Document Title: {title.text.strip()}")

        # Patient information
        patient_role = doc.find('.//{urn:hl7-org:v3}patientRole')
        if patient_role is not None:
            patient_info = self._extract_patient_info(patient_role)
            if patient_info:
                header_parts.append(f"Patient Information: {patient_info}")

        # Document metadata
        effective_time = doc.find('.//{urn:hl7-org:v3}effectiveTime')
        if effective_time is not None and effective_time.get('value'):
            header_parts.append(f"Document Date: {effective_time.get('value')}")

        if header_parts:
            header_text = "\n".join(header_parts)
            return XMLSemanticChunk(
                text=header_text,
                metadata=XMLChunkMetadata(
                    chunk_id=f"{document_id}_header",
                    document_id=document_id,
                    xml_path="/ClinicalDocument/header",
                    element_type="document_header",
                    chunk_type="header"
                )
            )
        return None

    def _chunk_cda_section(
        self,
        section: etree._Element,
        document_id: str,
        section_index: int,
        metadata: Dict[str, Any]
    ) -> List[XMLSemanticChunk]:
        """Chunk a CDA section with structure preservation."""
        chunks = []

        # Extract section title
        title_elem = section.find('.//{urn:hl7-org:v3}title')
        section_title = title_elem.text.strip() if title_elem is not None and title_elem.text else f"Section {section_index + 1}"

        # Extract narrative text
        text_elem = section.find('.//{urn:hl7-org:v3}text')
        narrative_text = ""
        if text_elem is not None:
            narrative_text = self._extract_xml_text_content(text_elem)

        # Extract entries
        entries = section.findall('.//{urn:hl7-org:v3}entry')
        entry_texts = []
        for entry in entries:
            entry_text = self._extract_xml_text_content(entry)
            if entry_text.strip():
                entry_texts.append(entry_text.strip())

        # Combine section content
        section_content = []
        if section_title:
            section_content.append(f"=== {section_title} ===")

        if narrative_text.strip():
            section_content.append(narrative_text.strip())

        if entry_texts:
            section_content.append("Clinical Entries:")
            for i, entry_text in enumerate(entry_texts, 1):
                section_content.append(f"{i}. {entry_text}")

        if section_content:
            full_text = "\n\n".join(section_content)

            # Check if section needs to be split
            if self._calculate_token_count(full_text) <= self.target_chunk_size:
                # Single chunk for the section
                chunks.append(XMLSemanticChunk(
                    text=full_text,
                    metadata=XMLChunkMetadata(
                        chunk_id=f"{document_id}_section_{section_index}",
                        document_id=document_id,
                        xml_path=f"/ClinicalDocument/section[{section_index}]",
                        element_type="section",
                        section_title=section_title,
                        chunk_type="section"
                    )
                ))
            else:
                # Split large sections
                sub_chunks = self._split_large_section(
                    full_text, document_id, section_index, section_title
                )
                chunks.extend(sub_chunks)

        return chunks

    def _chunk_fhir_document(
        self,
        doc: etree._Element,
        document_id: str,
        metadata: Dict[str, Any]
    ) -> List[XMLSemanticChunk]:
        """Chunk FHIR document using resource-based structure."""
        chunks = []

        if doc.tag.endswith('Bundle'):
            # Process FHIR Bundle
            entries = doc.findall('.//{http://hl7.org/fhir}entry')
            for i, entry in enumerate(entries):
                resource = entry.find('.//{http://hl7.org/fhir}resource')
                if resource is not None:
                    resource_chunk = self._chunk_fhir_resource(
                        resource, document_id, i, metadata
                    )
                    if resource_chunk:
                        chunks.append(resource_chunk)
        else:
            # Single FHIR resource
            resource_chunk = self._chunk_fhir_resource(doc, document_id, 0, metadata)
            if resource_chunk:
                chunks.append(resource_chunk)

        return chunks

    def _chunk_fhir_resource(
        self,
        resource: etree._Element,
        document_id: str,
        resource_index: int,
        metadata: Dict[str, Any]
    ) -> Optional[XMLSemanticChunk]:
        """Chunk a single FHIR resource."""
        resource_type = resource.tag.split('}')[-1] if '}' in resource.tag else resource.tag

        content_parts = [f"=== FHIR {resource_type} Resource ==="]

        # Extract narrative
        narrative = resource.find('.//{http://hl7.org/fhir}text/{http://hl7.org/fhir}div')
        if narrative is not None:
            narrative_text = etree.tostring(narrative, method='text', encoding='unicode')
            if narrative_text.strip():
                content_parts.append(f"Narrative: {narrative_text.strip()}")

        # Extract key-value pairs
        for elem in resource.iter():
            if elem.get('value') and not elem.tag.endswith('text'):
                field_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                content_parts.append(f"{field_name}: {elem.get('value')}")

        if len(content_parts) > 1:
            full_text = "\n".join(content_parts)
            return XMLSemanticChunk(
                text=full_text,
                metadata=XMLChunkMetadata(
                    chunk_id=f"{document_id}_resource_{resource_index}",
                    document_id=document_id,
                    xml_path=f"/Bundle/entry[{resource_index}]",
                    element_type="fhir_resource",
                    section_title=f"FHIR {resource_type}",
                    chunk_type="resource"
                )
            )
        return None

    def _chunk_generic_xml(
        self,
        doc: etree._Element,
        document_id: str,
        metadata: Dict[str, Any]
    ) -> List[XMLSemanticChunk]:
        """Chunk generic XML document using hierarchical structure."""
        chunks = []

        # Process top-level elements
        for i, child in enumerate(doc):
            chunk = self._chunk_xml_element(child, document_id, f"element_{i}", metadata)
            if chunk:
                chunks.append(chunk)

        # If no child elements, process the root element
        if not chunks:
            root_text = self._extract_xml_text_content(doc)
            if root_text.strip():
                chunks.append(XMLSemanticChunk(
                    text=root_text,
                    metadata=XMLChunkMetadata(
                        chunk_id=f"{document_id}_root",
                        document_id=document_id,
                        xml_path=f"/{doc.tag}",
                        element_type="root_element",
                        chunk_type="content"
                    )
                ))

        return chunks

    def _chunk_xml_element(
        self,
        element: etree._Element,
        document_id: str,
        element_id: str,
        metadata: Dict[str, Any]
    ) -> Optional[XMLSemanticChunk]:
        """Chunk a generic XML element."""
        text_content = self._extract_xml_text_content(element)
        if not text_content.strip():
            return None

        element_name = element.tag.split('}')[-1] if '}' in element.tag else element.tag

        # Format content
        content_lines = [f"=== {element_name} ==="]

        # Add attributes if present
        if element.attrib:
            attr_str = ", ".join([f"{k}={v}" for k, v in element.attrib.items()])
            content_lines.append(f"Attributes: {attr_str}")

        content_lines.append(text_content.strip())

        full_text = "\n".join(content_lines)

        return XMLSemanticChunk(
            text=full_text,
            metadata=XMLChunkMetadata(
                chunk_id=f"{document_id}_{element_id}",
                document_id=document_id,
                xml_path=self._get_element_xpath(element),
                element_type=element_name,
                chunk_type="content",
                attributes=element.attrib
            )
        )

    def _extract_xml_text_content(self, element: etree._Element) -> str:
        """Extract all text content from an XML element and its children."""
        texts = []

        # Add element text
        if element.text:
            texts.append(element.text.strip())

        # Process child elements recursively
        for child in element:
            child_text = self._extract_xml_text_content(child)
            if child_text:
                texts.append(child_text)

            # Add tail text
            if child.tail:
                texts.append(child.tail.strip())

        return ' '.join(filter(None, texts))

    def _extract_patient_info(self, patient_role: etree._Element) -> str:
        """Extract patient information from CDA patientRole."""
        info_parts = []

        # Patient ID
        id_elem = patient_role.find('.//{urn:hl7-org:v3}id')
        if id_elem is not None:
            patient_id = id_elem.get('extension')
            if patient_id:
                info_parts.append(f"ID: {patient_id}")

        # Patient name
        name_elem = patient_role.find('.//{urn:hl7-org:v3}patient/{urn:hl7-org:v3}name')
        if name_elem is not None:
            name_parts = []
            for part in name_elem:
                if part.text:
                    name_parts.append(part.text.strip())
            if name_parts:
                info_parts.append(f"Name: {' '.join(name_parts)}")

        return "; ".join(info_parts)

    def _split_large_section(
        self,
        text: str,
        document_id: str,
        section_index: int,
        section_title: str
    ) -> List[XMLSemanticChunk]:
        """Split large sections into smaller chunks while preserving context."""
        chunks = []

        # Split by paragraphs first
        paragraphs = re.split(r'\n\s*\n', text)
        current_chunk = ""
        chunk_counter = 0

        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue

            potential_chunk = current_chunk + "\n\n" + paragraph if current_chunk else paragraph

            if self._calculate_token_count(potential_chunk) <= self.target_chunk_size or not current_chunk:
                current_chunk = potential_chunk
            else:
                # Create chunk from current content
                if current_chunk:
                    chunks.append(XMLSemanticChunk(
                        text=current_chunk,
                        metadata=XMLChunkMetadata(
                            chunk_id=f"{document_id}_section_{section_index}_chunk_{chunk_counter}",
                            document_id=document_id,
                            xml_path=f"/ClinicalDocument/section[{section_index}]/chunk[{chunk_counter}]",
                            element_type="section_chunk",
                            section_title=section_title,
                            chunk_type="content"
                        )
                    ))
                    chunk_counter += 1

                # Start new chunk
                current_chunk = paragraph

        # Add final chunk
        if current_chunk:
            chunks.append(XMLSemanticChunk(
                text=current_chunk,
                metadata=XMLChunkMetadata(
                    chunk_id=f"{document_id}_section_{section_index}_chunk_{chunk_counter}",
                    document_id=document_id,
                    xml_path=f"/ClinicalDocument/section[{section_index}]/chunk[{chunk_counter}]",
                    element_type="section_chunk",
                    section_title=section_title,
                    chunk_type="content"
                )
            ))

        return chunks

    def _chunk_text_content(
        self,
        text: str,
        document_id: str,
        metadata: Dict[str, Any]
    ) -> List[XMLSemanticChunk]:
        """Fallback text-based chunking when XML parsing fails."""
        chunks = []

        # Simple paragraph-based splitting
        paragraphs = re.split(r'\n\s*\n', text)
        current_chunk = ""
        chunk_counter = 0

        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue

            potential_chunk = current_chunk + "\n\n" + paragraph if current_chunk else paragraph

            if self._calculate_token_count(potential_chunk) <= self.target_chunk_size or not current_chunk:
                current_chunk = potential_chunk
            else:
                if current_chunk:
                    chunks.append(XMLSemanticChunk(
                        text=current_chunk,
                        metadata=XMLChunkMetadata(
                            chunk_id=f"{document_id}_text_chunk_{chunk_counter}",
                            document_id=document_id,
                            xml_path="/text_content",
                            element_type="text_chunk",
                            chunk_type="content"
                        )
                    ))
                    chunk_counter += 1

                current_chunk = paragraph

        if current_chunk:
            chunks.append(XMLSemanticChunk(
                text=current_chunk,
                metadata=XMLChunkMetadata(
                    chunk_id=f"{document_id}_text_chunk_{chunk_counter}",
                    document_id=document_id,
                    xml_path="/text_content",
                    element_type="text_chunk",
                    chunk_type="content"
                )
            ))

        return chunks

    def _add_overlapping_context(self, chunks: List[XMLSemanticChunk]) -> List[XMLSemanticChunk]:
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
                if next_chunk.metadata.overlap_with is None:
                    next_chunk.metadata.overlap_with = []
                next_chunk.metadata.overlap_with.append(current_chunk.metadata.chunk_id)

        return chunks

    def _optimize_chunk_sizes(self, chunks: List[XMLSemanticChunk]) -> List[XMLSemanticChunk]:
        """Optimize chunk sizes and merge small chunks."""
        optimized_chunks = []
        i = 0

        while i < len(chunks):
            current_chunk = chunks[i]

            # Check if chunk is too small and can be merged
            if (current_chunk.token_count < self.min_chunk_size and
                i < len(chunks) - 1 and
                chunks[i + 1].token_count < self.target_chunk_size):

                # Merge with next chunk
                next_chunk = chunks[i + 1]
                merged_text = f"{current_chunk.text}\n\n{next_chunk.text}"

                merged_metadata = XMLChunkMetadata(
                    chunk_id=current_chunk.metadata.chunk_id,
                    document_id=current_chunk.metadata.document_id,
                    xml_path=current_chunk.metadata.xml_path,
                    element_type="merged",
                    section_title=current_chunk.metadata.section_title,
                    chunk_type="merged",
                    semantic_context=current_chunk.metadata.semantic_context,
                    overlap_with=(current_chunk.metadata.overlap_with or []) + (next_chunk.metadata.overlap_with or [])
                )

                merged_chunk = XMLSemanticChunk(
                    text=merged_text,
                    metadata=merged_metadata
                )

                optimized_chunks.append(merged_chunk)
                i += 2  # Skip next chunk as it's merged
            else:
                optimized_chunks.append(current_chunk)
                i += 1

        return optimized_chunks

    def _calculate_token_count(self, text: str) -> int:
        """Calculate approximate token count."""
        return int(len(text.split()) * 1.3)

    def _get_element_xpath(self, element: etree._Element) -> str:
        """Get XPath for an element."""
        try:
            tree = element.getroottree()
            return tree.getpath(element)
        except Exception:
            return f"/{element.tag}"