from __future__ import annotations 
import asyncio
import uuid
import os
import httpx
import json
import base64
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from typing import AsyncGenerator, Dict, Optional
from fastapi import FastAPI, HTTPException, Query, Path, Header, Depends # type: ignore
from fastapi.responses import StreamingResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from optimed.core.domain import PatientContext, User, UserSession, UserEHRConnection, UserRole, UserStatus
from optimed.core.ports import FHIRRepository
from optimed.apps.orchestrator.factory import create_app_dependencies

from pydantic import BaseModel

_engine, _fhir, _vector_store, _user_repo, _connection_repo, _connection_service = create_app_dependencies()


app = FastAPI(title="OptiMed API Gateway", version="0.1.0", debug=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
            import traceback
            traceback.print_exc()
    else:
        print("[DEBUG] No current user found, using default repository")
    
    # Fallback to default HAPI repository
    print("[API] Using default HAPI FHIR repository")
    return _fhir

@app.post("/health", summary="Health Check")
async def health():
    """Simple health check endpoint."""
    return {"status": "ok"}

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
            
            new_user = User(
                user_id=user_id,
                username=unique_username,
                email=user_info.get("email", ""),
                first_name=user_info.get("first_name", "EHR"),
                last_name=user_info.get("last_name", "User"),
                role=UserRole.DOCTOR,  # Default role
                status=UserStatus.ACTIVE,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
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

async def _event_stream(patient: PatientContext) -> AsyncGenerator[str, None]:
    async for delta in _engine.run_stream(patient):
        yield f"data: {delta}\n\n"
        await asyncio.sleep(0.1)  # Simulate async delay for streaming


@app.post("/diagnose/stream")
async def diagnose_stream(req: ChatRequest):
    try:
        patient = await _fhir.get_patient(str(req.patient_id)) # Cast to str to avoid type errors
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Patient not found: {e}")
    
    return StreamingResponse(_event_stream(patient), media_type="text/event-stream")


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
   