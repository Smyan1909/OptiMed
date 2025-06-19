from __future__ import annotations 
import asyncio
from typing import AsyncGenerator, Dict, Optional
from fastapi import FastAPI, HTTPException, Query, Path, Header, Depends # type: ignore
from fastapi.responses import StreamingResponse
from optimed.core.domain import PatientContext, User
from optimed.apps.orchestrator.factory import create_app_dependencies

from pydantic import BaseModel

_engine, _fhir, _vector_store, _user_repo = create_app_dependencies()

app = FastAPI(title="OptiMed API Gateway", version="0.1.0", debug=True)

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
    first_name: str
    last_name: str
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



async def get_current_user(
    x_session_id: str = Header(None, alias="X-Session-ID")
) -> Optional[UserOut]:
    
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

@app.post("/health", summary="Health Check")
async def health():
    """Simple health check endpoint."""
    return {"status": "ok"}

@app.post("/diagnose", response_model=dict)
async def diagnose(req: ChatRequest, user_ctx: dict = Depends(get_user_context)):

    user_id = user_ctx.get("user_id") or req.user_id
    current_user = user_ctx.get("user")

    if current_user:
        print(f"[API] Diagnosis request from {current_user.display_name} ({current_user.role.value})")

    try:
        # Fetch patient context
        patient_ctx: PatientContext = await _fhir.get_patient(str(req.patient_id)) # Cast to str to avoid type errors
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Patient not found: {e}")

    result = await _engine.run(patient_ctx, req.user_prompt, chat_mode=req.chat_mode, user_id=user_id, session_id=req.session_id)
    if hasattr(result, 'model_dump'):
        return result.model_dump()
    else:
        return result


@app.post("/api/chat-history")
async def get_chat_history(
    request: dict,
    user_ctx: dict = Depends(get_user_context)
):
    """Get chat history for a patient/session."""
    patient_id = request.get("patient_id")
    session_id = request.get("session_id")
    mode = request.get("mode", "diagnose")
    
    print(f"[API] Loading chat history for patient_id={patient_id}, session_id={session_id}, mode={mode}")
    
    try:
        if patient_id:
            # Get patient-specific history with session filter
            history_data = await _engine._vec.get_chat_history(
                patient_id=str(patient_id), 
                session_id=session_id,
                limit=50
            )
        else:
            # Get general chat history
            history_data = await _engine._vec.get_chat_history(
                patient_id="general_chat", 
                session_id=session_id,
                limit=50
            )
        
        print(f"[API] Returning {len(history_data)} chat history messages")
        return {"messages": history_data}
        
    except Exception as e:
        print(f"[API] Error loading chat history: {e}")
        return {"messages": []}

@app.get("/patients", response_model=list[PatientOut], summary="Search patients")
async def search_patients(q: str = Query("", alias="q")):
    try:
        # Adapt to your repository signature
        domain_objs = await _fhir.search_patients(q)  
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


@app.get(
    "/patients/{patient_id}",
    response_model=PatientOut,
    summary="Get single patient by ID",
)
async def get_patient(patient_id: str = Path(..., description="The patient ID")):
    try:
        pctx = await _fhir.get_patient(patient_id)
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
async def chat(req: ChatRequest, user_ctx: dict = Depends(get_user_context)):
    """General chat endpoint that works with or without patient context."""
    user_id = user_ctx.get("user_id") or req.user_id
    current_user = user_ctx.get("user")

    if current_user:
        print(f"[API] Chat request from {current_user.display_name} ({current_user.role.value})")

    patient_ctx = None
    if req.patient_id is not None:
        try:
            patient_ctx = await _fhir.get_patient(req.patient_id)
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
    
    # Create session
    import uuid
    from datetime import datetime
    from optimed.core.domain import UserSession
    
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

   