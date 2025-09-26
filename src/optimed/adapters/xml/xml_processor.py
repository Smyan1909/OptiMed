import lxml.etree as etree
from lxml import html
from typing import Dict, Any
from datetime import datetime
import re
from optimed.core.ports import XMLProcessor
from optimed.core.domain.xml_document import XMLMetadata


class LibXML2Processor(XMLProcessor):
    """XML processor implementation using lxml."""

    def __init__(self):
        # Medical document namespaces and patterns
        self.medical_namespaces = {
            'hl7': 'urn:hl7-org:v3',
            'fhir': 'http://hl7.org/fhir',
            'cda': 'urn:hl7-org:v3',
            'ccda': 'urn:hl7-org:v3'
        }

        # Document type detection patterns - ordered by specificity (most specific first)
        self.document_type_patterns = {
            'hl7-cda': [
                (r'ClinicalDocument.*xmlns.*urn:hl7-org:v3', True),  # Requires both elements
                (r'templateId.*2\.16\.840\.1\.113883', False),
                (r'urn:hl7-org:v3.*ClinicalDocument', True)
            ],
            'fhir': [
                (r'<Bundle.*xmlns.*http://hl7\.org/fhir', True),  # Requires both elements
                (r'<Patient.*xmlns.*http://hl7\.org/fhir', True),
                (r'http://hl7\.org/fhir.*<Bundle', True),
                (r'http://hl7\.org/fhir.*<Patient', True),
                (r'<.*resourceType.*value="Bundle"', False),
                (r'<.*resourceType.*value="Patient"', False)
            ],
            'ccda': [
                (r'Continuity of Care Document', False)
            ]
        }

    async def extract_text(self, file_content: bytes) -> str:
        """Extract text content from an XML file."""
        try:
            # Parse XML content
            doc = etree.fromstring(file_content)

            # Extract text using different strategies based on document type
            doc_type = await self.detect_document_type(file_content)

            if 'cda' in doc_type.lower() or 'hl7' in doc_type.lower():
                return self._extract_text_from_cda(doc)
            elif 'fhir' in doc_type.lower():
                return self._extract_text_from_fhir(doc)
            else:
                return self._extract_text_generic(doc)

        except Exception as e:
            raise ValueError(f"Failed to extract text from XML: {str(e)}")

    def _extract_text_from_cda(self, doc: etree._Element) -> str:
        """Extract text from HL7 CDA document."""
        text_parts = []

        # Extract document title/header info
        title_elem = doc.find('.//{urn:hl7-org:v3}title')
        if title_elem is not None and title_elem.text:
            text_parts.append(f"Document Title: {title_elem.text.strip()}")

        # Extract sections with their titles
        sections = doc.findall('.//{urn:hl7-org:v3}section')
        for i, section in enumerate(sections):
            section_text = []

            # Section title
            title = section.find('.//{urn:hl7-org:v3}title')
            if title is not None and title.text:
                section_text.append(f"--- Section: {title.text.strip()} ---")
            else:
                section_text.append(f"--- Section {i+1} ---")

            # Section content
            text_elem = section.find('.//{urn:hl7-org:v3}text')
            if text_elem is not None:
                # Extract all text content, including from nested elements
                content = self._extract_text_recursive(text_elem)
                if content.strip():
                    section_text.append(content.strip())

            # Extract structured entries
            entries = section.findall('.//{urn:hl7-org:v3}entry')
            if entries:
                for entry in entries:
                    entry_text = self._extract_text_recursive(entry)
                    if entry_text.strip():
                        section_text.append(f"Entry: {entry_text.strip()}")

            if len(section_text) > 1:  # Only add if we have content beyond the title
                text_parts.extend(section_text)

        return "\n\n".join(text_parts)

    def _extract_text_from_fhir(self, doc: etree._Element) -> str:
        """Extract text from FHIR document."""
        text_parts = []

        # Handle FHIR Bundle
        if doc.tag.endswith('Bundle'):
            entries = doc.findall('.//{http://hl7.org/fhir}entry')
            for i, entry in enumerate(entries):
                resource = entry.find('.//{http://hl7.org/fhir}resource')
                if resource is not None:
                    resource_text = self._extract_fhir_resource_text(resource)
                    if resource_text:
                        text_parts.append(f"--- Resource {i+1} ---\n{resource_text}")
        else:
            # Single FHIR resource
            resource_text = self._extract_fhir_resource_text(doc)
            if resource_text:
                text_parts.append(resource_text)

        return "\n\n".join(text_parts)

    def _extract_fhir_resource_text(self, resource: etree._Element) -> str:
        """Extract text from a FHIR resource."""
        text_parts = []

        # Extract narrative text
        narrative = resource.find('.//{http://hl7.org/fhir}text/{http://hl7.org/fhir}div')
        if narrative is not None:
            text_content = etree.tostring(narrative, method='text', encoding='unicode')
            if text_content.strip():
                text_parts.append(f"Narrative: {text_content.strip()}")

        # Extract specific field values
        for elem in resource.iter():
            if elem.get('value') and not elem.tag.endswith('text'):
                field_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                text_parts.append(f"{field_name}: {elem.get('value')}")

        return "\n".join(text_parts)

    def _extract_text_generic(self, doc: etree._Element) -> str:
        """Extract text from generic XML document with structure awareness."""
        # Remove any script or style elements if present
        for elem in doc.xpath('.//script | .//style'):
            elem.getparent().remove(elem)

        text_parts = []

        # Add document type/title if available
        if doc.tag and doc.tag not in ['root', 'document']:
            text_parts.append(f"Document Type: {doc.tag}")

        # Extract document root text if any
        if doc.text and doc.text.strip():
            text_parts.append(doc.text.strip())

        # Process all main sections/elements
        for child in doc:
            section_text = self._extract_section_text_simple(child)
            if section_text.strip():
                text_parts.append(section_text.strip())

        if not text_parts:
            # Fallback to simple text extraction
            text_content = etree.tostring(doc, method='text', encoding='unicode')
            text_content = re.sub(r'\s+', ' ', text_content)
            return text_content.strip()

        # Join sections with double newlines for readability
        result = '\n\n'.join(filter(None, text_parts))
        return result.strip()

    def _extract_section_text_simple(self, element: etree._Element) -> str:
        """Extract text from a generic XML section/element using simple approach."""
        section_parts = []

        # Add section header based on element name
        element_name = element.tag.split('}')[-1] if '}' in element.tag else element.tag
        if element_name:
            section_parts.append(f"--- {element_name.replace('_', ' ').replace('-', ' ').title()} ---")

        # Use recursive text extraction for all content under this section
        all_text = self._extract_text_recursive(element)
        if all_text.strip():
            section_parts.append(all_text.strip())

        return '\n'.join(filter(None, section_parts))

    def _extract_text_recursive(self, element: etree._Element) -> str:
        """Recursively extract text from XML element."""
        texts = []

        # Add element text
        if element.text:
            texts.append(element.text.strip())

        # Process child elements
        for child in element:
            child_text = self._extract_text_recursive(child)
            if child_text:
                texts.append(child_text)

            # Add tail text
            if child.tail:
                texts.append(child.tail.strip())

        return ' '.join(filter(None, texts))

    async def extract_metadata(self, file_content: bytes) -> XMLMetadata:
        """Extract metadata from an XML file."""
        try:
            doc = etree.fromstring(file_content)

            # Detect document type
            doc_type = await self.detect_document_type(file_content)

            # Extract basic metadata
            root_element = doc.tag
            namespace = doc.nsmap.get(None) if doc.nsmap else None

            # Extract encoding from XML declaration
            encoding = 'utf-8'  # Default
            content_str = file_content.decode('utf-8', errors='ignore')
            xml_decl_match = re.search(r'encoding=["\'](.*?)["\']', content_str)
            if xml_decl_match:
                encoding = xml_decl_match.group(1)

            base_metadata = {
                "document_type": doc_type,
                "root_element": root_element,
                "namespace": namespace,
                "encoding": encoding,
                "file_size": len(file_content)
            }

            # Extract specific metadata based on document type
            if 'cda' in doc_type.lower() or 'hl7' in doc_type.lower():
                base_metadata = self._extract_cda_metadata(doc, base_metadata)
            elif 'fhir' in doc_type.lower():
                base_metadata = self._extract_fhir_metadata(doc, base_metadata)
            else:
                base_metadata = self._extract_generic_metadata(doc, base_metadata)

            metadata = XMLMetadata(**base_metadata)

            return metadata

        except Exception as e:
            raise ValueError(f"Failed to extract metadata from XML: {str(e)}")

    def _extract_cda_metadata(self, doc: etree._Element, metadata_dict: dict) -> dict:
        """Extract CDA-specific metadata."""
        # Extract document title
        title_elem = doc.find('.//{urn:hl7-org:v3}title')
        if title_elem is not None and title_elem.text:
            metadata_dict["title"] = title_elem.text.strip()

        # Extract patient ID
        patient_id_elem = doc.find('.//{urn:hl7-org:v3}patientRole/{urn:hl7-org:v3}id')
        if patient_id_elem is not None:
            metadata_dict["patient_id_from_xml"] = patient_id_elem.get('extension')

        # Extract document ID
        doc_id_elem = doc.find('.//{urn:hl7-org:v3}id')
        if doc_id_elem is not None:
            metadata_dict["document_id_from_xml"] = doc_id_elem.get('extension')

        # Extract creation date
        effective_time = doc.find('.//{urn:hl7-org:v3}effectiveTime')
        if effective_time is not None and effective_time.get('value'):
            try:
                date_str = effective_time.get('value')
                # Parse HL7 date format (YYYYMMDDHHMMSS)
                if len(date_str) >= 8:
                    metadata_dict["creation_date"] = datetime.strptime(date_str[:8], '%Y%m%d')
            except ValueError:
                pass

        # Extract author
        author_elem = doc.find('.//{urn:hl7-org:v3}author/{urn:hl7-org:v3}assignedAuthor/{urn:hl7-org:v3}assignedPerson/{urn:hl7-org:v3}name')
        if author_elem is not None:
            author_parts = []
            for part in author_elem:
                if part.text:
                    author_parts.append(part.text.strip())
            if author_parts:
                metadata_dict["author"] = ' '.join(author_parts)

        # Count sections and entries
        sections = doc.findall('.//{urn:hl7-org:v3}section')
        metadata_dict["section_count"] = len(sections)

        entries = doc.findall('.//{urn:hl7-org:v3}entry')
        metadata_dict["entry_count"] = len(entries)

        return metadata_dict

    def _extract_fhir_metadata(self, doc: etree._Element, metadata_dict: dict) -> dict:
        """Extract FHIR-specific metadata."""
        # Extract Bundle metadata if present
        if doc.tag.endswith('Bundle'):
            # Extract Bundle ID
            id_elem = doc.find('.//{http://hl7.org/fhir}id')
            if id_elem is not None and id_elem.get('value'):
                metadata_dict["document_id_from_xml"] = id_elem.get('value')

            # Count entries
            entries = doc.findall('.//{http://hl7.org/fhir}entry')
            metadata_dict["entry_count"] = len(entries)

        # Extract timestamp
        timestamp_elem = doc.find('.//{http://hl7.org/fhir}meta/{http://hl7.org/fhir}lastUpdated')
        if timestamp_elem is not None and timestamp_elem.get('value'):
            try:
                timestamp_str = timestamp_elem.get('value')
                # Parse ISO 8601 format
                metadata_dict["modification_date"] = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except ValueError:
                pass

        return metadata_dict

    def _extract_generic_metadata(self, doc: etree._Element, metadata_dict: dict) -> dict:
        """Extract generic XML metadata."""
        # Count top-level elements as sections
        metadata_dict["section_count"] = len(list(doc))

        # Try to find common metadata elements
        common_fields = {
            'title': ['title', 'name', 'label'],
            'author': ['author', 'creator', 'by'],
            'created': ['created', 'date', 'timestamp']
        }

        for field, possible_names in common_fields.items():
            for name in possible_names:
                elem = doc.find(f'.//{name}') or doc.find(f'.//*[@{name}]')
                if elem is not None:
                    value = elem.text or elem.get(name)
                    if value and field == 'title' and not metadata_dict.get("title"):
                        metadata_dict["title"] = value.strip()
                    elif value and field == 'author' and not metadata_dict.get("author"):
                        metadata_dict["author"] = value.strip()
                    elif value and field == 'created' and not metadata_dict.get("creation_date"):
                        try:
                            metadata_dict["creation_date"] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        except ValueError:
                            pass
                    break

        return metadata_dict

    async def extract_structured_data(self, file_content: bytes) -> Dict[str, Any]:
        """Extract structured data from an XML file."""
        try:
            doc = etree.fromstring(file_content)
            return self._xml_to_dict(doc)
        except Exception as e:
            raise ValueError(f"Failed to extract structured data from XML: {str(e)}")

    def _xml_to_dict(self, element: etree._Element) -> Dict[str, Any]:
        """Convert XML element to dictionary."""
        result = {}

        # Add attributes
        if element.attrib:
            result['@attributes'] = element.attrib

        # Add text content
        if element.text and element.text.strip():
            result['@text'] = element.text.strip()

        # Process children
        children = {}
        for child in element:
            child_tag = child.tag
            child_data = self._xml_to_dict(child)

            if child_tag in children:
                if not isinstance(children[child_tag], list):
                    children[child_tag] = [children[child_tag]]
                children[child_tag].append(child_data)
            else:
                children[child_tag] = child_data

        result.update(children)

        # If only text and no attributes or children, return just the text
        if len(result) == 1 and '@text' in result:
            return result['@text']

        return result

    async def validate_xml_file(self, file_content: bytes) -> bool:
        """Validate if the file content is a valid XML file."""
        try:
            etree.fromstring(file_content)
            return True
        except etree.XMLSyntaxError:
            return False
        except Exception:
            return False

    async def detect_document_type(self, file_content: bytes) -> str:
        """Detect the type of XML document (HL7-CDA, FHIR, generic)."""
        try:
            content_str = file_content.decode('utf-8', errors='ignore')

            # Check against known patterns - ordered by specificity
            for doc_type, pattern_list in self.document_type_patterns.items():
                type_matched = False
                for pattern, requires_strict in pattern_list:
                    match = re.search(pattern, content_str, re.IGNORECASE | re.DOTALL)
                    if match:
                        if requires_strict:
                            # For strict patterns, we need strong evidence of the document type
                            type_matched = True
                            break
                        else:
                            # For loose patterns, continue checking but mark as potential match
                            type_matched = True

                if type_matched:
                    # Additional validation for FHIR to avoid false positives
                    if doc_type == 'fhir':
                        # Require either proper namespace OR resourceType attributes
                        has_fhir_namespace = 'http://hl7.org/fhir' in content_str
                        has_resource_type = re.search(r'resourceType.*value=', content_str, re.IGNORECASE)
                        if not (has_fhir_namespace or has_resource_type):
                            continue

                    return doc_type

            # Parse to check root element and namespace as fallback
            doc = etree.fromstring(file_content)
            root_tag = doc.tag
            namespace = doc.nsmap.get(None) if doc.nsmap else None

            # Check by root element and namespace
            if 'ClinicalDocument' in root_tag and 'hl7' in (namespace or ''):
                return 'hl7-cda'
            elif 'hl7' in (namespace or ''):
                return 'hl7-generic'

            return 'generic-xml'

        except Exception:
            return 'generic-xml'