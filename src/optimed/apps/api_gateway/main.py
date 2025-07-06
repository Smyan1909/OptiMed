from __future__ import annotations 
import asyncio
import uuid
import os
import httpx
import json
import base64
import time
import io
from PIL import Image
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from typing import AsyncGenerator, Dict, Optional, Any, List
from fastapi import FastAPI, HTTPException, UploadFile, Request, Query, Path, Header, Depends, File, Form, Body, Response # type: ignore
from fastapi.responses import StreamingResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from optimed.core.domain import PatientContext, User, UserSession, UserEHRConnection, UserRole, UserStatus, ImageGenerationRequest
from optimed.core.ports import FHIRRepository
from optimed.apps.orchestrator.factory import create_app_dependencies
from optimed.core.domain import JournalEntryCreate, JournalEntryUpdate, JournalEntryType


from pydantic import BaseModel

_engine, _fhir, _vector_store, _user_repo, _connection_repo, _connection_service, _create_image_service, _image_analysis_engine, _image_generation_service, _generated_image_repo = create_app_dependencies()


app = FastAPI(title="OptiMed API Gateway", version="0.1.0", debug=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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

    user_id: str | None = None  # Optional user ID for tracking
    session_id: str | None = None  # Optional session ID for tracking

class PatientOut(BaseModel):
    id: str
    name: str
    age: int
    sex: str
    care_unit: str
    vitals: Dict[str, str]
    labs:   Dict[str, str]

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
    user_can_join: bool = True

class SessionCreateRequest(BaseModel):
    patient_id: str | None = None
    mode: str = "chat"
    session_title: str | None = None

class ImageGenerationRequestModel(BaseModel):
    prompt: str
    width: int = 1024
    height: int = 1024
    patient_id: Optional[str] = None

async def get_current_user(
    x_session_id: str = Header(None, alias="X-Session-ID")
) -> Optional[User]:
    
    if not x_session_id:
        return None
    
    try:
        session = await _user_repo.get_active_session(x_session_id)
        if not session:
            return None
        
        user = await _user_repo.get_user_by_id(session.user_id)
        if user:
            await _user_repo.update_session_activity(x_session_id)
        
        return user
    except Exception as e:
        print(f"Error fetching current user: {e}")
        return None
    

async def get_user_context(user: Optional[User] = Depends(get_current_user)) -> dict:
    """Dependency to fetch user context."""
    return {
        "user_id": user.user_id if user else None,
        "user": user
    }

async def get_user_fhir_repository(user_ctx: dict = Depends(get_user_context)) -> FHIRRepository:
    """Get the appropriate FHIR repository for the current user."""
    current_user = user_ctx.get("user")
    
    if current_user:
        print(f"[DEBUG] Attempting to create SMART FHIR repository for user: {current_user.username} (ID: {current_user.user_id})")
        
        # Try to get an authenticated SMART FHIR repository for this user
        try:
            user_repo = await _connection_service.create_fhir_repository(
                current_user.user_id, 
                provider_type="smart_fhir"
            )
            if user_repo:
                print(f"[API] ✅ Using SMART FHIR repository for user {current_user.username}")
                return user_repo
            else:
                print(f"[DEBUG] ❌ create_fhir_repository returned None for user {current_user.username}")
        except Exception as e:
            print(f"[API] ❌ Failed to create SMART FHIR repo for user {current_user.username}: {e}")
    else:
        print("[DEBUG] No current user found, using default repository")
    
    # Fallback to default HAPI repository
    print("[API] Using default HAPI FHIR repository")
    return _fhir

@app.post("/health", summary="Health Check")
async def health():
    """Simple health check endpoint."""
    return {"status": "ok"}

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
        print(f"[API] Error listing sessions: {e}")
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
        session_id = await _engine.vector_store.create_chat_session(
            user_id=user_id,
            patient_id=request.patient_id,
            mode=request.mode,
            session_title=request.session_title
        )
        
        return {"session_id": session_id, "message": "Session created successfully"}
        
    except Exception as e:
        print(f"[API] Error creating session: {e}")
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
        print(f"[API] Error joining session: {e}")
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
        print(f"[API] Error getting session participants: {e}")
        raise HTTPException(status_code=500, detail="Could not get session participants")


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
        
        print(req.fhir_server_url)

        # Create temporary session data (no user creation needed)
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
        
        
        auth_params = {
            "response_type": "code",
            "client_id": req.client_id,
            "redirect_uri": redirect_uri,
            "scope": req.scope,
            "state": state,
            "aud": req.fhir_server_url
        }
        
        # Construct authorization URL for SMART on FHIR
        fhir_base = req.fhir_server_url.rstrip('/')
        
        # For SMART Health IT sandbox, use their specific authorization endpoint
        if "launch.smarthealthit.org" in fhir_base:
            # Remove /fhir suffix and use base URL for auth
            base_url = fhir_base.replace("/fhir", "")
            auth_url = f"{base_url}/auth/authorize"
        else:
            # For other FHIR servers, also try base URL approach
            base_url = fhir_base.replace("/fhir", "")
            auth_url = f"{base_url}/auth/authorize"
        
        authorization_url = f"{auth_url}?{urlencode(auth_params)}"
        
        #print(f"[DEBUG] Authorization URL: {authorization_url}")  # Add for debugging
        
        return EHRLoginResponse(
            authorization_url=authorization_url,
            connection_id=connection_id,
            state=state
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/patients", response_model=list[PatientOut], summary="Search patients")
async def search_patients(
    q: str = Query("", alias="q"),
    fhir_repo: FHIRRepository = Depends(get_user_fhir_repository)
):
    try:
        # Use the user-specific repository instead of the global _fhir
        domain_objs = await fhir_repo.search_patients(q)  
        return [
            PatientOut(
                id=p.patient_id,
                name=p.name,
                age=p.age,
                sex=p.sex,
                care_unit=p.care_unit,
                vitals=p.vitals,
                labs=p.labs,
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
        print(f"[ERROR] OAuth error received: {error} - {error_description}")
        
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
        print(f"[ERROR] Missing required parameters - code: {bool(code)}, state: {bool(state)}")
        frontend_url = f"{frontend_base}/login?error=Missing authorization parameters"
        return RedirectResponse(url=frontend_url, status_code=302)
    
    try:
        # Extract connection_id from state parameter
        try:
            state_data = json.loads(base64.urlsafe_b64decode(state).decode())
            connection_id = state_data["connection_id"]
        except Exception as e:
            print(f"[ERROR] Invalid state parameter: {e}")
            frontend_url = f"{frontend_base}/login?error=Invalid state parameter"
            return RedirectResponse(url=frontend_url, status_code=302)
        
        # Get the temporary session data
        session_data = await _connection_repo.get_ehr_login_session(connection_id)
        if not session_data:
            print(f"[ERROR] Login session expired for connection: {connection_id}")
            frontend_url = f"{frontend_base}/login?error=Login session expired"
            return RedirectResponse(url=frontend_url, status_code=302)
        
        # Verify state parameter
        if session_data["state"] != state:
            print("[ERROR] State parameter mismatch")
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
            print(f"[INFO] Using existing user: {final_user.username}")
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
            print(f"[INFO] Created new user: {final_user.username}")
        
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
        frontend_url = f"http://localhost:3000/auth/ehr-success?session_id={session.session_id}&user_id={final_user.user_id}"
        return RedirectResponse(url=frontend_url)
        
    except Exception as e:
        print(f"[ERROR] EHR callback failed: {e}")
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
    
    print(f"[DEBUG] Token URL: {token_url}")  # Add this for debugging
    
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
        
        print(f"[DEBUG] Token response status: {response.status_code}")
        print(f"[DEBUG] Token response: {response.text}")
        
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
        print(f"[API] Diagnosis request from {current_user.display_name} ({current_user.role.value})")

    try:
        # Use the user-specific repository
        patient_ctx: PatientContext = await fhir_repo.get_patient(str(req.patient_id))
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Patient not found: {e}")

    result = await _engine.run(patient_ctx, req.user_prompt, chat_mode=req.chat_mode, user_id=user_id, session_id=req.session_id)
    if hasattr(result, 'model_dump'):
        return result.model_dump()
    else:
        return result


@app.post("/chat-history")
async def get_chat_history(
    request: dict,
):
    """Get chat history for a patient/session."""
    patient_id = request.get("patient_id")
    session_id = request.get("session_id")
    mode = request.get("mode", "diagnose")
    
    print(f"[API] Loading chat history for patient_id={patient_id}, session_id={session_id}, mode={mode}")
    
    try:
        if patient_id:
            # Get patient-specific history with session filter
            history_data = await _engine.vector_store.get_chat_history(
                patient_id=str(patient_id), 
                session_id=session_id,
                limit=50
            )
        else:
            # Get general chat history
            history_data = await _engine.vector_store.get_chat_history(
                patient_id="general_chat", 
                session_id=session_id,
                limit=50
            )
        
        print(f"[API] Returning {len(history_data)} chat history messages")
        return {"messages": history_data}
        
    except Exception as e:
        print(f"[API] Error loading chat history: {e}")
        return {"messages": []}

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
    )

@app.delete("/patients/{patient_id}/chat-history", summary="Delete patient by ID")
async def clear_patient_chat_history(patient_id: str = Path(..., description="The patient ID")):
    try:

        await _vector_store.clear_chat_history(patient_id)
        return {"message": f"Chat history cleared for patient {patient_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not clear chat history: {e}")

async def _event_stream(patient: PatientContext | None = None, user_prompt: str | None = None, chat_mode: bool = False, user_id: str | None = None, session_id: str | None = None) -> AsyncGenerator[str, None]:
    """Stream events from the diagnostic engine."""
    try:
        async for update in _engine.run_stream(
            patient=patient, 
            user_prompt=user_prompt, 
            chat_mode=chat_mode, 
            user_id=user_id, 
            session_id=session_id
        ):


            if update.get("type") == "status":
                status_data = {
                    "type": "status",
                    "step": update.get("step", "Processing"),
                    "description": update.get("details", ""),
                    "timestamp": datetime.now().isoformat(),
                    "estimated_time": update.get("estimated_time"),
                    "is_long_running": update.get("is_long_running", False)
                }
                yield f"data: {json.dumps(status_data)}\n\n"
                
            elif update.get("type") == "reasoning":
                # Fix: Extract reasoning content from the correct field
                reasoning_content = update.get("content", "") or update.get("reasoning", "")
                reasoning_data = {
                    "type": "reasoning",
                    "reasoning": reasoning_content,
                    "step": update.get("step", ""),
                    "step_number": update.get("step_number", 0),
                    "total_steps": update.get("total_steps", 0),
                    "timestamp": datetime.now().isoformat()
                }

                yield f"data: {json.dumps(reasoning_data)}\n\n"
                
            elif update.get("type") == "reasoning_complete":
                complete_data = {
                    "type": "reasoning_complete",
                    "timestamp": datetime.now().isoformat()
                }
                yield f"data: {json.dumps(complete_data)}\n\n"
                
            elif update.get("type") == "completion":
                # Fix: Extract final response from the correct field
                final_content = (
                    update.get("final_response", "") or 
                    update.get("content", "") or 
                    ""
                )
                completion_data = {
                    "type": "completion",
                    "content": final_content,
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat(),
                    "metadata": update.get("metadata", {}),
                    # Add image information if available
                    "generated_image": update.get("generated_image")
                }

                yield f"data: {json.dumps(completion_data)}\n\n"
                
            else:
                # Handle any other update types
                yield f"data: {json.dumps(update)}\n\n"
            
            await asyncio.sleep(0.05)  # Smaller delay for more responsive updates
            
    except Exception as e:
        print(f"[ERROR] Stream error: {e}")
        error_update = {
            "type": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
        yield f"data: {json.dumps(error_update)}\n\n"


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
        print(f"[API] Streaming diagnosis request from {current_user.display_name} ({current_user.role.value})")

    patient_ctx = None
    if req.patient_id:
        try:
            patient_ctx = await fhir_repo.get_patient(str(req.patient_id))
        except Exception as e:
            # Capture the error message in the outer scope
            error_message = str(e)
            
            # Return error as SSE
            async def error_stream():
                error_data = {
                    "type": "error",
                    "error": f"Patient not found: {error_message}",
                    "timestamp": datetime.now().isoformat()
                }
                yield f"event: error\n"
                yield f"data: {json.dumps(error_data)}\n\n"
            
            return StreamingResponse(error_stream(), media_type="text/event-stream")
    
    return StreamingResponse(
        _event_stream(
            patient=patient_ctx,
            user_prompt=req.user_prompt, 
            chat_mode=req.chat_mode, 
            user_id=user_id, 
            session_id=req.session_id
        ), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Expose-Headers": "*"
        }
    )

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
        print(f"[API] Streaming chat request from {current_user.display_name} ({current_user.role.value})")

    patient_ctx = None
    if req.patient_id:
        try:
            patient_ctx = await fhir_repo.get_patient(req.patient_id)
        except Exception as e:
            print(f"Could not fetch patient {req.patient_id}: {e}")
    
    return StreamingResponse(
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
        }
    )

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
        print(f"[API] Chat request from {current_user.display_name} ({current_user.role.value})")

    patient_ctx = None
    if req.patient_id is not None:
        try:
            # Use the user-specific repository
            patient_ctx = await fhir_repo.get_patient(req.patient_id)
        except Exception as e:
            # Log the error but continue with general chat
            print(f"Could not fetch patient {req.patient_id}: {e}")
    
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
        
        return DICOMUploadResponse(
            image_id=dicom_image.image_id,
            message="DICOM image uploaded successfully",
            image=image_response
        )
        
    except Exception as e:
        print(f"[ERROR] DICOM upload failed: {e}")
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
            except Exception as e:
                print(f"[ERROR] Failed to serialize image {img.image_id}: {e}")
                # Skip this image and continue with others
                continue
        
        return DICOMImageListResponse(images=image_responses)
        
    except Exception as e:
        print(f"[ERROR] Failed to list DICOM images: {e}")
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
        print(f"[ERROR] Failed to get DICOM image: {e}")
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
        print(f"[ERROR] Failed to get pixel data: {e}")
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
        print(f"[ERROR] Failed to delete DICOM image: {e}")
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
        print(f"[ERROR] DICOM analysis failed: {e}")
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
        print(f"[ERROR] Similar image search failed: {e}")
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
        print(f"Error generating image: {e}")
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
        print(f"Error retrieving image: {e}")
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
        print(f"Error retrieving user images: {e}")
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
        print(f"Error checking image generation status: {e}")
        return {
            "enabled": True,
            "available": False,
            "message": f"Error checking service: {str(e)}"
        }
