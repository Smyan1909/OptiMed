from __future__ import annotations

import os
import uuid 
import json
from typing import List, Any, Union

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from optimed.core.domain import PatientContext, ChatMessage, DiagnosisResult, ChatRole
from optimed.core.ports import DiagnosticEngine
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter
from optimed.adapters.anthropic_claude.client import AnthropicClaudeClient
from optimed.embeddings.minilm import embed
from optimed.embeddings.service import embed_and_store



SYSTEM_MSG = ChatMessage(role=ChatRole.SYSTEM, 
                         content="""You are OptiMed‑AI, a clinical reasoning assistant and medical chat companion.
                                    When patient context is provided:
                                    - Combine real‑time vitals, labs, and external evidence to help physicians
                                    - Provide clinical diagnoses with explanations and cite sources
                                    - Focus on medical accuracy and clinical reasoning

                                    When no patient context is provided:
                                    - Engage in general medical conversations
                                    - Answer medical questions and provide health information
                                    - Maintain professional, helpful, and educational responses
                                    - Always remind users to consult healthcare providers for personal medical advice""") # Needs to be more specific and properly created to make the LLM function properly

class FlowState(BaseModel): # Potentially add 
    """Minimal LangGraph state.""" # Add field for user_id or session_id if needed later on as well
    patient_id: str | None = None
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
    
    history = state.chat_history[-6:] # Limit to last 6 messages for context but change number as needed later on

    messages = [SYSTEM_MSG] + history

    if state.patient_ctx:
        ctx = ChatMessage(
            role=ChatRole.USER,
            content="Patient context: \n" + state.patient_ctx.model_dump_json(indent=2),
        )
        messages.append(ctx)
    
    if state.retrieved_chunks:
        docs = ChatMessage(
            role=ChatRole.USER,
            content="Relevant notes:\n" + "\n---\n".join(state.retrieved_chunks),
        )
        messages.append(docs)

    user = ChatMessage(
        role=ChatRole.USER,
        content=state.user_prompt,
    )

    messages.append(user)

    state.llm_response = await _llm.chat(messages)

    state.chat_history.extend([user, state.llm_response])

    await embed_and_store(
        namespace="chat",
        object_type="ChatMessage",
        object_id=str(uuid.uuid4()),
        text={"content": user.content, "role":user.role.value},
        metadata={
            "patient_id": state.patient_id if state.patient_id else "general_chat",
            "role": user.role.value,
        },
    )

    await embed_and_store(
        namespace="chat",
        object_type="AssistantReply",
        object_id=str(uuid.uuid4()),
        text={"content": state.llm_response.content if state.llm_response else "", "role": ChatRole.ASSISTANT.value},
        metadata={
            "patient_id": state.patient_id if state.patient_id else "general_chat",
            "role": ChatRole.ASSISTANT.value,
        }
    )

    return state

async def parse_icd(state: FlowState) -> FlowState:
    """
    Currently uses claude to parse the ICD code from the response but can be replaced 
    with a proper regex or a more sophisticated parsing method in the future.
    """
    if state.patient_ctx:
        prompt = (
            "Return JSON with fields primary_icd, differential (list), "
            f"confidence (0-1) for the following medical diagnosis:\n\n{state.llm_response.content if state.llm_response else ''}\n\n"
        )
        parsed = await _llm.chat([SYSTEM_MSG, ChatMessage(role=ChatRole.USER, content=prompt)], json_mode=True)
        data = json.loads(parsed.content)
        state.primary_icd = data["primary_icd"]
        state.differential = data["differential"]
        state.confidence = data["confidence"]
    else:
        # For general chat, set default values
        state.primary_icd = "N/A - General Chat"
        state.differential = []
        state.confidence = 0.0

    return state

def check_patient_exists(state: FlowState) -> FlowState:
    """Check if patient_id is provided in the state."""
    # This node doesn't need to do anything - just pass through
    return state

def has_patient(state: FlowState) -> bool:
    return state.patient_id is not None and state.patient_id.strip() != ""


_builder = StateGraph(FlowState)
_builder.add_node("check_patient", check_patient_exists)  # New decision node
_builder.add_node("fetch_patient", fetch_patient)
_builder.add_node("retrieve_chunks", retrieve_chunks)
_builder.add_node("diagnose", diagnose)
_builder.add_node("parse_icd", parse_icd)

_builder.set_entry_point("check_patient")

# Conditional logic right at the start
_builder.add_conditional_edges(
    "check_patient",
    has_patient,
    {
        True: "fetch_patient",      # Patient ID provided -> fetch details
        False: "retrieve_chunks"    # No patient ID -> skip to chunks
    }
)

# Linear flow after patient fetch
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

def chat_output(data: dict[str, Any]) -> dict[str, Any]:
    """Convert raw dict emitted by compiled_graph to a chat output format."""
    return {
        "explaination": data["llm_response"].content if data["llm_response"] else "",
    }

class LangGraphDiagnosticEngine(DiagnosticEngine):
    """Concrete engine that streams or returns full result."""

    def __init__(self, default_prompt: str = "Provide the most likely diagnosis"):
        self._default_prompt = default_prompt

    async def run(self, patient: PatientContext | None = None, user_prompt: str | None = None) -> Union[DiagnosisResult,  dict]:
        
        prompt = user_prompt or self._default_prompt
        if patient is not None:
            data = await compiled_graph.ainvoke({
                "patient_id": patient.patient_id,
                "user_prompt": prompt,
            })
        else:
            data = await compiled_graph.ainvoke({
                "user_prompt": prompt,
            })
        
        if patient is not None:
            if hasattr(data, "model_dump"):
                return _to_output(data.model_dump())
            else:
                return _to_output(data)
        else:
            return chat_output(data)

    async def run_stream(self, patient: PatientContext, user_prompt: str | None = None):
        """Async generator that yields chunks as they stream from the graph."""

        prompt = user_prompt or self._default_prompt

        async for update in compiled_graph.astream({
            "patient_id": patient.patient_id,
            "user_prompt": prompt,
        }):
            yield update

    
