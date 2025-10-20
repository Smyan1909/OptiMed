"""
In-memory PDF service for GDPR-compliant temporary PDF processing.
PDFs are stored in memory only for the duration of the session.
"""

import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timezone
from optimed.core.domain.pdf_document import PDFDocument, PDFMetadata, PDFProcessingInfo, PDFUploadRequest
from optimed.core.ports import PDFService, PDFProcessor
from optimed.core.domain import ImageStatus
from optimed.core.logging_utils import get_logger, sanitize_user_id, sanitize_patient_id, sanitize_session_id, sanitize_document_id, log_error
from typing import Sequence
import uuid

logger = get_logger(__name__)


class SessionPDFData:
    """Container for PDF data associated with a session."""

    def __init__(self) -> None:
        self.pdfs: Dict[str, PDFDocument] = {}
        self.raw_content: Dict[str, bytes] = {}  # Store raw PDF bytes
        self.last_accessed = datetime.now(timezone.utc)

    def update_access_time(self) -> None:
        self.last_accessed = datetime.now(timezone.utc)


class MemoryPDFService(PDFService):
    """
    In-memory PDF service that stores PDFs temporarily per session.
    PDFs are automatically cleaned up when sessions expire.
    """

    def __init__(self, pdf_processor: PDFProcessor):
        self.pdf_processor = pdf_processor
        self.sessions: Dict[str, SessionPDFData] = {}
        self.cleanup_interval = 3600  # 1 hour in seconds
        self._cleanup_task: Optional[asyncio.Task] = None
        self._start_cleanup_task()

    def _start_cleanup_task(self):
        """Start the background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_expired_sessions())

    async def _cleanup_expired_sessions(self):
        """Background task to clean up expired sessions."""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                current_time = datetime.now(timezone.utc)
                expired_sessions = []

                for session_id, session_data in self.sessions.items():
                    # Clean up sessions older than 2 hours
                    if (current_time - session_data.last_accessed).total_seconds() > 7200:
                        expired_sessions.append(session_id)

                for session_id in expired_sessions:
                    await self.cleanup_session(session_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log_error(logger, "PDF cleanup task", e)

    def _get_session_key(self, user_id: str, session_id: str, patient_id: Optional[str] = None) -> str:
        """Generate a unique session key."""
        return f"{user_id}:{session_id}:{patient_id or 'general'}"

    def _get_or_create_session(self, user_id: str, session_id: str, patient_id: Optional[str] = None) -> SessionPDFData:
        """Get or create session data."""
        key = self._get_session_key(user_id, session_id, patient_id)
        if key not in self.sessions:
            self.sessions[key] = SessionPDFData()
        else:
            self.sessions[key].update_access_time()
        return self.sessions[key]

    async def upload_document(self, upload_request: PDFUploadRequest) -> PDFDocument:
        """Upload and process a PDF document in memory."""
        try:
            # Validate upload request
            upload_request.validate_request()

            # Generate document ID
            document_id = str(uuid.uuid4())
            logger.info(f"Starting upload for document_id: {sanitize_document_id(document_id)}")
            logger.info(f"Upload params - user_id: {sanitize_user_id(upload_request.user_id)}, session_id: {sanitize_session_id(upload_request.session_id)}, filename: {upload_request.filename}, patient_id: {sanitize_patient_id(upload_request.patient_id) if upload_request.patient_id else 'None'}")

            # Use the provided session_id instead of hardcoded default
            logger.info("Generated session key for upload")

            session_data = self._get_or_create_session(upload_request.user_id, upload_request.session_id, upload_request.patient_id)

            # Store raw content
            session_data.raw_content[document_id] = upload_request.file_content
            logger.info(f"Stored raw content ({len(upload_request.file_content)} bytes)")

            # Extract metadata and text
            logger.info("Extracting metadata...")
            metadata = await self.pdf_processor.extract_metadata(upload_request.file_content)
            logger.info("Metadata extraction complete")

            logger.info("Extracting text...")
            extracted_text = await self.pdf_processor.extract_text(upload_request.file_content)
            logger.info(f"Text extraction complete: {len(extracted_text) if extracted_text else 0} characters")

            # Create PDF document
            pdf_doc = PDFDocument(
                document_id=document_id,
                patient_id=upload_request.patient_id,
                user_id=upload_request.user_id,
                filename=upload_request.filename,
                file_size=len(upload_request.file_content),
                metadata=metadata,
                processing_info=PDFProcessingInfo(
                    processing_started_at=datetime.now(timezone.utc),
                    processing_completed_at=datetime.now(timezone.utc),
                    text_extraction_success=bool(extracted_text),
                    page_count=metadata.page_count if metadata and metadata.page_count else 0,
                    extracted_text_length=len(extracted_text) if extracted_text else 0
                ),
                status=ImageStatus.READY,
                extracted_text=extracted_text,
                uploaded_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )

            # Store in session
            session_data.pdfs[document_id] = pdf_doc

            return pdf_doc

        except Exception as e:
            log_error(logger, "PDF processing", e)

            # Create error document
            error_doc = PDFDocument(
                document_id=str(uuid.uuid4()),
                patient_id=upload_request.patient_id,
                user_id=upload_request.user_id,
                filename=upload_request.filename,
                file_size=len(upload_request.file_content),
                metadata=PDFMetadata(
                    title=upload_request.filename,
                    author="",
                    subject="",
                    creator="",
                    producer="",
                    creation_date=None,
                    modification_date=None,
                    page_count=0
                ),
                processing_info=PDFProcessingInfo(
                    processing_started_at=datetime.now(timezone.utc),
                    processing_completed_at=datetime.now(timezone.utc),
                    text_extraction_success=False,
                    page_count=0,
                    error_message=str(e),
                    extracted_text_length=0
                ),
                status=ImageStatus.ERROR,
                extracted_text=None,
                uploaded_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )

            session_data = self._get_or_create_session(upload_request.user_id, upload_request.session_id, upload_request.patient_id)
            session_data.pdfs[error_doc.document_id] = error_doc

            return error_doc

    async def get_document(self, document_id: str, user_id: str) -> Optional[PDFDocument]:
        """Get a specific PDF document."""
        # Search through all sessions for this user to find the document
        for session_key, session_data in self.sessions.items():
            if user_id in session_key:
                if document_id in session_data.pdfs:
                    session_data.update_access_time()
                    return session_data.pdfs[document_id]
        return None

    async def list_user_documents(self, user_id: str) -> Sequence[PDFDocument]:
        """List all PDF documents uploaded by a user."""
        logger.info(f"List user documents request - user_id: {sanitize_user_id(user_id)}")

        pdf_list: List[PDFDocument] = []
        # Search through all sessions for this user
        for session_key, session_data in self.sessions.items():
            if user_id in session_key:
                session_data.update_access_time()
                pdf_list.extend(session_data.pdfs.values())

        logger.info(f"Found {len(pdf_list)} PDFs for user")

        return pdf_list

    async def list_patient_documents(self, patient_id: str, user_id: str) -> Sequence[PDFDocument]:
        """List all PDF documents associated with a patient."""
        logger.info(f"List patient documents request - patient_id: {sanitize_patient_id(patient_id)}, user_id: {sanitize_user_id(user_id)}")

        pdf_list = []
        # Search through all sessions for this user and patient
        for session_key, session_data in self.sessions.items():
            if user_id in session_key and patient_id in session_key:
                session_data.update_access_time()
                # Filter for documents associated with this patient
                patient_pdfs = [pdf for pdf in session_data.pdfs.values() if pdf.patient_id == patient_id]
                pdf_list.extend(patient_pdfs)

        logger.info(f"Found {len(pdf_list)} PDFs for patient")

        return pdf_list

    async def delete_document(self, document_id: str, user_id: str, session_id: Optional[str] = None, patient_id: Optional[str] = None) -> bool:
        """Delete a PDF document by its ID."""
        logger.info(f"Delete request - document_id: {sanitize_document_id(document_id)}, user_id: {sanitize_user_id(user_id)}, session_id: {sanitize_session_id(session_id) if session_id else 'None'}, patient_id: {sanitize_patient_id(patient_id) if patient_id else 'None'}")

        if session_id:
            # If session_id is provided, look in that specific session
            session_key = self._get_session_key(user_id, session_id, patient_id)

            if session_key in self.sessions:
                session_data = self.sessions[session_key]

                if document_id in session_data.pdfs:
                    logger.info("Deleting PDF document")
                    del session_data.pdfs[document_id]

                    # Also delete raw content if it exists
                    if document_id in session_data.raw_content:
                        del session_data.raw_content[document_id]

                    session_data.update_access_time()
                    logger.info("Document deleted successfully")
                    return True
                else:
                    logger.warning("PDF document not found in session")
            else:
                logger.warning("Session not found")
        else:
            # Fallback: Search through all sessions for this user (original behavior)
            logger.info("No session_id provided, searching all sessions for user")
            for session_key, session_data in self.sessions.items():
                if user_id in session_key:
                    if document_id in session_data.pdfs:
                        logger.info("Deleting PDF document")
                        del session_data.pdfs[document_id]

                        # Also delete raw content if it exists
                        if document_id in session_data.raw_content:
                            del session_data.raw_content[document_id]

                        session_data.update_access_time()
                        logger.info("Document deleted successfully")
                        return True

        logger.warning("PDF document not found")
        return False

    async def get_documents_for_context(self, user_id: str, patient_id: Optional[str] = None) -> Sequence[PDFDocument]:
        """Get PDF documents relevant for the current context (patient-specific or general)."""
        logger.info(f"Get documents for context - user_id: {sanitize_user_id(user_id)}, patient_id: {sanitize_patient_id(patient_id) if patient_id else 'None'}")

        pdf_list = []
        # Search through all sessions for this user
        for session_key, session_data in self.sessions.items():
            if user_id in session_key:
                session_data.update_access_time()
                for pdf in session_data.pdfs.values():
                    # Include documents that are ready and have text
                    if pdf.status == ImageStatus.READY and pdf.extracted_text:
                        # If patient_id is specified, include patient-specific docs and general docs
                        # If patient_id is None, include only general docs
                        if patient_id is None:
                            if pdf.patient_id is None:  # General documents only
                                pdf_list.append(pdf)
                        else:
                            if pdf.patient_id == patient_id or pdf.patient_id is None:  # Patient-specific or general
                                pdf_list.append(pdf)

        logger.info(f"Found {len(pdf_list)} documents for context")
        return pdf_list

    # Legacy session-based methods for internal use
    async def list_documents(
        self,
        user_id: str,
        session_id: str,
        patient_id: Optional[str] = None
    ) -> List[PDFDocument]:
        """List all PDF documents for a session (internal method)."""
        logger.info(f"List request - user_id: {sanitize_user_id(user_id)}, session_id: {sanitize_session_id(session_id)}, patient_id: {sanitize_patient_id(patient_id) if patient_id else 'None'}")

        _session_key = self._get_session_key(user_id, session_id, patient_id)

        session_data = self._get_or_create_session(user_id, session_id, patient_id)
        pdf_list = list(session_data.pdfs.values())

        logger.info(f"Found {len(pdf_list)} PDFs in session")

        return pdf_list

    async def cleanup_session(self, session_key: str) -> None:
        """Clean up a specific session."""
        if session_key in self.sessions:
            session_data = self.sessions[session_key]
            # Clear all data
            session_data.pdfs.clear()
            session_data.raw_content.clear()
            del self.sessions[session_key]
            logger.info("Cleaned up PDF session")

    async def cleanup_user_session(
        self,
        user_id: str,
        session_id: str,
        patient_id: Optional[str] = None
    ) -> None:
        """Clean up PDFs for a specific user session."""
        session_key = self._get_session_key(user_id, session_id, patient_id)
        await self.cleanup_session(session_key)

    def get_session_stats(self) -> Dict[str, int]:
        """Get statistics about current sessions."""
        stats = {
            "total_sessions": len(self.sessions),
            "total_pdfs": sum(len(session.pdfs) for session in self.sessions.values()),
            "total_memory_usage": sum(
                len(content) for session in self.sessions.values()
                for content in session.raw_content.values()
            )
        }
        return stats

    def debug_all_sessions(self):
        """Debug method to show all current sessions and their PDFs."""
        logger.info(f"DEBUG: Total sessions: {len(self.sessions)}")
        for session_key, session_data in self.sessions.items():
            pdf_count = len(session_data.pdfs)
            logger.info(f"Session PDFs: {pdf_count}")
        return {
            "sessions": list(self.sessions.keys()),
            "session_pdfs": {k: list(v.pdfs.keys()) for k, v in self.sessions.items()}
        }

    async def shutdown(self):
        """Shutdown the service and cleanup."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Clear all sessions
        for session_key in list(self.sessions.keys()):
            await self.cleanup_session(session_key)