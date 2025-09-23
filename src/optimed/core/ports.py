from __future__ import annotations

from typing import AsyncGenerator, Protocol, Sequence, Any, Union, Optional

from optimed.core.domain import (
    PatientContext,
    Chunk, Record, ChunkPolicy, PolicySet,
    KPIEvent,
    ChatMessage,
    DiagnosisResult,
    WebSearchResponse,
    User,
    UserSession,
    UserAction,
    UserEHRConnection,
    DICOMImage,
    ImagePixelData,
    ImageUploadRequest,
    DICOMMetadata,
    ImageDimensions,
    ImageGenerationContext,
    ImageGenerationRequest,
    GeneratedImage,
    WindowLevel,
    ChatSession,
    SessionParticipant,
    JournalEntry,
    JournalEntryCreate,
    JournalEntryUpdate )

from optimed.core.domain.pdf_document import PDFDocument, PDFUploadRequest

# core/ports.py
#
# Hexagonal “ports” that your adapters (Issue #8 Claude, #9 FHIR, #10 pgvector)
# will implement.  Nothing here should import concrete infrastructure libs.


class FHIRRepository(Protocol):
    """Read-only access to EHR data expoised as FHIR / SMART-onFHIR APIs."""

    async def get_patient(self, patient_id: str) -> PatientContext:
        """Get patient context by ID."""
        ...

    async def search_patients(self, query: str) -> Sequence[PatientContext]:
        """Simple convenience search"""
        ...

    async def close(self) -> None:
        """Close any resources like HTTP clients."""
        ...

    async def _get_patient_resource(self, pid: str) -> PatientContext:
        """Fetch a single Patient resource by ID."""
        ...
    
    async def _get_observations(
        self, pid: str, *, category: str, count: int = 10
    ) -> list[Any]:
        """Fetch observations of a specific category for a patient."""
        ...

    # Journal/Notes methods
    async def get_patient_journal_entries(self, patient_id: str) -> Sequence[JournalEntry]:
        """Get all journal entries for a patient from FHIR DocumentReference resources."""
        ...
    
    async def create_journal_entry(self, entry: JournalEntryCreate, user: User) -> JournalEntry:
        """Create a new journal entry as FHIR DocumentReference."""
        ...
    
    async def get_journal_entry_by_id(self, entry_id: str) -> Optional[JournalEntry]:
        """Get a specific journal entry by ID."""
        ...
    
    async def update_journal_entry(self, entry_id: str, updates: JournalEntryUpdate, user: User) -> JournalEntry:
        """Update an existing journal entry."""
        ...
    
    async def delete_journal_entry(self, entry_id: str, user: User) -> bool:
        """Delete a journal entry."""
        ...


class KPIEventSink(Protocol):

    async def record(self, event: KPIEvent) -> None:
        """Record a KPI event."""
        ...
    
    async def flush(self) -> None:
        """Flush any buffered events."""
        ...


class ImageEmbeddingService(Protocol):
    """Service for creating embeddings from DICOM images."""
    
    async def create_image_embedding(self, pixel_data: ImagePixelData) -> Sequence[float]:
        """Create vector embedding from DICOM pixel data."""
        ...
    
    async def create_metadata_embedding(self, metadata: DICOMMetadata) -> Sequence[float]:
        """Create vector embedding from DICOM metadata."""
        ...


class VisionLLMClient(Protocol):
    """LLM client capable of analyzing images."""
    
    async def analyze_dicom_image(
        self, 
        pixel_data: ImagePixelData, 
        metadata: DICOMMetadata,
        query: str,
        patient_context: Optional[PatientContext] = None
    ) -> str:
        """Analyze a DICOM image and provide medical insights."""
        ...
    

class LLMClient(Protocol):

            # --- runtime definitions ---
    async def chat(
        self,
        messages: Sequence[ChatMessage],
        json_mode: bool = False,
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatMessage:
        """Send a chat message sequence to the LLM and get a response."""
        ...

    # --- chat_stream ---
    
    async def chat_stream(
        self,
        messages: Sequence[ChatMessage],
        json_mode: bool = False,
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream chat responses from the LLM."""
        ...
    
    
class VectorStore(Protocol):

    """pgvector / Pinecone / FAISS – whatever backs similarity search."""

    async def upsert(
        self,
        embedding_id: str,
        embedding: Sequence[float],
        object_type: str,
        object_id: str,
        content: str | dict,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Upsert an embedding vector with optional metadata."""
        ...

    async def similarity_search(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        filter_: dict[str, str] | None = None, 
    ) -> Sequence[tuple[str, float, str]]:
        """Find top-k most similar embeddings."""
        ...

    async def delete(self, embedding_ids: Sequence[str]) -> None:
        """Delete an embedding vector by ID."""
        ...

    async def get_chat_history(self, patient_id: str, session_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Get chat history for a patient."""
        ...

    async def clear_chat_history(self, patient_id: str) -> None:
        """Clear chat history for a patient."""
        ...

    async def update(
        self,
        embedding_id: str,
        embedding: Sequence[float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update an existing embedding vector's metadata or embedding."""
        ...

    async def store_dicom_embedding(
        self,
        image_id: str,
        embedding: Sequence[float],
        metadata: dict[str, Any]
    ) -> str:
        """Store a DICOM image embedding with metadata."""
        ...

    async def search_similar_dicom(
        self,
        query_embedding: Sequence[float],
        limit: int = 5,
        similarity_threshold: float = 0.7
    ) -> list[dict[str, Any]]:
        """Search for similar DICOM images by embedding."""
        ... 
    
    async def get_sessions_for_patient(
        self, 
        patient_id: str | None = None,
        limit: int = 50,
        include_general: bool = False
    ) -> list[ChatSession]:
        """Get all chat sessions for a patient (regardless of user)."""
        ...
    
    async def get_user_sessions_for_patient(
        self, 
        user_id: str, 
        patient_id: str | None = None,
        limit: int = 50
    ) -> list[ChatSession]:
        """Get sessions where user has participated for a specific patient."""
        ...
    
    async def add_user_to_session(
        self,
        session_id: str,
        user_id: str
    ) -> bool:
        """Add a user as a participant to an existing session."""
        ...
    
    async def get_session_participants(
        self,
        session_id: str
    ) -> list[SessionParticipant]:
        """Get all participants of a session."""
        ...
    
    async def create_chat_session(
        self,
        user_id: str,
        patient_id: str | None,
        mode: str,
        session_title: str | None = None
    ) -> str:
        """Create a new chat session and return session_id."""
        ...
    
    async def update_session_activity(
        self,
        session_id: str,
        user_id: str,
        message_count_increment: int = 1
    ) -> None:
        """Update session's last activity and user participation."""
        ...

    async def get_session_info(self, session_id: str) -> ChatSession | None:
        """Get session information by session_id."""
        ...
    
    async def get_session_messages(
        self,
        session_id: str,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get all messages for a specific session."""
        ...
    

class DiagnosticEngine(Protocol):
    """Pure-domain service used by LangGraph; orchestrates everything."""

    async def run(self, patient: PatientContext | None = None, user_prompt: str | None = None, chat_mode: bool = False, user_id: str | None = None, session_id: str | None = None) -> Union[DiagnosisResult,  dict]:
        """Return the top diagnosis (v0) or ranked list (v1)."""
        ...

    def run_stream(self, patient: PatientContext | None = None, user_prompt: str | None = None, chat_mode: bool = False, diagnostic_mode: str = "post_meet", user_id: str | None = None, session_id: str | None = None) -> AsyncGenerator[dict[str, Any], None]:
        """Run the diagnostic engine with streaming support."""
        ...

    async def get_or_create_session(
        self, 
        user_id: str, 
        patient_id: str | None, 
        mode: str,
        session_id: str | None = None,
        allow_join_existing: bool = True
    ) -> str:
        """Get existing session or create a new one, with multi-user support."""
        ...

    @property
    def vector_store(self) -> VectorStore:
        """Access to the underlying vector store."""
        ...

class ImageAnalysisEngine(Protocol):
    """Service for analyzing DICOM images and generating insights."""

    async def analyze(
        self,
        pixel_data: ImagePixelData,
        metadata: DICOMMetadata,
        query: str,
        user_id: Optional[str] = None,
        patient_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        ...

class AuthenticationProvider(Protocol):
    """Generic authentication provider interface."""

    async def initiate_auth_flow(self, **kwargs: Any) -> dict[str, Any]:
        """Initiate an authentication flow."""
        ...
    
    async def complete_auth_flow(self, auth_code: str, **kwargs: Any) -> dict[str, Any]:
        """Complete an authentication flow and return user info."""
        ...
    
    async def refresh_token(self, refresh_token: str, **kwargs: Any) -> dict[str, Any]:
        """Refresh an access token."""
        ...

    async def validate_token(self, token: str) -> dict[str, Any]:
        """Validate an access token and return user info."""
        ...

class AuthenticatedFHIRRepository(Protocol):
    """FHIR Repository that can be created from authentication credentials."""
    
    @classmethod
    async def from_connection(
        cls, 
        connection: UserEHRConnection,
        auth_provider: Optional[AuthenticationProvider] = None,
        **kwargs: Any
    ) -> 'AuthenticatedFHIRRepository':
        """Create repository instance from external connection."""
        ...
    
    async def is_authenticated(self) -> bool:
        """Check if the repository is properly authenticated."""
        ...
    
    async def refresh_authentication(self) -> bool:
        """Refresh authentication if possible."""
        ...

class UserEHRConnectionRepository(Protocol):
    """Repository for managing user EHR connections."""
    
    async def create_connection(self, connection: UserEHRConnection) -> UserEHRConnection:
        """Create a new EHR connection."""
        ...
    
    async def get_connection_by_id(self, connection_id: str) -> Optional[UserEHRConnection]:
        """Get connection by ID."""
        ...
    
    async def get_connections_by_user(self, user_id: str, provider_type: Optional[str] = None) -> Sequence[UserEHRConnection]:
        """Get all connections for a user, optionally filtered by provider type."""
        ...
    
    async def update_connection(self, connection: UserEHRConnection) -> UserEHRConnection:
        """Update an existing connection."""
        ...
    
    async def delete_connection(self, connection_id: str) -> bool:
        """Delete a connection."""
        ...
    
    async def get_active_connection_by_user(self, user_id: str, provider_type: str) -> Optional[UserEHRConnection]:
        """Get the active connection for a user and provider type."""
        ...
    
    # New methods for EHR login sessions
    async def create_ehr_login_session(self, session_data: dict) -> str:
        """Create a temporary EHR login session."""
        ...
    
    async def get_ehr_login_session(self, connection_id: str) -> Optional[dict]:
        """Get EHR login session by connection ID."""
        ...
    
    async def delete_ehr_login_session(self, connection_id: str) -> bool:
        """Delete EHR login session."""
        ...
    
    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired EHR login sessions."""
        ...



class UserRepository(Protocol):
    """User management and session handling."""

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        ...

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        ...

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        ...

    async def create_user(self, user: User) -> User:
        """Create a new user."""
        ...
    
    async def update_user(self, user: User) -> User:
        """Update an existing user."""
        ... 

    async def delete_user(self, user_id: str) -> None:
        """Delete a user by ID."""
        ...
    
    async def list_users_by_role(self, role: str) -> Sequence[User]:
        """List users by role."""
        ...

    async def create_session(self, session: UserSession) -> UserSession:
        """Create a new user session."""
        ...

    async def update_session_activity(self, session_id: str) -> None:
        """Update the last activity timestamp of a user session."""
        ...

    async def get_active_session(self, session_id: str) -> Optional[UserSession]:
        """Get an active user session by ID."""
        ...
    
    async def log_action(self, action: UserAction) -> UserAction:
        """Log a user action."""
        ...

class ImageRepository(Protocol):
    """Repository for managing DICOM images."""

    async def save_image(self, image: DICOMImage) -> None:
        """Save a DICOM image."""
        ...
    
    async def get_image_by_id(self, image_id: str) -> Optional[DICOMImage]:
        """Get a DICOM image by its ID."""
        ...
    
    async def get_images_by_user(self, user_id: str) -> Sequence[DICOMImage]:
        """Get all DICOM images uploaded by a user."""
        ...
    
    async def get_images_by_patient(self, patient_id: str) -> Sequence[DICOMImage]:
        """Get all DICOM images associated with a patient."""
        ...

    async def update_image(self, image: DICOMImage) -> None:
        """Update an existing DICOM image."""
        ...

    async def delete_image(self, image_id: str) -> None:
        """Delete a DICOM image by its ID."""
        ...
    

class ImageStorage(Protocol):
    """Port for DICOM image file storage"""

    async def store_image_file(self, image_id: str, file_content: bytes) -> str:
        """Store the raw DICOM file content and return the storage path."""
        ...

    async def get_image_file(self, storage_path: str) -> bytes:
        """Retrieve the raw DICOM file content from storage."""
        ...
    
    async def store_pixel_data(self, pixel_data: ImagePixelData) -> None:
        """Store pixel data for a DICOM image."""
        ...

    async def get_pixel_data(self, image_id: str) -> Optional[ImagePixelData]:
        """Get pixel data for a DICOM image by its ID."""
        ...

    async def delete_image_file(self, storage_path: str) -> None:
        """Delete the stored DICOM file."""
        ...

class DICOMProcessor(Protocol):
    """Port for processing DICOM images."""

    async def extract_metadata(self, file_content: bytes) -> DICOMMetadata:
        """Extract metadata from a DICOM file."""
        ...
    async def extract_pixel_data(self, file_content: bytes, image_id: str) -> ImagePixelData:
        """Extract pixel data from a DICOM file."""
        ...
    
    async def get_image_dimensions(self, file_content: bytes) -> ImageDimensions:
        """Get dimensions of the DICOM image."""
        ...
    
    async def get_default_window_level(self, file_content: bytes) -> WindowLevel:
        """Get the default window/level settings for the DICOM image."""
        ...
    
    async def validate_dicom_file(self, file_content: bytes) -> bool:
        """Validate if the file content is a valid DICOM file."""
        ...
    

    

class ImageService(Protocol):
    """Service for processing and managing DICOM images."""

    async def upload_image(self, upload_request: ImageUploadRequest) -> DICOMImage:
        """Process and upload a DICOM image."""
        ...

    async def get_image(self, image_id: str, user_id: str) -> Optional[DICOMImage]:
        """Get a DICOM image by its ID and user ID."""
        ...
    
    async def get_image_pixel_data(
        self,
        image_id: str,
        user_id: str,
        window_level: Optional[WindowLevel] = None
    ) -> Optional[ImagePixelData]:
        """Get pixel data for a DICOM image with optional windowing."""
        ...
    
    async def list_user_images(self, user_id: str) -> Sequence[DICOMImage]:
        """List all DICOM images uploaded by a user."""
        ... 
    
    async def list_patient_images(self, patient_id: str, user_id: str) -> Sequence[DICOMImage]:
        """List all DICOM images associated with a patient."""
        ...

    async def delete_image(self, image_id: str, user_id: str) -> None:
        """Delete a DICOM image by its ID."""
        ...
    

class WebSearchService(Protocol):
    """Service for performing web searches and retrieving results."""

    async def search(
        self, 
        query: str, 
        max_results: int = 10,
        patient_context: Optional[str] = None,
        search_intent: Optional[str] = None,
        target_language: Optional[str] = None
    ) -> WebSearchResponse:
        """Perform a web search and return structured results."""
        ...
    
    async def evaluate_search_need(
        self, 
        user_query: str, 
        patient_context: Optional[str] = None,
        chat_history: Optional[list[str]] = None
    ) -> bool:
        """Evaluate if web search is needed for the given query."""
        ...

class ImageGenerationService(Protocol):
    """Service for generating images using AI models like Stable Diffusion."""
    
    async def generate_image(self, request: ImageGenerationRequest) -> GeneratedImage:
        """Generate an image based on the request."""
        ...
    
    async def evaluate_generation_need(
        self, 
        context: ImageGenerationContext
    ) -> tuple[bool, Optional[str]]:
        """Evaluate if image generation would be helpful and return prompt if needed."""
        ...
    
    async def is_available(self) -> bool:
        """Check if the image generation service is available."""
        ...

class GeneratedImageRepository(Protocol):
    """Repository for storing and retrieving generated images."""
    
    async def store_generated_image(self, image: GeneratedImage) -> str:
        """Store generated image and return its ID."""
        ...
    
    async def get_generated_image(self, image_id: str) -> Optional[GeneratedImage]:
        """Retrieve a generated image by ID."""
        ...
    
    async def get_user_generated_images(
        self, 
        user_id: str, 
        limit: int = 10
    ) -> list[GeneratedImage]:
        """Get generated images for a user."""
        ...

    async def search_generated_images_by_prompt(
        self, 
        search_query: str, 
        user_id: Optional[str] = None,
        limit: int = 10
    ) -> list[GeneratedImage]:
        """Search generated images by prompt text using full-text search."""
        ...


# --- Chunking Ports ---

class TokenizerPort(Protocol):
    """Tokenizer abstraction to count tokens and split text."""

    def token_count(self, text: str) -> int:
        ...

    def split_sentences(self, text: str) -> list[str]:
        ...


class PhiRedactorPort(Protocol):
    """Redact PHI/PII from text; conservative by default."""

    def redact(self, text: str) -> str:
        ...


class ChunkingStrategy(Protocol):
    """Strategy interface for producing chunks from normalized records."""

    @property
    def strategy_id(self) -> str:
        ...

    @property
    def strategy_version(self) -> str:
        ...

    def apply(self, records: Sequence[Record], policy: ChunkPolicy, tokenizer: TokenizerPort) -> list[Chunk]:
        ...


class ChunkerPort(Protocol):
    """Inbound port to chunk either patient contexts or documents."""

    def chunk_from_patient(self, patient_context: PatientContext, policy_set: PolicySet) -> list[Chunk]:
        ...

    def chunk_from_document(self, document_ref: dict[str, Any], policy_set: PolicySet) -> list[Chunk]:
        ...


class ChunkingOrchestrator(Protocol):
    """Service coordinating record creation, strategy application and privacy checks."""

    def chunk_patient(self, patient_context: PatientContext, policy_set: PolicySet) -> list[Chunk]:
        ...

    def chunk_document(self, document_ref: dict[str, Any], policy_set: PolicySet) -> list[Chunk]:
        ...


class PDFStoragePort(Protocol):
    """Port for PDF document file storage."""

    async def store_pdf_file(self, document_id: str, file_content: bytes) -> str:
        """Store the raw PDF file content and return the storage path."""
        ...

    async def get_pdf_file(self, storage_path: str) -> bytes:
        """Retrieve the raw PDF file content from storage."""
        ...

    async def delete_pdf_file(self, document_id: str) -> None:
        """Delete the stored PDF file."""
        ...

    async def file_exists(self, document_id: str) -> bool:
        """Check if PDF file exists."""
        ...


class PDFRepository(Protocol):
    """Repository for managing PDF documents."""

    async def save_document(self, document: PDFDocument) -> None:
        """Save a PDF document."""
        ...

    async def get_document_by_id(self, document_id: str) -> Optional[PDFDocument]:
        """Get a PDF document by its ID."""
        ...

    async def get_documents_by_user(self, user_id: str) -> Sequence[PDFDocument]:
        """Get all PDF documents uploaded by a user."""
        ...

    async def get_documents_by_patient(self, patient_id: str) -> Sequence[PDFDocument]:
        """Get all PDF documents associated with a patient."""
        ...

    async def update_document(self, document: PDFDocument) -> None:
        """Update an existing PDF document."""
        ...

    async def delete_document(self, document_id: str) -> None:
        """Delete a PDF document by its ID."""
        ...


class PDFProcessor(Protocol):
    """Port for processing PDF documents."""

    async def extract_text(self, file_content: bytes) -> str:
        """Extract text content from a PDF file."""
        ...

    async def extract_metadata(self, file_content: bytes) -> dict[str, Any]:
        """Extract metadata from a PDF file."""
        ...

    async def validate_pdf_file(self, file_content: bytes) -> bool:
        """Validate if the file content is a valid PDF file."""
        ...


class PDFService(Protocol):
    """Service for processing and managing PDF documents."""

    async def upload_document(self, upload_request: PDFUploadRequest) -> PDFDocument:
        """Process and upload a PDF document."""
        ...

    async def get_document(self, document_id: str, user_id: str) -> Optional[PDFDocument]:
        """Get a PDF document by its ID and user ID."""
        ...

    async def list_user_documents(self, user_id: str) -> Sequence[PDFDocument]:
        """List all PDF documents uploaded by a user."""
        ...

    async def list_patient_documents(self, patient_id: str, user_id: str) -> Sequence[PDFDocument]:
        """List all PDF documents associated with a patient."""
        ...

    async def delete_document(self, document_id: str, user_id: str) -> None:
        """Delete a PDF document by its ID."""
        ...

    async def get_documents_for_context(self, user_id: str, patient_id: Optional[str] = None) -> Sequence[PDFDocument]:
        """Get PDF documents relevant for the current context (patient-specific or general)."""
        ...

