from __future__ import annotations
from .streaming_decorators import streaming_step
from .streaming_llm import StreamingLLMWrapper

import uuid 
import json
import time
import math
import asyncio
from typing import List, Any, Union, AsyncGenerator, Optional
from datetime import datetime

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from optimed.core.domain import PatientContext, ChatMessage, DiagnosisResult, ChatRole, UserAction, User, WebSearchResponse
from optimed.core.lang import detect_language_code

from optimed.core.ports import DiagnosticEngine, FHIRRepository, LLMClient, VectorStore, UserRepository, WebSearchService

from optimed.apps.orchestrator.connection_service import UserEHRConnectionService

from optimed.embeddings.minilm import embed
from optimed.embeddings.service import embed_and_store
from optimed.apps.orchestrator.chunking_orchestrator import ChunkingOrchestrator
from optimed.apps.orchestrator.chunking_config import STRATEGY_REGISTRY as CHUNK_STRATEGY_REGISTRY, POLICY_PRESETS as CHUNK_POLICY_PRESETS
from optimed.adapters.outbound.tokenizer.whitespace_tokenizer import WhitespaceTokenizer
from optimed.adapters.outbound.phi_redactor.simple_redactor import SimplePhiRedactor
from optimed.apps.orchestrator.ml_adapters import MultilingualCrossEncoder, MultilingualZeroShotClassifier
import re


# =========================
# RAM-only mode and retrieval params
# =========================
# Global flag to disable any persistence (DB/files/caches). All writes are gated.
PERSISTENCE_ENABLED: bool = False

# Retrieval parameters
TOPK_INITIAL: int = 100
TOPK_RERANK: int = 30
N_MIN: int = 5
N_MAX: int = 15
MMR_LAMBDA: float = 0.5
GATE_THRESH: float = 0.65
RETRY_MAX: int = 2



# Single system message for information relay only
SYSTEM_MSG_INFO_RELAY = ChatMessage(role=ChatRole.SYSTEM, 
                         content="""You are CLARA, a clinical information assistant.

                                    You are not a doctor or a medical device, so always state that the user should make their decisions independently and review the sources for further information.

                                    Your goal is to provide information to the user so that they can make decisions based upon the information you provide.

                                    The primary users of this service are doctors and nurses.

                                    General response guideline (apply only when helpful for the current question):
                                    - Provide a thorough, well-developed answer while remaining concise (aim for 3–5 short sections).
                                    - Use previous conversation history (between === lines) when relevant.
                                    - **Always output in valid GitHub-flavored Markdown** to ensure clean rendering in the application.
                                    - Organize responses using appropriate Markdown structure:
                                        - Use `#` for the main title, `##` for section titles, and `###` for subsections when needed.
                                        - Use bullet points (`-`) or numbered lists (`1.`, `2.`) where appropriate.
                                        - Use proper Markdown tables for structured data.
                                        - Format all URLs as **clickable Markdown links** instead of showing raw URLs.
                                    - If web search results are used, cite with inline Markdown links like:  
                                        `[Source Title](URL)`  
                                        Otherwise, omit citations.
                                    - Link policy (**STRICT for EHR**):  
                                        The clinical information chunks provided to you already contain embedded EHR source links. When referencing specific patient data from these chunks, preserve and use the existing source links that are already embedded in the chunk content. Do not create new links or modify existing ones.
                                        - The chunks contain pre-formatted source information with URLs
                                        - Use the source links exactly as they appear in the chunk content
                                        - If a chunk mentions data without a source link, write `(from EHR, no link available)` immediately after that item
                                    - Do not escape Markdown unnecessarily; the final response must always render cleanly.

                                    Restrictions:
                                    - Provide information and education, **not** diagnostic conclusions or treatment recommendations.
                                    - Do not provide any treatment recommendations or diagnostic conclusions.
                                    - Refer all clinical decision-making to qualified healthcare providers.
                                    """)


class FlowState(BaseModel):
    """LangGraph state for information relay."""
    patient_id: str | None = None
    user_prompt: str
    # Remove diagnostic-specific fields
    # primary_icd: str = ""
    # differential: List[str] = Field(default_factory=list)
    # confidence: float = 0.0
    # parsed_response: Optional[DiagnosisResult] = None

    patient_ctx: PatientContext | None = None
    retrieved_chunks: List[str] = Field(default_factory=list)

    chunk_analysis: dict[str, Any] = Field(default_factory=dict)
    filtered_chunks: List[dict[str, Any]] = Field(default_factory=list)
    retrieval_reasoning: str = ""

    requires_full_processing: bool = True

    llm_response: ChatMessage | None = None

    retrieved_web: List[str] = Field(default_factory=list)
    web_search_response: Optional[WebSearchResponse] = None
    web_search_performed: bool = False

    # Remove diagnostic mode - just use single mode
    # info_retrieval_mode: str = "info_retrieval"
    chat_mode: bool = False # Keep for backward compatibility
    # Remove ICD parsing flag
    # should_parse_icd_codes: bool = False
    chat_history: List[ChatMessage] = Field(default_factory=list)

    needs_cross_session_search: bool = False
    relevant_cross_session_history: List[dict] = Field(default_factory=list)

    user_id: str | None = None
    user_context: User | None = None
    session_id: str | None = None


    # Reasoning fields
    llm_reasoning: str = ""
    reasoning_steps: List[str] = Field(default_factory=list)
    current_reasoning_step: int = 0
    reasoning_complete: bool = False

    # Streaming status fields
    current_step: str = ""
    step_status: str = ""
    step_details: str = ""
    progress_percentage: float = 0.0
    total_steps: int = 10  # Reduced from 12 since we removed ICD parsing steps
    completed_steps: int = 0
    streaming_updates: List[dict] = Field(default_factory=list)

    should_stream_response: bool = False  # New field to control streaming behavior
    streaming_response: str = ""  # Accumulated response during streaming
    stream_callback: Optional[Any] = None  # Callback for streaming updates
    
    # Retrieval refinement fields (agentic loop)
    retrieval_retry_attempts: int = 0
    refined_queries: List[str] = Field(default_factory=list)
    needs_refinement: bool = False
    


class LangGraphInformationEngine(DiagnosticEngine):
    """Concrete engine that streams or returns full result."""

    def __init__(self, fhir_repo: FHIRRepository, 
                 vector_store: VectorStore, 
                 llm_client: LLMClient, 
                 user_repo: UserRepository, 
                 connection_service: UserEHRConnectionService, 
                 web_search_service: WebSearchService,
                 default_prompt: str = "Provide the most likely diagnosis"):
        self._fhir = fhir_repo
        self._vec = vector_store
        self._llm = llm_client
        self._streaming_llm = StreamingLLMWrapper(llm_client=llm_client)

        self._user_repo = user_repo
        self._connection_service = connection_service
        self._web_search = web_search_service
        self._default_prompt = default_prompt

        self._compiled_graph = self._build_graph()
        # Ephemeral per-session chat memory (RAM-only)
        self._session_memory: dict[str, list[dict[str, Any]]] = {}

    def _build_graph(self) -> Any:
        """Build the LangGraph state graph for diagnosis."""

        @streaming_step("fetch_patient")
        async def fetch_patient(state: FlowState) -> FlowState:
            # Try to use user's EHR connection first
            fhir_repo = self._fhir
            
            if state.user_id:
                try:
                    user_fhir_repo = await self._connection_service.create_fhir_repository(
                        state.user_id, 
                        "smart_fhir"
                    )
                    if user_fhir_repo:
                        fhir_repo = user_fhir_repo
                        print("[fetch_patient] Using user's SMART on FHIR connection")
                except Exception as e:
                    print(f"[fetch_patient] Failed to use SMART connection: {e}, falling back to default")
            
            state.patient_ctx = await fhir_repo.get_patient(str(state.patient_id))
            return state

        @streaming_step("load_user_context")
        async def load_user_context(state: FlowState) -> FlowState:
            """Load user context if available."""
            if state.user_id:
                try: 
                    state.user_context = await self._user_repo.get_user_by_id(state.user_id)
                    if not state.user_context:
                        print(f"[load_user_context] No user found with ID {state.user_id}")
                except Exception as e:
                    print(f"[load_user_context] Error loading user context: {e}")
                    state.user_context = None
            
            return state

        @streaming_step("evaluate_web_search_need")
        async def evaluate_web_search_need(state: FlowState) -> FlowState:
            """Evaluate if web search is needed for medical information."""
            try:
                # For other modes, evaluate based on query content
                patient_context_str = None
                if state.patient_ctx:
                    patient_context_str = f"Patient: {state.patient_ctx.name}, Age: {state.patient_ctx.age}"
                
                chat_history_str = None
                if state.chat_history:
                    chat_history_str = [msg.content for msg in state.chat_history[-3:]]
                
                needs_search = await self._web_search.evaluate_search_need(
                    user_query=state.user_prompt,
                    patient_context=patient_context_str,
                    chat_history=chat_history_str
                )
                
                state.web_search_performed = needs_search
                print(f"[web_search] Web search needed: {needs_search}")
                
            except Exception as e:
                print(f"[web_search] Error evaluating search need: {e}")
                state.web_search_performed = False
            
            return state

        @streaming_step("perform_web_search")
        async def perform_web_search(state: FlowState) -> FlowState:
            """Perform web search if needed."""
            try:
                if not state.web_search_performed:
                    return state
                
                # Prepare enhanced query with patient context
                search_query = state.user_prompt
                patient_context_str = None
                
                if state.patient_ctx:
                    patient_context_str = (
                        f"Patient demographics: {state.patient_ctx.name}, "
                        f"Age: {state.patient_ctx.age}, Sex: {state.patient_ctx.sex}"
                    )
                
                # Perform search with target language based on user's prompt
                try:
                    active_lang = detect_language_code(state.user_prompt or "")
                except Exception:
                    active_lang = "en"
                search_response = await self._web_search.search(
                    query=search_query,
                    max_results=8,
                    patient_context=patient_context_str,
                    search_intent="clinical_information",
                    target_language=(active_lang if active_lang and active_lang != "en" else None)
                )
                
                state.web_search_response = search_response
                
                # Also populate the legacy retrieved_web field for compatibility
                if search_response.results:
                    state.retrieved_web = [
                        f"Source: {result.title}\nURL: {result.url}\nContent: {result.snippet}"
                        for result in search_response.results[:3]
                    ]
                
                print(f"[web_search] Found {len(search_response.results)} results")
                
            except Exception as e:
                print(f"[web_search] Error performing search: {e}")
                state.web_search_response = None
                state.retrieved_web = []
            
            return state

        def needs_web_search(state: FlowState) -> bool:
            """Conditional function to determine if web search should be performed."""
            return state.web_search_performed


        @streaming_step("load_current_session_history")
        async def load_current_session_history(state: FlowState) -> FlowState:
            """Always load current session chat history from in-memory session store (ephemeral)."""
            print(f"[load_current_session_history] Loading for patient_id={state.patient_id}, session_id={state.session_id}")
            try:
                history = self._session_memory.get(state.session_id or "", []) if state.session_id else []
                chat_messages: list[ChatMessage] = []
                for item in history:
                        try:
                            role = ChatRole(item.get("role", "user"))
                            content = item.get("content", "")
                            chat_messages.append(ChatMessage(role=role, content=content))
                        except Exception as e:
                            print(f"[load_current_session_history] Error parsing item: {e}")
                            continue
                state.chat_history = chat_messages
            except Exception as e:
                print(f"[load_current_session_history] Error loading in-memory chat history: {e}")
                state.chat_history = []
            return state
        

        @streaming_step("evaluate_cross_session_history_need")
        async def evaluate_cross_session_history_need(state: FlowState) -> FlowState:
            """Evaluate if cross-session chat history would be helpful for context."""
            if not PERSISTENCE_ENABLED:
                state.needs_cross_session_search = False
                return state
            try:
                # Use LLM to determine if historical context from other sessions would help
                evaluation_prompt = f"""
                Analyze this user query to determine if consulting previous conversations from other sessions would be helpful:
                
                Query: "{state.user_prompt}"
                Patient ID: {state.patient_id or "General chat"}
                Current session history length: {len(state.chat_history)}
                
                Consider if the query:
                - References information that might have been discussed before ("we talked about this before", "as mentioned previously")
                - Asks about follow-up on treatments or conditions discussed in past sessions
                - Would benefit from understanding the patient's historical care progression
                - Seeks clarification on decisions made in previous consultations
                - Asks about medication changes, test results, or ongoing conditions
                - References "last time", "before", "previously discussed", etc.
                
                Respond with only "YES" or "NO".
                """
                
                evaluation_msg = ChatMessage(role=ChatRole.USER, content=evaluation_prompt)
                response = await self._llm.chat([
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a clinical assistant that determines if historical conversation context is needed."),
                    evaluation_msg
                ])
                
                needs_cross_session_history = "YES" in response.content.upper()
                state.needs_cross_session_search = needs_cross_session_history
                
                print(f"[cross_session_eval] Cross-session history needed: {needs_cross_session_history} for query: '{state.user_prompt[:50]}...'")
                
            except Exception as e:
                print(f"[cross_session_eval] Error evaluating cross-session history need: {e}")
                state.needs_cross_session_search = False
            
            return state

        @streaming_step("search_cross_session_history")
        async def search_cross_session_history(state: FlowState) -> FlowState:
            """Search across all previous sessions for relevant context."""
            if not PERSISTENCE_ENABLED:
                state.relevant_cross_session_history = []
                return state
            if not state.needs_cross_session_search:
                state.relevant_cross_session_history = []
                return state
                
            try:
                # Use embedding-based search to find relevant historical conversations
                query_embedding = await embed(state.user_prompt, "query")
                
                # Search for relevant chat history across all sessions
                if state.patient_id:
                    # Patient-specific cross-session search
                    rows = await self._vec.similarity_search(
                        query_embedding,
                        top_k=8,  # Get more results to filter through
                        filter_={
                            "namespace": "chat_history", 
                            "patient_id": str(state.patient_id)
                        },
                    )
                else:
                    # General chat cross-session search for this user
                    rows = await self._vec.similarity_search(
                        query_embedding,
                        top_k=8,
                        filter_={
                            "namespace": "chat_history",
                            "user_id": str(state.user_id)
                        },
                    )
                
                # Parse and filter the results
                relevant_history = []
                current_session_id = state.session_id
                
                for row in rows:
                    try:
                        # Extract content and metadata
                        # rows are (id, similarity, content)
                        content_text = row[2] if len(row) > 2 else row[1]
                        
                        # Parse if it's JSON
                        if isinstance(content_text, str) and content_text.strip().startswith('{'):
                            content_data = json.loads(content_text)
                            session_id_from_content = content_data.get("session_id")
                            role = content_data.get("role", "user")
                            message_content = content_data.get("content", "")
                            timestamp = content_data.get("timestamp")
                        else:
                            # Simple text content
                            message_content = content_text
                            session_id_from_content = None
                            role = "user"
                            timestamp = None
                        
                        # Skip if it's from current session (we already have that)
                        if session_id_from_content == current_session_id:
                            continue
                            
                        # Skip empty content
                        if not message_content or len(message_content.strip()) < 10:
                            continue
                        
                        # Add relevant historical context
                        relevant_history.append({
                            "content": message_content,
                            "role": role,
                            "session_id": session_id_from_content,
                            "timestamp": timestamp,
                            "similarity_score": row[1] if len(row) > 1 else 0.0
                        })
                        
                    except Exception as e:
                        print(f"[cross_session_search] Error parsing history row: {e}")
                        continue
                
                # Sort by similarity score and take the most relevant
                relevant_history.sort(key=lambda x: x.get("similarity_score", 0.0), reverse=True)
                state.relevant_cross_session_history = relevant_history[:5]  # Keep top 5 most relevant
                
                print(f"[cross_session_search] Found {len(state.relevant_cross_session_history)} relevant historical conversations")
                
            except Exception as e:
                print(f"[cross_session_search] Error searching cross-session history: {e}")
                state.relevant_cross_session_history = []

            return state

        async def store_patient_chunks(state: FlowState) -> FlowState:
            """Store patient context as chunks in the vector database for future retrieval."""
            if not state.patient_ctx:
                return state
            # RAM-only mode: bypass all storage
            if not PERSISTENCE_ENABLED:
                return state
                
            try:
                patient_id = str(state.patient_id)
                
                # Check if we already have chunks for this patient
                existing_chunks = await self._vec.similarity_search(
                    await embed("patient context", "query"),
                    top_k=1,
                    filter_={
                        "namespace": "clinical",
                        "patient_id": patient_id
                    }
                )
                
                if existing_chunks:
                    print(f"[store_chunks] Patient {patient_id} chunks already exist, checking for new journal entries")
                else:
                    print(f"[store_chunks] Creating new chunks for patient {patient_id}")
                
                patient_data = state.patient_ctx
                
                # Helper function to extract sources from patient data - CORRECTED
                def extract_sources_for_data_type(data_dict: dict, sources_dict: dict) -> list:
                    """Extract source information for a data type."""
                    sources_list = []
                    for key, value in data_dict.items():
                        if key in sources_dict:
                            source = sources_dict[key]
                            sources_list.append({
                                "data_field": key,
                                "value": value,
                                "source_type": source.source_type,
                                "resource_id": source.resource_id,
                                "resource_url": source.resource_url,
                                "timestamp": source.timestamp.isoformat() if getattr(source, "timestamp", None) else "",
                                "category": source.category,
                                "display_name": source.display_name
                            })
                    return sources_list
                
                # Store chunks with source information
                if not existing_chunks:
                    # 1. Demographics chunk
                    demographics_text = f"""
                    Patient Demographics:
                    Name: {patient_data.name}
                    Age: {patient_data.age}
                    Sex: {patient_data.sex}
                    Patient ID: {patient_id}
                    """
                    
                    await embed_and_store(
                        namespace="clinical",
                        object_type="Demographics",
                        object_id=f"{patient_id}_demographics",
                        text={"content": demographics_text.strip()},
                        metadata={
                            "patient_id": patient_id,
                            "data_type": "demographics",
                            "timestamp": str(int(time.time() * 1000))
                        }
                    )
                    
                    # 2. Vitals chunk with sources
                    if patient_data.vitals:
                        vitals_sources = extract_sources_for_data_type(
                            patient_data.vitals, 
                            patient_data.vitals_sources
                        )
                        
                        vitals_text = f"""
                        Patient Vitals for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.vitals.items()])}
                        
                        Data Sources:
                        {chr(10).join([f"- {s['data_field']}: {s['resource_url']} (recorded: {s['timestamp'][:10]})" for s in vitals_sources])}
                        """
                        
                        await embed_and_store(
                            namespace="clinical",
                            object_type="Vitals",
                            object_id=f"{patient_id}_vitals",
                            text={"content": vitals_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "vitals",
                                "timestamp": str(int(time.time() * 1000)),
                                "sources": vitals_sources
                            }
                        )
                    
                    # 3. Labs chunk with sources
                    if patient_data.labs:
                        labs_sources = extract_sources_for_data_type(
                            patient_data.labs, 
                            patient_data.labs_sources
                        )
                        
                        labs_text = f"""
                        Laboratory Results for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.labs.items()])}
                        
                        Data Sources:
                        {chr(10).join([f"- {s['data_field']}: {s['resource_url']} (recorded: {s['timestamp'][:10]})" for s in labs_sources])}
                        """
                        
                        await embed_and_store(
                            namespace="clinical",
                            object_type="Labs",
                            object_id=f"{patient_id}_labs",
                            text={"content": labs_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "labs",
                                "timestamp": str(int(time.time() * 1000)),
                                "sources": labs_sources
                            }
                        )
                    
                    # 4. Medications chunk with sources
                    if patient_data.medications:
                        medications_sources = extract_sources_for_data_type(
                            patient_data.medications, 
                            patient_data.medications_sources
                        )
                        
                        medications_text = f"""
                        Medications for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.medications.items()])}
                        
                        Data Sources:
                        {chr(10).join([f"- {s['data_field']}: {s['resource_url']} (recorded: {s['timestamp'][:10]})" for s in medications_sources])}
                        """
                        
                        await embed_and_store(
                            namespace="clinical",
                            object_type="Medications",
                            object_id=f"{patient_id}_medications",
                            text={"content": medications_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "medications",
                                "timestamp": str(int(time.time() * 1000)),
                                "sources": medications_sources
                            }
                        )
                    
                    # 5. Allergies chunk with sources
                    if patient_data.allergies:
                        allergies_sources = extract_sources_for_data_type(
                            patient_data.allergies,
                            patient_data.allergies_sources
                        )
                        allergies_text = f"""
                        Allergies for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.allergies.items()])}
                        
                        Data Sources:
                        {chr(10).join([f"- {s['data_field']}: {s['resource_url']} (recorded: {s['timestamp'][:10]})" for s in allergies_sources])}
                        """
                        await embed_and_store(
                            namespace="clinical",
                            object_type="Allergies",
                            object_id=f"{patient_id}_allergies",
                            text={"content": allergies_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "allergies",
                                "timestamp": str(int(time.time() * 1000)),
                                "sources": allergies_sources
                            }
                        )

                    # 6. Diagnoses chunk with sources
                    if patient_data.diagnoses:
                        diagnoses_sources = extract_sources_for_data_type(
                            patient_data.diagnoses,
                            patient_data.diagnoses_sources
                        )
                        diagnoses_text = f"""
                        Diagnoses for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.diagnoses.items()])}
                        
                        Data Sources:
                        {chr(10).join([f"- {s['data_field']}: {s['resource_url']} (recorded: {s['timestamp'][:10]})" for s in diagnoses_sources])}
                        """
                        await embed_and_store(
                            namespace="clinical",
                            object_type="Diagnoses",
                            object_id=f"{patient_id}_diagnoses",
                            text={"content": diagnoses_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "diagnoses",
                                "timestamp": str(int(time.time() * 1000)),
                                "sources": diagnoses_sources
                            }
                        )

                    # 7. Immunizations chunk with sources
                    if patient_data.immunizations:
                        immunizations_sources = extract_sources_for_data_type(
                            patient_data.immunizations,
                            patient_data.immunizations_sources
                        )
                        immunizations_text = f"""
                        Immunizations for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.immunizations.items()])}
                        
                        Data Sources:
                        {chr(10).join([f"- {s['data_field']}: {s['resource_url']} (recorded: {s['timestamp'][:10]})" for s in immunizations_sources])}
                        """
                        await embed_and_store(
                            namespace="clinical",
                            object_type="Immunizations",
                            object_id=f"{patient_id}_immunizations",
                            text={"content": immunizations_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "immunizations",
                                "timestamp": str(int(time.time() * 1000)),
                                "sources": immunizations_sources
                            }
                        )

                    # 8. Medication Statements chunk with sources
                    if patient_data.medication_statement:
                        med_stmt_sources = extract_sources_for_data_type(
                            patient_data.medication_statement,
                            patient_data.medication_statement_sources
                        )
                        med_stmt_text = f"""
                        Medication Statements for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.medication_statement.items()])}
                        
                        Data Sources:
                        {chr(10).join([f"- {s['data_field']}: {s['resource_url']} (recorded: {s['timestamp'][:10]})" for s in med_stmt_sources])}
                        """
                        await embed_and_store(
                            namespace="clinical",
                            object_type="MedicationStatement",
                            object_id=f"{patient_id}_medication_statement",
                            text={"content": med_stmt_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "medication_statement",
                                "timestamp": str(int(time.time() * 1000)),
                                "sources": med_stmt_sources
                            }
                        )

                    # 9. Questionnaire Responses chunk with sources
                    if patient_data.questionnaire_response:
                        qnr_sources = extract_sources_for_data_type(
                            patient_data.questionnaire_response,
                            patient_data.questionnaire_response_sources
                        )
                        qnr_text = f"""
                        Questionnaire Responses for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.questionnaire_response.items()])}
                        
                        Data Sources:
                        {chr(10).join([f"- {s['data_field']}: {s['resource_url']} (recorded: {s['timestamp'][:10]})" for s in qnr_sources])}
                        """
                        await embed_and_store(
                            namespace="clinical",
                            object_type="QuestionnaireResponse",
                            object_id=f"{patient_id}_questionnaire_response",
                            text={"content": qnr_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "questionnaire_response",
                                "timestamp": str(int(time.time() * 1000)),
                                "sources": qnr_sources
                            }
                        )

                    # 10. Encounters chunk with sources
                    if patient_data.encounters:
                        encounters_sources = extract_sources_for_data_type(
                            patient_data.encounters,
                            patient_data.encounters_sources
                        )
                        encounters_text = f"""
                        Encounters for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.encounters.items()])}
                        
                        Data Sources:
                        {chr(10).join([f"- {s['data_field']}: {s['resource_url']} (recorded: {s['timestamp'][:10]})" for s in encounters_sources])}
                        """
                        await embed_and_store(
                            namespace="clinical",
                            object_type="Encounters",
                            object_id=f"{patient_id}_encounters",
                            text={"content": encounters_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "encounters",
                                "timestamp": str(int(time.time() * 1000)),
                                "sources": encounters_sources
                            }
                        )

                    # 11. Exams chunk with sources
                    if patient_data.exam:
                        exam_sources = extract_sources_for_data_type(
                            patient_data.exam,
                            patient_data.exam_sources
                        )
                        exam_text = f"""
                        Physical Exams for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.exam.items()])}
                        
                        Data Sources:
                        {chr(10).join([f"- {s['data_field']}: {s['resource_url']} (recorded: {s['timestamp'][:10]})" for s in exam_sources])}
                        """
                        await embed_and_store(
                            namespace="clinical",
                            object_type="Exams",
                            object_id=f"{patient_id}_exams",
                            text={"content": exam_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "exam",
                                "timestamp": str(int(time.time() * 1000)),
                                "sources": exam_sources
                            }
                        )

                    # 12. Procedures chunk with sources
                    if patient_data.procedure:
                        procedure_sources = extract_sources_for_data_type(
                            patient_data.procedure,
                            patient_data.procedure_sources
                        )
                        procedure_text = f"""
                        Procedures for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.procedure.items()])}
                        
                        Data Sources:
                        {chr(10).join([f"- {s['data_field']}: {s['resource_url']} (recorded: {s['timestamp'][:10]})" for s in procedure_sources])}
                        """
                        await embed_and_store(
                            namespace="clinical",
                            object_type="Procedures",
                            object_id=f"{patient_id}_procedures",
                            text={"content": procedure_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "procedure",
                                "timestamp": str(int(time.time() * 1000)),
                                "sources": procedure_sources
                            }
                        )

                    # 13. Social History chunk with sources
                    if patient_data.social_history:
                        social_sources = extract_sources_for_data_type(
                            patient_data.social_history,
                            patient_data.social_history_sources
                        )
                        social_text = f"""
                        Social History for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.social_history.items()])}
                        
                        Data Sources:
                        {chr(10).join([f"- {s['data_field']}: {s['resource_url']} (recorded: {s['timestamp'][:10]})" for s in social_sources])}
                        """
                        await embed_and_store(
                            namespace="clinical",
                            object_type="SocialHistory",
                            object_id=f"{patient_id}_social_history",
                            text={"content": social_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "social_history",
                                "timestamp": str(int(time.time() * 1000)),
                                "sources": social_sources
                            }
                        )

                    # Imaging chunk removed in current version
                    
                    # 5. Complete patient context with all sources
                    all_sources = []
                    for data_type in ['vitals', 'labs', 'medications', 'allergies', 'diagnoses', 'immunizations', 'medication_statement', 'questionnaire_response', 'encounters', 'exam', 'procedure', 'social_history']:
                        data_dict = getattr(patient_data, data_type, {})
                        sources_dict = getattr(patient_data, f"{data_type}_sources", {})
                        all_sources.extend(extract_sources_for_data_type(data_dict, sources_dict))
                    
                    complete_context = patient_data.model_dump_json(indent=2)
                    
                    complete_context_with_sources = f"""
                    Complete patient context for {patient_data.name} (ID: {patient_id}):
                    {complete_context}
                    
                    All Data Sources:
                    {chr(10).join([f"- {s['data_field']} ({s['category']}): {s['resource_url']}" for s in all_sources])}
                    """
                    
                    await embed_and_store(
                        namespace="clinical",
                        object_type="PatientContext",
                        object_id=f"{patient_id}_complete",
                        text={"content": complete_context_with_sources.strip()},
                        metadata={
                            "patient_id": patient_id,
                            "data_type": "complete_context",
                            "timestamp": str(int(time.time() * 1000)),
                            "all_sources": all_sources
                        }
                    )


                # 5. Fetch and store recent journal entries
                try:
                    # Try to use user's EHR connection first
                    fhir_repo = self._fhir
                    if state.user_id:
                        try:
                            user_fhir_repo = await self._connection_service.create_fhir_repository(
                                state.user_id, 
                                "smart_fhir"
                            )
                            if user_fhir_repo:
                                fhir_repo = user_fhir_repo
                        except Exception as e:
                            print(f"[store_chunks] Failed to use SMART connection for journal: {e}")

                    # Fetch journal entries for this patient
                    journal_entries = await fhir_repo.get_patient_journal_entries(patient_id)
                    
                    if journal_entries:
                        print(f"[store_chunks] Found {len(journal_entries)} journal entries for patient {patient_id}")

                        # Prepare a reusable embedding for existence checks to avoid duplicates
                        existence_query_vec = await embed("journal entry existence check", "query")
                        count = 0
                        # Store only new journal entries as separate chunks
                        for entry in journal_entries:
                            # Skip if this journal entry is already stored (avoid duplicates)
                            try:
                                existing_entry = await self._vec.similarity_search(
                                    existence_query_vec,
                                    top_k=1,
                                    filter_={
                                        "namespace": "clinical",
                                        "patient_id": patient_id,
                                        "entry_id": entry.entry_id,
                                    },
                                )
                                if existing_entry:
                                    print(f"[store_chunks] Skipping already stored journal entry {entry.entry_id}")
                                    continue
                                count += 1
                            except Exception as e:
                                print(f"[store_chunks] Existence check failed for journal entry {entry.entry_id}: {e}")
                                # Fall through and attempt to store
                                pass
                            journal_text = f"""
                            Journal Entry: {entry.title}
                            Type: {entry.entry_type.value}
                            Author: {entry.author_name} ({entry.author_role})
                            Date: {entry.created_at.strftime('%Y-%m-%d %H:%M')}
                            Patient: {patient_data.name} (ID: {patient_id})
                            
                            Content:
                            {entry.content}
                            """
                            
                            await embed_and_store(
                                namespace="clinical",
                                object_type="JournalEntry",
                                object_id=f"{patient_id}_journal_{entry.entry_id}",
                                text={"content": journal_text.strip()},
                                metadata={
                                    "patient_id": patient_id,
                                    "data_type": "journal_entry",
                                    "entry_type": entry.entry_type.value,
                                    "entry_id": entry.entry_id,
                                    "author_name": entry.author_name,
                                    "author_role": entry.author_role,
                                    "created_at": entry.created_at.isoformat() if getattr(entry, "created_at", None) else "",
                                    "timestamp": str(int(entry.created_at.timestamp() * 1000))
                                }
                            )
                        
                        print(f"[store_chunks] Successfully stored {count} journal entries")
                    else:
                        print(f"[store_chunks] No journal entries found for patient {patient_id}")
                        
                except Exception as journal_error:
                    print(f"[store_chunks] Error fetching/storing journal entries: {journal_error}")
                    # Continue without journal entries - don't fail the entire process
                
                print(f"[store_chunks] Successfully processed chunks for patient {patient_id}")
                
            except Exception as e:
                print(f"[store_chunks] Error storing patient chunks: {e}")
            
            return state

        @streaming_step("intelligent_retrieve_chunks")
        async def intelligent_retrieve_chunks(state: FlowState) -> FlowState:
            """In-RAM retrieval: chunk, embed, paraphrase, bi-encoder, cross-encoder rerank, dynamic-N MMR, gate, retry."""
            try:
                if not state.patient_ctx:
                    state.retrieved_chunks = []
                    state.chunk_analysis = {"method": "none", "reason": "No patient context available"}
                    return state

                # 1) Chunking via ChunkingOrchestrator (policy-driven)
                patient_id_str = str(state.patient_id) if state.patient_id else ""
                tokenizer = WhitespaceTokenizer()
                redactor = SimplePhiRedactor()
                orchestrator = ChunkingOrchestrator(
                    tokenizer=tokenizer,
                    redactor=redactor,
                    strategy_registry=CHUNK_STRATEGY_REGISTRY,
                    policies=CHUNK_POLICY_PRESETS,
                )
                produced = orchestrator.chunk_patient(state.patient_ctx, CHUNK_POLICY_PRESETS)
                # Adapt to local chunk dicts
                chunks = [{
                    "id": c.id,
                    "content": c.text,
                    "metadata": {"patient_id": patient_id_str, "data_type": c.resource_type, "timestamp": str(int(time.time()*1000))},
                    "data_type": c.resource_type,
                } for c in produced]
                if not chunks:
                    state.retrieved_chunks = [state.patient_ctx.model_dump_json(indent=2)]
                    state.chunk_analysis = {"method": "fallback", "reason": "No chunks from context"}
                    return state

                # 2) Embed chunks
                chunk_texts = [c["content"] for c in chunks]
                chunk_vecs = await self._embed_many(chunk_texts, mode="passage")
                for i, vec in enumerate(chunk_vecs):
                    chunks[i]["embedding"] = vec

                # 3) Query variants
                try:
                    paraphrases = await self._paraphrase_query_variants(state.user_prompt)
                except Exception:
                    paraphrases = []
                # If in refinement loop, include refined queries at front
                refinements = getattr(state, 'refined_queries', []) or []
                base_variants = [state.user_prompt] + paraphrases[:2]
                query_variants = refinements + base_variants
                query_vecs = await self._embed_many(query_variants, mode="query")

                # 4) Bi-encoder scoring (max cosine)
                def bi_score(vec: list[float]) -> float:
                    return max(self._cosine(vec, qv) for qv in query_vecs)
                bi_scored = [(i, bi_score(chunks[i]["embedding"])) for i in range(len(chunks))]
                bi_scored.sort(key=lambda x: x[1], reverse=True)
                initial_indices = [idx for idx, _ in bi_scored[:TOPK_INITIAL]]

                # 5) Cross-encoder rerank (multilingual)
                lang = detect_language_code(state.user_prompt or "")
                cross = MultilingualCrossEncoder()
                rerank_scores = cross.score_pairs(state.user_prompt, [chunks[i]["content"] for i in initial_indices])
                # Align with indices
                rerank_scores = list(rerank_scores)
                reranked = list(zip(initial_indices, rerank_scores))
                reranked.sort(key=lambda x: x[1], reverse=True)
                reranked = reranked[:TOPK_RERANK]

                # 6) Dynamic n via multilingual classifier (fallback to heuristic)
                rerank_only_scores = [s for _, s in reranked]
                n_dynamic = self._compute_dynamic_n(state.user_prompt, rerank_only_scores)
                try:
                    classifier = MultilingualZeroShotClassifier()
                    label = classifier.classify_query(state.user_prompt, [
                        "factoid", "temporal", "broad"
                    ])
                    if label == "factoid":
                        n_dynamic = max(N_MIN, min(n_dynamic, 6))
                    elif label == "temporal":
                        n_dynamic = max(n_dynamic, 10)
                    elif label == "broad":
                        n_dynamic = max(n_dynamic, 12)
                except Exception:
                    pass

                # 7) MMR on top 30
                candidate_vecs = [chunks[i]["embedding"] for i, _ in reranked]
                best_q_idx = max(range(len(query_vecs)), key=lambda qi: sum(self._cosine(query_vecs[qi], v) for v in candidate_vecs) / max(len(candidate_vecs), 1))
                best_q_vec = query_vecs[best_q_idx]
                mmr_local_indices = self._mmr(candidate_vecs, best_q_vec, n_dynamic, lambda_=MMR_LAMBDA)
                selected_indices = [reranked[j][0] for j in mmr_local_indices]

                # 8) Binary gate via cross-encoder threshold
                gate_scores = cross.score_pairs(state.user_prompt, [chunks[i]["content"] for i in selected_indices])
                gate_results = [s >= GATE_THRESH for s in gate_scores]
                final_selected = [i for i, ok in zip(selected_indices, gate_results) if ok]

                # 9) Retry if too few
                # Agentic refinement handoff: if too few, set state and branch in the graph
                state.needs_refinement = len(final_selected) < max(N_MIN, min(N_MAX, len(chunks))) and state.retrieval_retry_attempts < RETRY_MAX
                if state.needs_refinement:
                    try:
                        refinements = await self._refine_queries(state.user_prompt, [chunks[i]["content"] for i in final_selected])
                    except Exception:
                        refinements = []
                    state.refined_queries = [r for r in refinements if r][:2]
                    state.retrieval_retry_attempts += 1
                    # Do not finalize retrieved_chunks yet; upstream conditional edge will loop
                    return state

                if not final_selected:
                    fallback_n = min(max(N_MIN, 1), len(reranked))
                    final_selected = [idx for idx, _ in reranked[:fallback_n]]

                state.retrieved_chunks = [chunks[i]["content"] for i in final_selected]
                state.chunk_analysis = {
                    "method": "bi_cross_mmr_gate",
                    "dynamic_n": len(final_selected),
                    "selected_chunks": [f"chunk_{i}" for i in final_selected]
                }
                state.retrieval_reasoning = "Paraphrases + bi-encoder, cross-encoder rerank, MMR diversity, binary gating"
            except Exception as e:
                print(f"[intelligent_retrieve_chunks] Error: {e}")
                state.retrieved_chunks = []
                state.chunk_analysis = {"method": "error", "reason": str(e)}
                return state

            return state

        async def store_user_message(state: FlowState) -> FlowState:
            """Store the user message in ephemeral memory for current session only."""
            if not state.user_prompt:
                return state
            
            try:
                # Append to in-memory session store if available
                if state.session_id:
                    self._session_memory.setdefault(state.session_id, [])
                    self._session_memory[state.session_id].append({
                        "role": "user",
                        "content": state.user_prompt,
                        "timestamp": str(int(time.time() * 1000)),
                        "user_id": state.user_id or ""
                    })
                
            except Exception as e:
                print(f"[store_user_message] Error: {e}")
                import traceback
                traceback.print_exc()
            
            return state

        async def store_assistant_response(state: FlowState) -> FlowState:
            """Store the assistant response in ephemeral memory for current session only."""
            if not state.llm_response:
                return state
            
            try:
                if state.session_id:
                    self._session_memory.setdefault(state.session_id, [])
                    self._session_memory[state.session_id].append({
                    "role": state.llm_response.role.value,
                    "content": state.llm_response.content,
                    "timestamp": str(int(time.time() * 1000)),
                        "user_id": state.user_id or ""
                    })
                
            except Exception as e:
                print(f"[store_assistant_response] Error: {e}")
                import traceback
                traceback.print_exc()
            
            return state

        @streaming_step("provide_information")
        async def provide_information(state: FlowState) -> FlowState:
            # Use the single system message for information relay
            messages = [SYSTEM_MSG_INFO_RELAY]

            # Language policy system message (answer in user's prompt language)
            try:
                from optimed.core.lang import detect_language_code  # local import to avoid cycles
                active_lang = detect_language_code(state.user_prompt or "")
            except Exception:
                active_lang = "en"
            language_system_msg = ChatMessage(
                role=ChatRole.SYSTEM,
                content=(
                    f"Language policy: Respond in '{active_lang}'. Use clinically appropriate terminology in this language. "
                    f"If citing or quoting sources in another language, translate faithfully and, if relevant, include the original term in parentheses."
                )
            )
            messages.insert(0, language_system_msg)

            # For direct path (simple queries), use a simplified system message
            if not getattr(state, 'requires_full_processing', True):
                simple_system_msg = ChatMessage(
                    role=ChatRole.SYSTEM, 
                    content="""You are CLARA, a helpful medical information assistant. Provide clear, accurate medical information. For general medical questions, draw on your medical knowledge. Keep responses concise and helpful.

Link policy (STRICT for EHR): For every EHR-derived item you mention (vital, lab value, medication, allergy, diagnosis, imaging finding, date, encounter, note), include a clickable markdown link immediately after that specific item, within the same sentence, e.g., "BP 128/76 (2024‑05‑01) [Vitals](URL)" or "metformin 500 mg BID [Meds](URL)". Do this for each individual item you list. Do not group EHR links in a separate Sources section. If no URL is available, write "(from EHR, no link available)" immediately after the item.
"""
                )
                messages = [simple_system_msg]

            if state.user_context:
                user_info = ChatMessage(
                    role=ChatRole.USER,
                    content=f"Current user: {state.user_context.display_name} ({state.user_context.role.value})"
                )
                messages.append(user_info)

            current_history = state.chat_history[-15:]  # Recent current session history
            if current_history:
                history_header = ChatMessage(
                    role=ChatRole.USER,
                    content="=== CURRENT SESSION HISTORY ==="
                )
                messages.append(history_header)
                for msg in current_history:
                    messages.append(msg)
                
                history_footer = ChatMessage(
                    role=ChatRole.USER,
                    content="=== END OF CURRENT SESSION HISTORY ==="
                )
                messages.append(history_footer)
            
            # Ensure intelligent retrieval results are available for direct path as well
            try:
                if not getattr(state, 'requires_full_processing', True):
                    if state.patient_ctx and not state.retrieved_chunks:
                        # Populate retrieval using the new intelligent retrieval within this node
                        await intelligent_retrieve_chunks(state)
            except Exception as e:
                print(f"[provide_information] Retrieval attempt failed on direct path: {e}")

            # Add cross-session relevant history if available (for both paths)
            if state.relevant_cross_session_history:
                cross_session_header = ChatMessage(
                    role=ChatRole.USER,
                    content="=== RELEVANT PREVIOUS CONVERSATIONS (FROM OTHER SESSIONS) ==="
                )
                messages.append(cross_session_header)
                
                for historical_item in state.relevant_cross_session_history:
                    session_info = f"Session: {historical_item.get('session_id', 'unknown')}"
                    timestamp_info = ""
                    if historical_item.get('timestamp'):
                        try:
                            timestamp_ms = int(historical_item['timestamp'])
                            timestamp_dt = datetime.fromtimestamp(timestamp_ms / 1000)
                            timestamp_info = f" | Date: {timestamp_dt.strftime('%Y-%m-%d %H:%M')}"
                        except Exception:
                            pass
                    
                    role = historical_item.get('role', 'user').upper()
                    content = historical_item.get('content', '')
                    
                    historical_msg = ChatMessage(
                        role=ChatRole.USER,
                        content=f"[{session_info}{timestamp_info}] {role}: {content}"
                    )
                    messages.append(historical_msg)
                
                cross_session_footer = ChatMessage(
                    role=ChatRole.USER,
                    content="=== END OF PREVIOUS CONVERSATIONS ==="
                )
                messages.append(cross_session_footer)

            # Add retrieved chunks (this is now the primary source of patient data)
            if state.retrieved_chunks:
                chunk_context = "Relevant clinical information"
                if state.retrieval_reasoning:
                    chunk_context += f" (Selected because: {state.retrieval_reasoning})"
                
                # Add recency context if available
                temporal_context = ""
                if state.chunk_analysis:
                    temporal_strategy = state.chunk_analysis.get("temporal_strategy")
                    if temporal_strategy:
                        temporal_context = f"\n\nTEMPORAL STRATEGY: {temporal_strategy}"
                        if temporal_strategy == "recent_priority":
                            temporal_context += " - Prioritizing most recent clinical data"
                        elif temporal_strategy == "trend_analysis": 
                            temporal_context += " - Including data to show trends over time"
                        elif temporal_strategy == "historical_context":
                            temporal_context += " - Including historical context for comparison"
                
                docs = ChatMessage(
                    role=ChatRole.USER,
                    content=f"{chunk_context}:{temporal_context}\n" + "\n---\n".join(state.retrieved_chunks),
                )
                messages.append(docs)

                # Include chunk analysis metadata for transparency
                if state.chunk_analysis and state.chunk_analysis.get("query_type"):
                    analysis_info = ChatMessage(
                        role=ChatRole.USER,
                        content=f"Query type identified: {state.chunk_analysis['query_type']}"
                    )
                    messages.append(analysis_info)

            # Add web search results if available
            if state.web_search_response and state.web_search_response.results:
                # Create a more detailed and instructional web search message
                sources_list = []
                for i, result in enumerate(state.web_search_response.results[:5], 1):
                    sources_list.append(f"{i}. [{result.title}]({result.url})\n   - {result.snippet[:200]}...")
                
                web_info = ChatMessage(
                    role=ChatRole.USER,
                    content=f"""=== WEB SEARCH RESULTS FOR: '{state.user_prompt}' ===

SEARCH SUMMARY: {state.web_search_response.summary}

SOURCES TO CITE IN YOUR RESPONSE:
{chr(10).join(sources_list)}

INSTRUCTION: You MUST cite these sources in your response using the format [Source Title](URL). Include at least 2-3 citations in your answer.

=== END OF WEB SEARCH RESULTS ===""")
                messages.append(web_info)


            user = ChatMessage(
                role=ChatRole.USER,
                content=state.user_prompt,
                user_id=state.user_id,
                user_role=state.user_context.role if state.user_context else None,
            )

            messages.append(user)

            # Use simpler reasoning for direct path
            if getattr(state, 'requires_full_processing', True):
                reasoning_prompt = self._create_reasoning_prompt(state)
            else:
                reasoning_prompt = """Think through this query step by step:
1. What is the user asking about?
2. What medical knowledge can I provide to help?
3. How can I give a clear, helpful response?"""

            if getattr(state, 'should_stream_response', False):
                state.streaming_response = ""  # Reset streaming response
                
                # Initialize streaming callback to emit chunks in real-time
                if not hasattr(state, 'streaming_updates'):
                    state.streaming_updates = []
                
                async for update in self._streaming_llm.chat_with_reasoning_stream(messages=messages, state=state, reasoning_prompt=reasoning_prompt):
                    if update["type"] == "content":
                        # Format EHR links during streaming accumulation
                        state.streaming_response = self._normalize_markdown(
                            self._format_ehr_links(update.get("accumulated_content", ""))
                        )

                        chunk_update = {
                            "type": "response_chunk",
                            "content": update.get("content", ""),
                            "accumulated_content": state.streaming_response,
                            "timestamp": datetime.now().isoformat(),
                        }
                        state.streaming_updates.append(chunk_update)

                        state.current_step = "Generating Response"
                        state.step_details = f"Generated {len(state.streaming_response)} characters..."
                        
                        # CRITICAL: Call the streaming callback if it exists to emit immediately
                        if hasattr(state, 'stream_callback') and state.stream_callback:
                            await state.stream_callback(chunk_update)

                    elif update["type"] == "completion":
                        # Finalize with hyperlink formatting and normalized markdown
                        state.llm_response = ChatMessage(
                            role = ChatRole.ASSISTANT,
                            content=self._normalize_markdown(
                                self._format_ehr_links(update.get("full_content", state.streaming_response))
                            ),
                            metadata={
                                "reasoning": update.get("reasoning", ""),
                                "reasoning_steps": update.get("reasoning_steps", []),
                            }
                        )
                        break
            else:
                llm_resp = await self._streaming_llm.chat_with_reasoning(messages=messages, state=state, reasoning_prompt=reasoning_prompt)
                state.llm_response = ChatMessage(
                    role=llm_resp.role,
                    content=self._normalize_markdown(self._format_ehr_links(llm_resp.content)),
                    metadata=llm_resp.metadata
                )

            # Log user action (same as before)
            if state.user_id and state.user_context:
                action = UserAction(
                    action_id=str(uuid.uuid4()),
                    user_id=state.user_id,
                    action_type="diagnosis_request" if not state.chat_mode else "chat_message",
                    resource_type="patient" if state.patient_id else "general_chat",
                    resource_id=state.patient_id,
                    description=f"{state.user_context.display_name} {'requested diagnosis for' if not state.chat_mode else 'chatted about'} {'patient ' + state.patient_id if state.patient_id else 'general topic'}",
                    metadata={
                        "prompt": state.user_prompt,
                        "chat_mode": state.chat_mode,
                        "session_id": state.session_id,
                        "direct_path": not getattr(state, 'requires_full_processing', True)
                    }
                )
                await self._user_repo.log_action(action)

            return state


        @streaming_step("evaluate_query_complexity")
        async def evaluate_query_complexity(state: FlowState) -> FlowState:
            """Evaluate if the query needs patient data, web search, or can be answered directly."""
            try:
                # For info retrieval mode, determine processing based on query content
                evaluation_prompt = f"""
                Analyze this query to determine if it requires patient data, web search, or can be answered directly:

                QUERY: "{state.user_prompt}"
                CONTEXT: User is requesting medical information
                PATIENT_ID_PROVIDED: {state.patient_id is not None}

                Classify the query type:

                REQUIRES_FULL_PROCESSING (needs patient data/web search):
                - Asks about specific patient symptoms, conditions, or medical history
                - Requests information about specific medications, lab results, or test interpretation
                - References "this patient", "my patient", patient-specific data
                - Requests analysis of provided medical data
                - Complex medical questions requiring current research

                CAN_ANSWER_DIRECTLY (general medical knowledge):
                - General medical education questions ("What is diabetes?")
                - Basic medical facts or definitions
                - General health advice not patient-specific
                - Questions about medical procedures in general
                - Medical terminology explanations
                - General treatment approaches (not patient-specific)
                - Simple greetings, thanks, or conversational messages
                - General "how to" medical questions

                EXAMPLES:
                - "What are the symptoms of pneumonia?" → DIRECT
                - "What should I ask this patient about their chest pain?" → FULL_PROCESSING
                - "Hello, how are you?" → DIRECT
                - "Can you analyze this patient's lab results?" → FULL_PROCESSING
                - "What is the difference between Type 1 and Type 2 diabetes?" → DIRECT
                - "What questions should I ask during the pre-visit for patient ID 123?" → FULL_PROCESSING

                Respond with only: "FULL_PROCESSING" or "DIRECT"
                """

                evaluation_msg = ChatMessage(role=ChatRole.USER, content=evaluation_prompt)
                response = await self._llm.chat([
                    ChatMessage(role=ChatRole.SYSTEM, content="You classify medical queries to optimize processing. Be conservative - when in doubt, choose FULL_PROCESSING."),
                    evaluation_msg
                ])

                # Parse response
                response_text = response.content.strip().upper()
                requires_full_processing = "FULL_PROCESSING" in response_text

                state.requires_full_processing = requires_full_processing
                
                print(f"[query_complexity] Query: '{state.user_prompt[:50]}...' -> {'FULL_PROCESSING' if requires_full_processing else 'DIRECT'}")
                
            except Exception as e:
                print(f"[query_complexity] Error evaluating query complexity: {e}")
                # Default to full processing on error to be safe
                state.requires_full_processing = True
                
            return state

        def requires_full_processing(state: FlowState) -> bool:
            """Conditional function to determine if full processing is needed."""
            return getattr(state, 'requires_full_processing', True)

        def check_patient_exists(state: FlowState) -> FlowState:
            """Check if patient_id is provided in the state."""
            # This node doesn't need to do anything - just pass through
            return state

        def has_patient(state: FlowState) -> bool:
            return state.patient_id is not None and state.patient_id.strip() != ""

        def needs_cross_session_search(state: FlowState) -> bool:
            """Conditional function to determine if cross-session search should be performed."""
            return state.needs_cross_session_search

        _builder = StateGraph(FlowState)
        _builder.add_node("check_patient", check_patient_exists)  # New decision node
        _builder.add_node("load_user_context", load_user_context)  # Load user context if available
        _builder.add_node("evaluate_query_complexity", evaluate_query_complexity)
        _builder.add_node("store_user_message", store_user_message)
        _builder.add_node("load_current_session_history", load_current_session_history)
        _builder.add_node("evaluate_cross_session_history_need", evaluate_cross_session_history_need)  
        _builder.add_node("search_cross_session_history", search_cross_session_history)
        _builder.add_node("fetch_patient", fetch_patient)
        _builder.add_node("store_patient_chunks", store_patient_chunks)
        _builder.add_node("intelligent_retrieve_chunks", intelligent_retrieve_chunks)
        _builder.add_node("evaluate_web_search_need", evaluate_web_search_need)
        _builder.add_node("perform_web_search", perform_web_search)
        _builder.add_node("provide_information", provide_information)
        _builder.add_node("store_assistant_response", store_assistant_response)

        _builder.set_entry_point("load_user_context")  # Start with loading user context

        # Add edges for user context loading
        _builder.add_edge("load_user_context", "evaluate_query_complexity")
        _builder.add_edge("evaluate_query_complexity", "store_user_message")
        _builder.add_edge("store_user_message", "load_current_session_history")
        # Branch based on query complexity
        _builder.add_conditional_edges(
            "load_current_session_history",
            requires_full_processing,
            {
                True: "check_patient",    # Full processing starts with session history
                False: "provide_information"                        # Direct path - skip all heavy processing
            }
        )

        # SESSION HISTORY LOADING (now happens for both patient and general chat)
        # After loading session history, decide if we need patient data
        _builder.add_conditional_edges(
            "check_patient",
            has_patient,
            {
                True: "fetch_patient",                   # Patient ID provided -> fetch patient details
                False: "evaluate_cross_session_history_need"  # No patient ID -> skip patient fetch
            }
        )

        # PATIENT PROCESSING PATH (only when patient_id exists)
        _builder.add_edge("fetch_patient", "store_patient_chunks")
        _builder.add_edge("store_patient_chunks", "evaluate_cross_session_history_need")

        _builder.add_conditional_edges(
            "evaluate_cross_session_history_need",
             needs_cross_session_search,
            {
                True: "search_cross_session_history",
                False: "intelligent_retrieve_chunks"
            }
        )

        _builder.add_edge("search_cross_session_history", "intelligent_retrieve_chunks")
        _builder.add_conditional_edges(
            "evaluate_web_search_need",
            needs_web_search,
            {
                True: "perform_web_search",
                False: "provide_information"
            }
        )

        # Agentic refinement: loop back to intelligent_retrieve_chunks if needed
        def needs_refinement(state: FlowState) -> bool:
            return getattr(state, 'needs_refinement', False)

        _builder.add_conditional_edges(
            "intelligent_retrieve_chunks",
            needs_refinement,
            {
                True: "intelligent_retrieve_chunks",
                False: "evaluate_web_search_need",
            }
        )

        _builder.add_edge("perform_web_search", "provide_information")
        _builder.add_edge("provide_information", "store_assistant_response")
        _builder.add_edge("store_assistant_response", END)

        return _builder.compile()

    def _format_ehr_links(self, text: str) -> str:
        """Convert bare URLs to markdown hyperlinks to ensure clickability.

        If a URL is already embedded in [title](url) format, it is not modified.
        """
        if not text:
            return text

        url_pattern = r"(?P<url>https?://[\w\-\.\:/%#\?=&]+)"

        def repl(match: re.Match[str]) -> str:
            url = match.group("url")
            # Avoid altering existing markdown links by checking preceding context
            start = max(match.start() - 60, 0)
            context = text[start:match.start()]
            if "](" in context:
                return url
            return f"[EHR record]({url})"

        return re.sub(url_pattern, repl, text)

    def _normalize_markdown(self, text: str) -> str:
        """Normalize common markdown issues that can break rendering.

        - Ensure a blank line before headers (##, ###) if missing.
        - Promote common label lines that precede a list into real headers.
        - Trim extra spaces after header markers.
        """
        if not text:
            return text

        lines = text.split('\n')
        normalized: list[str] = []
        for i, raw_line in enumerate(lines):
            line = raw_line
            is_header = line.startswith('## ') or line.startswith('### ')
            if is_header and normalized and normalized[-1].strip() != '':
                normalized.append('')
            if line.startswith('##'):
                line = line.replace('##\t', '## ').replace('##  ', '## ')
            if line.startswith('###'):
                line = line.replace('###\t', '### ').replace('###  ', '### ')
            # Heuristic: promote standalone label preceding a list to a header
            if not is_header:
                next_line = lines[i + 1] if i + 1 < len(lines) else ''
                looks_like_list = (
                    next_line.lstrip().startswith(('-', '*')) or
                    next_line.lstrip().startswith(tuple(str(d) + '.' for d in range(1, 10)))
                )
                looks_like_label = (
                    len(line.strip()) > 0 and
                    not line.lstrip().startswith(('#', '-', '*', '>', '`')) and
                    ':' not in line and
                    len(line.strip()) <= 80
                )
                if looks_like_list and looks_like_label:
                    if normalized and normalized[-1].strip() != '':
                        normalized.append('')
                    normalized.append(f"## {line.strip()}")
                    continue
            normalized.append(line)

        return '\n'.join(normalized)


    def _create_reasoning_prompt(self, state: FlowState) -> str:
        """Create a reasoning prompt for information retrieval mode."""
        return """Think through this information retrieval request step by step:
1. What is the user asking about?
2. What relevant medical information do I have available from patient records, web search, and previous conversations?
3. What key points should I address in my response?
4. How can I provide helpful, accurate medical information while staying within appropriate boundaries?
5. What sources should I cite and what references should I include?
6. Are there any important warnings, limitations, or considerations to mention?
7. How can I best present this information to be helpful and educational?"""

    # =========================
    # Retrieval helpers (RAM-only)
    # =========================
    def _cosine(self, a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        n = min(len(a), len(b))
        dot = sum(a[i] * b[i] for i in range(n))
        na = math.sqrt(sum(a[i] * a[i] for i in range(n)))
        nb = math.sqrt(sum(b[i] * b[i] for i in range(n)))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    async def _embed_many(self, texts: list[str], mode: str = "passage") -> list[list[float]]:
        tasks = [embed(t or "", mode) for t in texts]
        return await asyncio.gather(*tasks)

    def _mmr(self, doc_vecs: list[list[float]], query_vec: list[float], top_n: int, lambda_: float = 0.5) -> list[int]:
        selected: list[int] = []
        candidates = list(range(len(doc_vecs)))
        sim_to_query = [self._cosine(v, query_vec) for v in doc_vecs]
        while candidates and len(selected) < top_n:
            best_idx = None
            best_score = -1.0
            for i in candidates:
                diversity = 0.0
                if selected:
                    diversity = max(self._cosine(doc_vecs[i], doc_vecs[j]) for j in selected)
                score = lambda_ * sim_to_query[i] - (1 - lambda_) * diversity
                if score > best_score:
                    best_score = score
                    best_idx = i
            if best_idx is None:
                break
            selected.append(best_idx)
            candidates.remove(best_idx)
        return selected

    async def _paraphrase_query_variants(self, query: str) -> list[str]:
        prompt = (
            "Generate 3 brief paraphrases of the clinical query, maintaining meaning. "
            "Return as a JSON array of strings only.\n\nQuery: " + (query or "")
        )
        try:
            resp = await self._llm.chat([
                ChatMessage(role=ChatRole.SYSTEM, content="You produce concise paraphrases for retrieval."),
                ChatMessage(role=ChatRole.USER, content=prompt),
            ], json_mode=True)
            if resp and resp.content:
                content = resp.content.strip()
                if content.startswith("```"):
                    start = content.find('\n') + 1
                    end = content.rfind("```")
                    if start > 0 and end > start:
                        content = content[start:end].strip()
                arr = json.loads(content)
                if isinstance(arr, list):
                    return [str(x) for x in arr if isinstance(x, (str,))][:3]
        except Exception:
            pass
        return []

    # removed: LLM-based cross scoring and gating replaced with sentence-transformers adapters

    def _compute_dynamic_n(self, query: str, scores: list[float]) -> int:
        if not scores:
            return N_MIN
        diffs = [scores[i] - scores[i+1] for i in range(len(scores)-1)]
        if not diffs:
            n_elbow = len(scores)
        else:
            median_delta = sorted(diffs)[len(diffs)//2]
            knee_idx = next((i for i, d in enumerate(diffs) if d < median_delta), len(diffs)-1)
            n_elbow = knee_idx + 1
        mean_score = sum(scores) / len(scores)
        n_thresh = sum(1 for s in scores if s >= mean_score)
        if n_thresh == 0:
            n_thresh = 10**9
        n_class = self._classify_query(query)
        n = max(min(n_elbow, n_thresh), n_class)
        return max(N_MIN, min(N_MAX, n))

    def _classify_query(self, query: str) -> int:
        """Heuristic fallback; primary classification now uses MultilingualZeroShotClassifier in retrieval."""
        q = (query or "").lower()
        if any(k in q for k in ["what is", "define", "range", "normal", "dose", "dosage", "meaning"]):
            return 6
        if any(k in q for k in ["trend", "over time", "change", "increase", "decrease", "since"]):
            return 10
        if any(k in q for k in ["plan", "overview", "summary", "workup", "approach", "evaluation"]):
            return 12
        return 8

    async def _refine_queries(self, query: str, seen_passages: list[str]) -> list[str]:
        prompt = (
            "Given the clinical query and partial relevant passages, propose up to 2 refined queries "
            "that might retrieve missing aspects or synonyms. Return a JSON array of strings only.\n\n"
            f"Query: {query}\nPassages:\n- " + "\n- ".join([(p or "")[:300] for p in seen_passages])
        )
        try:
            resp = await self._llm.chat([
                ChatMessage(role=ChatRole.SYSTEM, content="You refine clinical search queries succinctly."),
                ChatMessage(role=ChatRole.USER, content=prompt),
            ], json_mode=True)
            if resp and resp.content:
                content = resp.content.strip()
                if content.startswith("```"):
                    start = content.find('\n') + 1
                    end = content.rfind("```")
                    if start > 0 and end > start:
                        content = content[start:end].strip()
                arr = json.loads(content)
                if isinstance(arr, list):
                    return [str(x) for x in arr if isinstance(x, (str,))][:2]
        except Exception:
            pass
        return []

    # removed: obsolete manual chunk builder; using ChunkingOrchestrator instead

    async def get_or_create_session(
        self, 
        user_id: str, 
        patient_id: str | None, 
        mode: str,
        session_id: str | None = None,
        allow_join_existing: bool = True
    ) -> str:
        """Get existing session or create a new one, with multi-user support."""
        if not PERSISTENCE_ENABLED:
            # On new session, clear any existing ephemeral chat
            sid = session_id or str(uuid.uuid4())
            self._session_memory[sid] = []
            return sid
        if session_id:
            # Verify session exists
            session_info = await self._vec.get_session_info(session_id)
            if session_info:
                # Add user to session if not already a participant
                if user_id not in session_info.participants:
                    if allow_join_existing:
                        success = await self._vec.add_user_to_session(session_id, user_id)
                        if success:
                            print(f"[session] User {user_id} joined existing session {session_id}")
                        else:
                            print(f"[session] Failed to add user {user_id} to session {session_id}")
                    else:
                        print(f"[session] User {user_id} not allowed to join session {session_id}")
                        return await self._vec.create_chat_session(user_id, patient_id, mode)
                
                return session_id
        
        # Create new session
        return await self._vec.create_chat_session(
            user_id=user_id,
            patient_id=patient_id,
            mode=mode
        )

    async def run(self, patient: PatientContext | None = None, user_prompt: str | None = None, chat_mode: bool = False, user_id: str | None = None, session_id: str | None = None) -> Union[DiagnosisResult,  dict]:

        if user_id:
            session_id = await self.get_or_create_session(
                user_id=user_id,
                patient_id=patient.patient_id if patient else None,
                mode="chat" if chat_mode else "info_retrieval",
                session_id=session_id,
                allow_join_existing=True  # Allow users to join existing sessions
            )

        prompt = user_prompt or self._default_prompt
        if patient is not None:
            data = await self._compiled_graph.ainvoke({
                "patient_id": patient.patient_id,
                "user_prompt": prompt,
                "chat_mode": chat_mode,
                "user_id": user_id,
                "session_id": session_id
            })
        else:
            data = await self._compiled_graph.ainvoke({
                "user_prompt": prompt,
                "chat_mode": chat_mode,
                "user_id": user_id,
                "session_id": session_id
            })
        
        if PERSISTENCE_ENABLED and session_id and user_id:
            await self._vec.update_session_activity(session_id=session_id, user_id=user_id)
        
        # Always return the same completion-shaped output as run_stream's final chunk
        if hasattr(data, "model_dump"):
            return self._to_output(data.model_dump())
        return self._to_output(data)

    def run_stream(self, patient: PatientContext | None = None, user_prompt: str | None = None, chat_mode: bool = False, diagnostic_mode: str = "info_retrieval", user_id: str | None = None, session_id: str | None = None) -> AsyncGenerator[dict[str, Any], None]:
        """Return an async generator that yields chunks as they stream from the graph."""

        async def _stream_generator():
            if user_id:
                session_id_final = await self.get_or_create_session(
                    user_id=user_id,
                    patient_id=patient.patient_id if patient else None,
                    mode="chat" if chat_mode else "info_retrieval",
                    session_id=session_id,
                    allow_join_existing=True
                )
            else:
                session_id_final = session_id

            prompt = user_prompt or self._default_prompt
            
            # Create a queue for real-time streaming chunks
            chunk_queue = asyncio.Queue()
            
            # Define the streaming callback to emit chunks immediately
            async def stream_callback(chunk_update):
                await chunk_queue.put(chunk_update)
            
            # Create initial input
            if patient is not None:
                initial_input = {
                    "patient_id": patient.patient_id,
                    "user_prompt": prompt,
                    "chat_mode": chat_mode,
                    "info_retrieval_mode": diagnostic_mode if not chat_mode else "chat",
                    "user_id": user_id,
                    "session_id": session_id_final,
                    "should_stream_response": True,  # Indicate we want streaming
                    "stream_callback": stream_callback  # Pass the callback
                }
            else:
                initial_input = {
                    "user_prompt": prompt,
                    "chat_mode": chat_mode,
                    "info_retrieval_mode": diagnostic_mode if not chat_mode else "chat",
                    "user_id": user_id,
                    "session_id": session_id_final,
                    "should_stream_response": True,  # Indicate we want streaming
                    "stream_callback": stream_callback  # Pass the callback
                }

            graph_task = None
            
            try:
                # Start the graph processing as a background task
                async def run_graph():
                    # Move these variables inside the function to avoid scope issues
                    previous_state = None
                    reasoning_emitted = set()  # Track which reasoning steps we've emitted
                    
                    async for update in self._compiled_graph.astream(initial_input):
                        # Extract the current state from the update
                        for node_name, node_output in update.items():
                            if isinstance(node_output, dict):
                                current_state = node_output
                                
                                # Handle status updates (non-streaming steps)
                                if (previous_state is None or 
                                    current_state.get("current_step") != previous_state.get("current_step") or
                                    current_state.get("step_status") != previous_state.get("step_status")):
                                    
                                    status_update = {
                                        "type": "status",
                                        "step": current_state.get("current_step", ""),
                                        "description": current_state.get("step_details", ""),  # Use auto-generated details
                                        "status": current_state.get("step_status", ""),
                                        "progress": current_state.get("progress_percentage", 0.0),
                                        "timestamp": datetime.now().isoformat()
                                    }
                                    
                                    # Add special flags for important events
                                
                                    await chunk_queue.put(status_update)
                                

                                #Emit reasoning steps as they become available from the streaming LLM
                                if current_state.get("reasoning_steps"):
                                    for i, step in enumerate(current_state["reasoning_steps"]):
                                        step_id = f"{current_state.get('session_id', 'unknown')}_{i}"
                                        if step_id not in reasoning_emitted:
                                            reasoning_update = {
                                                "type": "reasoning",
                                                "step_number": i + 1,
                                                "total_steps": len(current_state["reasoning_steps"]),
                                                "content": step,  # This is the actual reasoning content
                                                "timestamp": datetime.now().isoformat()
                                            }
                                            await chunk_queue.put(reasoning_update)
                                            reasoning_emitted.add(step_id)
                                
                                # Emit reasoning complete when LLM finishes thinking
                                if (current_state.get("llm_reasoning") and 
                                    current_state.get("reasoning_complete") and
                                    (not previous_state or not previous_state.get("reasoning_complete"))):
                                    
                                    reasoning_complete_update = {
                                        "type": "reasoning_complete",
                                        "full_reasoning": current_state["llm_reasoning"],
                                        "timestamp": datetime.now().isoformat()
                                    }
                                    await chunk_queue.put(reasoning_complete_update)
                                
                                previous_state = current_state
                    
                    # Emit final completion
                    final_response_content = ""
                    if previous_state and previous_state.get("llm_response"):
                        final_response_content = previous_state["llm_response"].content if hasattr(previous_state["llm_response"], 'content') else str(previous_state["llm_response"])
                    
                    completion_update = {
                        "type": "completion",
                        "status": "completed",
                        "details": "Analysis complete",
                        "progress": 100.0,
                        "timestamp": datetime.now().isoformat(),
                        "final_response": final_response_content
                    }
                    
                    # Include reasoning in completion
                    if previous_state and previous_state.get("llm_reasoning"):
                        completion_update["reasoning"] = previous_state["llm_reasoning"]
                        completion_update["reasoning_steps"] = previous_state.get("reasoning_steps", [])
                    

                    
                    await chunk_queue.put(completion_update)
                    await chunk_queue.put(None)  # Signal end of stream
                
                # Start graph processing
                graph_task = asyncio.create_task(run_graph())
                
                # Yield chunks as they become available in real-time
                while True:
                    try:
                        # Wait for next chunk with a timeout
                        chunk = await asyncio.wait_for(chunk_queue.get(), timeout=0.1)
                        
                        if chunk is None:  # End of stream signal
                            break
                            
                        yield chunk
                        
                    except asyncio.TimeoutError:
                        # Check if graph is still running
                        if graph_task.done():
                            # Graph finished, drain remaining chunks
                            while not chunk_queue.empty():
                                chunk = chunk_queue.get_nowait()
                                if chunk is None:
                                    break
                                yield chunk
                            break
                        continue
                        
            except Exception:
                if graph_task and not graph_task.done():
                    graph_task.cancel()
                raise

        return _stream_generator()

    def _to_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Build the same completion-shaped dict that run_stream emits at the end."""
        final_response_content = ""
        if data.get("llm_response"):
            try:
                final_response_content = data["llm_response"].content
            except Exception:
                final_response_content = str(data.get("llm_response", ""))

        completion_update: dict[str, Any] = {
            "type": "completion",
            "status": "completed",
            "details": "Analysis complete",
            "progress": 100.0,
            "timestamp": data.get("timestamp", datetime.now().isoformat()),
            "final_response": final_response_content,
        }

        # Include reasoning if available
        if data.get("llm_reasoning"):
            completion_update["reasoning"] = data.get("llm_reasoning")
        if data.get("reasoning_steps"):
            completion_update["reasoning_steps"] = data.get("reasoning_steps", [])


        return completion_update

    def chat_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert raw dict emitted by compiled_graph to a chat output format."""
        web_search_info = {}
        if data.get("web_search_response"):
            web_response = data["web_search_response"]
            
            # Check if the response actually contains citations
            response_content = data["llm_response"].content if data["llm_response"] else ""
            citations_found = []
            
            for result in web_response.results[:5]:
                if result.url in response_content or result.title in response_content:
                    citations_found.append(result.url)
            
            web_search_info = {
                "web_search_performed": True,
                "sources_consulted": [result.url for result in web_response.results[:5]],
                "sources_cited_in_response": citations_found,
                "search_summary": web_response.summary,
                "source_count": len(web_response.results),
                "citations_included": len(citations_found) > 0
            }
        else:
            web_search_info = {
                "web_search_performed": False,
                "sources_consulted": [],
                "sources_cited_in_response": [],
                "search_summary": "",
                "source_count": 0,
                "citations_included": False
            }
        
        cross_session_info = {}
        if data.get("relevant_cross_session_history"):
            cross_session_info = {
                "cross_session_search_performed": True,
                "historical_sessions_consulted": len(set(item.get("session_id") for item in data["relevant_cross_session_history"] if item.get("session_id"))),
                "historical_messages_found": len(data["relevant_cross_session_history"]),
                "oldest_reference": min((item.get("timestamp") for item in data["relevant_cross_session_history"] if item.get("timestamp")), default=None)
            }
        else:
            cross_session_info = {
                "cross_session_search_performed": data.get("needs_cross_session_search", False),
                "historical_sessions_consulted": 0,
                "historical_messages_found": 0,
                "oldest_reference": None
            }

        return {
            "explanation": data["llm_response"].content if data["llm_response"] else "",
            "created_by_user_id": data.get("user_id"),
            "is_ai_generated": True,
            "web_search_info": web_search_info,
            "cross_session_history_info": cross_session_info,
            "session_id": data.get("session_id"),
        }
    

    @property
    def vector_store(self) -> VectorStore:
        """Access to the underlying vector store."""
        return self._vec

    
