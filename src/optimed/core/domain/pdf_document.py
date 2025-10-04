from __future__ import annotations
from .mixins import FrozenModel
from .enums import ImageStatus  # Reusing existing status enum
from typing import Optional, Dict, List, Any
from datetime import datetime


class PDFMetadata(FrozenModel):
    """PDF metadata extracted from the document."""
    title: Optional[str] = None
    author: Optional[str] = None
    subject: Optional[str] = None
    creator: Optional[str] = None
    producer: Optional[str] = None
    creation_date: Optional[datetime] = None
    modification_date: Optional[datetime] = None
    page_count: Optional[int] = None
    file_size: Optional[int] = None

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


class PDFProcessingInfo(FrozenModel):
    """Information about PDF processing results."""
    processing_started_at: datetime
    processing_completed_at: datetime
    text_extraction_success: bool
    page_count: int
    error_message: Optional[str] = None
    extracted_text_length: Optional[int] = None
    chunk_count: Optional[int] = None
    extraction_method: str = "pymupdf"  # Track which library was used


class PDFDocument(FrozenModel):
    """Domain model for a PDF document that can be processed for information retrieval."""
    document_id: str
    patient_id: Optional[str]  # None for general documents, specific ID for patient documents
    user_id: str  # User who uploaded the document
    filename: str
    file_size: int  # Size in bytes

    # Document properties
    metadata: PDFMetadata
    processing_info: Optional[PDFProcessingInfo] = None

    # Tracking
    status: ImageStatus  # Reusing existing enum: UPLOADED, PROCESSING, READY, ERROR
    uploaded_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime] = None

    # File storage reference
    storage_path: Optional[str] = None

    # Content
    extracted_text: Optional[str] = None  # Temporarily store extracted text

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
        else:
            return self.filename.replace('.pdf', '')

    def get_namespace(self) -> str:
        """Get the appropriate namespace for vector storage."""
        if self.is_patient_specific():
            return "clinical"
        else:
            return "general_documents"

    def get_chunk_metadata(self) -> Dict[str, Any]:
        """Get metadata for chunking operations."""
        base_metadata = {
            "document_id": self.document_id,
            "user_id": self.user_id,
            "document_type": "pdf",
            "filename": self.filename,
            "namespace": self.get_namespace()
        }

        if self.patient_id:
            base_metadata["patient_id"] = self.patient_id

        return base_metadata


class PDFUploadRequest(FrozenModel):
    """Request for uploading a PDF document."""
    user_id: str
    session_id: str
    filename: str
    file_content: bytes
    patient_id: Optional[str] = None

    def validate_request(self) -> None:
        """Validate the upload request."""
        if not self.filename.lower().endswith('.pdf'):
            raise ValueError("File must be a PDF file (.pdf)")

        if len(self.file_content) == 0:
            raise ValueError("File content cannot be empty")

        if len(self.file_content) > 50 * 1024 * 1024:  # 50MB limit for PDFs
            raise ValueError("File size cannot exceed 50MB")


class PDFListResponse(FrozenModel):
    """Response for listing PDF documents."""
    documents: List[PDFDocument]
    total_count: int
    patient_specific_count: int
    general_count: int