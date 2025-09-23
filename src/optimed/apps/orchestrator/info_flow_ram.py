from __future__ import annotations
from .streaming_decorators import streaming_step
from .streaming_llm import StreamingLLMWrapper

import uuid 
import json
import time
import math
import asyncio
from typing import List, Any, Union, AsyncGenerator, Optional, Dict
from datetime import datetime

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from optimed.core.domain import PatientContext, ChatMessage, DiagnosisResult, ChatRole, UserAction, User, WebSearchResponse, JournalEntry, Chunk
from optimed.core.domain.pdf_document import PDFDocument
from optimed.core.lang import detect_language_code

from optimed.core.ports import DiagnosticEngine, FHIRRepository, LLMClient, VectorStore, UserRepository, WebSearchService, PDFService

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
N_MAX: int = 25
MMR_LAMBDA: float = 0.5
GATE_THRESH: float = 0.5
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
                                        When referencing specific patient data from the clinical information chunks, you MUST include the source links that are embedded in the chunk content.
                                        - For atomic data (vitals, labs, medications, etc.): The chunks contain data in the format "value [EHR Source](URL)" - preserve this exact format when referencing the data
                                        - For narrative data (reports, impressions, etc.): The chunks contain source information at the end as "**Source:** [EHR Record](URL)" - preserve this when referencing the content
                                        - If you see data without a source link, write `(from EHR, no link available)` immediately after that item
                                        - NEVER remove or modify existing source links - they are essential for clinical traceability
                                    - Do not escape Markdown unnecessarily; the final response must always render cleanly.
                                    - When the user asks for a summary start by explaining the current situation and then provide the summary.

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
    journal_entries: List[JournalEntry] = Field(default_factory=list)  # Store fetched journal entries
    uploaded_pdfs: List[PDFDocument] = Field(default_factory=list)  # Store PDF documents
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

    # SBAR flow fields
    query_classification: Optional[str] = None
    is_sbar_flow: bool = False

    # Separate fields for each SBAR component to avoid concurrent updates
    sbar_situation_chunks: Optional[List[str]] = None
    sbar_background_chunks: Optional[List[str]] = None
    sbar_assessment_chunks: Optional[List[str]] = None
    sbar_recommendation_chunks: Optional[List[str]] = None

    sbar_situation_result: Optional[str] = None
    sbar_background_result: Optional[str] = None
    sbar_assessment_result: Optional[str] = None
    sbar_recommendation_result: Optional[str] = None

    # SBAR retrieval cache for performance optimization
    sbar_retrieval_cache: Optional[Dict[str, Any]] = None
    


class LangGraphRAMInformationEngine(DiagnosticEngine):
    """Concrete engine that streams or returns full result."""

    def __init__(self, fhir_repo: FHIRRepository,
                 vector_store: VectorStore,
                 llm_client: LLMClient,
                 user_repo: UserRepository,
                 connection_service: UserEHRConnectionService,
                 web_search_service: WebSearchService,
                 cross_encoder: MultilingualCrossEncoder,
                 zero_shot_classifier: MultilingualZeroShotClassifier,
                 pdf_service: Optional[PDFService] = None,
                 default_prompt: str = "Provide the most likely diagnosis"):
        self._fhir = fhir_repo
        self._vec = vector_store
        self._llm = llm_client
        self._streaming_llm = StreamingLLMWrapper(llm_client=llm_client)

        self._user_repo = user_repo
        self._connection_service = connection_service
        self._web_search = web_search_service
        self._pdf_service = pdf_service
        self._default_prompt = default_prompt
        
        # ML models for intelligent retrieval
        self._cross_encoder = cross_encoder
        self._zero_shot_classifier = zero_shot_classifier

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
            
            # Also fetch journal entries for this patient
            try:
                journal_entries = await fhir_repo.get_patient_journal_entries(str(state.patient_id))
                state.journal_entries = list(journal_entries)
                print(f"[fetch_patient] Fetched {len(state.journal_entries)} journal entries for patient {state.patient_id}")
            except Exception as e:
                print(f"[fetch_patient] Failed to fetch journal entries: {e}")
                state.journal_entries = []
            
            return state

        @streaming_step("fetch_pdfs")
        async def fetch_pdfs(state: FlowState) -> FlowState:
            """Fetch PDF documents relevant for the current context."""
            if not self._pdf_service or not state.user_id or not state.session_id:
                state.uploaded_pdfs = []
                return state

            try:
                # Get PDF documents for the current session (patient-specific or general)
                pdf_documents = await self._pdf_service.get_documents_for_context(
                    user_id=state.user_id,
                    session_id=state.session_id,
                    patient_id=state.patient_id
                )

                # Filter to only include ready documents with extracted text
                ready_pdfs = [
                    doc for doc in pdf_documents
                    if doc.status.value == "READY" and doc.extracted_text
                ]

                state.uploaded_pdfs = ready_pdfs
                print(f"[fetch_pdfs] Fetched {len(state.uploaded_pdfs)} ready PDF documents for session {state.session_id} (patient_id={state.patient_id})")

            except Exception as e:
                print(f"[fetch_pdfs] Failed to fetch PDF documents: {e}")
                state.uploaded_pdfs = []

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
                # Note: No patient data is sent to external APIs for GDPR compliance
                chat_history_str = None
                if state.chat_history:
                    chat_history_str = [msg.content for msg in state.chat_history[-3:]]
                
                needs_search = await self._web_search.evaluate_search_need(
                    user_query=state.user_prompt,
                    patient_context=None,  # No patient data sent to external APIs
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
                
                # Prepare search query without patient data for GDPR compliance
                search_query = state.user_prompt
                
                # Perform search with target language based on user's prompt
                try:
                    active_lang = detect_language_code(state.user_prompt or "")
                except Exception:
                    active_lang = "en"
                search_response = await self._web_search.search(
                    query=search_query,
                    max_results=8,
                    patient_context=None,  # No patient data sent to external APIs
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
                print(f"[intelligent_retrieve_chunks] Starting retrieval for patient_id: {state.patient_id}")
                print(f"[intelligent_retrieve_chunks] User prompt: '{state.user_prompt[:100]}...'")
                
                # 1) Chunking via ChunkingOrchestrator (policy-driven)
                patient_id_str = str(state.patient_id) if state.patient_id else ""
                print(f"[intelligent_retrieve_chunks] Creating chunking orchestrator for patient: {patient_id_str}")

                tokenizer = WhitespaceTokenizer()
                redactor = SimplePhiRedactor()
                orchestrator = ChunkingOrchestrator(
                    tokenizer=tokenizer,
                    redactor=redactor,
                    strategy_registry=CHUNK_STRATEGY_REGISTRY,
                    policies=CHUNK_POLICY_PRESETS,
                )

                # Chunk patient context if available
                produced = []
                if state.patient_ctx:
                    print("[intelligent_retrieve_chunks] Chunking patient context...")
                    produced = orchestrator.chunk_patient(state.patient_ctx, CHUNK_POLICY_PRESETS)
                    print(f"[intelligent_retrieve_chunks] Patient context chunking produced {len(produced)} chunks")
                else:
                    print("[intelligent_retrieve_chunks] No patient context available - proceeding with PDF-only mode")
                
                # Also chunk journal entries if available
                journal_chunks = []
                if state.journal_entries:
                    print(f"[intelligent_retrieve_chunks] Chunking {len(state.journal_entries)} journal entries...")
                    journal_chunks = await self._chunk_journal_entries(state.journal_entries, orchestrator, patient_id_str)
                    print(f"[intelligent_retrieve_chunks] Journal entries chunking produced {len(journal_chunks)} chunks")

                # Also chunk PDF documents if available
                pdf_chunks = []
                if state.uploaded_pdfs:
                    print(f"[intelligent_retrieve_chunks] Chunking {len(state.uploaded_pdfs)} PDF documents...")
                    pdf_chunks = await self._chunk_pdf_documents(state.uploaded_pdfs, orchestrator, patient_id_str)
                    print(f"[intelligent_retrieve_chunks] PDF documents chunking produced {len(pdf_chunks)} chunks")

                # Combine all chunks
                all_chunks = produced + journal_chunks + pdf_chunks
                print(f"[intelligent_retrieve_chunks] Total chunks produced: {len(all_chunks)} (patient: {len(produced)}, journal: {len(journal_chunks)}, pdf: {len(pdf_chunks)})")
                
                # Log chunk details
                for i, chunk in enumerate(all_chunks):
                    print(f"[intelligent_retrieve_chunks] Chunk {i+1}: type={chunk.resource_type}, id={chunk.id}, length={len(chunk.text)} chars")
                    print(f"[intelligent_retrieve_chunks] Chunk {i+1} preview: '{chunk.text[:100]}...'")
                
                # Adapt to local chunk dicts
                chunks: list[dict[str, Any]] = [{
                    "id": c.id,
                    "content": c.text,
                    "metadata": {"patient_id": patient_id_str, "data_type": c.resource_type, "timestamp": str(int(time.time()*1000))},
                    "data_type": c.resource_type,
                } for c in all_chunks]
                
                if not chunks:
                    print("[intelligent_retrieve_chunks] No chunks produced")
                    if state.patient_ctx:
                        print("[intelligent_retrieve_chunks] Using fallback to full patient context")
                        state.retrieved_chunks = [state.patient_ctx.model_dump_json(indent=2)]
                        state.chunk_analysis = {"method": "fallback", "reason": "No chunks from patient context"}
                    else:
                        print("[intelligent_retrieve_chunks] No patient context or PDF content available")
                        state.retrieved_chunks = []
                        state.chunk_analysis = {"method": "none", "reason": "No content available for chunking"}
                    return state

                # 2) Embed chunks
                print(f"[intelligent_retrieve_chunks] Embedding {len(chunks)} chunks...")
                chunk_texts = [c["content"] for c in chunks]
                chunk_vecs = await self._embed_many(chunk_texts, mode="passage")
                for i, vec in enumerate(chunk_vecs):
                    chunks[i]["embedding"] = vec
                print(f"[intelligent_retrieve_chunks] Successfully embedded {len(chunk_vecs)} chunks")

                # 3) Query variants
                print("[intelligent_retrieve_chunks] Generating query variants...")
                try:
                    paraphrases = await self._paraphrase_query_variants(state.user_prompt)
                    print(f"[intelligent_retrieve_chunks] Generated {len(paraphrases)} paraphrases: {paraphrases}")
                except Exception as e:
                    print(f"[intelligent_retrieve_chunks] Failed to generate paraphrases: {e}")
                    paraphrases = []
                
                # If in refinement loop, include refined queries at front
                refinements = getattr(state, 'refined_queries', []) or []
                base_variants = [state.user_prompt] + paraphrases[:2]
                query_variants = refinements + base_variants
                print(f"[intelligent_retrieve_chunks] Using {len(query_variants)} query variants: {query_variants}")
                
                query_vecs = await self._embed_many(query_variants, mode="query")
                print(f"[intelligent_retrieve_chunks] Successfully embedded {len(query_vecs)} query variants")

                # 4) Bi-encoder scoring (max cosine)
                print(f"[intelligent_retrieve_chunks] Computing bi-encoder scores for {len(chunks)} chunks...")
                def bi_score(vec: list[float]) -> float:
                    return max(self._cosine(vec, qv) for qv in query_vecs)
                from typing import cast
                bi_scored = [(i, bi_score(cast(list[float], chunks[i]["embedding"]))) for i in range(len(chunks))]
                bi_scored.sort(key=lambda x: x[1], reverse=True)
                
                # Log top bi-encoder scores
                print("[intelligent_retrieve_chunks] Top 5 bi-encoder scores:")
                for i, (idx, score) in enumerate(bi_scored[:5]):
                    chunk_type = chunks[idx]["data_type"]
                    print(f"[intelligent_retrieve_chunks]   {i+1}. Chunk {idx} ({chunk_type}): {score:.4f}")
                
                # Log bi-encoder score range
                if bi_scored:
                    bi_scores = [score for _, score in bi_scored]
                    print(f"[intelligent_retrieve_chunks] Bi-encoder score range: [{min(bi_scores):.4f}, {max(bi_scores):.4f}]")
                
                initial_indices = [idx for idx, _ in bi_scored[:TOPK_INITIAL]]
                print(f"[intelligent_retrieve_chunks] Selected top {len(initial_indices)} chunks for cross-encoder reranking")

                # 5) Cross-encoder rerank (multilingual)
                lang = detect_language_code(state.user_prompt or "")
                print(f"[intelligent_retrieve_chunks] Detected language: {lang}")
                print("[intelligent_retrieve_chunks] Running cross-encoder reranking...")
                
                cross = self._cross_encoder
                rerank_scores = cross.score_pairs(state.user_prompt, [cast(str, chunks[i]["content"]) for i in initial_indices])
                # Align with indices
                rerank_scores = list(rerank_scores)
                reranked = list(zip(initial_indices, rerank_scores))
                reranked.sort(key=lambda x: x[1], reverse=True)
                reranked = reranked[:TOPK_RERANK]
                
                # Log top cross-encoder scores
                print(f"[intelligent_retrieve_chunks] Top {len(reranked)} cross-encoder scores:")
                for i, (idx, score) in enumerate(reranked):
                    chunk_type = chunks[idx]["data_type"]
                    print(f"[intelligent_retrieve_chunks]   {i+1}. Chunk {idx} ({chunk_type}): {score:.4f}")
                
                # Log cross-encoder score range
                if reranked:
                    cross_scores = [score for _, score in reranked]
                    print(f"[intelligent_retrieve_chunks] Cross-encoder score range: [{min(cross_scores):.4f}, {max(cross_scores):.4f}]")

                # 6) Dynamic n via multilingual classifier (fallback to heuristic)
                rerank_only_scores = [s for _, s in reranked]
                n_dynamic = self._compute_dynamic_n(state.user_prompt, rerank_only_scores, state.query_classification)
                print(f"[intelligent_retrieve_chunks] dynamic n: {n_dynamic}")
                

                # 7) MMR on top 30
                print(f"[intelligent_retrieve_chunks] Running MMR with lambda={MMR_LAMBDA}, n={n_dynamic}")
                candidate_vecs = [cast(list[float], chunks[i]["embedding"]) for i, _ in reranked]
                best_q_idx = max(range(len(query_vecs)), key=lambda qi: sum(self._cosine(query_vecs[qi], v) for v in candidate_vecs) / max(len(candidate_vecs), 1))
                best_q_vec = query_vecs[best_q_idx]
                mmr_local_indices = self._mmr(candidate_vecs, best_q_vec, n_dynamic, lambda_=MMR_LAMBDA)
                selected_indices = [reranked[j][0] for j in mmr_local_indices]
                print(f"[intelligent_retrieve_chunks] MMR selected {len(selected_indices)} chunks: {selected_indices}")

                # 8) Binary gate via cross-encoder threshold
                print(f"[intelligent_retrieve_chunks] Applying binary gate with threshold {GATE_THRESH}")
                gate_scores = cross.score_pairs(state.user_prompt, [cast(str, chunks[i]["content"]) for i in selected_indices])
                gate_results = [s >= GATE_THRESH for s in gate_scores]
                final_selected = [i for i, ok in zip(selected_indices, gate_results) if ok]
                
                # Log gating results
                print("[intelligent_retrieve_chunks] Gate results:")
                for i, (idx, score, passed) in enumerate(zip(selected_indices, gate_scores, gate_results)):
                    chunk_type = chunks[idx]["data_type"]
                    status = "PASSED" if passed else "FILTERED"
                    print(f"[intelligent_retrieve_chunks]   Chunk {idx} ({chunk_type}): {score:.4f} - {status}")
                
                print(f"[intelligent_retrieve_chunks] Final selected chunks after gating: {len(final_selected)}")
                
                # If no chunks pass gating, try with a lower threshold
                if not final_selected and gate_scores:
                    max_score = max(gate_scores)
                    print(f"[intelligent_retrieve_chunks] No chunks passed gating (max score: {max_score:.4f}), trying with lower threshold")
                    lower_threshold = min(0.3, max_score * 0.8)  # Use 80% of max score or 0.3, whichever is lower
                    print(f"[intelligent_retrieve_chunks] Using lower threshold: {lower_threshold:.4f}")
                    gate_results_lower = [s >= lower_threshold for s in gate_scores]
                    final_selected = [i for i, ok in zip(selected_indices, gate_results_lower) if ok]
                    print(f"[intelligent_retrieve_chunks] Final selected chunks with lower threshold: {len(final_selected)}")
                    
                    # Log the new results
                    for i, (idx, score, passed) in enumerate(zip(selected_indices, gate_scores, gate_results_lower)):
                        chunk_type = chunks[idx]["data_type"]
                        status = "PASSED" if passed else "FILTERED"
                        print(f"[intelligent_retrieve_chunks]   Chunk {idx} ({chunk_type}): {score:.4f} - {status}")

                # 9) Retry if too few
                # Agentic refinement handoff: if too few, set state and branch in the graph
                min_required = max(N_MIN, min(N_MAX, len(chunks)))
                state.needs_refinement = len(final_selected) < min_required and state.retrieval_retry_attempts < RETRY_MAX
                
                print(f"[intelligent_retrieve_chunks] Retry check: {len(final_selected)} < {min_required} and attempts {state.retrieval_retry_attempts} < {RETRY_MAX}")
                
                if state.needs_refinement:
                    print(f"[intelligent_retrieve_chunks] Too few chunks selected ({len(final_selected)}), attempting refinement...")
                    try:
                        refinements = await self._refine_queries(state.user_prompt, [cast(str, chunks[i]["content"]) for i in final_selected])
                        print(f"[intelligent_retrieve_chunks] Generated {len(refinements)} refined queries: {refinements}")
                    except Exception as e:
                        print(f"[intelligent_retrieve_chunks] Refinement failed: {e}")
                        refinements = []
                    state.refined_queries = [r for r in refinements if r][:2]
                    state.retrieval_retry_attempts += 1
                    
                    # Set partial state for streaming decorator to show progress
                    state.retrieved_chunks = [cast(str, chunks[i]["content"]) for i in final_selected] if final_selected else []
                    state.chunk_analysis = {
                        "method": "bi_cross_mmr_gate_refining",
                        "dynamic_n": len(final_selected),
                        "selected_chunks": [f"chunk_{i}" for i in final_selected],
                        "total_chunks_processed": len(chunks),
                        "chunks_after_bi_encoder": len(initial_indices),
                        "chunks_after_cross_encoder": len(reranked),
                        "chunks_after_mmr": len(selected_indices),
                        "chunks_after_gating": len(final_selected),
                        "refinement_attempt": state.retrieval_retry_attempts,
                        "refined_queries": state.refined_queries
                    }
                    state.retrieval_reasoning = f"Refining search (attempt {state.retrieval_retry_attempts}) - too few chunks selected"
                    
                    print(f"[intelligent_retrieve_chunks] Setting up for retry with {len(state.refined_queries)} refined queries")
                    # Do not finalize retrieved_chunks yet; upstream conditional edge will loop
                    return state

                if not final_selected:
                    print("[intelligent_retrieve_chunks] No chunks passed gating, using fallback selection")
                    fallback_n = min(max(N_MIN, 1), len(reranked))
                    final_selected = [idx for idx, _ in reranked[:fallback_n]]
                    print(f"[intelligent_retrieve_chunks] Fallback selected {len(final_selected)} chunks: {final_selected}")

                # Log final selected chunks
                print(f"[intelligent_retrieve_chunks] Final selected chunks ({len(final_selected)}):")
                for i, idx in enumerate(final_selected):
                    chunk_type = chunks[idx]["data_type"]
                    chunk_preview = cast(str, chunks[idx]["content"])[:100]
                    print(f"[intelligent_retrieve_chunks]   {i+1}. Chunk {idx} ({chunk_type}): '{chunk_preview}...'")

                # Set state variables early so streaming decorator can access them
                state.retrieved_chunks = [cast(str, chunks[i]["content"]) for i in final_selected]
                state.chunk_analysis = {
                    "method": "bi_cross_mmr_gate",
                    "dynamic_n": len(final_selected),
                    "selected_chunks": [f"chunk_{i}" for i in final_selected],
                    "total_chunks_processed": len(chunks),
                    "chunks_after_bi_encoder": len(initial_indices),
                    "chunks_after_cross_encoder": len(reranked),
                    "chunks_after_mmr": len(selected_indices),
                    "chunks_after_gating": len(final_selected)
                }
                state.retrieval_reasoning = "Paraphrases + bi-encoder, cross-encoder rerank, MMR diversity, binary gating"
                
                print(f"[intelligent_retrieve_chunks] Retrieval complete: {len(state.retrieved_chunks)} chunks selected")
                print(f"[intelligent_retrieve_chunks] Chunk analysis: {state.chunk_analysis}")
            except Exception as e:
                print(f"[intelligent_retrieve_chunks] Error: {e}")
                state.retrieved_chunks = []
                state.chunk_analysis = {"method": "error", "reason": str(e)}
                return state

            return state

        async def _intelligent_retrieve_chunks_with_focus(state: FlowState, focus: str, focus_queries: List[str]) -> List[str]:
            """Helper function for focused retrieval with specific query variants."""
            try:
                print(f"[{focus}_retrieve] Starting focused retrieval for: {focus}")

                if not state.patient_ctx:
                    print(f"[{focus}_retrieve] No patient context available")
                    return []

                # Use existing chunking logic
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

                # Also chunk journal entries if available
                journal_chunks = []
                if state.journal_entries:
                    journal_chunks = await self._chunk_journal_entries(state.journal_entries, orchestrator, patient_id_str)

                all_chunks = produced + journal_chunks

                if not all_chunks:
                    print(f"[{focus}_retrieve] No chunks produced")
                    return []

                # Convert chunks to text
                chunks = [chunk.text for chunk in all_chunks]

                # Parallel embedding processing
                print(f"[{focus}_retrieve] Starting parallel embedding...")
                embedding_tasks = [
                    self._embed_many(chunks, mode="passage"),
                    self._embed_many([state.user_prompt] + focus_queries, mode="query")
                ]

                # Execute embeddings in parallel
                embedding_results = await asyncio.gather(*embedding_tasks)
                chunk_vecs, query_vecs = embedding_results
                all_queries = [state.user_prompt] + focus_queries

                print(f"[{focus}_retrieve] Parallel embedding complete: {len(chunk_vecs)} chunks, {len(query_vecs)} queries")

                # Bi-encoder scoring
                import numpy as np
                query_stack = np.stack(query_vecs, axis=0)
                chunk_stack = np.stack(chunk_vecs, axis=0)
                scores_matrix = np.dot(query_stack, chunk_stack.T)
                max_scores = np.max(scores_matrix, axis=0)

                # Get top chunks based on pre-stored classification
                n_class = 15  # Default for focused retrieval
                if state.query_classification:
                    if state.query_classification == "lookup":
                        n_class = 8
                    elif state.query_classification == "temporal-trend":
                        n_class = 20
                    elif state.query_classification == "comparative":
                        n_class = 25
                    elif state.query_classification in ["reasoning", "summary"]:
                        n_class = 30
                    elif state.query_classification == "guideline":
                        n_class = 12

                # Select top N chunks
                sorted_indices = np.argsort(max_scores)[::-1]
                top_indices = sorted_indices[:min(n_class, len(chunks))]

                # Parallel cross-encoder reranking for focused queries
                print(f"[{focus}_retrieve] Starting parallel cross-encoder reranking...")

                if len(all_queries) > 1 and len(top_indices) > 4:
                    # Use parallel processing for multiple queries and sufficient chunks
                    async def process_query_batch(query_batch, chunk_indices):
                        """Process a batch of queries against chunks in parallel."""
                        batch_pairs = []
                        for query in query_batch:
                            for idx in chunk_indices:
                                batch_pairs.append((query, chunks[idx]))

                        if batch_pairs:
                            return await self._cross_encoder.compute_similarity_scores(batch_pairs)
                        return []

                    # Optimized batching strategy based on cross-encoder capacity
                    # Aim for optimal batch sizes: 8-16 pairs per batch for best GPU utilization
                    OPTIMAL_BATCH_SIZE = 12
                    MAX_PARALLEL_BATCHES = 6

                    # Calculate optimal batch sizes
                    total_pairs = len(all_queries) * len(top_indices)
                    if total_pairs <= OPTIMAL_BATCH_SIZE:
                        # Small dataset: process all at once
                        parallel_tasks = [process_query_batch(all_queries, top_indices)]
                    else:
                        # Large dataset: create optimized batches
                        # Split chunks more granularly for better parallelization
                        chunk_size = max(3, len(top_indices) // MAX_PARALLEL_BATCHES)
                        chunk_batches = [top_indices[i:i+chunk_size] for i in range(0, len(top_indices), chunk_size)]

                        # Create tasks with balanced load
                        parallel_tasks = []
                        for c_batch in chunk_batches:
                            if len(c_batch) * len(all_queries) <= OPTIMAL_BATCH_SIZE:
                                # Batch small enough for all queries
                                parallel_tasks.append(process_query_batch(all_queries, c_batch))
                            else:
                                # Split queries for this chunk batch
                                query_size = max(1, OPTIMAL_BATCH_SIZE // len(c_batch))
                                query_batches = [all_queries[i:i+query_size] for i in range(0, len(all_queries), query_size)]
                                for q_batch in query_batches:
                                    parallel_tasks.append(process_query_batch(q_batch, c_batch))

                    # Limit total parallel tasks to prevent overload
                    if len(parallel_tasks) > MAX_PARALLEL_BATCHES:
                        print(f"[{focus}_retrieve] Limiting {len(parallel_tasks)} tasks to {MAX_PARALLEL_BATCHES} for stability")
                        parallel_tasks = parallel_tasks[:MAX_PARALLEL_BATCHES]

                    # Execute all batches in parallel with timeout
                    print(f"[{focus}_retrieve] Executing {len(parallel_tasks)} parallel cross-encoder batches")
                    try:
                        # Set reasonable timeout based on batch count (5 seconds per batch max)
                        timeout = min(30, max(10, len(parallel_tasks) * 5))
                        batch_results = await asyncio.wait_for(
                            asyncio.gather(*parallel_tasks, return_exceptions=True),
                            timeout=timeout
                        )
                    except asyncio.TimeoutError:
                        print(f"[{focus}_retrieve] Cross-encoder timeout after {timeout}s, using bi-encoder fallback")
                        final_indices = top_indices[:min(12, len(top_indices))]
                    except Exception as e:
                        print(f"[{focus}_retrieve] Cross-encoder parallel execution failed: {e}, using bi-encoder fallback")
                        final_indices = top_indices[:min(12, len(top_indices))]
                    else:
                        # Optimized result processing with error handling
                        cross_scores = []
                        successful_batches = 0

                        for i, result in enumerate(batch_results):
                            if isinstance(result, Exception):
                                print(f"[{focus}_retrieve] Cross-encoder batch {i} failed: {result}")
                                continue

                            if result:  # Non-empty result
                                cross_scores.extend(result)
                                successful_batches += 1

                        print(f"[{focus}_retrieve] Cross-encoder completed: {successful_batches}/{len(batch_results)} batches successful")

                        # Check if we have enough results for meaningful reranking
                        expected_scores = len(all_queries) * len(top_indices)
                        if cross_scores and len(cross_scores) >= expected_scores * 0.7:  # Allow 30% failure tolerance
                            try:
                                # Pad missing scores with average if needed
                                if len(cross_scores) < expected_scores:
                                    avg_score = sum(cross_scores) / len(cross_scores) if cross_scores else 0.5
                                    cross_scores.extend([avg_score] * (expected_scores - len(cross_scores)))

                                # Fast numpy processing
                                cross_scores_matrix = np.array(cross_scores[:expected_scores]).reshape(len(all_queries), len(top_indices))
                                max_cross_scores = np.max(cross_scores_matrix, axis=0)

                                # Re-rank based on cross-encoder scores
                                cross_sorted = np.argsort(max_cross_scores)[::-1]
                                final_indices = [top_indices[i] for i in cross_sorted[:min(12, len(top_indices))]]

                                print(f"[{focus}_retrieve] Cross-encoder reranking successful with {len(cross_scores)} scores")
                            except Exception as e:
                                print(f"[{focus}_retrieve] Cross-encoder result processing failed: {e}, using bi-encoder fallback")
                                final_indices = top_indices[:min(12, len(top_indices))]
                        else:
                            print(f"[{focus}_retrieve] Insufficient cross-encoder results ({len(cross_scores)}/{expected_scores}), using bi-encoder fallback")
                            final_indices = top_indices[:min(12, len(top_indices))]
                else:
                    # Fall back to sequential processing for small datasets
                    rerank_pairs = []
                    for query in all_queries:
                        for idx in top_indices:
                            rerank_pairs.append((query, chunks[idx]))

                    if rerank_pairs:
                        cross_scores = await self._cross_encoder.compute_similarity_scores(rerank_pairs)
                        cross_scores_matrix = np.array(cross_scores).reshape(len(all_queries), len(top_indices))
                        max_cross_scores = np.max(cross_scores_matrix, axis=0)
                        cross_sorted = np.argsort(max_cross_scores)[::-1]
                        final_indices = [top_indices[i] for i in cross_sorted[:min(12, len(top_indices))]]
                    else:
                        final_indices = top_indices[:min(12, len(top_indices))]

                print(f"[{focus}_retrieve] Cross-encoder reranking complete")

                # Return selected chunks
                selected_chunks = [chunks[i] for i in final_indices]
                print(f"[{focus}_retrieve] Selected {len(selected_chunks)} chunks for {focus}")

                return selected_chunks

            except Exception as e:
                print(f"[{focus}_retrieve] Error in focused retrieval: {e}")
                return []

        async def _fast_sbar_retrieve(state: FlowState, focus: str, queries: List[str]) -> List[str]:
            """Fast SBAR retrieval using only bi-encoder similarity (no cross-encoder)."""
            try:
                print(f"[_fast_sbar_retrieve] {focus} - Starting fast bi-encoder retrieval")

                # Get chunks from state - try multiple sources
                chunks = []
                if state.retrieved_chunks:
                    chunks = state.retrieved_chunks[:50]  # Use cached chunks if available
                    print(f"[_fast_sbar_retrieve] {focus} - Using {len(chunks)} cached chunks")
                else:
                    # Fall back to doing quick retrieval ourselves
                    print(f"[_fast_sbar_retrieve] {focus} - No cached chunks, doing quick retrieval")
                    if state.patient_ctx and state.journal_entries:
                        # Quick retrieval from journal entries (most relevant for SBAR)
                        for entry in state.journal_entries[:15]:  # Limit for speed
                            if hasattr(entry, 'content') and entry.content:
                                chunks.append(entry.content)
                            elif hasattr(entry, 'text') and entry.text:
                                chunks.append(entry.text)

                    if not chunks:
                        print(f"[_fast_sbar_retrieve] {focus} - No chunks available")
                        return []

                # Simple keyword-based retrieval for maximum speed
                scored_chunks = []
                for i, chunk in enumerate(chunks):
                    score = 0.0
                    chunk_lower = chunk.lower()

                    for query in queries:
                        query_words = query.lower().split()
                        for word in query_words:
                            if word in chunk_lower:
                                score += 1.0

                    if score > 0:
                        scored_chunks.append((score, chunk))

                # Sort by score and return top chunks
                scored_chunks.sort(key=lambda x: x[0], reverse=True)
                result_chunks = [chunk for _, chunk in scored_chunks[:15]]

                print(f"[_fast_sbar_retrieve] {focus} - Retrieved {len(result_chunks)} chunks using keyword matching")
                return result_chunks

            except Exception as e:
                print(f"[_fast_sbar_retrieve] {focus} - Error: {e}")
                return []

        async def _generate_sbar_queries(state: FlowState, sbar_component: str, focus_instruction: str) -> List[str]:
            """Generate focused queries for each SBAR component based on the user's original query."""
            try:
                print(f"[_generate_sbar_queries] Generating {sbar_component} queries from: '{state.user_prompt[:100]}...'")

                # Define SBAR component specific instructions
                component_prompts = {
                    "situation": "Current symptoms, vital signs, immediate presentation, active problems",
                    "background": "Medical history, past conditions, medications, family history, social history",
                    "assessment": "Clinical findings, lab results, diagnostic tests, professional observations",
                    "recommendation": "Treatment plans, medications, follow-up care, interventions, next steps"
                }

                prompt = f"""
Based on this user query: "{state.user_prompt}"

Generate 3 specific search queries focused on the {sbar_component.upper()} component of SBAR medical reporting.

{sbar_component.upper()} should focus on: {component_prompts.get(sbar_component, focus_instruction)}

Return only the 3 queries, one per line, without numbers or bullets.
Keep queries concise and medical terminology appropriate.
"""

                messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a medical information specialist generating focused search queries for SBAR components."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                response = await self._llm.chat(messages)

                # Parse response into individual queries
                queries = []
                for line in response.content.strip().split('\n'):
                    query = line.strip()
                    if query and not query.startswith(('1.', '2.', '3.', '-', '•')):
                        queries.append(query)

                if len(queries) < 3:
                    # Fallback queries if LLM didn't generate enough
                    fallback = {
                        "situation": ["current symptoms", "vital signs", "active problems"],
                        "background": ["medical history", "past conditions", "medications"],
                        "assessment": ["clinical findings", "test results", "observations"],
                        "recommendation": ["treatment plans", "medications", "follow-up care"]
                    }
                    queries.extend(fallback.get(sbar_component, ["medical information"])[:3-len(queries)])

                print(f"[_generate_sbar_queries] Generated {len(queries)} {sbar_component} queries: {queries}")
                return queries[:3]  # Limit to 3 queries

            except Exception as e:
                print(f"[_generate_sbar_queries] Error generating {sbar_component} queries: {e}")
                # Return fallback queries
                fallback_queries = {
                    "situation": ["current symptoms complaints", "vital signs measurements", "active problems"],
                    "background": ["medical history", "past conditions", "medications"],
                    "assessment": ["clinical findings", "test results", "observations"],
                    "recommendation": ["treatment plans", "medications", "follow-up"]
                }
                return fallback_queries.get(sbar_component, ["medical information"])

        @streaming_step("retrieve_situation_chunks")
        async def retrieve_situation_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on current patient situation (fast SBAR version)."""
            try:
                print("[retrieve_situation_chunks] Generating situation-focused queries from user prompt")

                # Generate SBAR-focused queries from the original user query
                situation_queries = await _generate_sbar_queries(state, "situation",
                    "Generate queries focused on the current patient situation and immediate concerns")

                chunks = await _fast_sbar_retrieve(state, "situation", situation_queries)
                state.sbar_situation_chunks = chunks[:10]  # Limit for speed
                print(f"[retrieve_situation_chunks] Retrieved {len(state.sbar_situation_chunks)} chunks")

            except Exception as e:
                print(f"[retrieve_situation_chunks] Error: {e}")
                state.sbar_situation_chunks = []

            return state

        @streaming_step("retrieve_background_chunks")
        async def retrieve_background_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on patient background and history (fast SBAR version)."""
            try:
                print("[retrieve_background_chunks] Generating background-focused queries from user prompt")

                # Generate SBAR-focused queries from the original user query
                background_queries = await _generate_sbar_queries(state, "background",
                    "Generate queries focused on patient medical history and background")

                chunks = await _fast_sbar_retrieve(state, "background", background_queries)
                state.sbar_background_chunks = chunks[:10]  # Limit for speed
                print(f"[retrieve_background_chunks] Retrieved {len(state.sbar_background_chunks)} chunks")

            except Exception as e:
                print(f"[retrieve_background_chunks] Error: {e}")
                state.sbar_background_chunks = []

            return state

        @streaming_step("retrieve_assessment_chunks")
        async def retrieve_assessment_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on clinical assessment data (fast SBAR version)."""
            try:
                print("[retrieve_assessment_chunks] Generating assessment-focused queries from user prompt")

                # Generate SBAR-focused queries from the original user query
                assessment_queries = await _generate_sbar_queries(state, "assessment",
                    "Generate queries focused on clinical assessment and diagnostic findings")

                chunks = await _fast_sbar_retrieve(state, "assessment", assessment_queries)
                state.sbar_assessment_chunks = chunks[:10]  # Limit for speed
                print(f"[retrieve_assessment_chunks] Retrieved {len(state.sbar_assessment_chunks)} chunks")

            except Exception as e:
                print(f"[retrieve_assessment_chunks] Error: {e}")
                state.sbar_assessment_chunks = []

            return state

        @streaming_step("retrieve_recommendation_chunks")
        async def retrieve_recommendation_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on treatment and recommendations (fast SBAR version)."""
            try:
                print("[retrieve_recommendation_chunks] Generating recommendation-focused queries from user prompt")

                # Generate SBAR-focused queries from the original user query
                recommendation_queries = await _generate_sbar_queries(state, "recommendation",
                    "Generate queries focused on treatment recommendations and next steps")

                chunks = await _fast_sbar_retrieve(state, "recommendation", recommendation_queries)
                state.sbar_recommendation_chunks = chunks[:10]  # Limit for speed
                print(f"[retrieve_recommendation_chunks] Retrieved {len(state.sbar_recommendation_chunks)} chunks")

            except Exception as e:
                print(f"[retrieve_recommendation_chunks] Error: {e}")
                state.sbar_recommendation_chunks = []

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

        @streaming_step("generate_sbar_situation")
        async def generate_sbar_situation(state: FlowState) -> FlowState:
            """Generate SBAR Situation component."""
            try:
                print("[generate_sbar_situation] Starting SBAR Situation generation")

                # Get situation-specific chunks
                situation_chunks = state.sbar_situation_chunks or []

                # Build prompt for situation
                situation_prompt = f"""
                Generate a CONCISE SBAR Situation summary (max 3-4 bullet points).

                USER QUERY: {state.user_prompt}

                FOCUS: Current patient status and immediate concerns.

                Include ONLY:
                • Chief complaint and onset
                • Key vital signs (if abnormal)
                • Current symptoms (most important)
                • Immediate concerns requiring attention

                Format: Short bullet points. No headers. Be clinical and direct.
                """

                messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a healthcare professional creating SBAR situation summaries. Focus on current patient status and immediate concerns."),
                    ChatMessage(role=ChatRole.USER, content=situation_prompt)
                ]

                # Add chunks if available
                if situation_chunks:
                    chunk_content = "Relevant patient information:\n" + "\n---\n".join(situation_chunks)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                # Generate response
                response = await self._llm.chat(messages)

                # Store in SBAR results
                state.sbar_situation_result = response.content.strip()

                print(f"[generate_sbar_situation] Generated situation summary: {len(response.content)} chars")

            except Exception as e:
                print(f"[generate_sbar_situation] Error: {e}")
                state.sbar_situation_result = f"Error generating situation summary: {str(e)}"

            return state

        @streaming_step("generate_sbar_background")
        async def generate_sbar_background(state: FlowState) -> FlowState:
            """Generate SBAR Background component."""
            try:
                print("[generate_sbar_background] Starting SBAR Background generation")

                # Get background-specific chunks
                background_chunks = state.sbar_background_chunks or []

                # Build prompt for background
                background_prompt = f"""
                Generate a CONCISE SBAR Background summary (max 3-4 bullet points).

                USER QUERY: {state.user_prompt}

                FOCUS: Essential patient history relevant to current situation.

                Include ONLY:
                • Relevant medical history/comorbidities
                • Current medications (key ones)
                • Known allergies
                • Recent significant events/treatments

                Format: Short bullet points. No headers. Be clinical and direct.
                """

                messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a healthcare professional creating SBAR background summaries. Focus on relevant patient history and context."),
                    ChatMessage(role=ChatRole.USER, content=background_prompt)
                ]

                # Add chunks if available
                if background_chunks:
                    chunk_content = "Relevant patient information:\n" + "\n---\n".join(background_chunks)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                # Generate response
                response = await self._llm.chat(messages)

                # Store in SBAR results
                state.sbar_background_result = response.content.strip()

                print(f"[generate_sbar_background] Generated background summary: {len(response.content)} chars")

            except Exception as e:
                print(f"[generate_sbar_background] Error: {e}")
                state.sbar_background_result = f"Error generating background summary: {str(e)}"

            return state

        @streaming_step("generate_sbar_assessment")
        async def generate_sbar_assessment(state: FlowState) -> FlowState:
            """Generate SBAR Assessment component."""
            try:
                print("[generate_sbar_assessment] Starting SBAR Assessment generation")

                # Get assessment-specific chunks
                assessment_chunks = state.sbar_assessment_chunks or []

                # Build prompt for assessment
                assessment_prompt = f"""
                Generate a CONCISE SBAR Assessment summary (max 3-4 bullet points).

                USER QUERY: {state.user_prompt}

                FOCUS: Clinical interpretation and professional judgment.

                Include ONLY:
                • Primary clinical impression/working diagnosis
                • Key clinical findings analysis
                • Risk level/severity assessment
                • Most likely differential diagnoses (if relevant)

                Format: Short bullet points. No headers. Be clinical and direct.
                """

                messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a healthcare professional creating SBAR assessment summaries. Focus on clinical analysis and professional interpretation."),
                    ChatMessage(role=ChatRole.USER, content=assessment_prompt)
                ]

                # Add chunks if available
                if assessment_chunks:
                    chunk_content = "Relevant patient information:\n" + "\n---\n".join(assessment_chunks)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                # Generate response
                response = await self._llm.chat(messages)

                # Store in SBAR results
                state.sbar_assessment_result = response.content.strip()

                print(f"[generate_sbar_assessment] Generated assessment summary: {len(response.content)} chars")

            except Exception as e:
                print(f"[generate_sbar_assessment] Error: {e}")
                state.sbar_assessment_result = f"Error generating assessment summary: {str(e)}"

            return state

        @streaming_step("generate_sbar_recommendation")
        async def generate_sbar_recommendation(state: FlowState) -> FlowState:
            """Generate SBAR Recommendation component."""
            try:
                print("[generate_sbar_recommendation] Starting SBAR Recommendation generation")

                # Get recommendation-specific chunks
                recommendation_chunks = state.sbar_recommendation_chunks or []

                # Build prompt for recommendation
                recommendation_prompt = f"""
                Generate a CONCISE SBAR Recommendation summary (max 3-4 bullet points).

                USER QUERY: {state.user_prompt}

                FOCUS: Essential next steps and actions.

                Include ONLY:
                • Most urgent intervention needed
                • Key diagnostic tests/monitoring
                • Important follow-up care
                • Specialist consultation (if needed)

                Format: Short bullet points. No headers. Be clinical and direct.
                IMPORTANT: Educational information only. Refer complex decisions to healthcare providers.
                """

                messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a healthcare professional creating SBAR recommendation summaries. Focus on actionable next steps while providing education, not specific treatments."),
                    ChatMessage(role=ChatRole.USER, content=recommendation_prompt)
                ]

                # Add chunks if available
                if recommendation_chunks:
                    chunk_content = "Relevant patient information:\n" + "\n---\n".join(recommendation_chunks)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                # Generate response
                response = await self._llm.chat(messages)

                # Store in SBAR results
                state.sbar_recommendation_result = response.content.strip()

                print(f"[generate_sbar_recommendation] Generated recommendation summary: {len(response.content)} chars")

            except Exception as e:
                print(f"[generate_sbar_recommendation] Error: {e}")
                state.sbar_recommendation_result = f"Error generating recommendation summary: {str(e)}"

            return state

        @streaming_step("merge_sbar_results")
        async def merge_sbar_results(state: FlowState) -> FlowState:
            """Merge parallel SBAR results and prepare final response."""
            try:
                print("[merge_sbar_results] All parallel SBAR components completed, merging results")

                # Collect results from separate fields
                sbar_results = {
                    "situation": state.sbar_situation_result,
                    "background": state.sbar_background_result,
                    "assessment": state.sbar_assessment_result,
                    "recommendation": state.sbar_recommendation_result
                }

                completed_components = [comp for comp, result in sbar_results.items() if result]
                print(f"[merge_sbar_results] Available components: {completed_components}")

                if not completed_components:
                    print("[merge_sbar_results] No SBAR results available")
                    state.llm_response = ChatMessage(
                        role=ChatRole.ASSISTANT,
                        content="Error: No SBAR results were generated"
                    )
                    return state

                # Create structured SBAR response for frontend cards
                import json

                structured_sbar = {
                    "type": "sbar_cards",
                    "components": {
                        "situation": {
                            "title": "Situation",
                            "content": sbar_results.get("situation", "Content generation failed").strip() or "Content generation failed",
                            "icon": "info-circle",
                            "color": "blue"
                        },
                        "background": {
                            "title": "Background",
                            "content": sbar_results.get("background", "Content generation failed").strip() or "Content generation failed",
                            "icon": "history",
                            "color": "green"
                        },
                        "assessment": {
                            "title": "Assessment",
                            "content": sbar_results.get("assessment", "Content generation failed").strip() or "Content generation failed",
                            "icon": "stethoscope",
                            "color": "orange"
                        },
                        "recommendation": {
                            "title": "Recommendation",
                            "content": sbar_results.get("recommendation", "Content generation failed").strip() or "Content generation failed",
                            "icon": "lightbulb",
                            "color": "purple"
                        }
                    }
                }

                # Create JSON response for frontend
                json_response = json.dumps(structured_sbar, indent=2)

                # Create response message with structured data
                state.llm_response = ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=json_response
                )

                print(f"[merge_sbar_results] Created structured SBAR response: {len(json_response)} chars")

            except Exception as e:
                print(f"[merge_sbar_results] Error merging SBAR results: {e}")
                # Fallback response
                import json
                fallback_sbar = {
                    "type": "sbar_cards",
                    "error": str(e),
                    "components": {
                        "situation": {"title": "Situation", "content": "Error generating content", "icon": "info-circle", "color": "blue"},
                        "background": {"title": "Background", "content": "Error generating content", "icon": "history", "color": "green"},
                        "assessment": {"title": "Assessment", "content": "Error generating content", "icon": "stethoscope", "color": "orange"},
                        "recommendation": {"title": "Recommendation", "content": "Error generating content", "icon": "lightbulb", "color": "purple"}
                    }
                }
                state.llm_response = ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=json.dumps(fallback_sbar, indent=2)
                )

            return state

        @streaming_step("sbar_parallel_dispatcher")
        async def sbar_parallel_dispatcher(state: FlowState) -> FlowState:
            """Dispatcher node that triggers parallel SBAR processing."""
            try:
                print("[sbar_parallel_dispatcher] Initiating parallel SBAR processing")

                # Initialize SBAR component fields if needed
                print("[sbar_parallel_dispatcher] SBAR fields initialized for parallel processing")

                # This node doesn't do much - it's just a dispatcher
                # The actual parallel work will happen in the parallel tasks
                print("[sbar_parallel_dispatcher] Dispatcher ready for parallel execution")

            except Exception as e:
                print(f"[sbar_parallel_dispatcher] Error in dispatcher: {e}")

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

Link policy (STRICT for EHR): When referencing patient data from clinical information chunks, preserve the source links that are embedded in the chunk content:
- For atomic data: Use the format "value [EHR Source](URL)" as it appears in the chunks
- For narrative data: Include the "**Source:** [EHR Record](URL)" information from the chunks
- If no source link is available, write "(from EHR, no link available)" immediately after the item
- NEVER remove or modify existing source links - they are essential for clinical traceability
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
                    print("[provide_information] Direct path - checking if retrieval needed")
                    print(f"[provide_information] Patient context available: {state.patient_ctx is not None}")
                    print(f"[provide_information] Retrieved chunks available: {len(state.retrieved_chunks) if state.retrieved_chunks else 0}")
                    
                    if state.patient_ctx and not state.retrieved_chunks:
                        print("[provide_information] Direct path - running intelligent retrieval for patient context")
                        # Populate retrieval using the new intelligent retrieval within this node
                        await intelligent_retrieve_chunks(state)
                        print(f"[provide_information] Direct path - retrieval complete, got {len(state.retrieved_chunks) if state.retrieved_chunks else 0} chunks")
                    else:
                        print(f"[provide_information] Direct path - no retrieval needed (patient_ctx: {state.patient_ctx is not None}, chunks: {len(state.retrieved_chunks) if state.retrieved_chunks else 0})")
            except Exception as e:
                print(f"[provide_information] Retrieval attempt failed on direct path: {e}")
                import traceback
                traceback.print_exc()


            # Add retrieved chunks (this is now the primary source of patient data)
            print(f"[provide_information] Retrieved chunks count: {len(state.retrieved_chunks) if state.retrieved_chunks else 0}")
            if state.retrieved_chunks:
                print(f"[provide_information] Adding {len(state.retrieved_chunks)} chunks to LLM context")
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
                
                # Log chunk previews
                for i, chunk in enumerate(state.retrieved_chunks):
                    print(f"[provide_information] Chunk {i+1} preview: '{chunk[:100]}...'")
                
                docs = ChatMessage(
                    role=ChatRole.USER,
                    content=f"{chunk_context}:{temporal_context}\n" + "\n---\n".join(state.retrieved_chunks),
                )
                messages.append(docs)
                print(f"[provide_information] Added chunks message to LLM context (total length: {len(docs.content)} chars)")

                # Include chunk analysis metadata for transparency
                if state.chunk_analysis and state.chunk_analysis.get("query_type"):
                    analysis_info = ChatMessage(
                        role=ChatRole.USER,
                        content=f"Query type identified: {state.chunk_analysis['query_type']}"
                    )
                    messages.append(analysis_info)
            else:
                print("[provide_information] No retrieved chunks available - LLM will rely on general knowledge and other context")

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

        @streaming_step("classify_query_intent")
        async def classify_query_intent(state: FlowState) -> FlowState:
            """Classify the query to determine if it should use SBAR flow or regular flow."""
            try:
                print(f"[classify_query_intent] Classifying query: '{state.user_prompt[:100]}...'")

                # Use the existing classifier
                classifier = self._zero_shot_classifier
                label = classifier.classify_query(state.user_prompt, [
                    "lookup", "temporal-trend", "comparative", "reasoning", "summary", "guideline"
                ])

                print(f"[classify_query_intent] Query classified as: {label}")

                # Store classification in state
                state.query_classification = label

                # Determine if this should use SBAR flow (big picture queries)
                sbar_query_types = ["summary", "comparative", "reasoning", "temporal-trend", "guideline"]
                state.is_sbar_flow = label in sbar_query_types

                print(f"[classify_query_intent] SBAR flow: {state.is_sbar_flow}")

                # Initialize SBAR cache if using SBAR flow
                if state.is_sbar_flow:
                    state.sbar_retrieval_cache = {}

            except Exception as e:
                print(f"[classify_query_intent] Classification failed: {e}, defaulting to regular flow")
                state.query_classification = "lookup"  # Default fallback
                state.is_sbar_flow = False

            return state

        def requires_full_processing(state: FlowState) -> bool:
            """Conditional function to determine if full processing is needed."""
            return getattr(state, 'requires_full_processing', True)

        def is_sbar_flow(state: FlowState) -> bool:
            """Conditional function to determine if SBAR flow should be used."""
            return getattr(state, 'is_sbar_flow', False)

        def check_patient_exists(state: FlowState) -> FlowState:
            """Check if patient_id is provided in the state."""
            # This node doesn't need to do anything - just pass through
            return state

        def has_patient(state: FlowState) -> bool:
            return state.patient_id is not None and state.patient_id.strip() != ""
            
        def needs_refinement(state: FlowState) -> bool:
            return getattr(state, 'needs_refinement', False)


        _builder = StateGraph(FlowState)
        _builder.add_node("check_patient", check_patient_exists)  # New decision node
        _builder.add_node("load_user_context", load_user_context)  # Load user context if available
        _builder.add_node("evaluate_query_complexity", evaluate_query_complexity)
        _builder.add_node("classify_query_intent", classify_query_intent)
        _builder.add_node("store_user_message", store_user_message)
        _builder.add_node("load_current_session_history", load_current_session_history)
        _builder.add_node("search_cross_session_history", search_cross_session_history)
        _builder.add_node("fetch_patient", fetch_patient)
        _builder.add_node("fetch_pdfs", fetch_pdfs)
        _builder.add_node("store_patient_chunks", store_patient_chunks)
        _builder.add_node("intelligent_retrieve_chunks", intelligent_retrieve_chunks)
        # SBAR parallel retrieval nodes
        _builder.add_node("retrieve_situation_chunks", retrieve_situation_chunks)
        _builder.add_node("retrieve_background_chunks", retrieve_background_chunks)
        _builder.add_node("retrieve_assessment_chunks", retrieve_assessment_chunks)
        _builder.add_node("retrieve_recommendation_chunks", retrieve_recommendation_chunks)
        # SBAR parallel generation nodes
        _builder.add_node("generate_sbar_situation", generate_sbar_situation)
        _builder.add_node("generate_sbar_background", generate_sbar_background)
        _builder.add_node("generate_sbar_assessment", generate_sbar_assessment)
        _builder.add_node("generate_sbar_recommendation", generate_sbar_recommendation)
        _builder.add_node("merge_sbar_results", merge_sbar_results)
        _builder.add_node("sbar_parallel_dispatcher", sbar_parallel_dispatcher)
        _builder.add_node("evaluate_web_search_need", evaluate_web_search_need)
        _builder.add_node("perform_web_search", perform_web_search)
        _builder.add_node("provide_information", provide_information)
        _builder.add_node("store_assistant_response", store_assistant_response)

        _builder.set_entry_point("load_user_context")  # Start with loading user context

        # Add edges for user context loading and classification
        _builder.add_edge("load_user_context", "evaluate_query_complexity")
        _builder.add_edge("evaluate_query_complexity", "classify_query_intent")
        _builder.add_edge("classify_query_intent", "store_user_message")
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
                False: "fetch_pdfs"  # No patient ID -> fetch general PDFs, then continue
            }
        )

        # PATIENT PROCESSING PATH (only when patient_id exists)
        # Always fetch PDFs after fetching patient data
        _builder.add_edge("fetch_patient", "fetch_pdfs")

        # Route after fetching PDFs - different paths for patient vs general mode
        def route_after_pdfs(state: FlowState) -> str:
            if has_patient(state):
                # Patient mode: proceed with patient flow
                if is_sbar_flow(state):
                    return "intelligent_retrieve_chunks"
                else:
                    return "intelligent_retrieve_chunks"
            else:
                # General mode: proceed directly to chunk retrieval
                return "intelligent_retrieve_chunks"

        _builder.add_conditional_edges(
            "fetch_pdfs",
            route_after_pdfs,
            {
                "intelligent_retrieve_chunks": "intelligent_retrieve_chunks"
            }
        )

        # Sequential SBAR execution to avoid concurrent state updates
        _builder.add_edge("sbar_parallel_dispatcher", "retrieve_situation_chunks")

        # Sequential retrieval and generation chain
        _builder.add_edge("retrieve_situation_chunks", "generate_sbar_situation")
        _builder.add_edge("generate_sbar_situation", "retrieve_background_chunks")
        _builder.add_edge("retrieve_background_chunks", "generate_sbar_background")
        _builder.add_edge("generate_sbar_background", "retrieve_assessment_chunks")
        _builder.add_edge("retrieve_assessment_chunks", "generate_sbar_assessment")
        _builder.add_edge("generate_sbar_assessment", "retrieve_recommendation_chunks")
        _builder.add_edge("retrieve_recommendation_chunks", "generate_sbar_recommendation")

        # Final generation node goes to merge
        _builder.add_edge("generate_sbar_recommendation", "merge_sbar_results")

        # SBAR merge to store response (skip web search for now in SBAR flow)
        _builder.add_edge("merge_sbar_results", "store_assistant_response")

        # Route after chunk retrieval: check if SBAR flow
        def route_after_chunks(state):
            if hasattr(state, 'is_sbar_flow') and state.is_sbar_flow:
                return "sbar_parallel_dispatcher"
            elif hasattr(state, 'needs_refinement') and state.needs_refinement:
                return "intelligent_retrieve_chunks"
            else:
                return "evaluate_web_search_need"

        _builder.add_conditional_edges(
            "intelligent_retrieve_chunks",
            route_after_chunks,
            {
                "sbar_parallel_dispatcher": "sbar_parallel_dispatcher",
                "intelligent_retrieve_chunks": "intelligent_retrieve_chunks",
                "evaluate_web_search_need": "evaluate_web_search_need"
            }
        )
        _builder.add_conditional_edges(
            "evaluate_web_search_need",
            needs_web_search,
            {
                True: "perform_web_search",
                False: "provide_information"
            }
        )

        # Agentic refinement: loop back to intelligent_retrieve_chunks if needed
        

        _builder.add_edge("perform_web_search", "provide_information")
        _builder.add_edge("provide_information", "store_assistant_response")
        _builder.add_edge("store_assistant_response", END)

        return _builder.compile()

    def _format_ehr_links(self, text: str) -> str:
        """Convert bare URLs to markdown hyperlinks to ensure clickability.

        If a URL is already embedded in [title](url) format, it is not modified.
        This method works with the new chunk format that embeds source links.
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
            # For bare URLs, create a generic EHR record link
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
    # Journal entry chunking
    # =========================
    async def _chunk_journal_entries(self, journal_entries: List[JournalEntry], orchestrator: ChunkingOrchestrator, patient_id_str: str) -> List[Chunk]:
        """Chunk journal entries using the narrative strategy."""
        from optimed.core.domain import Record
        from optimed.adapters.chunking.strategies.narrative_v1 import NarrativeV1
        from optimed.adapters.outbound.tokenizer.whitespace_tokenizer import WhitespaceTokenizer
        from optimed.adapters.outbound.phi_redactor.simple_redactor import SimplePhiRedactor
        from optimed.core.services.hash_utils import stable_hash
        
        if not journal_entries:
            return []
        
        # Create records from journal entries
        records = []
        pseudo_patient = stable_hash({"pid": patient_id_str}, namespace="patient")
        
        for entry in journal_entries:
            # Create a comprehensive text representation of the journal entry
            journal_text = f"""
Journal Entry: {entry.title}
Type: {entry.entry_type.value}
Author: {entry.author_name} ({entry.author_role})
Date: {entry.created_at.strftime('%Y-%m-%d %H:%M')}
Patient ID: {patient_id_str}

Content:
{entry.content}
"""
            
            record = Record(
                patient_ref=pseudo_patient,
                encounter_ref=None,
                resource_type="journal_entry",
                key=entry.entry_id,
                text=journal_text.strip(),
                timestamp=entry.created_at,
            )
            records.append(record)
        
        # Use narrative strategy to chunk the journal entries
        tokenizer = WhitespaceTokenizer()
        redactor = SimplePhiRedactor()
        strategy = NarrativeV1()
        
        # Get narrative policy from the orchestrator's policies
        policy = CHUNK_POLICY_PRESETS.get("narrative_default")
        if not policy:
            # Fallback policy if narrative_default is not available
            from optimed.core.domain import ChunkPolicy
            policy = ChunkPolicy(
                name="journal_fallback",
                max_tokens=512,
                overlap=0.1
            )
        
        # Apply redaction to records
        redacted_records = []
        for record in records:
            redacted_text = redactor.redact(record.text or "")
            redacted_record = record.model_copy(update={"text": redacted_text})
            redacted_records.append(redacted_record)
        
        # Apply chunking strategy
        chunks = strategy.apply(redacted_records, policy, tokenizer)
        
        print(f"[_chunk_journal_entries] Created {len(chunks)} chunks from {len(journal_entries)} journal entries")
        
        return chunks

    async def _chunk_pdf_documents(self, pdf_documents: List[PDFDocument], orchestrator: ChunkingOrchestrator, patient_id_str: Optional[str]) -> List[Chunk]:
        """Chunk PDF documents using the narrative strategy."""
        from optimed.core.domain import Record
        from optimed.adapters.chunking.strategies.narrative_v1 import NarrativeV1
        from optimed.adapters.outbound.tokenizer.whitespace_tokenizer import WhitespaceTokenizer
        from optimed.adapters.outbound.phi_redactor.simple_redactor import SimplePhiRedactor
        from optimed.core.services.hash_utils import stable_hash

        if not pdf_documents:
            return []

        # Create records from PDF documents
        records = []

        for pdf in pdf_documents:
            if not pdf.extracted_text:
                continue

            # Create a comprehensive text representation of the PDF document
            metadata_text = ""
            if pdf.metadata.title:
                metadata_text += f"Title: {pdf.metadata.title}\n"
            if pdf.metadata.author:
                metadata_text += f"Author: {pdf.metadata.author}\n"
            if pdf.metadata.subject:
                metadata_text += f"Subject: {pdf.metadata.subject}\n"

            pdf_text = f"""
PDF Document: {pdf.get_display_name()}
Filename: {pdf.filename}
{metadata_text}
Uploaded by User: {pdf.user_id}
Upload Date: {pdf.uploaded_at.strftime('%Y-%m-%d %H:%M')}
{f"Patient ID: {pdf.patient_id}" if pdf.patient_id else "General Document (No Patient Association)"}

Content:
{pdf.extracted_text}
"""

            # Use appropriate patient reference
            if pdf.patient_id:
                pseudo_patient = stable_hash({"pid": pdf.patient_id}, namespace="patient")
            else:
                pseudo_patient = stable_hash({"uid": pdf.user_id}, namespace="user")

            record = Record(
                patient_ref=pseudo_patient,
                encounter_ref=None,
                resource_type="pdf_document",
                resource_id=pdf.document_id,
                text=pdf_text
            )
            records.append(record)

        if not records:
            return []

        # Apply redaction and chunking
        tokenizer = WhitespaceTokenizer()
        redactor = SimplePhiRedactor()
        strategy = NarrativeV1()
        policy = CHUNK_POLICY_PRESETS.get("narrative")

        redacted_records = []
        for record in records:
            redacted_text = redactor.redact(record.text or "")
            redacted_record = record.model_copy(update={"text": redacted_text})
            redacted_records.append(redacted_record)

        # Apply chunking strategy
        chunks = strategy.apply(redacted_records, policy, tokenizer)

        print(f"[_chunk_pdf_documents] Created {len(chunks)} chunks from {len(pdf_documents)} PDF documents")

        return chunks

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
        from typing import cast, Literal
        mode_literal = cast(Literal["query", "passage"], mode)
        tasks = [embed(t or "", mode_literal) for t in texts]
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

    def _compute_dynamic_n(self, query: str, scores: list[float], pre_classification: str = None) -> int:
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

        # Use pre-stored classification if available, otherwise classify
        try:
            if pre_classification:
                label = pre_classification
                print(f"[_compute_dynamic_n] Using pre-stored classification: {label}")
            else:
                classifier = self._zero_shot_classifier
                label = classifier.classify_query(query, [
                    "lookup", "temporal-trend", "comparative", "reasoning", "summary", "guideline"
                ])
                print(f"[_compute_dynamic_n] Query classified as: {label}")

            if label == "lookup":
                n_class = min(8, N_MAX)        # ~5–8
            elif label == "temporal-trend":
                n_class = min(20, N_MAX)       # ~12–20
            elif label == "comparative":
                n_class = min(28, N_MAX)       # ~18–28
            elif label == "reasoning":
                n_class = min(30, N_MAX)       # ~25–40, capped at 30
            elif label == "summary":
                n_class = min(30, N_MAX)       # ~40–80, capped at 30
            elif label == "guideline":
                n_class = min(12, N_MAX)       # ~6–12
            else:
                n_class = 8  # Default fallback
        except Exception as e:
            print(f"[_compute_dynamic_n] Classification failed: {e}, using heuristic fallback")
            n_class = self._classify_query(query)
        
        n = max(min(n_elbow, n_thresh), n_class)
        return max(N_MIN, min(N_MAX, n))

    def _classify_query(self, query: str) -> int:
        """Heuristic fallback for when MultilingualZeroShotClassifier fails."""
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
                        
            except Exception as e:
                if graph_task and not graph_task.done():
                    graph_task.cancel()
                # Check if the graph task also failed and retrieve its exception
                if graph_task and graph_task.done() and not graph_task.cancelled():
                    try:
                        graph_task.result()  # This will raise the exception if the task failed
                    except Exception as task_exception:
                        # If the task exception is different from the current exception, 
                        # it might be more specific (like the ReadError)
                        if not isinstance(e, type(task_exception)):
                            raise task_exception from e
                raise
            finally:
                # Ensure we retrieve any task exception to prevent "Task exception was never retrieved" warnings
                if graph_task and graph_task.done() and not graph_task.cancelled():
                    try:
                        graph_task.result()  # This will raise the exception if the task failed
                    except Exception as task_exception:
                        # Log the task exception but don't re-raise it since we're in finally
                        import logging
                        logging.error(f"Graph task failed with exception: {task_exception}")

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

    
