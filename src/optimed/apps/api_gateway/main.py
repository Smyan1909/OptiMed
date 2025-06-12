from __future__ import annotations 
import asyncio
from typing import AsyncGenerator, Dict
from fastapi import FastAPI, HTTPException, Query, Path # type: ignore
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv # type: ignore

from optimed.core.domain import PatientContext
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from optimed.apps.orchestrator.patient_flow import LangGraphDiagnosticEngine

from pydantic import BaseModel

load_dotenv()

_fhir = HAPIFHIRRepository()
_engine = LangGraphDiagnosticEngine()

app = FastAPI(title="OptiMed API Gateway", version="0.1.0", debug=True)

class ChatRequest(BaseModel):
    patient_id: str | None = None
    user_prompt: str | None = None


class PatientOut(BaseModel):
    id: str
    name: str
    age: int
    sex: str
    care_unit: str
    vitals: Dict[str, str]
    labs:   Dict[str, str]


@app.post("/health", summary="Health Check")
async def health():
    """Simple health check endpoint."""
    return {"status": "ok"}

@app.post("/diagnose", response_model=dict)
async def diagnose(req: ChatRequest):

    try:
        # Fetch patient context
        patient_ctx: PatientContext = await _fhir.get_patient(str(req.patient_id)) # Cast to str to avoid type errors
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Patient not found: {e}")
    
    result = await _engine.run(patient_ctx, req.user_prompt)
    if hasattr(result, 'model_dump'):
        return result.model_dump()
    else:
        return result


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

from fastapi import Path

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
async def chat(req: ChatRequest):
    """General chat endpoint that works with or without patient context."""
    try:
        patient_ctx = None
        if req.patient_id is not None:
            try:
                patient_ctx = await _fhir.get_patient(req.patient_id)
            except Exception as e:
                # Log the error but continue with general chat
                print(f"Could not fetch patient {req.patient_id}: {e}")
        
        # Create a mock patient context for general chat
        if not patient_ctx:
            result = await _engine.run(user_prompt=req.user_prompt)
            return result
        else:
            result = await _engine.run(patient=patient_ctx, user_prompt=req.user_prompt)
            if hasattr(result, 'model_dump'):
                return result.model_dump()
            else:
                return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")