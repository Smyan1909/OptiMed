from __future__ import annotations
from .mixins import FrozenModel
from .enums import ImageStatus  # Reusing existing status enum
from typing import Optional, Dict, List, Any
from datetime import datetime
from pydantic import Field


class XMLMetadata(FrozenModel):
    """XML metadata extracted from the document."""
    document_type: Optional[str] = None  # HL7-CDA, FHIR, Generic-XML
    root_element: Optional[str] = None
    namespace: Optional[str] = None
    schema_version: Optional[str] = None
    encoding: Optional[str] = None
    creation_date: Optional[datetime] = None
    modification_date: Optional[datetime] = None
    author: Optional[str] = None
    title: Optional[str] = None
    patient_id_from_xml: Optional[str] = None  # Patient ID found in XML
    document_id_from_xml: Optional[str] = None  # Document ID from XML
    file_size: Optional[int] = None
    section_count: Optional[int] = None  # Number of main sections found
    entry_count: Optional[int] = None   # Number of clinical entries (for CDA)

    def to_dict(self) -> Dict[str, str]:
        """Convert metadata to dictionary for serialization."""
        result = {}
        for key, value in self.__dict__.items():
            if value is not None:
                if isinstance(value, datetime):
                    result[key.replace('_', ' ').title()] = value.isoformat()
                else:
                    result[key.replace('_', ' ').title()] = str(value)
        return result


class XMLProcessingInfo(FrozenModel):
    """Information about XML processing results."""
    processing_started_at: datetime
    processing_completed_at: datetime
    parsing_success: bool
    structure_extraction_success: bool
    section_count: int
    error_message: Optional[str] = None
    extracted_text_length: Optional[int] = None
    chunk_count: Optional[int] = None
    extraction_method: str = "lxml"  # Track which library was used
    detected_format: Optional[str] = None  # HL7-CDA, FHIR, generic
    validation_errors: List[str] = Field(default_factory=list)


class XMLDocument(FrozenModel):
    """Domain model for an XML document that can be processed for information retrieval."""
    document_id: str
    patient_id: Optional[str]  # None for general documents, specific ID for patient documents
    user_id: str  # User who uploaded the document
    filename: str
    file_size: int  # Size in bytes

    # Document properties
    metadata: XMLMetadata
    processing_info: Optional[XMLProcessingInfo] = None

    # Tracking
    status: ImageStatus  # Reusing existing enum: UPLOADED, PROCESSING, READY, ERROR
    uploaded_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime] = None

    # File storage reference
    storage_path: Optional[str] = None

    # Content
    extracted_text: Optional[str] = None  # Temporarily store extracted text
    structured_data: Optional[Dict[str, Any]] = None  # Store structured XML data

    def is_ready(self) -> bool:
        """Check if document is ready for querying."""
        return self.status == ImageStatus.READY

    def is_patient_specific(self) -> bool:
        """Check if this document is associated with a specific patient."""
        return self.patient_id is not None

    def get_display_name(self) -> str:
        """Get a human-readable display name for the document."""
        if self.metadata.title:
            return self.metadata.title
        elif self.metadata.document_type:
            return f"{self.metadata.document_type} - {self.filename.replace('.xml', '')}"
        else:
            return self.filename.replace('.xml', '')

    def get_namespace(self) -> str:
        """Get the appropriate namespace for vector storage."""
        if self.is_patient_specific():
            return "clinical"
        else:
            return "general_documents"

    def get_document_type(self) -> str:
        """Get the detected document type."""
        if self.processing_info and self.processing_info.detected_format:
            return self.processing_info.detected_format
        elif self.metadata.document_type:
            return self.metadata.document_type
        else:
            return "generic-xml"

    def get_chunk_metadata(self) -> Dict[str, Any]:
        """Get metadata for chunking operations."""
        base_metadata = {
            "document_id": self.document_id,
            "user_id": self.user_id,
            "document_type": "xml",
            "xml_format": self.get_document_type(),
            "filename": self.filename,
            "namespace": self.get_namespace()
        }

        if self.patient_id:
            base_metadata["patient_id"] = self.patient_id

        if self.metadata.namespace:
            base_metadata["xml_namespace"] = self.metadata.namespace

        if self.metadata.root_element:
            base_metadata["root_element"] = self.metadata.root_element

        return base_metadata

    def is_medical_document(self) -> bool:
        """Check if this is a medical document (HL7, FHIR, etc.)."""
        doc_type = self.get_document_type().lower()
        return any(med_type in doc_type for med_type in ["hl7", "cda", "fhir", "ccda", "c-cda"])


class XMLUploadRequest(FrozenModel):
    """Request for uploading an XML document."""
    user_id: str
    filename: str
    file_content: bytes
    patient_id: Optional[str] = None

    def validate_request(self) -> None:
        """Validate the upload request."""
        valid_extensions = ['.xml', '.hl7', '.cda', '.ccda']
        if not any(self.filename.lower().endswith(ext) for ext in valid_extensions):
            raise ValueError(f"File must be an XML file with one of these extensions: {', '.join(valid_extensions)}")

        if len(self.file_content) == 0:
            raise ValueError("File content cannot be empty")

        if len(self.file_content) > 100 * 1024 * 1024:  # 100MB limit for XML files
            raise ValueError("File size cannot exceed 100MB")

        # Basic XML validation - check if file starts with XML declaration or root element
        content_start = self.file_content[:1000].decode('utf-8', errors='ignore').strip()
        if not (content_start.startswith('<?xml') or content_start.startswith('<')):
            raise ValueError("File content does not appear to be valid XML")


class XMLListResponse(FrozenModel):
    """Response for listing XML documents."""
    documents: List[XMLDocument]
    total_count: int
    patient_specific_count: int
    general_count: int
    medical_document_count: int  # Count of medical documents (HL7, FHIR, etc.)