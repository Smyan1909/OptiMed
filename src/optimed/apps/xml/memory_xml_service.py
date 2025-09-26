"""
In-memory XML service for GDPR-compliant temporary XML processing.
XML documents are stored in memory only for the duration of the session.
"""

import asyncio
from typing import Dict, List, Optional, Set, Any
from datetime import datetime, timezone
from optimed.core.domain.xml_document import XMLDocument, XMLMetadata, XMLProcessingInfo
from optimed.adapters.xml.xml_processor import LibXML2Processor
from optimed.core.ports import XMLService, XMLProcessor
from optimed.core.domain import ImageStatus
import uuid


class SessionXMLData:
    """Container for XML data associated with a session."""

    def __init__(self):
        self.xml_documents: Dict[str, XMLDocument] = {}
        self.raw_content: Dict[str, bytes] = {}  # Store raw XML bytes
        self.last_accessed = datetime.now(timezone.utc)

    def update_access_time(self):
        self.last_accessed = datetime.now(timezone.utc)


class MemoryXMLService(XMLService):
    """
    In-memory XML service that stores XML documents temporarily per session.
    XML documents are automatically cleaned up when sessions expire.
    """

    def __init__(self, xml_processor: XMLProcessor):
        self.xml_processor = xml_processor
        self.sessions: Dict[str, SessionXMLData] = {}
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
                print(f"Error in XML cleanup task: {e}")

    def _get_session_key(self, user_id: str, session_id: str, patient_id: Optional[str] = None) -> str:
        """Generate a unique session key."""
        return f"{user_id}:{session_id}:{patient_id or 'general'}"

    def _get_or_create_session(self, user_id: str, session_id: str, patient_id: Optional[str] = None) -> SessionXMLData:
        """Get or create session data."""
        key = self._get_session_key(user_id, session_id, patient_id)
        if key not in self.sessions:
            self.sessions[key] = SessionXMLData()
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
    ) -> XMLDocument:
        """Upload and process an XML document in memory."""
        try:
            # Generate document ID
            document_id = str(uuid.uuid4())
            print(f"[MemoryXMLService] Starting upload for document_id: {document_id}")
            print(f"[MemoryXMLService] Upload params - user_id: {user_id}, session_id: {session_id}, patient_id: {patient_id}")

            # Get session data
            session_key = self._get_session_key(user_id, session_id, patient_id)
            print(f"[MemoryXMLService] Generated session key for upload: {session_key}")

            session_data = self._get_or_create_session(user_id, session_id, patient_id)

            # Store raw content
            session_data.raw_content[document_id] = content
            print(f"[MemoryXMLService] Stored raw content ({len(content)} bytes)")

            # Validate XML
            print(f"[MemoryXMLService] Validating XML...")
            is_valid = await self.xml_processor.validate_xml_file(content)
            if not is_valid:
                raise ValueError("Invalid XML file format")

            # Detect document type
            print(f"[MemoryXMLService] Detecting document type...")
            doc_type = await self.xml_processor.detect_document_type(content)
            print(f"[MemoryXMLService] Detected document type: {doc_type}")

            # Extract metadata
            print(f"[MemoryXMLService] Extracting metadata...")
            metadata = await self.xml_processor.extract_metadata(content)
            print(f"[MemoryXMLService] Metadata extraction complete: {metadata}")

            # Extract text content
            print(f"[MemoryXMLService] Extracting text...")
            extracted_text = await self.xml_processor.extract_text(content)
            print(f"[MemoryXMLService] Text extraction complete: {len(extracted_text) if extracted_text else 0} characters")

            # Extract structured data
            print(f"[MemoryXMLService] Extracting structured data...")
            structured_data = await self.xml_processor.extract_structured_data(content)
            print(f"[MemoryXMLService] Structured data extraction complete")

            # Create XML document
            xml_doc = XMLDocument(
                document_id=document_id,
                patient_id=patient_id,
                user_id=user_id,
                filename=filename,
                file_size=len(content),
                metadata=metadata,
                processing_info=XMLProcessingInfo(
                    processing_started_at=datetime.now(timezone.utc),
                    processing_completed_at=datetime.now(timezone.utc),
                    parsing_success=True,
                    structure_extraction_success=bool(structured_data),
                    section_count=metadata.section_count or 0,
                    extracted_text_length=len(extracted_text) if extracted_text else 0,
                    detected_format=doc_type
                ),
                status=ImageStatus.READY,
                extracted_text=extracted_text,
                structured_data=structured_data,
                uploaded_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )

            # Store in session
            session_data.xml_documents[document_id] = xml_doc

            return xml_doc

        except Exception as e:
            print(f"[MemoryXMLService] ERROR during XML processing: {e}")
            import traceback
            traceback.print_exc()

            # Create error document
            error_doc = XMLDocument(
                document_id=str(uuid.uuid4()),
                patient_id=patient_id,
                user_id=user_id,
                filename=filename,
                file_size=len(content),
                metadata=XMLMetadata(
                    document_type="unknown",
                    root_element="unknown",
                    file_size=len(content)
                ),
                processing_info=XMLProcessingInfo(
                    processing_started_at=datetime.now(timezone.utc),
                    processing_completed_at=datetime.now(timezone.utc),
                    parsing_success=False,
                    structure_extraction_success=False,
                    section_count=0,
                    error_message=str(e),
                    extracted_text_length=0
                ),
                status=ImageStatus.ERROR,
                extracted_text=None,
                structured_data=None,
                uploaded_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )

            session_data = self._get_or_create_session(user_id, session_id, patient_id)
            session_data.xml_documents[error_doc.document_id] = error_doc

            return error_doc

    async def get_document(
        self,
        document_id: str,
        user_id: str,
        session_id: str,
        patient_id: Optional[str] = None
    ) -> Optional[XMLDocument]:
        """Get a specific XML document."""
        session_data = self._get_or_create_session(user_id, session_id, patient_id)
        return session_data.xml_documents.get(document_id)

    async def list_documents(
        self,
        user_id: str,
        session_id: str,
        patient_id: Optional[str] = None
    ) -> List[XMLDocument]:
        """List all XML documents for a session."""
        print(f"[MemoryXMLService] List request - user_id: {user_id}, session_id: {session_id}, patient_id: {patient_id}")

        session_key = self._get_session_key(user_id, session_id, patient_id)
        print(f"[MemoryXMLService] Generated session key for list: {session_key}")

        session_data = self._get_or_create_session(user_id, session_id, patient_id)
        xml_list = list(session_data.xml_documents.values())

        print(f"[MemoryXMLService] Found {len(xml_list)} XML documents in session")
        print(f"[MemoryXMLService] XML document IDs: {[doc.document_id for doc in xml_list]}")

        return xml_list

    async def delete_document(
        self,
        document_id: str,
        user_id: str,
        session_id: str,
        patient_id: Optional[str] = None
    ) -> bool:
        """Delete an XML document from memory."""
        print(f"[MemoryXMLService] Delete request - document_id: {document_id}, user_id: {user_id}, session_id: {session_id}, patient_id: {patient_id}")

        session_key = self._get_session_key(user_id, session_id, patient_id)
        print(f"[MemoryXMLService] Generated session key: {session_key}")

        session_data = self._get_or_create_session(user_id, session_id, patient_id)
        print(f"[MemoryXMLService] Available XML documents in session: {list(session_data.xml_documents.keys())}")

        deleted_doc = document_id in session_data.xml_documents
        deleted_content = document_id in session_data.raw_content

        if deleted_doc:
            print(f"[MemoryXMLService] Deleting XML document: {document_id}")
            del session_data.xml_documents[document_id]
        else:
            print(f"[MemoryXMLService] WARNING: XML document not found: {document_id}")

        if deleted_content:
            print(f"[MemoryXMLService] Deleting raw content: {document_id}")
            del session_data.raw_content[document_id]
        else:
            print(f"[MemoryXMLService] WARNING: Raw content not found: {document_id}")

        success = deleted_doc or deleted_content
        print(f"[MemoryXMLService] Delete operation result: {success}")
        return success

    async def get_documents_for_context(
        self,
        user_id: str,
        session_id: str,
        patient_id: Optional[str] = None
    ) -> List[XMLDocument]:
        """Get all ready XML documents for context processing."""
        session_data = self._get_or_create_session(user_id, session_id, patient_id)
        return [
            doc for doc in session_data.xml_documents.values()
            if doc.status == ImageStatus.READY and doc.extracted_text
        ]

    async def cleanup_session(self, session_key: str) -> None:
        """Clean up a specific session."""
        if session_key in self.sessions:
            session_data = self.sessions[session_key]
            # Clear all data
            session_data.xml_documents.clear()
            session_data.raw_content.clear()
            del self.sessions[session_key]
            print(f"Cleaned up XML session: {session_key}")

    async def cleanup_user_session(
        self,
        user_id: str,
        session_id: str,
        patient_id: Optional[str] = None
    ) -> None:
        """Clean up XML documents for a specific user session."""
        session_key = self._get_session_key(user_id, session_id, patient_id)
        await self.cleanup_session(session_key)

    def get_session_stats(self) -> Dict[str, int]:
        """Get statistics about current sessions."""
        stats = {
            "total_sessions": len(self.sessions),
            "total_xml_documents": sum(len(session.xml_documents) for session in self.sessions.values()),
            "total_memory_usage": sum(
                len(content) for session in self.sessions.values()
                for content in session.raw_content.values()
            )
        }
        return stats

    def debug_all_sessions(self):
        """Debug method to show all current sessions and their XML documents."""
        print(f"[MemoryXMLService] DEBUG: Total sessions: {len(self.sessions)}")
        for session_key, session_data in self.sessions.items():
            doc_count = len(session_data.xml_documents)
            doc_ids = list(session_data.xml_documents.keys())
            print(f"[MemoryXMLService] Session: {session_key} | XML Docs: {doc_count} | IDs: {doc_ids}")
        return {
            "sessions": list(self.sessions.keys()),
            "session_documents": {k: list(v.xml_documents.keys()) for k, v in self.sessions.items()}
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