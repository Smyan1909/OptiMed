"""
In-memory PDF service for GDPR-compliant temporary PDF processing.
PDFs are stored in memory only for the duration of the session.
"""

import asyncio
from typing import Dict, List, Optional, Set
from datetime import datetime, timezone
from optimed.core.domain.pdf_document import PDFDocument, PDFMetadata, PDFProcessingInfo
from optimed.adapters.pdf.pdf_processor import PyMuPDFProcessor
from optimed.core.ports import PDFService, PDFProcessor
from optimed.core.domain import ImageStatus
import uuid


class SessionPDFData:
    """Container for PDF data associated with a session."""

    def __init__(self):
        self.pdfs: Dict[str, PDFDocument] = {}
        self.raw_content: Dict[str, bytes] = {}  # Store raw PDF bytes
        self.last_accessed = datetime.now(timezone.utc)

    def update_access_time(self):
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
                print(f"Error in PDF cleanup task: {e}")

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

    async def upload_document(
        self,
        user_id: str,
        session_id: str,
        filename: str,
        content: bytes,
        patient_id: Optional[str] = None
    ) -> PDFDocument:
        """Upload and process a PDF document in memory."""
        try:
            # Generate document ID
            document_id = str(uuid.uuid4())
            print(f"[MemoryPDFService] Starting upload for document_id: {document_id}")

            # Get session data
            session_data = self._get_or_create_session(user_id, session_id, patient_id)

            # Store raw content
            session_data.raw_content[document_id] = content
            print(f"[MemoryPDFService] Stored raw content ({len(content)} bytes)")

            # Extract metadata and text
            print(f"[MemoryPDFService] Extracting metadata...")
            metadata = await self.pdf_processor.extract_metadata(content)
            print(f"[MemoryPDFService] Metadata extraction complete: {metadata}")

            print(f"[MemoryPDFService] Extracting text...")
            extracted_text = await self.pdf_processor.extract_text(content)
            print(f"[MemoryPDFService] Text extraction complete: {len(extracted_text) if extracted_text else 0} characters")

            # Create PDF document
            pdf_doc = PDFDocument(
                document_id=document_id,
                patient_id=patient_id,
                user_id=user_id,
                filename=filename,
                file_size=len(content),
                metadata=metadata,
                processing_info=PDFProcessingInfo(
                    processing_started_at=datetime.now(timezone.utc),
                    processing_completed_at=datetime.now(timezone.utc),
                    text_extraction_success=bool(extracted_text),
                    page_count=metadata.page_count if metadata else 0,
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
            print(f"[MemoryPDFService] ERROR during PDF processing: {e}")
            import traceback
            traceback.print_exc()

            # Create error document
            error_doc = PDFDocument(
                document_id=str(uuid.uuid4()),
                patient_id=patient_id,
                user_id=user_id,
                filename=filename,
                file_size=len(content),
                metadata=PDFMetadata(
                    title=filename,
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

            session_data = self._get_or_create_session(user_id, session_id, patient_id)
            session_data.pdfs[error_doc.document_id] = error_doc

            return error_doc

    async def get_document(
        self,
        document_id: str,
        user_id: str,
        session_id: str,
        patient_id: Optional[str] = None
    ) -> Optional[PDFDocument]:
        """Get a specific PDF document."""
        session_data = self._get_or_create_session(user_id, session_id, patient_id)
        return session_data.pdfs.get(document_id)

    async def list_documents(
        self,
        user_id: str,
        session_id: str,
        patient_id: Optional[str] = None
    ) -> List[PDFDocument]:
        """List all PDF documents for a session."""
        session_data = self._get_or_create_session(user_id, session_id, patient_id)
        return list(session_data.pdfs.values())

    async def delete_document(
        self,
        document_id: str,
        user_id: str,
        session_id: str,
        patient_id: Optional[str] = None
    ) -> bool:
        """Delete a PDF document from memory."""
        session_data = self._get_or_create_session(user_id, session_id, patient_id)

        if document_id in session_data.pdfs:
            del session_data.pdfs[document_id]

        if document_id in session_data.raw_content:
            del session_data.raw_content[document_id]

        return True

    async def get_documents_for_context(
        self,
        user_id: str,
        session_id: str,
        patient_id: Optional[str] = None
    ) -> List[PDFDocument]:
        """Get all ready PDF documents for context processing."""
        session_data = self._get_or_create_session(user_id, session_id, patient_id)
        return [
            pdf for pdf in session_data.pdfs.values()
            if pdf.status == ImageStatus.READY and pdf.extracted_text
        ]

    async def cleanup_session(self, session_key: str) -> None:
        """Clean up a specific session."""
        if session_key in self.sessions:
            session_data = self.sessions[session_key]
            # Clear all data
            session_data.pdfs.clear()
            session_data.raw_content.clear()
            del self.sessions[session_key]
            print(f"Cleaned up PDF session: {session_key}")

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