from __future__ import annotations

import os
import uuid 
import json
from typing import List, Any

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from optimed.core.domain import PatientContext, ChatMessage, DiagnosisResult, ChatRole
from optimed.core.ports import DiagnosticEngine
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter
from optimed.adapters.anthropic_claude.client import AnthropicClaudeClient
from optimed.embeddings.minilm import embed
from optimed.embeddings.service import embed_and_store



SYSTEM_MSG = ChatMessage(role=ChatRole.SYSTEM, content="You are OptiMed‑AI, a clinical reasoning assistant."
        "Combine real‑time vitals, labs, and external evidence to help physicians." "Give an explanation as to why you give the response. Also cite sources where you feel it is required.") # Needs to be more specific and properly created to make the LLM function properly

class FlowState(BaseModel):
    """Minimal LangGraph state."""
    patient_id: str
    user_prompt: str
    primary_icd: str = ""
    differential: List[str] = Field(default_factory=list)
    confidence: float = 0.0

    patient_ctx: PatientContext | None = None
    retrieved_chunks: List[str] = Field(default_factory=list)
    llm_response: ChatMessage | None = None
    retrieved_web: List[str] = Field(default_factory=list) # This is for future use, if we want to retrieve web data To be implemented later

    chat_history: List[ChatMessage] = Field(default_factory=list)



_fhir = HAPIFHIRRepository()
_vec = PGVectorAdapter(os.getenv("PGVECTOR_DSN")) # type: ignore
_llm = AnthropicClaudeClient()


async def fetch_patient(state: FlowState) -> FlowState:
    state.patient_ctx = await _fhir.get_patient(state.patient_id)
    return state

async def retrieve_chunks(state: FlowState) -> FlowState:
    q_vec = await embed(state.user_prompt)
    rows = await _vec.similarity_search(q_vec, top_k=5, filter_={"namespace": "clinical"})
    state.retrieved_chunks = [row[2] if len(row) > 2 else row[1] for row in rows]
    return state


async def diagnose(state: FlowState) -> FlowState:
    if not state.patient_ctx:
        raise ValueError("Patient context is required for diagnosis.")
    
    history = state.chat_history[-6:] # Limit to last 6 messages for context but change number as needed later on

    ctx = ChatMessage(
        role=ChatRole.USER,
        content="Patient context: \n" + state.patient_ctx.model_dump_json(indent=2),
     )
    
    docs = ChatMessage(
        role=ChatRole.USER,
        content="Relevant notes:\n" + "\n---\n".join(state.retrieved_chunks),
    )

    user = ChatMessage(
        role=ChatRole.USER,
        content=state.user_prompt,
    )

    messages = [SYSTEM_MSG] + history + [ctx, docs, user]

    state.llm_response = await _llm.chat(messages)

    state.chat_history.extend([user, state.llm_response])

    await embed_and_store(
        namespace="chat",
        object_type="ChatMessage",
        object_id=str(uuid.uuid4()),
        text={"content": user.content, "role":user.role.value},
        metadata={
            "patient_id": state.patient_id,
            "role": user.role.value,
        },
    )

    await embed_and_store(
        namespace="chat",
        object_type="AssistantReply",
        object_id=str(uuid.uuid4()),
        text={"content": state.llm_response.content if state.llm_response else "", "role": ChatRole.ASSISTANT.value},
        metadata={
            "patient_id": state.patient_id,
            "role": ChatRole.ASSISTANT.value,
        }
    )

    return state

async def parse_icd(state: FlowState) -> FlowState:
    """
    Currently uses claude to parse the ICD code from the response but can be replaced 
    with a proper regex or a more sophisticated parsing method in the future.
    """
    prompt = (
        "Return JSON with fields primary_icd, differential (list), "
        f"confidence (0-1) for the following answer:\n\n{state.llm_response.content if state.llm_response else ''}\n\n"
    )
    parsed = await _llm.chat([SYSTEM_MSG, ChatMessage(role=ChatRole.USER, content=prompt)], json_mode=True)
    data = json.loads(parsed.content)
    state.primary_icd = data["primary_icd"]
    state.differential = data["differential"]
    state.confidence = data["confidence"]

    return state

_builder = StateGraph(FlowState)
_builder.add_node("fetch_patient", fetch_patient)
_builder.add_node("retrieve_chunks", retrieve_chunks)
_builder.add_node("diagnose", diagnose)
_builder.add_node("parse_icd", parse_icd)

_builder.set_entry_point("fetch_patient")
_builder.add_edge("fetch_patient", "retrieve_chunks")
_builder.add_edge("retrieve_chunks", "diagnose")
_builder.add_edge("diagnose", "parse_icd")
_builder.add_edge("parse_icd", END)

compiled_graph = _builder.compile()

def _to_output(data: dict[str, Any]) -> DiagnosisResult:
    """Convert raw dict emitted by compiled_graph to DiagnosisResult."""
    return DiagnosisResult(
        patient_id=data["patient_id"],
        primary_icd=data["primary_icd"], 
        differential=data["differential"],
        confidence=data["confidence"],
        explaination=data["llm_response"].content if data["llm_response"] else "",
    )

class LangGraphDiagnosticEngine(DiagnosticEngine):
    """Concrete engine that streams or returns full result."""

    def __init__(self, default_prompt: str = "Provide the most likely diagnosis"):
        self._default_prompt = default_prompt

    async def run(self, patient: PatientContext, user_prompt: str | None = None) -> DiagnosisResult:
        
        prompt = user_prompt or self._default_prompt
        
        data = await compiled_graph.ainvoke({
            "patient_id": patient.patient_id,
            "user_prompt": prompt,
        })
        
        if hasattr(data, "model_dump"):
            return _to_output(data.model_dump())
        else:
            return _to_output(data)

    async def run_stream(self, patient: PatientContext, user_prompt: str | None = None):
        """Async generator that yields chunks as they stream from the graph."""

        prompt = user_prompt or self._default_prompt

        async for update in compiled_graph.astream({
            "patient_id": patient.patient_id,
            "user_prompt": prompt,
        }):
            yield update

    
