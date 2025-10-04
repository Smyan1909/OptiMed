from __future__ import annotations 
import uuid
import os
import httpx
import json
import base64
import time
import asyncio
import io
from PIL import Image
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from typing import AsyncGenerator, Dict, Optional, Any, List, Any as _Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, Request, Query, Path, Header, Depends, File, Form, Body, Response # type: ignore
from fastapi.responses import StreamingResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from optimed.core.domain import PatientContext, User, UserSession, UserEHRConnection, UserRole, UserStatus, ImageGenerationRequest, DataSource, ChatRole, ChatMessage
from optimed.core.domain.pdf_document import PDFListResponse
from optimed.core.domain.xml_document import XMLListResponse
from optimed.core.ports import FHIRRepository
from optimed.apps.orchestrator.factory import create_app_dependencies
from optimed.core.domain import JournalEntryCreate, JournalEntryUpdate, JournalEntryType
from optimed.adapters.security.encryption_service import get_encryption_service, get_phi_redactor
from optimed.adapters.security.e2e_encryption_middleware import E2EEncryptionMiddleware, create_session_with_encryption
from optimed.adapters.security.auth_middleware import AuthenticationMiddleware
from optimed.adapters.security.rate_limiter import RateLimitMiddleware
from optimed.adapters.security.rls_middleware import RLSMiddleware
from optimed.adapters.middleware.audit_logger import AuditLoggingMiddleware
from optimed.apps.api_gateway.gdpr_endpoints import gdpr_router
from optimed.apps.api_gateway.document_events import get_broadcaster, DocumentEvent, format_sse_event
from optimed.core.logging_utils import (
    get_logger,
    sanitize_user_id,
    sanitize_patient_id,
    sanitize_session_id,
    sanitize_document_id,
    log_error
)

from pydantic import BaseModel

logger = get_logger(__name__)

# Defer heavy dependency wiring to startup to avoid crashing on import
# if env vars (e.g., PGVECTOR_DSN) are missing at container boot.
_engine: _Any = None
_fhir: _Any = None
_vector_store: _Any = None
_user_repo: _Any = None
_connection_repo: _Any = None
_connection_service: _Any = None
_create_image_service: _Any = None
_image_analysis_engine: _Any = None
_image_generation_service: _Any = None
_generated_image_repo: _Any = None
_journal_llm_service: _Any = None
_web_search_service: _Any = None
_pdf_service: _Any = None
_xml_service: _Any = None
_template_repo: _Any = None
_template_service: _Any = None
_note_generator: _Any = None
_audit_repo: _Any = None


_dependencies_ready: asyncio.Event = asyncio.Event()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine, _fhir, _vector_store, _user_repo, _connection_repo, _connection_service, _create_image_service, _image_analysis_engine, _image_generation_service, _generated_image_repo, _journal_llm_service, _web_search_service, _pdf_service, _xml_service, _template_repo, _template_service, _note_generator, _audit_repo
    try:
        (
            _engine,
            _fhir,
            _vector_store,
            _user_repo,
            _connection_repo,
            _connection_service,
            _create_image_service,
            _image_analysis_engine,
            _image_generation_service,
            _generated_image_repo,
            _journal_llm_service,
            _web_search_service,
            _pdf_service,
            _xml_service,
            _template_repo,
            _template_service,
            _note_generator,
            _audit_repo,
        ) = await create_app_dependencies()

        # Store repositories in app state for middleware access
        app.state._user_repo = _user_repo
        app.state._audit_repo = _audit_repo

        _dependencies_ready.set()
        logger.info("[startup] Dependencies initialized")
        yield
    except Exception as e:
        import traceback
        log_error(logger, "startup - Dependency initialization", e)
        traceback.print_exc()
        # Fail fast: prevent the app from serving if dependencies cannot initialize
        raise
    finally:
        # Optional: add shutdown/cleanup here if needed
        pass

app = FastAPI(title="OptiMed API Gateway", version="0.1.0", debug=True, lifespan=lifespan)

# Register GDPR Data Subject Rights endpoints (GDPR Articles 15-22)
app.include_router(gdpr_router)

# Add End-to-End Encryption middleware first (now supports streaming)
app.add_middleware(E2EEncryptionMiddleware, encrypt_responses=True, encrypt_requests=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Security and Audit Middlewares
# Order matters: outer -> inner execution
# 1. Rate limiting (check limits before auth)
app.add_middleware(RateLimitMiddleware)

# 2. Authentication & origin validation
app.add_middleware(AuthenticationMiddleware)

# 3. RLS context (requires authenticated user)
app.add_middleware(RLSMiddleware)

# 4. Audit logging (logs authenticated requests with user context)
app.add_middleware(AuditLoggingMiddleware)

# GDPR Compliance Middleware
@app.middleware("http")
async def gdpr_logging_middleware(request: Request, call_next):
    """Middleware to redact PHI from logs and add GDPR compliance headers."""
    # Log request without PHI
    phi_redactor = get_phi_redactor()
    safe_path = phi_redactor.redact_text(request.url.path)
    safe_query = phi_redactor.redact_text(str(request.query_params))

    logger.info(f"[GDPR] Request: {request.method} {safe_path} - Query: {safe_query}")
    
    # Process request
    response = await call_next(request)
    
    # Add GDPR compliance headers
    response.headers["X-GDPR-Compliant"] = "true"
    response.headers["X-PHI-Storage"] = "disabled"
    response.headers["X-Data-Retention"] = "session-only"
    
    return response
class JournalEntryRequest(BaseModel):
    patient_id: str
    title: str
    content: str
    entry_type: str

class JournalEntryResponse(BaseModel):
    entry_id: str
    patient_id: str
    title: str
    content: str
    entry_type: str
    created_by: str
    created_at: str
    updated_at: str
    author_name: str
    author_role: str

class JournalEntryUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    entry_type: Optional[str] = None

class ChatRequest(BaseModel):
    patient_id: str | None = None
    user_prompt: str | None = None
    chat_mode: bool = False
    diagnostic_mode: str = "post_meet"
    user_id: str | None = None  # Optional user ID for tracking
    session_id: str | None = None  # Optional session ID for tracking

class PatientOut(BaseModel):
    id: str
    name: str
    age: int
    sex: str
    care_unit: str
    vitals: Dict[str, str]
    labs: Dict[str, str]
    exam: Dict[str, str]
    procedure: Dict[str, str]
    imaging_observations: Dict[str, str]
    procedure_observations: Dict[str, str]
    social_history: Dict[str, str]
    medications: Dict[str, str]
    allergies: Dict[str, str]
    diagnoses: Dict[str, str]
    immunizations: Dict[str, str]
    diagnostic_reports: Dict[str, str]
    medication_statement: Dict[str, str]
    questionnaire_response: Dict[str, str]
    family_history: Dict[str, str]
    care_team: Dict[str, str]
    goals: Dict[str, str]
    clinical_impressions: Dict[str, str]
    risk_assessments: Dict[str, str]
    service_requests: Dict[str, str]
    medication_administrations: Dict[str, str]
    medication_dispenses: Dict[str, str]
    immunization_recommendations: Dict[str, str]
    appointments: Dict[str, str]
    episodes_of_care: Dict[str, str]
    imaging_studies: Dict[str, str]
    devices: Dict[str, str]
    device_use: Dict[str, str]
    nutrition_orders: Dict[str, str]
    adverse_events: Dict[str, str]
    # Timestamp fields
    vitals_timestamps: Dict[str, str]
    labs_timestamps: Dict[str, str]
    exam_timestamps: Dict[str, str]
    procedure_timestamps: Dict[str, str]
    imaging_observations_timestamps: Dict[str, str]
    procedure_observations_timestamps: Dict[str, str]
    social_history_timestamps: Dict[str, str]
    medications_timestamps: Dict[str, str]
    allergies_timestamps: Dict[str, str]
    diagnoses_timestamps: Dict[str, str]
    immunizations_timestamps: Dict[str, str]
    diagnostic_reports_timestamps: Dict[str, str]
    medication_statement_timestamps: Dict[str, str]
    questionnaire_response_timestamps: Dict[str, str]
    family_history_timestamps: Dict[str, str]
    care_team_timestamps: Dict[str, str]
    goals_timestamps: Dict[str, str]
    clinical_impressions_timestamps: Dict[str, str]
    risk_assessments_timestamps: Dict[str, str]
    service_requests_timestamps: Dict[str, str]
    medication_administrations_timestamps: Dict[str, str]
    medication_dispenses_timestamps: Dict[str, str]
    immunization_recommendations_timestamps: Dict[str, str]
    appointments_timestamps: Dict[str, str]
    episodes_of_care_timestamps: Dict[str, str]
    imaging_studies_timestamps: Dict[str, str]
    devices_timestamps: Dict[str, str]
    device_use_timestamps: Dict[str, str]
    nutrition_orders_timestamps: Dict[str, str]
    adverse_events_timestamps: Dict[str, str]
    # Encounters
    encounters: Dict[str, str]
    encounters_timestamps: Dict[str, str]

    vitals_sources: Dict[str, DataSource] = {}
    labs_sources: Dict[str, DataSource] = {}
    exam_sources: Dict[str, DataSource] = {}
    procedure_sources: Dict[str, DataSource] = {}
    imaging_observations_sources: Dict[str, DataSource] = {}
    procedure_observations_sources: Dict[str, DataSource] = {}
    social_history_sources: Dict[str, DataSource] = {}
    medications_sources: Dict[str, DataSource] = {}
    allergies_sources: Dict[str, DataSource] = {}
    diagnoses_sources: Dict[str, DataSource] = {}
    immunizations_sources: Dict[str, DataSource] = {}
    diagnostic_reports_sources: Dict[str, DataSource] = {}
    medication_statement_sources: Dict[str, DataSource] = {}
    questionnaire_response_sources: Dict[str, DataSource] = {}
    encounters_sources: Dict[str, DataSource] = {}
    family_history_sources: Dict[str, DataSource] = {}
    care_team_sources: Dict[str, DataSource] = {}
    goals_sources: Dict[str, DataSource] = {}
    clinical_impressions_sources: Dict[str, DataSource] = {}
    risk_assessments_sources: Dict[str, DataSource] = {}
    service_requests_sources: Dict[str, DataSource] = {}
    medication_administrations_sources: Dict[str, DataSource] = {}
    medication_dispenses_sources: Dict[str, DataSource] = {}
    immunization_recommendations_sources: Dict[str, DataSource] = {}
    appointments_sources: Dict[str, DataSource] = {}
    episodes_of_care_sources: Dict[str, DataSource] = {}
    imaging_studies_sources: Dict[str, DataSource] = {}
    devices_sources: Dict[str, DataSource] = {}
    device_use_sources: Dict[str, DataSource] = {}
    nutrition_orders_sources: Dict[str, DataSource] = {}
    adverse_events_sources: Dict[str, DataSource] = {}

class UserOut(BaseModel):
    user_id: str 
    username: str
    email: str
    first_name: str | None
    last_name: str | None
    role: str
    status: str
    department: str | None
    full_name: str
    display_name: str

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    user: UserOut
    session_id: str
    message: str

class EHRConnectionRequest(BaseModel):
    provider_type: str = "smart_fhir"
    fhir_server_url: str
    client_id: str
    scope: str = "patient/*.read"

class ConnectionCallbackRequest(BaseModel):
    connection_id: str
    code: str
    state: str

class EHRConnectionOut(BaseModel):
    connection_id: str
    provider_type: str
    fhir_server_url: str
    is_active: bool
    created_at: str
    patient_context: str | None

class EHRLoginRequest(BaseModel):
    fhir_server_url: str
    client_id: str
    scope: str = "user/*.cruds"

class EHRLoginResponse(BaseModel):
    authorization_url: str
    connection_id: str
    state: str


class DICOMImageResponse(BaseModel):
    image_id: str
    patient_id: Optional[str] = None
    user_id: str
    filename: str
    file_size: int
    metadata: Dict[str, str]
    dimensions: Dict[str, Any]
    default_window_level: Dict[str, float]
    status: str
    uploaded_at: datetime
    processed_at: Optional[datetime] = None
    storage_path: Optional[str] = None


class DICOMImageListResponse(BaseModel):
    images: List[DICOMImageResponse]

class DICOMPixelDataResponse(BaseModel):
    image_id: str
    image_data_base64: str  # Base64 encoded image for display
    original_dtype: str
    photometric_interpretation: Optional[str] = None
    statistics: Dict[str, Any]

class DICOMUploadResponse(BaseModel):
    image_id: str
    message: str
    image: DICOMImageResponse


class LookupRequest(BaseModel):
    term: str
    term_type: Optional[str] = None  # medication, diagnosis, vital, lab, general
    patient_id: Optional[str] = None
    session_id: Optional[str] = None

class LookupResponse(BaseModel):
    term: str
    summary: str
    sources: List[Dict[str, str]]  # [{ title, url }]
    raw_results: Optional[List[Dict[str, Any]]] = None


class SessionListRequest(BaseModel):
    patient_id: str | None = None
    user_id: str | None = None
    include_all_patient_sessions: bool = False

class SessionOut(BaseModel):
    session_id: str
    patient_id: str | None
    created_by_user_id: str
    participants: list[str]
    created_at: str
    last_message_at: str
    session_title: str
    message_count: int
    mode: str
    is_active: bool
    last_participant_id: str | None
    user_can_join: bool

class SessionCreateRequest(BaseModel):
    patient_id: str | None = None
    mode: str = "chat"
    session_title: str | None = None

class ImageGenerationRequestModel(BaseModel):
    prompt: str
    width: int = 1024
    height: int = 1024
    patient_id: Optional[str] = None

def get_health_status():
    return {"status": "ok"}

@app.get("/health", summary="Health Check (GET)")
async def health_get():
    return get_health_status()

@app.post("/health", summary="Health Check")
async def health():
    """Simple health check endpoint."""
    return get_health_status()

async def get_current_user(
    x_session_id: str = Header(None, alias="X-Session-ID")
) -> Optional[User]:

    if not x_session_id:
        logger.info("[DEBUG] get_current_user - No session ID provided")
        return None

    logger.info(f"[DEBUG] get_current_user - Looking up session: {sanitize_session_id(x_session_id)}")

    try:
        session = await _user_repo.get_active_session(x_session_id)
        if not session:
            logger.info(f"[DEBUG] get_current_user - Session not found or expired: {sanitize_session_id(x_session_id)}")
            return None

        logger.info(f"[DEBUG] get_current_user - Session found, user: {sanitize_user_id(session.user_id)}")

        user = await _user_repo.get_user_by_id(session.user_id)
        if user:
            logger.info(f"[DEBUG] get_current_user - User found: {user.username}")
            await _user_repo.update_session_activity(x_session_id)
        else:
            logger.warning(f"[DEBUG] get_current_user - User not found for user: {sanitize_user_id(session.user_id)}")

        return user
    except Exception as e:
        log_error(logger, "get_current_user", e)
        import traceback
        traceback.print_exc()
        return None
    

async def get_user_context(
    user: Optional[User] = Depends(get_current_user),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID")
) -> dict:
    """Dependency to fetch user context."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    return {
        "user_id": user.user_id,
        "user": user,
        "session_id": x_session_id
    }

async def get_user_fhir_repository(user_ctx: dict = Depends(get_user_context)) -> FHIRRepository:
    """Get the appropriate FHIR repository for the current user."""
    current_user = user_ctx.get("user")
    
    if current_user:
        logger.info(f"[DEBUG] Attempting to create SMART FHIR repository for user: {current_user.username} ({sanitize_user_id(current_user.user_id)})")

        # Try to get an authenticated SMART FHIR repository for this user
        try:
            user_repo = await _connection_service.create_fhir_repository(
                current_user.user_id,
                provider_type="smart_fhir"
            )
            if user_repo:
                logger.info(f"[API] SUCCESS: Using SMART FHIR repository for user {current_user.username}")
                return user_repo
            else:
                logger.warning(f"[DEBUG] ERROR: create_fhir_repository returned None for user {current_user.username}")
        except Exception as e:
            log_error(logger, f"Failed to create SMART FHIR repo for user {current_user.username}", e)
    else:
        logger.info("[DEBUG] No current user found, using default repository")

    # Fallback to default HAPI repository
    logger.info("[API] Using default HAPI FHIR repository")
    if _fhir is None:
        # Service not initialized yet
        raise HTTPException(status_code=503, detail="Service initializing, please try again shortly")
    return _fhir


# Note template dependency getters
async def get_template_repo():
    """Dependency to get template repository."""
    await _dependencies_ready.wait()
    if _template_repo is None:
        raise HTTPException(status_code=503, detail="Service initializing, please try again shortly")
    return _template_repo


async def get_template_service():
    """Dependency to get template service."""
    await _dependencies_ready.wait()
    if _template_service is None:
        raise HTTPException(status_code=503, detail="Service initializing, please try again shortly")
    return _template_service


async def get_note_generator():
    """Dependency to get note generator."""
    await _dependencies_ready.wait()
    if _note_generator is None:
        raise HTTPException(status_code=503, detail="Service initializing, please try again shortly")
    return _note_generator


# Removed duplicate /health endpoint (was redefining the same route)

@app.post("/sessions/list", response_model=List[SessionOut])
async def list_user_sessions(
    req: SessionListRequest,
    user_ctx: dict = Depends(get_user_context)
):
    """Get sessions for a user or all sessions for a patient."""
    
    user_id = user_ctx.get("user_id") or req.user_id
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID required")
    
    try:
        if req.include_all_patient_sessions and req.patient_id:
            # Get ALL sessions for the patient (regardless of user)
            sessions = await _engine.vector_store.get_sessions_for_patient(
                patient_id=req.patient_id
            )
        else:
            # Get only sessions where user has participated
            sessions = await _engine.vector_store.get_user_sessions_for_patient(
                user_id=user_id,
                patient_id=req.patient_id
            )
        
        return [
            SessionOut(
                session_id=session.session_id,
                patient_id=session.patient_id,
                created_by_user_id=session.created_by_user_id,
                participants=session.participants,
                created_at=session.created_at.isoformat(),
                last_message_at=session.last_message_at.isoformat(),
                session_title=session.session_title,
                message_count=session.message_count,
                mode=session.mode,
                is_active=session.is_active,
                last_participant_id=session.last_participant_id,
                user_can_join=user_id not in session.participants
            )
            for session in sessions
        ]

    except Exception as e:
        log_error(logger, "List sessions", e)
        raise HTTPException(status_code=500, detail="Could not load sessions")

@app.post("/sessions/create")
async def create_new_session(
    request: SessionCreateRequest,
    user_ctx: dict = Depends(get_user_context)
):
    """Create a new chat session."""

    user_id = user_ctx.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID required")

    try:
        # Clean up all existing sessions for this user before creating a new one
        logger.info(f"[Session Create] Cleaning up existing sessions for user: {sanitize_user_id(user_id)}")

        # Clean up PDF documents for all sessions of this user
        if hasattr(_pdf_service, 'sessions'):
            sessions_to_cleanup = []
            for session_key in _pdf_service.sessions.keys():
                if user_id in session_key:
                    sessions_to_cleanup.append(session_key)

            for session_key in sessions_to_cleanup:
                await _pdf_service.cleanup_session(session_key)
                logger.info(f"[Session Create] Cleaned up PDF session: {sanitize_session_id(session_key)}")

        # Clean up XML documents for all sessions of this user
        if hasattr(_xml_service, 'sessions'):
            sessions_to_cleanup = []
            for session_key in _xml_service.sessions.keys():
                if user_id in session_key:
                    sessions_to_cleanup.append(session_key)

            for session_key in sessions_to_cleanup:
                await _xml_service.cleanup_session(session_key)
                logger.info(f"[Session Create] Cleaned up XML session: {sanitize_session_id(session_key)}")

        session_id = await _engine.vector_store.create_chat_session(
            user_id=user_id,
            patient_id=request.patient_id,
            mode=request.mode,
            session_title=request.session_title
        )

        logger.info(f"[Session Create] Created new session: {sanitize_session_id(session_id)} for user: {sanitize_user_id(user_id)}")
        return {"session_id": session_id, "message": "Session created successfully"}

    except Exception as e:
        log_error(logger, "Create session", e, user_id=user_id)
        raise HTTPException(status_code=500, detail="Could not create session")

@app.post("/sessions/{session_id}/join")
async def join_session(
    session_id: str,
    user_ctx: dict = Depends(get_user_context)
):
    """Join an existing session."""
    
    user_id = user_ctx.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID required")
    
    try:
        success = await _engine.vector_store.add_user_to_session(session_id, user_id)
        
        if success:
            return {"message": "Successfully joined session", "session_id": session_id}
        else:
            return {"message": "Already a participant in this session", "session_id": session_id}

    except Exception as e:
        log_error(logger, "Join session", e)
        raise HTTPException(status_code=500, detail="Could not join session")

@app.get("/sessions/{session_id}/participants")
async def get_session_participants(
    session_id: str,
    user_ctx: dict = Depends(get_user_context)
):
    """Get all participants of a session."""
    
    try:
        participants = await _engine.vector_store.get_session_participants(session_id)
        
        return {
            "session_id": session_id,
            "participants": [
                {
                    "user_id": p.user_id,
                    "first_joined_at": p.first_joined_at.isoformat(),
                    "last_active_at": p.last_active_at.isoformat(),
                    "message_count": p.message_count
                }
                for p in participants
            ]
        }

    except Exception as e:
        log_error(logger, "Get session participants", e)
        raise HTTPException(status_code=500, detail="Could not get session participants")


# Encryption and Key Exchange Endpoints

class KeyExchangeRequest(BaseModel):
    session_id: str
    client_public_key: Optional[str] = None

class KeyExchangeResponse(BaseModel):
    session_id: str
    server_public_key: str
    encrypted_session_key: Optional[str] = None
    encrypted: bool
    version: str

@app.post("/encryption/key-exchange", response_model=KeyExchangeResponse)
async def setup_session_encryption(
    request: KeyExchangeRequest,
    user_ctx: dict = Depends(get_user_context)
):
    """Setup end-to-end encryption for a session with key exchange."""
    try:
        current_user = user_ctx.get("user")
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Create encrypted session
        result = create_session_with_encryption(
            request.session_id,
            request.client_public_key
        )

        return KeyExchangeResponse(
            session_id=result["session_id"],
            server_public_key=result["server_public_key"],
            encrypted_session_key=result.get("encrypted_session_key"),
            encrypted=result["encrypted"] == "true",
            version=result["version"]
        )

    except Exception as e:
        log_error(logger, "Key exchange", e)
        raise HTTPException(status_code=500, detail="Key exchange failed")

@app.get("/encryption/server-public-key")
async def get_server_public_key():
    """Get server's public key for encryption key exchange."""
    try:
        encryption_service = get_encryption_service()
        public_key_pem = encryption_service.get_public_key_pem()

        return {
            "public_key": public_key_pem,
            "key_format": "PEM",
            "algorithm": "RSA-2048",
            "usage": "key_exchange"
        }
    except Exception as e:
        log_error(logger, "Get server public key", e)
        raise HTTPException(status_code=500, detail="Could not retrieve server public key")


@app.get("/status/repository")
async def get_repository_status(
    user_ctx: dict = Depends(get_user_context),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository)
):
    """Get information about the current FHIR repository being used."""
    current_user = user_ctx.get("user")
    repo_type = type(fhir_repo).__name__
    
    repository_info = {
        "repository_type": repo_type,
        "user_id": current_user.user_id if current_user else None,
        "username": current_user.username if current_user else None,
        "is_authenticated": False,
        "base_url": getattr(fhir_repo, '_base', 'Unknown')
    }
    
    # Check if repository is authenticated
    if hasattr(fhir_repo, 'is_authenticated'):
        try:
            repository_info["is_authenticated"] = await fhir_repo.is_authenticated()
        except Exception:
            repository_info["is_authenticated"] = False
    
    # Get connection info if available
    if hasattr(fhir_repo, '_connection'):
        connection = fhir_repo._connection
        repository_info["connection_id"] = connection.connection_id
        repository_info["provider_type"] = connection.provider_type
        repository_info["fhir_server_url"] = connection.fhir_server_url
    
    return repository_info


@app.post("/auth/ehr-login", response_model=EHRLoginResponse)
async def initiate_ehr_login(req: EHRLoginRequest):
    """Initiate EHR-based login flow."""
    try:
        # Generate unique IDs for this login attempt
        connection_id = f"ehr_conn_{uuid.uuid4()}"
        session_id = f"ehr_sess_{uuid.uuid4()}"
        state_data = {
            "connection_id": connection_id,
            "nonce": str(uuid.uuid4())
        }
        # Encode state as base64 JSON
        state = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()
        
        redirect_uri = os.getenv("EHR_REDIRECT_URI", "http://localhost:8000/auth/ehr-callback")
        
        # Create temporary session data
        session_data = {
            "session_id": session_id,
            "connection_id": connection_id,
            "fhir_server_url": req.fhir_server_url,
            "client_id": req.client_id,
            "scope": req.scope,
            "state": state,
            "redirect_uri": redirect_uri,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1)
        }
        
        # Store the temporary session
        await _connection_repo.create_ehr_login_session(session_data)
        
        # Initialize auth_params and auth_url
        auth_params = {}
        auth_url = ""
        
        # Construct authorization URL for SMART on FHIR
        fhir_base = req.fhir_server_url.rstrip('/')
        
        # For SMART Health IT sandbox - use the launcher
        if "localhost:4013" in fhir_base:
            # The base URL for the sandbox
            base_url = fhir_base.replace("/fhir", "")
            
            # For provider standalone launch, go directly to authorization endpoint
            auth_url = f"{base_url}/auth/authorize"
            
            # Standard OAuth2 authorization parameters for provider standalone
            auth_params = {
                "response_type": "code",
                "client_id": req.client_id,
                "redirect_uri": redirect_uri,
                "scope": req.scope,  # Should be "user/*.cruds" or similar
                "state": state,
                "aud": req.fhir_server_url  # FHIR server as audience
            }
        elif "launch.smarthealthit.org" in fhir_base:
            # For public SMART Health IT - provider standalone
            base_url = fhir_base.replace("/fhir", "")
            auth_url = f"{base_url}/auth/authorize"
            
            auth_params = {
                "response_type": "code",
                "client_id": req.client_id,
                "redirect_uri": redirect_uri,
                "scope": req.scope,
                "state": state,
                "aud": req.fhir_server_url
            }
        else:
            # For other FHIR servers or direct authorization
            base_url = fhir_base.replace("/fhir", "")
            auth_url = f"{base_url}/auth/authorize"
            auth_params = {
                "response_type": "code",
                "client_id": req.client_id,
                "redirect_uri": redirect_uri,
                "scope": req.scope,
                "state": state,
                "aud": req.fhir_server_url
            }
        
        authorization_url = f"{auth_url}?{urlencode(auth_params)}"

        logger.info("[DEBUG] Authorization URL generated successfully")

        return EHRLoginResponse(
            authorization_url=authorization_url,
            connection_id=connection_id,
            state=state
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/patients", response_model=list[PatientOut], summary="Search patients")
async def search_patients(
    request: Request,
    q: str = Query("", alias="q"),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository)
):

    try:
        # Use the user-specific repository instead of the global _fhir
        domain_objs = await fhir_repo.search_patients(q)

        # GDPR compliance event logging (Article 30 - Records of Processing Activities)
        try:
            user = getattr(request.state, 'user', None)
            session_id = getattr(request.state, 'session_id', None)

            await _audit_repo.log_compliance_event(
                event_type="patient_data_access",
                compliance_framework="GDPR",
                session_id=session_id,
                user_id=user.user_id if user else "anonymous",
                data_categories=["health_data", "personal_identifiers"],
                processing_purposes=["clinical_decision_support", "patient_search"],                compliance_status="compliant",
                additional_context={"lawful_basis": "Article 6(1)(c) - Legal obligation (healthcare delivery)"}
            )
        except Exception as e:
            log_error(logger, "Patient access logging", e)

        return [
            PatientOut(
                id=p.patient_id,
                name=p.name,
                age=p.age,
                sex=p.sex,
                care_unit=p.care_unit,
                vitals=p.vitals,
                labs=p.labs,
                exam=p.exam,
                procedure=p.procedure,
                imaging_observations=p.imaging_observations,
                procedure_observations=p.procedure_observations,
                social_history=p.social_history,
                medications=p.medications,
                allergies=p.allergies,
                diagnoses=p.diagnoses,
                immunizations=p.immunizations,
                diagnostic_reports=p.diagnostic_reports,
                medication_statement=p.medication_statement,
                questionnaire_response=p.questionnaire_response,
                family_history=p.family_history,
                care_team=p.care_team,
                goals=p.goals,
                clinical_impressions=p.clinical_impressions,
                risk_assessments=p.risk_assessments,
                service_requests=p.service_requests,
                medication_administrations=p.medication_administrations,
                medication_dispenses=p.medication_dispenses,
                immunization_recommendations=p.immunization_recommendations,
                appointments=p.appointments,
                episodes_of_care=p.episodes_of_care,
                imaging_studies=p.imaging_studies,
                devices=p.devices,
                device_use=p.device_use,
                nutrition_orders=p.nutrition_orders,
                adverse_events=p.adverse_events,
                # Timestamp fields
                vitals_timestamps=p.vitals_timestamps,
                labs_timestamps=p.labs_timestamps,
                exam_timestamps=p.exam_timestamps,
                procedure_timestamps=p.procedure_timestamps,
                imaging_observations_timestamps=p.imaging_observations_timestamps,
                procedure_observations_timestamps=p.procedure_observations_timestamps,
                social_history_timestamps=p.social_history_timestamps,
                medications_timestamps=p.medications_timestamps,
                allergies_timestamps=p.allergies_timestamps,
                diagnoses_timestamps=p.diagnoses_timestamps,
                immunizations_timestamps=p.immunizations_timestamps,
                diagnostic_reports_timestamps=p.diagnostic_reports_timestamps,
                medication_statement_timestamps=p.medication_statement_timestamps,
                questionnaire_response_timestamps=p.questionnaire_response_timestamps,
                family_history_timestamps=p.family_history_timestamps,
                care_team_timestamps=p.care_team_timestamps,
                goals_timestamps=p.goals_timestamps,
                clinical_impressions_timestamps=p.clinical_impressions_timestamps,
                risk_assessments_timestamps=p.risk_assessments_timestamps,
                service_requests_timestamps=p.service_requests_timestamps,
                medication_administrations_timestamps=p.medication_administrations_timestamps,
                medication_dispenses_timestamps=p.medication_dispenses_timestamps,
                immunization_recommendations_timestamps=p.immunization_recommendations_timestamps,
                appointments_timestamps=p.appointments_timestamps,
                episodes_of_care_timestamps=p.episodes_of_care_timestamps,
                imaging_studies_timestamps=p.imaging_studies_timestamps,
                devices_timestamps=p.devices_timestamps,
                device_use_timestamps=p.device_use_timestamps,
                nutrition_orders_timestamps=p.nutrition_orders_timestamps,
                adverse_events_timestamps=p.adverse_events_timestamps,
                # Encounters
                encounters=p.encounters,
                encounters_timestamps=p.encounters_timestamps,
                # Data sources
                vitals_sources = p.vitals_sources,
                labs_sources = p.labs_sources,
                exam_sources = p.exam_sources,
                procedure_sources = p.procedure_sources,
                imaging_observations_sources = p.imaging_observations_sources,
                procedure_observations_sources = p.procedure_observations_sources,
                social_history_sources = p.social_history_sources,
                medications_sources = p.medications_sources,
                allergies_sources = p.allergies_sources,
                diagnoses_sources = p.diagnoses_sources,
                immunizations_sources = p.immunizations_sources,
                diagnostic_reports_sources = p.diagnostic_reports_sources,
                medication_statement_sources = p.medication_statement_sources,
                questionnaire_response_sources = p.questionnaire_response_sources,
                encounters_sources = p.encounters_sources,
                family_history_sources=p.family_history_sources,
                care_team_sources=p.care_team_sources,
                goals_sources=p.goals_sources,
                clinical_impressions_sources=p.clinical_impressions_sources,
                risk_assessments_sources=p.risk_assessments_sources,
                service_requests_sources=p.service_requests_sources,
                medication_administrations_sources=p.medication_administrations_sources,
                medication_dispenses_sources=p.medication_dispenses_sources,
                immunization_recommendations_sources=p.immunization_recommendations_sources,
                appointments_sources=p.appointments_sources,
                episodes_of_care_sources=p.episodes_of_care_sources,
                imaging_studies_sources=p.imaging_studies_sources,
                devices_sources=p.devices_sources,
                device_use_sources=p.device_use_sources,
                nutrition_orders_sources=p.nutrition_orders_sources,
                adverse_events_sources=p.adverse_events_sources

            )
            for p in domain_objs
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load patients: {e}")

@app.get("/auth/ehr-callback", response_model=LoginResponse)
async def complete_ehr_login(
    code: str = Query(..., description="Authorization code"),
    state: str = Query(..., description="State parameter"),
    error: Optional[str] = Query(None, description="Error code if any"),
    error_description: Optional[str] = Query(None, description="Error description if any")
):
    """Complete EHR-based login and create/update user."""
    frontend_base = os.getenv("FRONTEND_URL", "http://localhost:3000")


    if error:
        logger.error(f"[ERROR] OAuth error received: {error} - {error_description}")

        # Map common errors to user-friendly messages
        if error == "access_denied":
            error_msg = "Access was denied. Please try again if you want to connect your EHR."
        elif error == "invalid_request":
            if error_description == "Unauthorized":
                error_msg = "Access was denied by the user."
            else:
                error_msg = f"Invalid request: {error_description or 'Unknown error'}"
        else:
            error_msg = error_description or error or "Authorization failed"
        
        # Always redirect to frontend with error
        frontend_url = f"{frontend_base}/login?error={error_msg}"
        return RedirectResponse(url=frontend_url, status_code=302)
    
    # Check for missing required parameters
    if not code or not state:
        logger.error(f"[ERROR] Missing required parameters - code: {bool(code)}, state: {bool(state)}")
        frontend_url = f"{frontend_base}/login?error=Missing authorization parameters"
        return RedirectResponse(url=frontend_url, status_code=302)
    
    try:
        # Extract connection_id from state parameter
        try:
            state_data = json.loads(base64.urlsafe_b64decode(state).decode())
            connection_id = state_data["connection_id"]
        except Exception as e:
            log_error(logger, "Invalid state parameter", e)
            frontend_url = f"{frontend_base}/login?error=Invalid state parameter"
            return RedirectResponse(url=frontend_url, status_code=302)
        
        # Get the temporary session data
        session_data = await _connection_repo.get_ehr_login_session(connection_id)
        if not session_data:
            logger.error("[ERROR] Login session expired")
            frontend_url = f"{frontend_base}/login?error=Login session expired"
            return RedirectResponse(url=frontend_url, status_code=302)
        
        # Verify state parameter
        if session_data["state"] != state:
            logger.error("[ERROR] State parameter mismatch")
            frontend_url = f"{frontend_base}/login?error=Security validation failed"
            return RedirectResponse(url=frontend_url, status_code=302)
        
        # Rest of your existing success logic...
        # Exchange authorization code for access token
        access_token_data = await exchange_code_for_token(
            code,
            session_data["client_id"],
            session_data["redirect_uri"],
            session_data["fhir_server_url"]
        )
        
        # Get user info from FHIR server using the access token
        user_info = await get_user_info_from_fhir(
            session_data["fhir_server_url"],
            access_token_data["access_token"]
        )
        
        # Check if user already exists based on username (to avoid the duplicate key error)
        existing_user = None
        username = user_info.get("username", f"ehr_{uuid.uuid4().hex[:8]}")
        
        try:
            existing_user = await _user_repo.get_user_by_username(username)
        except Exception:
            pass  # User doesn't exist, we'll create them
        
        # Also check by email if available
        if not existing_user and user_info.get("email"):
            try:
                existing_user = await _user_repo.get_user_by_email(user_info["email"])
            except Exception:
                pass
        
        if existing_user:
            final_user = existing_user
            logger.info(f"[INFO] Using existing user: {final_user.username}")
        else:
            # Create new user with unique username
            user_id = f"ehr_user_{uuid.uuid4()}"
            # Ensure username is unique by adding timestamp
            unique_username = f"{username}_{int(time.time())}"
            
            email = user_info.get("email")
            if not email or email.strip() == "":
                email = f"noemail+{unique_username}@optimed.local"  # Generate a unique placeholder email

            new_user = User(
                user_id=user_id,
                username=unique_username,
                email=email,
                first_name=user_info.get("first_name", "EHR"),
                last_name=user_info.get("last_name", "User"),
                role=UserRole.DOCTOR,  # Default role
                status=UserStatus.ACTIVE,
            )
            
            await _user_repo.create_user(new_user)
            final_user = new_user
            logger.info(f"[INFO] Created new user: {final_user.username}")

        # Create the EHR connection
        connection = UserEHRConnection(
            connection_id=connection_id,
            user_id=final_user.user_id,
            provider_type="smart_fhir",
            fhir_server_url=session_data["fhir_server_url"],
            client_id=session_data["client_id"],
            credentials={},
            access_token=access_token_data["access_token"],
            refresh_token=access_token_data.get("refresh_token"),
            token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=access_token_data.get("expires_in", 3600)),
            scope=session_data["scope"],
            patient_context=access_token_data.get("patient"),
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            expires_at=None
        )
        
        await _connection_repo.create_connection(connection)
        
        # Clean up the temporary session
        await _connection_repo.delete_ehr_login_session(connection_id)
        
        # Create user session
        session = UserSession(
            session_id=str(uuid.uuid4()),
            user_id=final_user.user_id,
            login_time=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
            is_active=True
        )
        
        await _user_repo.create_session(session)
        
        # Redirect to frontend with success and session info
        frontend_url = f"{frontend_base}/auth/ehr-success?session_id={session.session_id}&user_id={final_user.user_id}"
        return RedirectResponse(url=frontend_url)


    except Exception as e:
        log_error(logger, "EHR callback", e)
        # Redirect to frontend with error
        frontend_url = f"{frontend_base}/login?error=Authentication failed: {str(e)}"
        return RedirectResponse(url=frontend_url)

# Helper functions
async def exchange_code_for_token(code: str, client_id: str, redirect_uri: str, fhir_server_url: str) -> dict:
    """Exchange authorization code for access token."""    
    
    # For SMART Health IT sandbox
    if "launch.smarthealthit.org" in fhir_server_url:
        # Remove the FHIR path and use the base server for auth endpoints
        # https://launch.smarthealthit.org/v/r4/fhir -> https://launch.smarthealthit.org/v/r4
        base_url = fhir_server_url.replace("/fhir", "")
        token_url = f"{base_url.rstrip('/')}/auth/token"
    else:
        # For other FHIR servers, also try the base server approach
        # Remove /fhir suffix if present
        base_url = fhir_server_url.replace("/fhir", "")
        token_url = f"{base_url.rstrip('/')}/auth/token"

    logger.info("[DEBUG] Token URL generated successfully")

    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        logger.info(f"[DEBUG] Token response status: {response.status_code}")

        response.raise_for_status()
        return response.json()

async def get_user_info_from_fhir(fhir_server_url: str, access_token: str) -> dict:
    """Get user information from FHIR server."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/fhir+json"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            # Try to get practitioner info
            response = await client.get(
                f"{fhir_server_url.rstrip('/')}/Practitioner",
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("entry") and len(data["entry"]) > 0:
                    practitioner = data["entry"][0]["resource"]
                    name = practitioner.get("name", [{}])[0]
                    
                    return {
                        "first_name": " ".join(name.get("given", ["EHR"])),
                        "last_name": name.get("family", "User"),
                        "email": "",  # Extract from telecom if available
                        "username": f"practitioner_{practitioner.get('id', uuid.uuid4().hex[:8])}"
                    }
    except Exception:
        pass
    
    # Return default user info if we can't get practitioner data
    return {
        "first_name": "EHR",
        "last_name": "User",
        "email": "",
        "username": f"ehr_user_{uuid.uuid4().hex[:8]}"
    }

@app.post("/diagnose", response_model=dict)
async def diagnose(
    req: ChatRequest, 
    user_ctx: dict = Depends(get_user_context),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository)
):
    user_id = user_ctx.get("user_id") or req.user_id
    current_user = user_ctx.get("user")

    if current_user:
        logger.info(f"[API] Diagnosis request from {current_user.display_name} ({current_user.role.value})")

    try:
        # Use the user-specific repository
        patient_ctx: PatientContext = await fhir_repo.get_patient(str(req.patient_id))
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Patient not found: {e}")

    # GDPR compliance event logging (Article 30 - Records of Processing Activities)
    try:
        import hashlib
        await _audit_repo.log_compliance_event(
            event_type="ai_diagnosis_request",
            compliance_framework="GDPR",
            session_id=req.session_id or user_ctx.get("session_id"),
            user_id=user_id,
            patient_id_hash=hashlib.sha256(str(req.patient_id).encode()).hexdigest() if req.patient_id else None,
            data_categories=["health_data", "diagnostic_data", "ai_generated_content"],
            processing_purposes=["clinical_decision_support", "ai_diagnosis", "healthcare_delivery"],            compliance_status="compliant",
            additional_context={"lawful_basis": "Article 6(1)(c) - Legal obligation, Article 9(2)(h) - Medical diagnosis"}
        )
    except Exception as e:
        log_error(logger, "Diagnosis request logging", e)

    result = await _engine.run(patient_ctx, req.user_prompt, chat_mode=req.chat_mode, user_id=user_id, session_id=req.session_id)
    if hasattr(result, 'model_dump'):
        return result.model_dump()
    else:
        return result


@app.post("/chat-history")
async def get_chat_history(
    request: dict,
):
    """GDPR-compliant: No chat history available to prevent PHI storage."""
    patient_id = request.get("patient_id")
    session_id = request.get("session_id")
    mode = request.get("mode", "diagnose")
    
    logger.info(f"[GDPR] Chat history request blocked - patient: {sanitize_patient_id(patient_id)}, session: {sanitize_session_id(session_id)}, mode={mode}")
    
    # GDPR Compliance: Return empty history to prevent PHI exposure
    return {"messages": [], "total": 0, "gdpr_compliant": True}

@app.get(
    "/patients/{patient_id}",
    response_model=PatientOut,
    summary="Get single patient by ID",
)
async def get_patient(
    patient_id: str = Path(..., description="The patient ID"),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository)
):
    try:
        # Use the user-specific repository
        pctx = await fhir_repo.get_patient(patient_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Patient not found: {e}")
    return PatientOut(
                id=pctx.patient_id,
                name=pctx.name,
                age=pctx.age,
                sex=pctx.sex,
                care_unit=pctx.care_unit,
                vitals=pctx.vitals,
                labs=pctx.labs,
                exam=pctx.exam,
                procedure=pctx.procedure,
                imaging_observations=pctx.imaging_observations,
                procedure_observations=pctx.procedure_observations,
                social_history=pctx.social_history,
                medications=pctx.medications,
                allergies=pctx.allergies,
                diagnoses=pctx.diagnoses,
                immunizations=pctx.immunizations,
                diagnostic_reports=pctx.diagnostic_reports,
                medication_statement=pctx.medication_statement,
                questionnaire_response=pctx.questionnaire_response,
                family_history=pctx.family_history,
                care_team=pctx.care_team,
                goals=pctx.goals,
                clinical_impressions=pctx.clinical_impressions,
                risk_assessments=pctx.risk_assessments,
                service_requests=pctx.service_requests,
                medication_administrations=pctx.medication_administrations,
                medication_dispenses=pctx.medication_dispenses,
                immunization_recommendations=pctx.immunization_recommendations,
                appointments=pctx.appointments,
                episodes_of_care=pctx.episodes_of_care,
                imaging_studies=pctx.imaging_studies,
                devices=pctx.devices,
                device_use=pctx.device_use,
                nutrition_orders=pctx.nutrition_orders,
                adverse_events=pctx.adverse_events,
                # Timestamp fields
                vitals_timestamps=pctx.vitals_timestamps,
                labs_timestamps=pctx.labs_timestamps,
                exam_timestamps=pctx.exam_timestamps,
                procedure_timestamps=pctx.procedure_timestamps,
                imaging_observations_timestamps=pctx.imaging_observations_timestamps,
                procedure_observations_timestamps=pctx.procedure_observations_timestamps,
                social_history_timestamps=pctx.social_history_timestamps,
                medications_timestamps=pctx.medications_timestamps,
                allergies_timestamps=pctx.allergies_timestamps,
                diagnoses_timestamps=pctx.diagnoses_timestamps,
                immunizations_timestamps=pctx.immunizations_timestamps,
                diagnostic_reports_timestamps=pctx.diagnostic_reports_timestamps,
                medication_statement_timestamps=pctx.medication_statement_timestamps,
                questionnaire_response_timestamps=pctx.questionnaire_response_timestamps,
                family_history_timestamps=pctx.family_history_timestamps,
                care_team_timestamps=pctx.care_team_timestamps,
                goals_timestamps=pctx.goals_timestamps,
                clinical_impressions_timestamps=pctx.clinical_impressions_timestamps,
                risk_assessments_timestamps=pctx.risk_assessments_timestamps,
                service_requests_timestamps=pctx.service_requests_timestamps,
                medication_administrations_timestamps=pctx.medication_administrations_timestamps,
                medication_dispenses_timestamps=pctx.medication_dispenses_timestamps,
                immunization_recommendations_timestamps=pctx.immunization_recommendations_timestamps,
                appointments_timestamps=pctx.appointments_timestamps,
                episodes_of_care_timestamps=pctx.episodes_of_care_timestamps,
                imaging_studies_timestamps=pctx.imaging_studies_timestamps,
                devices_timestamps=pctx.devices_timestamps,
                device_use_timestamps=pctx.device_use_timestamps,
                nutrition_orders_timestamps=pctx.nutrition_orders_timestamps,
                adverse_events_timestamps=pctx.adverse_events_timestamps,
                # Encounters
                encounters=pctx.encounters,
                encounters_timestamps=pctx.encounters_timestamps,
                # Data sources
                vitals_sources=pctx.vitals_sources,
                labs_sources=pctx.labs_sources,
                exam_sources=pctx.exam_sources,
                procedure_sources=pctx.procedure_sources,
                imaging_observations_sources=pctx.imaging_observations_sources,
                procedure_observations_sources=pctx.procedure_observations_sources,
                social_history_sources=pctx.social_history_sources,
                medications_sources=pctx.medications_sources,
                allergies_sources=pctx.allergies_sources,
                diagnoses_sources=pctx.diagnoses_sources,
                immunizations_sources=pctx.immunizations_sources,
                diagnostic_reports_sources=pctx.diagnostic_reports_sources,
                medication_statement_sources=pctx.medication_statement_sources,
                questionnaire_response_sources=pctx.questionnaire_response_sources,
                encounters_sources=pctx.encounters_sources,
                family_history_sources=pctx.family_history_sources,
                care_team_sources=pctx.care_team_sources,
                goals_sources=pctx.goals_sources,
                clinical_impressions_sources=pctx.clinical_impressions_sources,
                risk_assessments_sources=pctx.risk_assessments_sources,
                service_requests_sources=pctx.service_requests_sources,
                medication_administrations_sources=pctx.medication_administrations_sources,
                medication_dispenses_sources=pctx.medication_dispenses_sources,
                immunization_recommendations_sources=pctx.immunization_recommendations_sources,
                appointments_sources=pctx.appointments_sources,
                episodes_of_care_sources=pctx.episodes_of_care_sources,
                imaging_studies_sources=pctx.imaging_studies_sources,
                devices_sources=pctx.devices_sources,
                device_use_sources=pctx.device_use_sources,
                nutrition_orders_sources=pctx.nutrition_orders_sources,
                adverse_events_sources=pctx.adverse_events_sources
    )

@app.delete("/patients/{patient_id}/chat-history", summary="GDPR-compliant: No chat history to clear")
async def clear_patient_chat_history(patient_id: str = Path(..., description="The patient ID")):
    """GDPR-compliant: No chat history stored, so nothing to clear."""
    logger.info(f"[GDPR] Chat history clear request blocked for patient: {sanitize_patient_id(patient_id)}")
    return {"message": "No chat history stored (GDPR compliant)", "gdpr_compliant": True}

@app.get("/analytics/user-metrics", summary="Get GDPR-safe user metrics")
async def get_user_metrics(
    user_id: str = Query(..., description="User ID"),
    days: int = Query(30, description="Number of days to analyze"),
    user_ctx: dict = Depends(get_user_context)
):
    """Get GDPR-safe user metrics for analytics."""
    try:
        # Ensure user can only access their own metrics
        if user_id != user_ctx.get("user_id"):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Get metrics from user repository
        metrics = await _user_repo.get_user_metrics(user_id, days)
        
        return {
            "user_id": user_id,
            "metrics": metrics,
            "gdpr_compliant": True,
            "note": "No PHI data included in metrics"
        }
        
    except Exception as e:
        log_error(logger, "Get user metrics", e)
        raise HTTPException(status_code=500, detail=f"Could not retrieve metrics: {e}")

async def _event_stream(patient: PatientContext | None = None, user_prompt: str | None = None, chat_mode: bool = False, diagnostic_mode: str = "post_meet", user_id: str | None = None, session_id: str | None = None) -> AsyncGenerator[str, None]:
    """Stream events from the diagnostic engine."""
    try:
        chunk_count = 0
        async for update in _engine.run_stream(
            patient=patient, 
            user_prompt=user_prompt, 
            chat_mode=chat_mode,
            diagnostic_mode=diagnostic_mode,  # Add this parameter
            user_id=user_id, 
            session_id=session_id
        ):
            chunk_count += 1
            
            # Handle different update types
            if update.get("type") == "status":
                status_data = {
                    "type": "status",
                    "step": update.get("step", ""),
                    "description": update.get("description", ""),
                    "status": update.get("status", ""),
                    "progress": update.get("progress", 0.0),
                    "timestamp": update.get("timestamp", datetime.now().isoformat())
                }
                chunk_line = f"data: {json.dumps(status_data)}\n\n"
                yield chunk_line
                
            elif update.get("type") == "reasoning":
                reasoning_data = {
                    "type": "reasoning",
                    "step_number": update.get("step_number", 0),
                    "total_steps": update.get("total_steps", 0),
                    "content": update.get("content", ""),
                    "timestamp": update.get("timestamp", datetime.now().isoformat())
                }
                yield f"data: {json.dumps(reasoning_data)}\n\n"
                
            elif update.get("type") == "reasoning_complete":
                reasoning_complete_data = {
                    "type": "reasoning_complete",
                    "full_reasoning": update.get("full_reasoning", ""),
                    "timestamp": update.get("timestamp", datetime.now().isoformat())
                }
                yield f"data: {json.dumps(reasoning_complete_data)}\n\n"
            
            elif update.get("type") == "differential_diagnosis_progress":
                # Handle differential diagnosis progress updates
                logger.info("[DEBUG] API Gateway received differential diagnosis progress")
                diagnosis_progress_data = {
                    "type": "differential_diagnosis_progress",
                    "diagnosis_name": update.get("diagnosis_name", ""),
                    "step": update.get("step", ""),
                    "details": update.get("details", ""),
                    "message": update.get("message", ""),
                    "timestamp": update.get("timestamp", datetime.now().isoformat())
                }
                logger.info("[DEBUG] Emitting diagnosis progress data")
                yield f"data: {json.dumps(diagnosis_progress_data)}\n\n"
            
            elif update.get("type") == "response_chunk":
                response_chunk_data = {
                    "type": "response_chunk",
                    "content": update.get("content", ""),
                    "accumulated_content": update.get("accumulated_content", ""),
                    "timestamp": update.get("timestamp", datetime.now().isoformat())
                }
                
                # Immediately yield the chunk with explicit flush markers
                chunk_line = f"data: {json.dumps(response_chunk_data)}\n\n"
                yield chunk_line
                
                # Force a small delay to ensure chunk is sent
                await asyncio.sleep(0.001)

            elif update.get("type") == "completion":
                # Extract final response and differential diagnosis data
                final_content = (
                    update.get("final_response", "") or 
                    update.get("content", "") or 
                    ""
                )
                
                # Extract differential diagnosis data if available
                differential_diagnoses = None
                if update.get("differential_diagnoses"):
                    differential_diagnoses = update["differential_diagnoses"]
                elif update.get("diagnosis_result") and hasattr(update["diagnosis_result"], 'differential'):
                    # Extract from DiagnosisResult object
                    diagnosis_result = update["diagnosis_result"]
                    differential_diagnoses = [
                        {
                            "icd_code": diff.icd_code,
                            "diagnosis_name": diff.diagnosis_name,
                            "confidence": diff.confidence,
                            "reasoning": diff.reasoning,
                            "supporting_evidence": diff.supporting_evidence
                        }
                        for diff in diagnosis_result.differential
                    ]
                
                completion_data = {
                    "type": "completion",
                    "content": final_content,
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat(),
                    "metadata": update.get("metadata", {}),
                    "generated_image": update.get("generated_image"),
                    "differential_diagnoses": differential_diagnoses,
                    "reasoning": update.get("reasoning", ""),
                    "reasoning_steps": update.get("reasoning_steps", []),
                }

                yield f"data: {json.dumps(completion_data)}\n\n"
                
    except Exception as e:
        error_data = {
            "type": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }
        yield f"data: {json.dumps(error_data)}\n\n"


@app.post("/diagnose/stream")
async def diagnose_stream(
    req: ChatRequest,
    user_ctx: dict = Depends(get_user_context),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository)
):
    """Stream diagnosis process with real-time status updates."""
    user_id = user_ctx.get("user_id") or req.user_id
    current_user = user_ctx.get("user")

    if current_user:
        pass  # User context loaded

    patient_ctx = None
    if req.patient_id:
        try:
            patient_ctx = await fhir_repo.get_patient(str(req.patient_id))
        except Exception as e:
            error_message = str(e)
            
            async def error_stream():
                error_data = {
                    "type": "error",
                    "error": f"Patient not found: {error_message}",
                    "timestamp": datetime.now().isoformat()
                }
                yield "event: error\n"
                yield f"data: {json.dumps(error_data)}\n\n"
            
            response = StreamingResponse(
                error_stream(), 
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Transfer-Encoding": "chunked"
                }
            )
            
            # Explicitly remove Content-Length header to prevent mismatch
            if "content-length" in response.headers:
                del response.headers["content-length"]

            return response

    # GDPR compliance event logging (Article 30 - Records of Processing Activities)
    try:
        import hashlib
        await _audit_repo.log_compliance_event(
            event_type="ai_diagnosis_stream",
            compliance_framework="GDPR",
            session_id=req.session_id or user_ctx.get("session_id"),
            user_id=user_id,
            patient_id_hash=hashlib.sha256(str(req.patient_id).encode()).hexdigest() if req.patient_id else None,
            data_categories=["health_data", "diagnostic_data", "ai_generated_content"],
            processing_purposes=["clinical_decision_support", "ai_diagnosis", "real_time_streaming"],            compliance_status="compliant",
            additional_context={"lawful_basis": "Article 6(1)(c) - Legal obligation, Article 9(2)(h) - Medical diagnosis"}
        )
    except Exception as e:
        log_error(logger, "Diagnosis stream logging", e)

    response = StreamingResponse(
        _event_stream(
            patient=patient_ctx,
            user_prompt=req.user_prompt,
            chat_mode=req.chat_mode,
            diagnostic_mode=req.diagnostic_mode,  # Add this parameter
            user_id=user_id,
            session_id=req.session_id
        ), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Expose-Headers": "*",
            "Transfer-Encoding": "chunked"  # Use chunked encoding instead of Content-Length
        }
    )
    
    # Explicitly remove Content-Length header to prevent mismatch
    if "content-length" in response.headers:
        del response.headers["content-length"]
    
    return response


@app.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    user_ctx: dict = Depends(get_user_context),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository)
):
    """Stream chat process with real-time status updates."""
    user_id = user_ctx.get("user_id") or req.user_id
    current_user = user_ctx.get("user")

    if current_user:
        pass  # User context loaded

    patient_ctx = None
    if req.patient_id:
        try:
            patient_ctx = await fhir_repo.get_patient(req.patient_id)
        except Exception as e:
            log_error(logger, "Fetch patient for chat", e, patient_id=req.patient_id)

    # GDPR compliance event logging (Article 30 - Records of Processing Activities)
    try:
        import hashlib
        await _audit_repo.log_compliance_event(
            event_type="ai_chat_stream",
            compliance_framework="GDPR",
            session_id=req.session_id or user_ctx.get("session_id"),
            user_id=user_id,
            patient_id_hash=hashlib.sha256(str(req.patient_id).encode()).hexdigest() if req.patient_id else None,
            data_categories=["health_data", "ai_generated_content"] if patient_ctx else ["ai_generated_content"],
            processing_purposes=["clinical_decision_support", "conversational_ai", "real_time_streaming"],
            compliance_status="compliant",
            additional_context={"lawful_basis": "Article 6(1)(c) - Legal obligation" if patient_ctx else "Article 6(1)(a) - Consent"}
        )
    except Exception as e:
        log_error(logger, "Chat stream logging", e)

    response = StreamingResponse(
        _event_stream(
            patient=patient_ctx,
            user_prompt=req.user_prompt,
            chat_mode=True,  # Always true for chat
            user_id=user_id,
            session_id=req.session_id
        ), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Transfer-Encoding": "chunked"  # Use chunked encoding instead of Content-Length
        }
    )
    
    # Explicitly remove Content-Length header to prevent mismatch
    if "content-length" in response.headers:
        del response.headers["content-length"]
    
    return response

@app.post("/chat", response_model=dict)
async def chat(
    req: ChatRequest, 
    user_ctx: dict = Depends(get_user_context),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository)
):
    """General chat endpoint that works with or without patient context."""
    user_id = user_ctx.get("user_id") or req.user_id
    current_user = user_ctx.get("user")

    if current_user:
        logger.info(f"[API] Chat request from {current_user.display_name} ({current_user.role.value})")

    patient_ctx = None
    if req.patient_id is not None:
        try:
            # Use the user-specific repository
            patient_ctx = await fhir_repo.get_patient(req.patient_id)
        except Exception as e:
            # Log the error but continue with general chat
            log_error(logger, "Fetch patient for chat", e, patient_id=req.patient_id)

    # GDPR compliance event logging (Article 30 - Records of Processing Activities)
    try:
        import hashlib
        await _audit_repo.log_compliance_event(
            event_type="ai_chat_request",
            compliance_framework="GDPR",
            session_id=req.session_id or user_ctx.get("session_id"),
            user_id=user_id,
            patient_id_hash=hashlib.sha256(str(req.patient_id).encode()).hexdigest() if req.patient_id else None,
            data_categories=["health_data", "ai_generated_content"] if patient_ctx else ["ai_generated_content"],
            processing_purposes=["clinical_decision_support", "conversational_ai", "healthcare_assistance"],
            compliance_status="compliant",
            additional_context={"lawful_basis": "Article 6(1)(c) - Legal obligation" if patient_ctx else "Article 6(1)(a) - Consent"}
        )
    except Exception as e:
        log_error(logger, "Chat request logging", e)

    # Create a mock patient context for general chat
    if not patient_ctx:
        result = await _engine.run(user_prompt=req.user_prompt, chat_mode=req.chat_mode, user_id=user_id, session_id=req.session_id)
        return result
    else:
        result = await _engine.run(patient=patient_ctx, user_prompt=req.user_prompt, chat_mode=req.chat_mode, user_id=user_id, session_id=req.session_id)
        if hasattr(result, 'model_dump'):
            return result.model_dump()
        else:
            return result
        
@app.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """Authenticate user and create session."""
    # For now, simple username lookup (implement proper password checking later)
    user = await _user_repo.get_user_by_username(req.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    session = UserSession(
        session_id=str(uuid.uuid4()),
        user_id=user.user_id,
        login_time=datetime.now(),
        last_activity=datetime.now(),
        is_active=True
    )
    
    await _user_repo.create_session(session)
    
    return LoginResponse(
        user=UserOut(
            user_id=user.user_id,
            username=user.username,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            role=user.role.value,
            status=user.status.value,
            department=user.department,
            full_name=user.full_name,
            display_name=user.display_name
        ),
        session_id=session.session_id,
        message="Login successful"
    )

@app.get("/users/by-role/{role}", response_model=list[UserOut])
async def get_users_by_role(role: str, user_ctx: dict = Depends(get_user_context)):
    """Get users by role (admin only)."""
    current_user = user_ctx.get("user")
    if not current_user or current_user.role.value not in ["admin", "doctor"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    users = await _user_repo.list_users_by_role(role)
    return [
        UserOut(
            user_id=u.user_id,
            username=u.username,
            email=u.email,
            first_name=u.first_name,
            last_name=u.last_name,
            role=u.role.value,
            status=u.status.value,
            department=u.department,
            full_name=u.full_name,
            display_name=u.display_name
        )
        for u in users
    ]

@app.get("/auth/me", response_model=UserOut)
async def get_current_user_info(user_ctx: dict = Depends(get_user_context)):
    """Get current user information."""
    current_user = user_ctx.get("user")
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return UserOut(
        user_id=current_user.user_id,
        username=current_user.username,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        role=current_user.role.value,
        status=current_user.status.value,
        department=current_user.department,
        full_name=current_user.full_name,
        display_name=current_user.display_name
    )

@app.post("/auth/logout")
async def logout(user_ctx: dict = Depends(get_user_context)):
    """Logout user and invalidate session."""
    current_user = user_ctx.get("user")
    if current_user:
        # Get session ID from header
        # You might need to modify this based on how you store session ID
        pass
    
    return {"message": "Logout successful"}
   

### Image endpoints

@app.post("/dicom/upload", response_model=DICOMUploadResponse)
async def upload_dicom_image(
    request: Request,
    file: UploadFile = File(...),
    patient_id: Optional[str] = Form(None)
):
    """Upload a DICOM image file."""
    # Get current user from session
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")
    
    session = await _user_repo.get_active_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    user = await _user_repo.get_user_by_id(session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    try:
        # Read file content
        file_content = await file.read()
        
        # Create upload request
        from optimed.core.domain import ImageUploadRequest
        upload_request = ImageUploadRequest(
            user_id=user.user_id,
            filename=file.filename or "unknown.dcm",
            file_content=file_content,
            patient_id=patient_id
        )
        
        # Get image service
        image_service = _create_image_service()
        
        # Process upload
        dicom_image = await image_service.upload_image(upload_request)
        
        # Convert to response model
        image_response = DICOMImageResponse(
            image_id=dicom_image.image_id,
            patient_id=dicom_image.patient_id,
            user_id=dicom_image.user_id,
            filename=dicom_image.filename,
            file_size=dicom_image.file_size,
            metadata=dicom_image.metadata.to_dict(),
            dimensions={
                'width': dicom_image.dimensions.width,
                'height': dicom_image.dimensions.height,
                'depth': dicom_image.dimensions.depth,
                'pixel_spacing_x': dicom_image.dimensions.pixel_spacing_x,
                'pixel_spacing_y': dicom_image.dimensions.pixel_spacing_y,
                'slice_thickness': dicom_image.dimensions.slice_thickness
            },
            default_window_level={
                'center': dicom_image.default_window_level.center,
                'width': dicom_image.default_window_level.width
            },
            status=dicom_image.status.value,
            uploaded_at=dicom_image.uploaded_at,
            processed_at=dicom_image.processed_at,
            storage_path=dicom_image.storage_path
        )

        # GDPR compliance event logging (Article 30 - Records of Processing Activities)
        try:
            import hashlib
            await _audit_repo.log_compliance_event(
                event_type="dicom_image_upload",
                compliance_framework="GDPR",
                session_id=session_id,
                user_id=user.user_id,
                patient_id_hash=hashlib.sha256(patient_id.encode()).hexdigest() if patient_id else None,
                data_categories=["medical_imaging", "diagnostic_data", "health_data"],
                processing_purposes=["clinical_decision_support", "diagnostic_analysis", "medical_imaging"],                compliance_status="compliant",
                additional_context={"lawful_basis": "Article 6(1)(c) - Legal obligation (healthcare delivery), Article 9(2)(h) - Medical diagnosis"}
            )
        except Exception as e:
            log_error(logger, "DICOM upload logging", e)

        return DICOMUploadResponse(
            image_id=dicom_image.image_id,
            message="DICOM image uploaded successfully",
            image=image_response
        )
        
    except Exception as e:
        log_error(logger, "DICOM upload", e)
        raise HTTPException(status_code=400, detail=f"Failed to upload DICOM image: {str(e)}")

@app.get("/dicom/images", response_model=DICOMImageListResponse)
async def list_user_dicom_images(request: Request):
    """List all DICOM images for the current user."""
    # Get current user from session
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")
    
    session = await _user_repo.get_active_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    try:
        # Get image service
        image_service = _create_image_service()
        
        # Get user's images
        images = await image_service.list_user_images(session.user_id)
        
        # Convert to response models with better error handling
        image_responses = []
        for img in images:
            try:
                # Ensure metadata.to_dict() works properly
                metadata_dict = img.metadata.to_dict() if hasattr(img.metadata, 'to_dict') else {}
                
                image_responses.append(DICOMImageResponse(
                    image_id=img.image_id,
                    patient_id=img.patient_id,
                    user_id=img.user_id,
                    filename=img.filename,
                    file_size=img.file_size,
                    metadata=metadata_dict,
                    dimensions={
                        'width': img.dimensions.width,
                        'height': img.dimensions.height,
                        'depth': img.dimensions.depth,
                        'pixel_spacing_x': img.dimensions.pixel_spacing_x,
                        'pixel_spacing_y': img.dimensions.pixel_spacing_y,
                        'slice_thickness': img.dimensions.slice_thickness
                    },
                    default_window_level={
                        'center': img.default_window_level.center,
                        'width': img.default_window_level.width
                    },
                    status=img.status.value,
                    uploaded_at=img.uploaded_at,
                    processed_at=img.processed_at,
                    storage_path=img.storage_path
                ))
            except Exception:
                logger.error(f"[ERROR] Failed to serialize image - doc: {sanitize_document_id(img.image_id)}")
                # Skip this image and continue with others
                continue
        
        return DICOMImageListResponse(images=image_responses)
        
    except Exception as e:
        log_error(logger, "List DICOM images", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to list images: {str(e)}")

@app.get("/dicom/images/{image_id}", response_model=DICOMImageResponse)
async def get_dicom_image(image_id: str, request: Request):
    """Get a specific DICOM image by ID."""
    # Get current user from session
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")
    
    session = await _user_repo.get_active_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    try:
        # Get image service
        image_service = _create_image_service()
        
        # Get image
        image = await image_service.get_image(image_id, session.user_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        
        # Convert to response model
        return DICOMImageResponse(
            image_id=image.image_id,
            patient_id=image.patient_id,
            user_id=image.user_id,
            filename=image.filename,
            file_size=image.file_size,
            metadata=image.metadata.to_dict(),
            dimensions={
                'width': image.dimensions.width,
                'height': image.dimensions.height,
                'depth': image.dimensions.depth,
                'pixel_spacing_x': image.dimensions.pixel_spacing_x,
                'pixel_spacing_y': image.dimensions.pixel_spacing_y,
                'slice_thickness': image.dimensions.slice_thickness
            },
            default_window_level={
                'center': image.default_window_level.center,
                'width': image.default_window_level.width
            },
            status=image.status.value,
            uploaded_at=image.uploaded_at,
            processed_at=image.processed_at,
            storage_path=image.storage_path
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Get DICOM image", e)
        raise HTTPException(status_code=500, detail=f"Failed to get image: {str(e)}")

@app.get("/dicom/images/{image_id}/pixel-data", response_model=DICOMPixelDataResponse)
async def get_dicom_pixel_data(
    image_id: str, 
    request: Request,
    window_center: Optional[float] = Query(None),
    window_width: Optional[float] = Query(None)
):
    """Get pixel data for a DICOM image with optional windowing."""
    # Get current user from session
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")
    
    session = await _user_repo.get_active_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    try:
        # Get image service
        image_service = _create_image_service()
        
        # Create window level if specified
        window_level = None
        if window_center is not None and window_width is not None:
            from optimed.core.domain import WindowLevel
            window_level = WindowLevel(center=window_center, width=window_width)
        
        # Get pixel data
        pixel_data = await image_service.get_image_pixel_data(
            image_id, session.user_id, window_level
        )
        if not pixel_data:
            raise HTTPException(status_code=404, detail="Pixel data not found")
        
        # Convert numpy array to PIL Image and then to base64
        if pixel_data.pixel_array.ndim == 2:
            # Grayscale image
            pil_image = Image.fromarray(pixel_data.pixel_array, mode='L')
        elif pixel_data.pixel_array.ndim == 3:
            # RGB image
            pil_image = Image.fromarray(pixel_data.pixel_array, mode='RGB')
        else:
            raise HTTPException(status_code=400, detail="Unsupported image format")
        
        # Convert to base64
        buffer = io.BytesIO()
        pil_image.save(buffer, format='PNG')
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        return DICOMPixelDataResponse(
            image_id=pixel_data.image_id,
            image_data_base64=f"data:image/png;base64,{image_base64}",
            original_dtype=pixel_data.original_dtype,
            photometric_interpretation=pixel_data.photometric_interpretation,
            statistics=pixel_data.get_statistics()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Get pixel data", e)
        raise HTTPException(status_code=500, detail=f"Failed to get pixel data: {str(e)}")

@app.delete("/dicom/images/{image_id}")
async def delete_dicom_image(image_id: str, request: Request):
    """Delete a DICOM image."""
    # Get current user from session
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")
    
    session = await _user_repo.get_active_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    try:
        # Get image service
        image_service = _create_image_service()
        
        # Delete image
        await image_service.delete_image(image_id, session.user_id)
        
        return {"message": "Image deleted successfully"}
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_error(logger, "Delete DICOM image", e)
        raise HTTPException(status_code=500, detail=f"Failed to delete image: {str(e)}")

@app.post("/dicom/images/{image_id}/analyze", response_model=dict)
async def analyze_dicom_image(
    image_id: str,
    request: Request,
    query: str = Body(..., description="Analysis query or clinical question"),
    patient_id: Optional[str] = Body(None, description="Optional patient ID for context")
):
    """Analyze a DICOM image using AI vision."""
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")
    
    session = await _user_repo.get_active_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    try:
        # Get image service
        image_service = _create_image_service()
        
        # Get image details
        image = await image_service.get_image(image_id, session.user_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        
        # Get pixel data
        pixel_data = await image_service.get_image_pixel_data(image_id, session.user_id)
        if not pixel_data:
            raise HTTPException(status_code=404, detail="Image pixel data not found")
        
        # Run analysis using the image analysis engine
        analysis = await _image_analysis_engine.analyze(
            pixel_data=pixel_data,
            metadata=image.metadata,
            query=query,
            user_id=session.user_id,
            patient_id=patient_id,
            session_id=session_id
        )
        
        return {
            "image_id": image_id,
            "patient_id": patient_id,
            "query": query,
            "analysis": analysis,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        log_error(logger, "DICOM analysis", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@app.get("/dicom/images/{image_id}/similar")
async def find_similar_dicom_images(
    image_id: str,
    request: Request,
    limit: int = Query(5, ge=1, le=20)
):
    """Find similar DICOM images based on embeddings."""
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")
    
    session = await _user_repo.get_active_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    try:
        image_service = _create_image_service()
        similar_images = await image_service.find_similar_images(
            image_id, session.user_id, limit
        )
        
        return {
            "reference_image_id": image_id,
            "similar_images": similar_images
        }
        
    except Exception as e:
        log_error(logger, "Similar image search", e)
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
    

@app.get("/patients/{patient_id}/journal", response_model=List[JournalEntryResponse])
async def get_patient_journal(
    patient_id: str,
    user_ctx: dict = Depends(get_user_context),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository)
):
    """Get journal entries for a patient."""
    try:
        entries = await fhir_repo.get_patient_journal_entries(patient_id)
        return [
            JournalEntryResponse(
                entry_id=entry.entry_id,
                patient_id=entry.patient_id,
                title=entry.title,
                content=entry.content,
                entry_type=entry.entry_type.value,
                created_by=entry.created_by,
                created_at=entry.created_at.isoformat(),
                updated_at=entry.updated_at.isoformat(),
                author_name=entry.author_name,
                author_role=entry.author_role
            )
            for entry in entries
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load journal: {e}")

@app.post("/patients/{patient_id}/journal", response_model=JournalEntryResponse)
async def create_journal_entry(
    patient_id: str,
    request: JournalEntryRequest,
    user_ctx: dict = Depends(get_user_context),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository)
):
    """Create a new journal entry."""
    try:
        current_user = user_ctx.get("user")
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        # Validate entry type
        try:
            entry_type = JournalEntryType(request.entry_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid entry type: {request.entry_type}")
        
        create_request = JournalEntryCreate(
            patient_id=patient_id,
            title=request.title,
            content=request.content,
            entry_type=entry_type
        )
        
        entry = await fhir_repo.create_journal_entry(create_request, current_user)
        
        return JournalEntryResponse(
            entry_id=entry.entry_id,
            patient_id=entry.patient_id,
            title=entry.title,
            content=entry.content,
            entry_type=entry.entry_type.value,
            created_by=entry.created_by,
            created_at=entry.created_at.isoformat(),
            updated_at=entry.updated_at.isoformat(),
            author_name=entry.author_name,
            author_role=entry.author_role
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create journal entry: {e}")

@app.put("/patients/{patient_id}/journal/{entry_id}", response_model=JournalEntryResponse)
async def update_journal_entry(
    patient_id: str,
    entry_id: str,
    request: JournalEntryUpdateRequest,
    user_ctx: dict = Depends(get_user_context),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository)
):
    """Update a journal entry."""
    try:
        current_user = user_ctx.get("user")
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        # Validate entry type if provided
        update_data = {}
        if request.title is not None:
            update_data["title"] = request.title
        if request.content is not None:
            update_data["content"] = request.content
        if request.entry_type is not None:
            try:
                update_data["entry_type"] = JournalEntryType(request.entry_type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid entry type: {request.entry_type}")

        update_request = JournalEntryUpdate(**update_data)  # type: ignore
        entry = await fhir_repo.update_journal_entry(entry_id, update_request, current_user)
        
        return JournalEntryResponse(
            entry_id=entry.entry_id,
            patient_id=entry.patient_id,
            title=entry.title,
            content=entry.content,
            entry_type=entry.entry_type.value,
            created_by=entry.created_by,
            created_at=entry.created_at.isoformat(),
            updated_at=entry.updated_at.isoformat(),
            author_name=entry.author_name,
            author_role=entry.author_role
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update journal entry: {e}")

@app.delete("/patients/{patient_id}/journal/{entry_id}")
async def delete_journal_entry(
    patient_id: str,
    entry_id: str,
    user_ctx: dict = Depends(get_user_context),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository)
):
    """Delete a journal entry."""
    try:
        current_user = user_ctx.get("user")
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        deleted = await fhir_repo.delete_journal_entry(entry_id, current_user)
        if not deleted:
            raise HTTPException(status_code=404, detail="Journal entry not found")
        
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete journal entry: {e}")

@app.post("/journal/generate")
async def generate_journal_entry(
    request: dict,
    user_ctx: dict = Depends(get_user_context),
    accept_language: str | None = Header(default=None, alias="Accept-Language")
):
    """Generate a complete journal entry based on user prompt."""
    try:
        current_user = user_ctx.get("user")
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        prompt = request.get("prompt", "")
        entry_type = request.get("entry_type", "note")
        patient_id = request.get("patient_id")
        requested_language = request.get("language") or accept_language
        
        if not prompt.strip():
            raise HTTPException(status_code=400, detail="Prompt is required")
        
        # Get patient context if provided
        patient_context = ""
        if patient_id:
            try:
                # Get FHIR repository for this user
                fhir_repo = await _connection_service.create_fhir_repository(
                    current_user.user_id, 
                    provider_type="smart_fhir"
                ) or _fhir
                
                patient = await fhir_repo.get_patient(patient_id)
                patient_context = f"""
Patient Information:
- Name: {patient.name}
- Age: {patient.age}
- Sex: {patient.sex}
- Recent Vitals: {', '.join([f"{k}: {v}" for k, v in list(patient.vitals.items())[:5]])}
- Current Medications: {', '.join([f"{k}: {v}" for k, v in list(patient.medications.items())[:5]])}
- Active Diagnoses: {', '.join([f"{k}: {v}" for k, v in list(patient.diagnoses.items())[:3]])}
"""
            except Exception:
                logger.warning("[Warning] Could not fetch patient context")
                patient_context = ""
        
        # Define entry type contexts and templates
        entry_type_info = {
            "note": {
                "name": "Progress Note",
                "structure": """SUBJECTIVE: Patient's reported symptoms and concerns
OBJECTIVE: Vital signs, physical examination findings
ASSESSMENT: Clinical impression and analysis
PLAN: Treatment plan and follow-up"""
            },
            "observation": {
                "name": "Clinical Observation",
                "structure": """OBSERVATION: What was observed
FINDINGS: Key clinical findings
CLINICAL SIGNIFICANCE: Importance of findings
RECOMMENDATIONS: Suggested actions"""
            },
            "treatment": {
                "name": "Treatment Note",
                "structure": """TREATMENT PROVIDED: Intervention details
PATIENT RESPONSE: Response to treatment
POST-TREATMENT ASSESSMENT: Current status
PLAN: Next steps and monitoring"""
            },
            "diagnosis": {
                "name": "Diagnostic Assessment",
                "structure": """PRESENTING COMPLAINT: Chief complaint
HISTORY OF PRESENT ILLNESS: Timeline and details
EXAMINATION FINDINGS: Physical exam results
DIFFERENTIAL DIAGNOSIS: Possible diagnoses
WORKING DIAGNOSIS: Most likely diagnosis
PLAN FOR FURTHER EVALUATION: Next steps"""
            },
            "assessment": {
                "name": "Clinical Assessment",
                "structure": """PATIENT STATUS: Current condition
REVIEW OF SYSTEMS: System-by-system review
CLINICAL IMPRESSION: Assessment summary
RISK FACTORS: Identified risks
RECOMMENDATIONS: Clinical recommendations"""
            },
            "plan": {
                "name": "Care Plan",
                "structure": """CARE GOALS: Treatment objectives
INTERVENTIONS: Planned treatments
MONITORING PLAN: Follow-up schedule
PATIENT EDUCATION: Education provided
COORDINATION OF CARE: Team involvement"""
            }
        }
        
        entry_info = entry_type_info.get(entry_type, entry_type_info["note"])
        current_date = datetime.now().strftime("%B %d, %Y")
        
        # Determine active language code
        try:
            from optimed.core.lang import detect_language_code
            raw_lang = (requested_language or detect_language_code(prompt or "") or "en")
            # Normalize values like "sv-SE,sv;q=0.9" -> "sv"
            primary = str(raw_lang).split(',')[0]
            primary = primary.split(';')[0].strip().lower()
            active_lang = primary.split('-')[0] if '-' in primary else primary
        except Exception:
            active_lang = "en"

        # Create comprehensive prompt for journal generation with language policy
        generation_prompt = f"""You are an expert medical documentation assistant. Generate a complete {entry_info['name']} based on the following user request.

{patient_context}

User Request: "{prompt}"

Create a comprehensive {entry_info['name']} that follows this structure:
{entry_info['structure']}

Requirements:
- Use professional medical terminology
- Be specific and detailed where appropriate
- Include relevant clinical observations
- Follow standard medical documentation practices
- Ensure all sections are clinically relevant
- Use proper medical abbreviations when appropriate
- Make realistic clinical assessments based on the prompt

Generate both a title and complete content for this journal entry.

Please format your response as JSON with the following structure:
{{
    "title": "Generated title for the entry",
    "content": "Complete journal entry content with proper formatting and line breaks"
}}

Focus on creating realistic, clinically sound documentation that a healthcare provider would actually write.

Important language policy: Write both the title and content in '{active_lang}'. Use clinically appropriate terminology in this language.
"""

        # Generate using the journal LLM service
        response = await _journal_llm_service.chat([
            ChatMessage(role=ChatRole.SYSTEM, content=f"You are an expert medical documentation assistant. Always respond with valid JSON format. Respond in '{active_lang}'."),
            ChatMessage(role=ChatRole.USER, content=generation_prompt)
        ])
        
        # Parse the response
        try:
            # Try to extract JSON from the response
            response_text = response.content.strip()
            
            # Handle potential markdown code blocks
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            generated_data = json.loads(response_text)
            
            title = generated_data.get("title", f"{entry_info['name']} - {current_date}")
            content = generated_data.get("content", "")
            
        except json.JSONDecodeError:
            # Fallback: treat entire response as content
            content = response.content.strip()
            title = f"{entry_info['name']} - {current_date}"
        
        # Clean up content formatting
        content = content.replace("\\n", "\n").strip()
        
        return {
            "title": title,
            "content": content,
            "entry_type": entry_type,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt
        }
        
    except Exception as e:
        log_error(logger, "Journal generation", e)
        raise HTTPException(status_code=500, detail=f"Journal generation failed: {e}")

@app.post("/journal/autocomplete")
async def journal_autocomplete(
    request: dict,
    user_ctx: dict = Depends(get_user_context),
    accept_language: str | None = Header(default=None, alias="Accept-Language")
):
    """Provide LLM-guided autocomplete for journal entries."""
    try:
        current_user = user_ctx.get("user")
        if not current_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        text = request.get("text", "")
        entry_type = request.get("entry_type", "note")
        cursor_position = request.get("cursor_position", len(text))
        max_tokens = request.get("max_tokens", 50)
        requested_language = request.get("language") or accept_language
        
        if not text.strip():
            return {"completion": "", "suggestions": []}
        
        # Get text before cursor
        text_before_cursor = text[:cursor_position]
        
        # Create context-aware prompt based on entry type
        entry_type_context = {
            "note": "clinical progress note",
            "observation": "clinical observation",
            "treatment": "treatment documentation",
            "diagnosis": "diagnostic assessment",
            "assessment": "clinical assessment",
            "plan": "care plan"
        }
        
        context = entry_type_context.get(entry_type, "medical documentation")

        # Determine active language code for autocomplete
        try:
            from optimed.core.lang import detect_language_code
            raw_lang = (requested_language or detect_language_code(text or "") or "en")
            primary = str(raw_lang).split(',')[0]
            primary = primary.split(';')[0].strip().lower()
            active_lang = primary.split('-')[0] if '-' in primary else primary
        except Exception:
            active_lang = "en"
        
        completion_prompt = f"""You are assisting with medical documentation. Complete the following {context} text professionally and concisely.

Current text: "{text_before_cursor}"

Provide a natural continuation that:
- Uses appropriate medical terminology
- Maintains professional tone
- Is clinically relevant
- Follows standard documentation practices
- Is 1-3 words or a short phrase (max {max_tokens} characters)

Important language policy: Respond in '{active_lang}'.

Completion:"""

        
        response = await _journal_llm_service.chat([
            ChatMessage(role=ChatRole.SYSTEM, content=f"You are a medical documentation assistant. Respond in '{active_lang}'."),
            ChatMessage(role=ChatRole.USER, content=completion_prompt)
        ])
        
        completion = response.content.strip()
        
        # Clean up the completion
        if completion.startswith('"') and completion.endswith('"'):
            completion = completion[1:-1]
        
        # Limit completion length
        if len(completion) > max_tokens:
            completion = completion[:max_tokens].rsplit(' ', 1)[0]
        
        return {
            "completion": completion,
            "cursor_position": cursor_position
        }
        
    except Exception as e:
        log_error(logger, "Autocomplete", e)
        raise HTTPException(status_code=500, detail=f"Autocomplete failed: {e}")


@app.post("/images/generate")
async def generate_image(
    request: ImageGenerationRequestModel,
    user_ctx: dict = Depends(get_user_context)
):
    """Generate an educational image using AI."""
    try:
        if not _image_generation_service:
            raise HTTPException(status_code=503, detail="Image generation service not available")
        
        user_id = user_ctx.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        # Get or create session for image generation
        session_id = await _engine.get_or_create_session(
            user_id=user_id,
            patient_id=request.patient_id,
            mode="image_generation"
        )
        
        # Create generation request
        gen_request = ImageGenerationRequest(
            prompt=request.prompt,
            width=request.width,
            height=request.height,
            user_id=user_id,
            patient_id=request.patient_id,
            session_id=session_id
        )
        
        # Generate image
        generated_image = await _image_generation_service.generate_image(gen_request)
        
        # Store image
        if _generated_image_repo:
            await _generated_image_repo.store_generated_image(generated_image)
        
        return {
            "success": True,
            "image_id": generated_image.generation_id,
            "prompt": generated_image.prompt,
            "created_at": generated_image.created_at.isoformat(),
            "metadata": generated_image.metadata,
            "model_info": generated_image.model_info
        }
        
    except Exception as e:
        log_error(logger, "Generate image", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/images/generated/{image_id}")
async def get_generated_image(
    image_id: str,
    user_ctx: dict = Depends(get_user_context)
):
    """Retrieve a generated image by ID."""
    try:
        user_id = user_ctx.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        if not _generated_image_repo:
            raise HTTPException(status_code=404, detail="Image repository not available")
        
        generated_image = await _generated_image_repo.get_generated_image(image_id)
        if not generated_image:
            raise HTTPException(status_code=404, detail="Image not found")
        
        # Check if user has access to this image
        if generated_image.metadata.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        return Response(
            content=generated_image.image_data,
            media_type=f"image/{generated_image.image_format}",
            headers={
                "Content-Disposition": f"attachment; filename=generated_{image_id}.{generated_image.image_format}",
                "Cache-Control": "public, max-age=31536000"  # Cache for 1 year
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Retrieve image", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/images/user/{user_id}")
async def get_user_generated_images(
    user_id: str,
    limit: int = Query(10, description="Maximum number of images to return"),
    user_ctx: dict = Depends(get_user_context)
):
    """Get generated images for a user."""
    try:
        current_user_id = user_ctx.get("user_id")
        if not current_user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        # Only allow users to see their own images
        if current_user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        if not _generated_image_repo:
            raise HTTPException(status_code=404, detail="Image repository not available")
        
        images = await _generated_image_repo.get_user_generated_images(user_id, limit)
        
        return {
            "images": [
                {
                    "image_id": img.generation_id,
                    "prompt": img.prompt,
                    "created_at": img.created_at.isoformat(),
                    "metadata": img.metadata,
                    "model_info": img.model_info
                }
                for img in images
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Retrieve user images", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/images/service/status")
async def get_image_generation_status(
    user_ctx: dict = Depends(get_user_context)
):
    """Get the status of the image generation service."""
    try:
        if not _image_generation_service:
            return {
                "enabled": False,
                "available": False,
                "message": "Image generation service not configured"
            }
        
        available = await _image_generation_service.is_available()
        
        return {
            "enabled": True,
            "available": available,
            "message": "Service available" if available else "Service unavailable"
        }
        
    except Exception as e:
        logger.error("Error checking image generation status")
        return {
            "enabled": True,
            "available": False,
            "message": f"Error checking service: {str(e)}"
        }


@app.post("/lookup", response_model=LookupResponse)
async def lookup_term(
    request: LookupRequest,
    user_ctx: dict = Depends(get_user_context),
    accept_language: str | None = Header(default=None, alias="Accept-Language")
):
    """Lookup a medical term using web search (favoring medical sources, including FASS for medications) and summarize."""
    term = request.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="Term is required")

    # Build a source-biased query
    query_parts = [term]
    term_type = (request.term_type or "").lower()
    if term_type in ("medication", "medicine", "drug"):
        query_parts.append("site:fass.se OR site:drugs.com OR site:fda.gov")
    elif term_type in ("diagnosis", "condition"):
        query_parts.append("clinical guidelines site:who.int OR site:cdc.gov OR site:mayoclinic.org")
    elif term_type in ("vital", "lab"):
        query_parts.append("reference ranges site:who.int OR site:cdc.gov")
    else:
        query_parts.append("medical information")

    query = " ".join(query_parts)

    try:
        # Determine language preference from Accept-Language header
        active_lang = "en"
        try:
            if accept_language:
                primary = str(accept_language).split(',')[0]
                primary = primary.split(';')[0].strip().lower()
                active_lang = primary or "en"
            else:
                active_lang = "en"
        except Exception:
            active_lang = "en"


        web_response = await _web_search_service.search(
            query=query,
            max_results=8,
            target_language=(active_lang if active_lang != "en" else None)
        )

        sources = [
            {"title": r.title, "url": r.url}
            for r in web_response.results[:5]
        ]

        # If FASS link exists, place it first
        sources.sort(key=lambda s: ("fass.se" not in s["url"],))

        # Build a structured, type-aware summary using LLM
        summary_text = web_response.summary or ""
        try:
            # Prepare compact sources content to keep token usage under control
            def truncate(text: str, limit: int = 600) -> str:
                if not text:
                    return ""
                return text if len(text) <= limit else text[:limit] + "…"

            combined_content = "\n\n".join([
                f"Title: {r.title}\nURL: {r.url}\nSnippet: {truncate(r.snippet or '')}"
                for r in web_response.results[:5]
            ]) if web_response and web_response.results else ""

            detected_type = (request.term_type or "").lower()
            if detected_type in ("medication", "medicine", "drug"):
                type_instructions = (
                    "Provide a concise, clinically useful medication summary with bullet-point sections: "
                    "1) Indications/Uses, 2) Mechanism of Action, 3) Typical Adult Dosing (only if clearly available from sources), "
                    "4) Contraindications, 5) Common Side Effects and Serious Adverse Effects, "
                    "6) Important Interactions, 7) Monitoring, 8) Pregnancy/Lactation considerations."
                )
            elif detected_type in ("diagnosis", "condition", "disease"):
                type_instructions = (
                    "Provide a concise, clinically useful diagnosis summary with bullet-point sections: "
                    "1) Definition and Epidemiology, 2) Typical Presentation (key symptoms/signs), 3) Differential Diagnosis (commonly confused conditions), "
                    "4) Initial Workup (key labs/imaging), 5) First-line Management and Alternatives, 6) Red Flags/When to escalate, 7) Common Complications/Causes."
                )
            elif detected_type in ("vital", "lab", "laboratory"):
                type_instructions = (
                    "Provide a concise summary for a vital sign or laboratory value with bullet-point sections: "
                    "1) Typical Reference Range(s) (if known), 2) Clinical Interpretation, 3) Common Causes of High/Low, 4) Next Steps/Follow-up."
                )
            else:
                type_instructions = (
                    "Provide a concise clinical overview. If this relates to a medication, focus on safety and indications; "
                    "if it relates to a condition, focus on presentation and management. Use bullet points where appropriate."
                )

            summary_prompt = f"""
            Summarize the medical query "{term}" using the provided web findings.

            {type_instructions}

            Rules:
            - Respond in '{active_lang}'.
            - Be precise and evidence-oriented. Prefer information supported by the sources below.
            - Keep the overall summary under 220 words unless essential details are needed.
            - Do not fabricate dosing or numbers; include them only if clearly present in the sources.
            - If sources disagree, note the uncertainty briefly.

            Sources:
            {combined_content if combined_content else 'No specific web sources available.'}
            """

            llm_resp = await _journal_llm_service.chat([
                ChatMessage(role=ChatRole.SYSTEM, content="You are a senior clinical assistant who writes structured, succinct, and accurate medical summaries."),
                ChatMessage(role=ChatRole.USER, content=summary_prompt)
            ])

            if llm_resp and llm_resp.content and len(llm_resp.content.strip()) > 0:
                summary_text = llm_resp.content.strip()
        except Exception:
            logger.warning("[Lookup] Structured summary generation failed, using default summary")

        return LookupResponse(
            term=term,
            summary=summary_text,
            sources=sources,
            raw_results=[
                {"title": r.title, "url": r.url, "snippet": r.snippet, "score": r.relevance_score}
                for r in web_response.results
            ]
        )
    except Exception as e:
        log_error(logger, "Lookup", e)
        raise HTTPException(status_code=500, detail="Lookup failed")


# PDF Document Upload and Management Endpoints

class PDFUploadResponse(BaseModel):
    document_id: str
    filename: str
    file_size: int
    status: str
    uploaded_at: str
    patient_id: Optional[str] = None


class XMLUploadResponse(BaseModel):
    document_id: str
    filename: str
    file_size: int
    status: str
    uploaded_at: str
    patient_id: Optional[str] = None
    document_type: Optional[str] = None


class UploadContextResponse(BaseModel):
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    patient_id: Optional[str] = None
    chat_session_id: Optional[str] = None


@app.get("/documents/test-session")
async def test_session(request: Request):
    """Test endpoint to debug session issues"""
    headers = dict(request.headers)
    session_id = headers.get('x-session-id')

    result = {
        "received_session_id": session_id,
        "session_id_length": len(session_id) if session_id else 0,
        "all_headers": headers,
    }

    if session_id:
        try:
            session = await _user_repo.get_active_session(session_id)
            if session:
                result["session_exists"] = True
                result["session_user_id"] = session.user_id
                user = await _user_repo.get_user_by_id(session.user_id)
                if user:
                    result["user_found"] = True
                    result["username"] = user.username
                else:
                    result["user_found"] = False
            else:
                result["session_exists"] = False
        except Exception as e:
            result["error"] = str(e)

    return result


@app.get("/documents/upload-context", response_model=UploadContextResponse)
async def get_upload_context(
    request: Request,
    filename: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    user_ctx: dict = Depends(get_user_context)
):
    """Provide upload context for file watcher clients.

    This endpoint is used by the CLARA file watcher agent to fetch
    dynamic upload parameters (patient_id, chat_session_id) before
    uploading documents.

    Args:
        filename: Name of the file to be uploaded
        file_type: Type of file ("pdf" or "xml")
        user_ctx: User context from session (injected by dependency)

    Returns:
        UploadContextResponse with patient_id and chat_session_id
    """

    user_id = user_ctx.get("user_id")
    session_id = user_ctx.get("session_id")

    # Debug: Log headers
    logger.info("[DEBUG] upload-context - Headers received")
    logger.info(f"[DEBUG] upload-context - user: {sanitize_user_id(user_id) if user_id else "none"}, session: {sanitize_session_id(session_id) if session_id else "none"}")

    if not user_id:
        logger.error(f"[ERROR] User ID not found in user context - session: {sanitize_session_id(session_id) if session_id else "none"}")
        return UploadContextResponse(patient_id=None, chat_session_id=None)

    try:
        # Query database for most recent session for this user
        sessions = await _vector_store.get_user_sessions_for_patient(
            user_id=user_id,
            limit=1
        )

        logger.info(f"[DEBUG] upload-context - Found {len(sessions) if sessions else 0} sessions in vector store")

        if sessions and len(sessions) > 0:
            most_recent_session = sessions[0]
            logger.info("[INFO] upload-context - Returning most recent session from DB")
            return UploadContextResponse(
                patient_id=most_recent_session.patient_id,
                chat_session_id=most_recent_session.session_id
            )
        else:
            # No sessions in vector store yet - use auth session_id as fallback
            logger.info(f"[INFO] upload-context - No sessions in DB, using auth session as fallback: {sanitize_session_id(session_id)}")
            return UploadContextResponse(
                patient_id=None,
                chat_session_id=session_id  # Use auth session_id as chat_session_id
            )
    except Exception as e:
        log_error(logger, "upload-context", e)
        import traceback
        traceback.print_exc()
        # Still return session_id as fallback on error
        return UploadContextResponse(
            patient_id=None,
            chat_session_id=session_id
        )


@app.post("/documents/upload", response_model=PDFUploadResponse)
async def upload_pdf_document(
    request: Request,
    file: UploadFile = File(...),
    patient_id: Optional[str] = Form(None),
    chat_session_id: Optional[str] = Form(None),
    user_ctx: dict = Depends(get_user_context)
):
    """Upload a PDF document file."""
    logger.info("=" * 50)
    logger.info("PDF UPLOAD ENDPOINT HIT WITH NEW CODE!")
    logger.info(f"[PDF Upload] Raw form data - chat_session: {sanitize_session_id(chat_session_id) if chat_session_id else "none"}, patient: {sanitize_patient_id(patient_id) if patient_id else "none"}")
    logger.info("=" * 50)

    # Get session ID from user context
    session_id = user_ctx.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")

    user = user_ctx.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    try:
        # Validate file type
        if not file.filename or not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")

        # Check file size (10MB limit)
        if file.size and file.size > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File size must be less than 10MB")

        # Read file content
        file_content = await file.read()

        # Use chat_session_id if provided, otherwise fall back to auth session_id
        effective_session_id = chat_session_id or session_id

        logger.info(f"[PDF Upload] Request - user: {sanitize_user_id(user.user_id)}, auth_session: {sanitize_session_id(session_id)}, chat_session: {sanitize_session_id(chat_session_id) if chat_session_id else "none"}, effective_session: {sanitize_session_id(effective_session_id)}, filename: {file.filename}, patient: {sanitize_patient_id(patient_id) if patient_id else "none"}")

        # Create upload request
        from optimed.core.domain.pdf_document import PDFUploadRequest
        upload_request = PDFUploadRequest(
            user_id=user.user_id,
            session_id=effective_session_id,
            filename=file.filename,
            file_content=file_content,
            patient_id=patient_id
        )

        # Process upload using memory service
        pdf_document = await _pdf_service.upload_document(upload_request)

        logger.info(f"[PDF Upload] Success - document: {sanitize_document_id(pdf_document.document_id)}, status: {pdf_document.status}")

        # GDPR compliance event logging (Article 30)
        try:
            import hashlib
            await _audit_repo.log_compliance_event(
                event_type="document_upload",
                compliance_framework="GDPR",
                session_id=session_id,
                user_id=user.user_id,
                patient_id_hash=hashlib.sha256(patient_id.encode()).hexdigest() if patient_id else None,
                data_categories=["health_documents", "clinical_reports"],
                processing_purposes=["clinical_decision_support", "document_analysis"],
                compliance_status="compliant",
                additional_context={"lawful_basis": "Article 6(1)(c) - Legal obligation"}
            )
        except Exception as e:
            log_error(logger, "Document upload logging", e)

        response = PDFUploadResponse(
            document_id=pdf_document.document_id,
            filename=pdf_document.filename,
            file_size=pdf_document.file_size,
            status=pdf_document.status.value,
            uploaded_at=pdf_document.uploaded_at.isoformat(),
            patient_id=pdf_document.patient_id
        )

        # Broadcast real-time event
        try:
            broadcaster = get_broadcaster()
            event = DocumentEvent(
                type="uploaded",
                document_id=pdf_document.document_id,
                filename=pdf_document.filename,
                document_type="pdf",
                session_id=effective_session_id,
                patient_id=patient_id
            )
            await broadcaster.broadcast(user.user_id, event)
            logger.info(f"[PDF Upload] Event broadcasted to user {sanitize_user_id(user.user_id)}")
        except Exception as e:
            log_error(logger, "PDF Upload broadcast", e)

        return response

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_error(logger, "PDF Upload", e)
        raise HTTPException(status_code=500, detail="PDF upload failed")


# XML Document List and Get Endpoints (must come before generic /documents routes)
@app.get("/documents/xml", response_model=XMLListResponse)
async def list_xml_documents(
    request: Request,
    patient_id: Optional[str] = Query(None),
    chat_session_id: Optional[str] = Query(None),
    user_ctx: dict = Depends(get_user_context)
):
    """List XML documents for the user session."""
    await _dependencies_ready.wait()

    session_id = user_ctx.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")

    user = user_ctx.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    try:
        logger.info(f"[XML List] Request - user: {sanitize_user_id(user.user_id)}, auth_session: {sanitize_session_id(session_id)}, chat_session: {sanitize_session_id(chat_session_id) if chat_session_id else "none"}, patient: {sanitize_patient_id(patient_id) if patient_id else "none"}")

        documents = []
        seen_ids = set()

        # Strategy: Always search both chat session (if provided) and auth session (where watcher uploads)
        # Frontend is responsible for clearing state on new session

        # First, search chat session if provided
        if chat_session_id:
            logger.info(f"[XML List] Searching in chat session: {sanitize_session_id(chat_session_id)}")
            chat_docs = await _xml_service.list_documents(
                user_id=user.user_id,
                session_id=chat_session_id,
                patient_id=patient_id
            )
            for doc in chat_docs:
                if doc.document_id not in seen_ids:
                    documents.append(doc)
                    seen_ids.add(doc.document_id)
            logger.info(f"[XML List] Found {len(chat_docs)} documents in chat session")

        # Always check auth session (where watcher uploads go)
        if session_id != chat_session_id:
            logger.info(f"[XML List] Searching in auth session: {sanitize_session_id(session_id)}")
            auth_docs = await _xml_service.list_documents(
                user_id=user.user_id,
                session_id=session_id,
                patient_id=patient_id
            )
            for doc in auth_docs:
                if doc.document_id not in seen_ids:
                    documents.append(doc)
                    seen_ids.add(doc.document_id)
            logger.info(f"[XML List] Found {len(auth_docs)} documents in auth session")

        logger.info(f"[XML List] Total unique documents: {len(documents)}")

        # Separate counts
        total_count = len(documents)
        patient_specific_count = len([doc for doc in documents if doc.patient_id])
        general_count = total_count - patient_specific_count
        medical_document_count = len([doc for doc in documents if doc.is_medical_document()])

        return XMLListResponse(
            documents=documents,
            total_count=total_count,
            patient_specific_count=patient_specific_count,
            general_count=general_count,
            medical_document_count=medical_document_count
        )

    except Exception as e:
        log_error(logger, "XML List", e)
        raise HTTPException(status_code=500, detail="Failed to list XML documents")


@app.get("/documents/xml/{document_id}")
async def get_xml_document(
    request: Request,
    document_id: str = Path(...),
    patient_id: Optional[str] = Query(None),
    user_ctx: dict = Depends(get_user_context)
):
    """Get a specific XML document."""
    await _dependencies_ready.wait()

    session_id = user_ctx.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")

    user = user_ctx.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    try:
        document = await _xml_service.get_document(
            document_id=document_id,
            user_id=user.user_id,
            session_id=session_id,
            patient_id=patient_id
        )

        if not document:
            raise HTTPException(status_code=404, detail="XML document not found")

        return {
            "document_id": document.document_id,
            "filename": document.filename,
            "file_size": document.file_size,
            "status": document.status.value,
            "uploaded_at": document.uploaded_at.isoformat(),
            "updated_at": document.updated_at.isoformat() if document.updated_at else None,
            "patient_id": document.patient_id,
            "document_type": document.get_document_type(),
            "metadata": {
                "title": document.metadata.title,
                "root_element": document.metadata.root_element,
                "namespace": document.metadata.namespace,
                "document_type": document.metadata.document_type,
                "section_count": document.metadata.section_count,
                "entry_count": document.metadata.entry_count
            } if document.metadata else None,
            "processing_info": {
                "parsing_success": document.processing_info.parsing_success,
                "structure_extraction_success": document.processing_info.structure_extraction_success,
                "section_count": document.processing_info.section_count,
                "detected_format": document.processing_info.detected_format,
                "error_message": document.processing_info.error_message
            } if document.processing_info else None
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        log_error(logger, "XML Get", e)
        raise HTTPException(status_code=500, detail="Failed to get XML document")


# PDF Document List and Get Endpoints
@app.get("/documents", response_model=PDFListResponse)
async def list_pdf_documents(
    request: Request,
    patient_id: Optional[str] = Query(None),
    chat_session_id: Optional[str] = Query(None),
    user_ctx: dict = Depends(get_user_context)
):
    """List PDF documents for the current session."""
    logger.info(f"[PDF List] Raw query params - chat_session: {sanitize_session_id(chat_session_id) if chat_session_id else "none"}, patient: {sanitize_patient_id(patient_id) if patient_id else "none"}")

    # Get session ID from user context
    session_id = user_ctx.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")

    user = user_ctx.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    try:
        logger.info(f"[PDF List] Request - user: {sanitize_user_id(user.user_id)}, auth_session: {sanitize_session_id(session_id)}, chat_session: {sanitize_session_id(chat_session_id) if chat_session_id else "none"}, patient: {sanitize_patient_id(patient_id) if patient_id else "none"}")

        documents = []
        seen_ids = set()

        # Strategy: Always search both chat session (if provided) and auth session (where watcher uploads)
        # Frontend is responsible for clearing state on new session

        # First, search chat session if provided
        if chat_session_id:
            logger.info(f"[PDF List] Searching in chat session: {sanitize_session_id(chat_session_id)}")
            chat_docs = await _pdf_service.list_documents(
                user_id=user.user_id,
                session_id=chat_session_id,
                patient_id=patient_id
            )
            for doc in chat_docs:
                if doc.document_id not in seen_ids:
                    documents.append(doc)
                    seen_ids.add(doc.document_id)
            logger.info(f"[PDF List] Found {len(chat_docs)} documents in chat session")

        # Always check auth session (where watcher uploads go)
        if session_id != chat_session_id:
            logger.info(f"[PDF List] Searching in auth session: {sanitize_session_id(session_id)}")
            auth_docs = await _pdf_service.list_documents(
                user_id=user.user_id,
                session_id=session_id,
                patient_id=patient_id
            )
            for doc in auth_docs:
                if doc.document_id not in seen_ids:
                    documents.append(doc)
                    seen_ids.add(doc.document_id)
            logger.info(f"[PDF List] Found {len(auth_docs)} documents in auth session")

        logger.info(f"[PDF List] Total unique documents: {len(documents)}")
        for doc in documents:
            logger.info(f"[PDF List] Document: {doc.filename} (status: {doc.status}, patient: {sanitize_patient_id(doc.patient_id) if doc.patient_id else "none"})")

        # Separate patient-specific and general documents
        patient_docs = [doc for doc in documents if doc.patient_id is not None]
        general_docs = [doc for doc in documents if doc.patient_id is None]

        return PDFListResponse(
            documents=list(documents),
            total_count=len(documents),
            patient_specific_count=len(patient_docs),
            general_count=len(general_docs)
        )

    except Exception as e:
        log_error(logger, "PDF List", e)
        raise HTTPException(status_code=500, detail="Failed to list PDF documents")


@app.get("/documents/events")
async def document_events_stream(
    request: Request,
    user_ctx: dict = Depends(get_user_context)
):
    """
    SSE stream for real-time document notifications.
    Uses same streaming approach as /chat/stream.
    """
    try:
        logger.info("[DocEvents] SSE request received")

        session_id = user_ctx.get("session_id")
        if not session_id:
            raise HTTPException(status_code=401, detail="Session required")

        user = user_ctx.get("user")
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        user_id = user.user_id
        logger.info(f"[DocEvents] User {sanitize_user_id(user_id)} connecting to SSE stream")

        broadcaster = get_broadcaster()
    except Exception as e:
        log_error(logger, "DocEvents setup", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"SSE setup failed: {str(e)}")

    # Subscribe to events
    queue = await broadcaster.subscribe(user_id)

    async def event_generator():
        try:
            # Send connection confirmation
            yield f"data: {json.dumps({'type': 'connected', 'user_id': user_id})}\n\n"

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    logger.info(f"[DocEvents] Client disconnected: {sanitize_user_id(user_id)}")
                    break

                try:
                    # Wait for event (30s timeout for keepalive)
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)

                    # Send event in SSE format
                    yield format_sse_event(event)

                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"

        except Exception as e:
            log_error(logger, "DocEvents stream", e)
        finally:
            await broadcaster.unsubscribe(user_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/documents/{document_id}")
async def get_pdf_document(
    request: Request,
    document_id: str = Path(...),
    patient_id: Optional[str] = Query(None),
    user_ctx: dict = Depends(get_user_context)
):
    """Get a specific PDF document."""
    # Get session ID from user context
    session_id = user_ctx.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")

    user = user_ctx.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    try:
        document = await _pdf_service.get_document(
            document_id=document_id,
            user_id=user.user_id,
            session_id=session_id,
            patient_id=patient_id
        )
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        return {
            "document_id": document.document_id,
            "filename": document.filename,
            "file_size": document.file_size,
            "status": document.status.value,
            "uploaded_at": document.uploaded_at.isoformat(),
            "updated_at": document.updated_at.isoformat() if document.updated_at else None,
            "patient_id": document.patient_id,
            "metadata": {
                "title": document.metadata.title,
                "page_count": document.metadata.page_count,
                "author": document.metadata.author
            } if document.metadata else None,
            "processing_info": {
                "text_extraction_success": document.processing_info.text_extraction_success,
                "page_count": document.processing_info.page_count,
                "error_message": document.processing_info.error_message
            } if document.processing_info else None
        }

    except Exception as e:
        log_error(logger, "PDF Get", e)
        raise HTTPException(status_code=500, detail="Failed to get PDF document")


@app.delete("/documents/{document_id}")
async def delete_pdf_document(
    request: Request,
    document_id: str = Path(...),
    patient_id: Optional[str] = Query(None),
    chat_session_id: Optional[str] = Query(None),
    user_ctx: dict = Depends(get_user_context)
):
    """Delete a PDF document."""
    # Get session ID from user context
    session_id = user_ctx.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")

    user = user_ctx.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    try:
        logger.info("[PDF Delete] Request details:")
        logger.info(f"  - document: {sanitize_document_id(document_id)}")
        logger.info(f"  - user: {sanitize_user_id(user.user_id)}")
        logger.info(f"  - auth_session: {sanitize_session_id(session_id)}")
        logger.info(f"  - chat_session: {sanitize_session_id(chat_session_id) if chat_session_id else "none"}")
        logger.info(f"  - patient: {sanitize_patient_id(patient_id) if patient_id else "none"}")

        # Try deleting from chat session first, then auth session (search both like list does)
        success = False

        if chat_session_id:
            logger.info(f"[PDF Delete] Trying chat session: {sanitize_session_id(chat_session_id)}")
            success = await _pdf_service.delete_document(
                document_id=document_id,
                user_id=user.user_id,
                session_id=chat_session_id,
                patient_id=patient_id
            )

        if not success:
            logger.info(f"[PDF Delete] Trying auth session: {sanitize_session_id(session_id)}")
            success = await _pdf_service.delete_document(
                document_id=document_id,
                user_id=user.user_id,
                session_id=session_id,
                patient_id=patient_id
            )

        logger.info(f"[PDF Delete] Delete operation returned: {success}")

        if success:
            return {"message": "Document deleted successfully"}
        else:
            logger.warning("[PDF Delete] Document not found in any session, returning 404")
            raise HTTPException(status_code=404, detail="Document not found")

    except HTTPException as he:
        # Re-raise HTTP exceptions as-is
        logger.error(f"[PDF Delete] HTTP Exception: {he.status_code} - {he.detail}")
        raise he
    except Exception as e:
        log_error(logger, "PDF Delete", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to delete PDF document")


@app.post("/documents/cleanup-session")
async def cleanup_session_documents(
    request: Request,
    user_ctx: dict = Depends(get_user_context)
):
    """Clean up old documents from auth session when starting a new chat session.

    This endpoint is called by the frontend when creating a new session to prevent
    old watcher uploads from accumulating in memory.
    """
    session_id = user_ctx.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")

    user = user_ctx.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    try:
        logger.info(f"[Cleanup] Starting cleanup for auth session: {sanitize_session_id(session_id)}, user: {sanitize_user_id(user.user_id)}")

        # Get all documents from auth session
        pdf_docs = await _pdf_service.list_documents(
            user_id=user.user_id,
            session_id=session_id,
            patient_id=None
        )

        xml_docs = await _xml_service.list_documents(
            user_id=user.user_id,
            session_id=session_id,
            patient_id=None
        )

        # Delete all documents from auth session
        deleted_pdfs = 0
        for doc in pdf_docs:
            try:
                await _pdf_service.delete_document(doc.document_id, user.user_id, session_id)
                deleted_pdfs += 1
            except Exception:
                logger.error(f"[Cleanup] Failed to delete PDF {sanitize_document_id(doc.document_id)}")

        deleted_xmls = 0
        for doc in xml_docs:
            try:
                await _xml_service.delete_document(doc.document_id, user.user_id, session_id)
                deleted_xmls += 1
            except Exception:
                logger.error(f"[Cleanup] Failed to delete XML {sanitize_document_id(doc.document_id)}")

        logger.info(f"[Cleanup] Cleaned up {deleted_pdfs} PDFs and {deleted_xmls} XMLs from auth session")

        return {
            "message": "Session cleaned up successfully",
            "deleted_pdfs": deleted_pdfs,
            "deleted_xmls": deleted_xmls
        }

    except Exception as e:
        log_error(logger, "Cleanup", e)
        raise HTTPException(status_code=500, detail="Failed to cleanup session")


# XML Document Upload and Management Endpoints

@app.post("/documents/upload-xml", response_model=XMLUploadResponse)
async def upload_xml_document(
    request: Request,
    file: UploadFile = File(...),
    patient_id: Optional[str] = Form(None),
    chat_session_id: Optional[str] = Form(None),
    user_ctx: dict = Depends(get_user_context)
):
    """Upload and process an XML document."""
    await _dependencies_ready.wait()

    session_id = user_ctx.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")

    user = user_ctx.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Validate file type
    valid_extensions = ['.xml', '.hl7', '.cda', '.ccda']
    if not file.filename or not any(file.filename.lower().endswith(ext) for ext in valid_extensions):
        raise HTTPException(status_code=400, detail=f"File must have one of these extensions: {', '.join(valid_extensions)}")

    # Use chat_session_id if provided, otherwise fall back to auth session_id
    effective_session_id = chat_session_id or session_id

    try:
        # Read file content
        content = await file.read()

        logger.info(f"[XML Upload] Request - user: {sanitize_user_id(user.user_id)}, auth_session: {sanitize_session_id(session_id)}, chat_session: {sanitize_session_id(chat_session_id) if chat_session_id else "none"}, effective_session: {sanitize_session_id(effective_session_id)}, filename: {file.filename}, patient: {sanitize_patient_id(patient_id) if patient_id else "none"}")

        # Process upload using memory service (XML service uses individual parameters)
        xml_document = await _xml_service.upload_document(
            user_id=user.user_id,
            session_id=effective_session_id,
            filename=file.filename,
            content=content,
            patient_id=patient_id
        )

        response = XMLUploadResponse(
            document_id=xml_document.document_id,
            filename=xml_document.filename,
            file_size=xml_document.file_size,
            status=xml_document.status.value,
            uploaded_at=xml_document.uploaded_at.isoformat(),
            patient_id=xml_document.patient_id,
            document_type=xml_document.get_document_type()
        )

        # Broadcast real-time event
        try:
            broadcaster = get_broadcaster()
            event = DocumentEvent(
                type="uploaded",
                document_id=xml_document.document_id,
                filename=xml_document.filename,
                document_type="xml",
                session_id=effective_session_id,
                patient_id=patient_id
            )
            await broadcaster.broadcast(user.user_id, event)
            logger.info(f"[XML Upload] Event broadcasted to user {sanitize_user_id(user.user_id)}")
        except Exception as e:
            log_error(logger, "XML Upload broadcast", e)

        return response

    except Exception as e:
        log_error(logger, "XML Upload", e)
        raise HTTPException(status_code=500, detail="XML upload failed")


@app.delete("/documents/xml/{document_id}")
async def delete_xml_document(
    request: Request,
    document_id: str = Path(...),
    patient_id: Optional[str] = Query(None),
    chat_session_id: Optional[str] = Query(None),
    user_ctx: dict = Depends(get_user_context)
):
    """Delete an XML document."""
    await _dependencies_ready.wait()

    session_id = user_ctx.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")

    user = user_ctx.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    try:
        logger.info("[XML Delete] Request details:")
        logger.info(f"  - document: {sanitize_document_id(document_id)}")
        logger.info(f"  - user: {sanitize_user_id(user.user_id)}")
        logger.info(f"  - auth_session: {sanitize_session_id(session_id)}")
        logger.info(f"  - chat_session: {sanitize_session_id(chat_session_id) if chat_session_id else "none"}")
        logger.info(f"  - patient: {sanitize_patient_id(patient_id) if patient_id else "none"}")

        # Try deleting from chat session first, then auth session (search both like list does)
        success = False

        if chat_session_id:
            logger.info(f"[XML Delete] Trying chat session: {sanitize_session_id(chat_session_id)}")
            success = await _xml_service.delete_document(
                document_id=document_id,
                user_id=user.user_id,
                session_id=chat_session_id,
                patient_id=patient_id
            )

        if not success:
            logger.info(f"[XML Delete] Trying auth session: {sanitize_session_id(session_id)}")
            success = await _xml_service.delete_document(
                document_id=document_id,
                user_id=user.user_id,
                session_id=session_id,
                patient_id=patient_id
            )

        logger.info(f"[XML Delete] Delete operation returned: {success}")

        if success:
            return {"message": "XML document deleted successfully"}
        else:
            logger.warning("[XML Delete] Document not found in any session, returning 404")
            raise HTTPException(status_code=404, detail="XML document not found")

    except HTTPException as he:
        # Re-raise HTTP exceptions as-is
        logger.error(f"[XML Delete] HTTP Exception: {he.status_code} - {he.detail}")
        raise he
    except Exception as e:
        log_error(logger, "XML Delete", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to delete XML document")


# ==================== NOTE TEMPLATE ENDPOINTS ====================

class NoteGenerationRequestModel(BaseModel):
    template_id: str
    session_id: str
    patient_id: Optional[str] = None
    context_prompt: Optional[str] = None
    include_conversation_history: bool = True


@app.post("/templates/upload")
async def upload_template(
    file: UploadFile = File(...),
    name: str = Form(...),
    language: str = Form(...),
    template_type: str = Form(...),
    user_ctx: dict = Depends(get_user_context),
    template_service = Depends(get_template_service)
):
    """Upload and parse a template file (DOCX, PDF, XLSX, TXT)."""
    try:
        logger.info(f"[Template Upload] User {sanitize_user_id(user_ctx["user_id"])} uploading template: {name}")

        # Read file content
        content = await file.read()

        # Create template using service
        from optimed.core.domain import TemplateType
        template = await template_service.create_template_from_upload(
            user_id=user_ctx["user_id"],
            name=name,
            language=language,
            template_type=TemplateType(template_type),
            file_content=content,
            filename=file.filename
        )

        logger.info("[Template Upload] Template created successfully")

        return {
            "template_id": template.template_id,
            "name": template.name,
            "language": template.language,
            "template_type": template.template_type.value,
            "fields": template.template_structure.get("fields", [])
        }

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        log_error(logger, "Template Upload", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to upload template")


@app.get("/templates/list")
async def list_templates(
    language: Optional[str] = Query(None),
    template_type: Optional[str] = Query(None),
    user_ctx: dict = Depends(get_user_context),
    template_repo = Depends(get_template_repo)
):
    """List available templates (user + system)."""
    try:
        templates = await template_repo.list_templates(
            user_id=user_ctx["user_id"],
            include_system=True,
            language=language,
            template_type=template_type
        )

        return {
            "templates": [
                {
                    "template_id": t.template_id,
                    "name": t.name,
                    "language": t.language,
                    "template_type": t.template_type.value,
                    "is_system_template": t.is_system_template,
                    "file_format": t.file_format,
                    "template_structure": t.template_structure if isinstance(t.template_structure, dict) else {},
                    "created_at": t.created_at.isoformat()
                }
                for t in templates
            ]
        }

    except Exception as e:
        log_error(logger, "Template List", e)
        raise HTTPException(status_code=500, detail="Failed to list templates")


@app.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    user_ctx: dict = Depends(get_user_context),
    template_repo = Depends(get_template_repo)
):
    """Get template details by ID."""
    try:
        template = await template_repo.get_template_by_id(template_id)

        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # Check access (user templates are private, system templates are public)
        if not template.is_system_template and template.user_id != user_ctx["user_id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        return {
            "template_id": template.template_id,
            "name": template.name,
            "language": template.language,
            "template_type": template.template_type.value,
            "template_structure": template.template_structure,
            "is_system_template": template.is_system_template,
            "file_format": template.file_format,
            "created_at": template.created_at.isoformat(),
            "updated_at": template.updated_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Template Get", e)
        raise HTTPException(status_code=500, detail="Failed to get template")


@app.delete("/templates/{template_id}")
async def delete_template(
    template_id: str,
    user_ctx: dict = Depends(get_user_context),
    template_repo = Depends(get_template_repo)
):
    """Delete a user template (system templates cannot be deleted)."""
    try:
        template = await template_repo.get_template_by_id(template_id)

        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        if template.user_id != user_ctx["user_id"]:
            raise HTTPException(status_code=403, detail="Access denied")

        if template.is_system_template:
            raise HTTPException(status_code=400, detail="Cannot delete system template")

        success = await template_repo.delete_template(template_id)

        return {"success": success}

    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Template Delete", e)
        raise HTTPException(status_code=500, detail="Failed to delete template")


@app.post("/notes/generate/stream")
async def generate_note_stream(
    req: NoteGenerationRequestModel,
    user_ctx: dict = Depends(get_user_context),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository),
    template_repo = Depends(get_template_repo)
):
    """Generate clinical note with streaming (GDPR: content never stored)."""
    try:
        logger.info("[Note Generate] Starting generation for template")

        # Get template
        template = await template_repo.get_template_by_id(req.template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # Get patient context if provided
        patient_ctx = None
        if req.patient_id:
            try:
                patient_ctx = await fhir_repo.get_patient(req.patient_id)
            except Exception:
                logger.warning("[Note Generate] Warning: Could not fetch patient")

        # Start metadata tracking
        import hashlib
        generation_id = str(uuid.uuid4())
        from optimed.core.domain import NoteGenerationMetadata, NoteGenerationStatus

        context_hash = None
        if req.context_prompt:
            context_hash = hashlib.sha256(req.context_prompt.encode()).hexdigest()

        metadata = NoteGenerationMetadata(
            generation_id=generation_id,
            user_id=user_ctx["user_id"],
            patient_id=req.patient_id,
            template_id=req.template_id,
            session_id=req.session_id,
            template_name=template.name,
            template_type=template.template_type,
            language=template.language,
            status=NoteGenerationStatus.STARTED,
            context_prompt_hash=context_hash,
            created_at=datetime.now(timezone.utc)
        )
        await template_repo.save_generation_metadata(metadata)

        # Stream generation using orchestrator
        async def event_stream():
            try:
                async for event in _engine.run_stream(
                    patient=patient_ctx,
                    user_prompt=req.context_prompt or "Generate clinical note",
                    user_id=user_ctx["user_id"],
                    session_id=req.session_id,
                    note_template=template,
                    note_generation_id=generation_id,
                    note_context_prompt=req.context_prompt
                ):
                    # Forward all events to frontend
                    yield f"data: {json.dumps(event)}\n\n"

                # Update metadata on completion
                await template_repo.update_generation_metadata(
                    generation_id=generation_id,
                    status=NoteGenerationStatus.COMPLETED
                )

            except Exception as e:
                error_event = {"type": "error", "message": str(e)}
                yield f"data: {json.dumps(error_event)}\n\n"

                await template_repo.update_generation_metadata(
                    generation_id=generation_id,
                    status=NoteGenerationStatus.ERROR,
                    error_message=str(e)
                )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Note Generate", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to generate note")


@app.get("/notes/metadata/history")
async def get_generation_history(
    patient_id: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    user_ctx: dict = Depends(get_user_context),
    template_repo = Depends(get_template_repo)
):
    """Get generation metadata history (GDPR: no actual note content)."""
    try:
        history = await template_repo.get_generation_history(
            user_id=user_ctx["user_id"],
            patient_id=patient_id,
            limit=limit
        )

        return {
            "history": [
                {
                    "generation_id": h.generation_id,
                    "template_name": h.template_name,
                    "template_type": h.template_type.value,
                    "language": h.language,
                    "status": h.status.value,
                    "patient_id": h.patient_id,
                    "chunks_used_count": h.chunks_used_count,
                    "conversation_turns_included": h.conversation_turns_included,
                    "export_method": h.export_method.value if h.export_method else None,
                    "created_at": h.created_at.isoformat(),
                    "completed_at": h.completed_at.isoformat() if h.completed_at else None,
                    "duration_seconds": h.duration_seconds
                }
                for h in history
            ]
        }

    except Exception as e:
        log_error(logger, "Note History", e)
        raise HTTPException(status_code=500, detail="Failed to get history")
