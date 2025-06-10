from __future__ import annotations 
import os
import asyncio
from typing import AsyncGenerator
from fastapi import FastAPI, Depends, HTTPException # type: ignore
from fastapi.responses import StreamingResponse, JSONResponse
from dotenv import load_dotenv # type: ignore

from optimed.core.domain import PatientContext
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from optimed.apps.orchestrator.patient_flow import LangGraphDiagnosticEngine

from pydantic import BaseModel

_fhir = HAPIFHIRRepository()
_engine = LangGraphDiagnosticEngine()

app = FastAPI(title="OptiMed API Gateway", version="0.1.0")

class ChatRequest(BaseModel):
    patient_id: str
    user_prompt: str


@app.post("/health", summary="Health Check")
async def health():
    """Simple health check endpoint."""
    return {"status": "ok"}

@app.post("/diagnose", response_model=dict)
async def diagnose(req: ChatRequest):

    try:
        # Fetch patient context
        patient_ctx: PatientContext = await _fhir.get_patient(req.patient_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Patient not found: {e}")
    
    result = await _engine.run(patient_ctx, req.user_prompt)
    return result.model_dump()



async def _event_stream(patient: PatientContext) -> AsyncGenerator[str, None]:
    async for delta in _engine.run_stream(patient):
        yield f"data: {delta}\n\n"
        await asyncio.sleep(0.1)  # Simulate async delay for streaming


@app.post("/diagnose/stream")
async def diagnose_stream(req: ChatRequest):
    try:
        patient = await _fhir.get_patient(req.patient_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Patient not found: {e}")
    
    return StreamingResponse(_event_stream(patient), media_type="text/event-stream")
