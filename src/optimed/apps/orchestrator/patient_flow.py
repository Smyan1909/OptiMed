from __future__ import annotations
from .streaming_decorators import streaming_step
from .streaming_llm import StreamingLLMWrapper

import uuid 
import json
import time
import asyncio
import re
from typing import List, Any, Union, AsyncGenerator, Optional
from datetime import datetime

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from optimed.core.domain import PatientContext, ChatMessage, DiagnosisResult, ChatRole, UserAction, User, WebSearchResponse, GeneratedImage, ImageGenerationContext, WebSearchInfo, CrossSessionHistoryInfo, GeneratedImageInfo, DifferentialDiagnosis
from optimed.core.lang import detect_language_code

from optimed.core.ports import DiagnosticEngine, FHIRRepository, LLMClient, VectorStore, UserRepository, WebSearchService, ImageGenerationService, GeneratedImageRepository

from optimed.apps.orchestrator.connection_service import UserEHRConnectionService

from optimed.embeddings.minilm import embed
from optimed.embeddings.service import embed_and_store



SYSTEM_MSG_PRE_MEET = ChatMessage(role=ChatRole.SYSTEM, 
                         content="""You are CLARA, a clinical pre‑visit preparation assistant.

                                    General response guideline (apply only when helpful for the current question):
                                    - Keep responses concise yet complete (aim for 3–5 short sections or 8–15 bullets; expand only if complexity requires).
                                    - Always answer in standard Markdown.
                                      • If you create sections, start lines with '## ' for section headers and '### ' for subheaders.
                                      • Put a blank line before and after each header.
                                      • Do not simulate headers with numbers or bold; do not place headers inside list items.
                                      • Prefer bullet lists for checklists and action items; use tables for compact comparisons.
                                    - Link policy (STRICT for EHR): For every EHR-derived item you mention (vital, lab value, medication, allergy, diagnosis, imaging finding, date, encounter, note), include a clickable markdown link immediately after that specific item, within the same sentence, e.g., "HbA1c 8.1% (2024‑04‑02) [EHR](URL)" or "lisinopril 10 mg daily [Meds](URL)". Do this for each individual item you list. Do not group EHR links in a separate Sources section.
                                      • If multiple EHR items appear in one sentence, each item must have its own adjacent link.
                                      • If no URL is available, write "(from EHR, no link available)" immediately after the item.
                                    - Match the user's language. Avoid boilerplate and preambles.

                                    Pre‑visit focus (use any subset that fits):
                                    - Key Facts (recent vitals, meds, allergies, notable history) with EHR links.
                                    - Issues To Address Today (prioritized list).
                                    - Questions/Checklist for the visit.
                                    - Next Steps / Coordination.
                                    """)

SYSTEM_MSG_POST_MEET = ChatMessage(role=ChatRole.SYSTEM, 
                         content="""You are CLARA, a post‑encounter clinical analysis assistant.

                                    General response guideline (apply only when helpful for the current question):
                                    - Aim for 3–6 compact sections or 8–15 bullets; be clear and avoid verbosity.
                                    - Always answer in standard Markdown.
                                      • If you create sections, start lines with '## ' for section headers and '### ' for subheaders.
                                      • Put a blank line before and after each header.
                                      • Do not simulate headers with numbers or bold; do not place headers inside list items.
                                      • Use bullets/tables for clarity.
                                    - Link policy (STRICT for EHR): For every EHR-derived item you mention (vital, lab value, medication, allergy, diagnosis, imaging finding, date, encounter, note), include a clickable markdown link immediately after that specific item, within the same sentence, e.g., "HbA1c 8.1% (2024‑04‑02) [EHR](URL)" or "lisinopril 10 mg daily [Meds](URL)". Do this for each individual item you list. Do not group EHR links in a separate Sources section.
                                      • If multiple EHR items appear in one sentence, each item must have its own adjacent link.
                                      • If no URL is available, write "(from EHR, no link available)" immediately after the item.
                                    - Use all available information (EHR, exams, history). Match the user's language.

                                    Suggested sections (use any subset that fits):
                                    - Clinical Assessment
                                    - Differential Diagnoses (≤5, brief evidence)
                                    - Plan / Orders
                                    - Follow‑up
                                    - Sources
                                    """)

SYSTEM_MSG_RESEARCH = ChatMessage(role=ChatRole.SYSTEM, 
                         content="""You are CLARA, a clinical research assistant for complex or atypical cases.

                                    General response guideline (apply only when helpful for the current question):
                                    - Provide rich, well‑supported but focused analysis (3–6 sections); avoid unnecessary length.
                                    - Always answer in standard Markdown.
                                      • If you create sections, use '## ' headers and '### ' subheaders with blank lines around them.
                                      • Prefer bullets/tables for comparisons and evidence summaries.
                                    - Link policy: cite web sources inline as [Title](URL). For EHR-derived items, include a clickable markdown link immediately after each specific item, e.g., "CT chest (2024‑03‑12) [Imaging](URL)"; if no URL is available, add "(from EHR, no link available)". Do not group EHR links only at the end; each item must be linked inline.

                                    Suggested sections (choose as needed):
                                    - Clinical Question / Context
                                    - Evidence Summary (with key citations)
                                    - Differential / Options
                                    - Recommendations / Considerations
                                    - Sources
                                    """)

SYSTEM_MSG_CHAT = ChatMessage(role=ChatRole.SYSTEM, 
                         content="""You are CLARA, a clinical chat companion.
                         
                                    General response guideline (apply only when helpful for the current question):
                                    - Provide a helpful, medium‑length reply (more than a short paragraph, less than an essay).
                                    - Always answer in standard Markdown.
                                      • If you create sections, use '## ' headers and '### ' subheaders with blank lines around them.
                                      • Prefer bullets for enumerations.
                                    - Reference prior chat context when relevant.
                                    - Link policy (STRICT for EHR): For every EHR-derived item you mention, add a clickable markdown link immediately after that item, within the same sentence, e.g., "allergy: penicillin [Allergies](URL)". If no URL is available, add "(from EHR, no link available)". Do not group EHR links only at the end.
                                    - Match the user's language and tone.
                                    """)
                                    

class FlowState(BaseModel):
    """Minimal LangGraph state."""
    patient_id: str | None = None
    user_prompt: str
    primary_icd: str = ""
    differential: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    parsed_response: Optional[DiagnosisResult] = None

    patient_ctx: PatientContext | None = None
    retrieved_chunks: List[str] = Field(default_factory=list)

    chunk_analysis: dict[str, Any] = Field(default_factory=dict)
    filtered_chunks: List[dict[str, Any]] = Field(default_factory=list)
    retrieval_reasoning: str = ""

    requires_full_processing: bool = True  # New field

    llm_response: ChatMessage | None = None

    retrieved_web: List[str] = Field(default_factory=list)
    web_search_response: Optional[WebSearchResponse] = None
    web_search_performed: bool = False

    # Add diagnostic mode
    diagnostic_mode: str = "post_meet"  # "pre_meet", "post_meet", "research", "chat"
    chat_mode: bool = False # Keep for backward compatibility
    should_parse_icd_codes: bool = False
    chat_history: List[ChatMessage] = Field(default_factory=list)

    needs_cross_session_search: bool = False
    relevant_cross_session_history: List[dict] = Field(default_factory=list)

    user_id: str | None = None
    user_context: User | None = None
    session_id: str | None = None

    # Image generation fields
    image_generation_needed: bool = False
    image_generation_prompt: str = ""
    generated_image: Optional[GeneratedImage] = None
    image_generation_context: Optional[ImageGenerationContext] = None

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
    total_steps: int = 10
    completed_steps: int = 0
    streaming_updates: List[dict] = Field(default_factory=list)

    # Streaming diagnosis updates
    prelim_diagnosis_name: str = ""
    diff_diag_compute_step: str = ""

    should_stream_response: bool = False  # New field to control streaming behavior
    streaming_response: str = ""  # Accumulated response during streaming
    stream_callback: Optional[Any] = None  # Callback for streaming updates


class LangGraphDiagnosticEngine(DiagnosticEngine):
    """Concrete engine that streams or returns full result."""

    def __init__(self, fhir_repo: FHIRRepository, 
                 vector_store: VectorStore, 
                 llm_client: LLMClient, 
                 user_repo: UserRepository, 
                 connection_service: UserEHRConnectionService, 
                 web_search_service: WebSearchService,
                 image_generation_service: ImageGenerationService | None = None,
                 generated_image_repo: GeneratedImageRepository | None = None, 
                 default_prompt: str = "Provide the most likely diagnosis"):
        self._fhir = fhir_repo
        self._vec = vector_store
        self._llm = llm_client
        self._streaming_llm = StreamingLLMWrapper(llm_client=llm_client)

        self._user_repo = user_repo
        self._connection_service = connection_service
        self._web_search = web_search_service
        self._default_prompt = default_prompt
        self._image_generation = image_generation_service
        self._generated_image_repo = generated_image_repo

        self._compiled_graph = self._build_graph()

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
            """Evaluate if web search is needed based on diagnostic mode."""
            try:
                # Research mode always needs web search for comprehensive analysis
                if state.diagnostic_mode == "research":
                    state.web_search_performed = True
                    print("[web_search] Research mode: Web search automatically enabled")
                    return state
                
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
                print(f"[web_search] Mode {state.diagnostic_mode}: Web search needed: {needs_search}")
                
            except Exception as e:
                print(f"[web_search] Error evaluating search need: {e}")
                # Default to web search for research mode even on error
                state.web_search_performed = (state.diagnostic_mode == "research")
            
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
                    active_lang = detect_language_code(search_query or "")
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

        # Image generation disabled in this flow to reduce compute time

        @streaming_step("load_current_session_history")
        async def load_current_session_history(state: FlowState) -> FlowState:
            """Load chat history for the patient if available."""
            print(f"[load_current_session_history] Loading for patient_id={state.patient_id}, session_id={state.session_id}")

            if state.patient_id and state.session_id:
                try:
                    # Get history for this specific session
                    history_data = await self._vec.get_chat_history(
                        patient_id=str(state.patient_id), 
                        session_id=state.session_id,
                        limit=20
                    )
                    print(f"[load_current_session_history] Retrieved {len(history_data)} messages")

                    chat_messages = []
                    
                    for item in history_data:
                        try:
                            role = ChatRole(item.get("role", "user"))
                            content = item.get("content", "")
                            chat_messages.append(ChatMessage(role=role, content=content))
                        except Exception as e:
                            print(f"[load_current_session_history] Error parsing item: {e}")
                            continue
                            
                    state.chat_history = chat_messages
                except Exception as e:
                    print(f"[load_current_session_history] Error loading chat history: {e}")
                    state.chat_history = []
            else:
                try:
                    # Get history for this specific session
                    history_data = await self._vec.get_chat_history(
                        patient_id="general_chat", 
                        session_id=state.session_id,
                        limit=20
                    )
                    print(f"[load_current_session_history] Retrieved {len(history_data)} messages")

                    chat_messages = []
                    
                    for item in history_data:
                        try:
                            role = ChatRole(item.get("role", "user"))
                            content = item.get("content", "")
                            chat_messages.append(ChatMessage(role=role, content=content))
                        except Exception as e:
                            print(f"[load_current_session_history] Error parsing item: {e}")
                            continue
                            
                    state.chat_history = chat_messages
                except Exception as e:
                    print(f"[load_current_session_history] Error loading chat history: {e}")
                    state.chat_history = []

            return state
        

        @streaming_step("evaluate_cross_session_history_need")
        async def evaluate_cross_session_history_need(state: FlowState) -> FlowState:
            """Evaluate if cross-session chat history would be helpful for context."""
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
                    # Still proceed to check for new journal entries
                else:
                    print(f"[store_chunks] Creating new chunks for patient {patient_id}")
                
                # Break down patient context into meaningful chunks
                patient_data = state.patient_ctx
                
                # 1. Demographics chunk (only if no existing chunks)
                if not existing_chunks:
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
                    
                    # 2. Vitals chunk (if available)
                    if patient_data.vitals:
                        vitals_text = f"""
                        Patient Vitals for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.vitals.items()])}
                        """
                        
                        await embed_and_store(
                            namespace="clinical",
                            object_type="Vitals",
                            object_id=f"{patient_id}_vitals",
                            text={"content": vitals_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "vitals",
                                "timestamp": str(int(time.time() * 1000))
                            }
                        )
                    
                    # 3. Labs chunk (if available)
                    if patient_data.labs:
                        labs_text = f"""
                        Laboratory Results for {patient_data.name} (ID: {patient_id}):
                        {chr(10).join([f"{key}: {value}" for key, value in patient_data.labs.items()])}
                        """
                        
                        await embed_and_store(
                            namespace="clinical",
                            object_type="Labs",
                            object_id=f"{patient_id}_labs",
                            text={"content": labs_text.strip()},
                            metadata={
                                "patient_id": patient_id,
                                "data_type": "labs",
                                "timestamp": str(int(time.time() * 1000))
                            }
                        )
                    
                    # 4. Complete patient context as a single chunk for fallback
                    complete_context = patient_data.model_dump_json(indent=2)
                    await embed_and_store(
                        namespace="clinical",
                        object_type="PatientContext",
                        object_id=f"{patient_id}_complete",
                        text={"content": f"Complete patient context for {patient_data.name} (ID: {patient_id}):\n{complete_context}"},
                        metadata={
                            "patient_id": patient_id,
                            "data_type": "complete_context",
                            "timestamp": str(int(time.time() * 1000))
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
                        
                        # Store each journal entry as a separate chunk
                        for entry in journal_entries:
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
                                    "created_at": entry.created_at.isoformat(),
                                    "timestamp": str(int(entry.created_at.timestamp() * 1000))
                                }
                            )
                        
                        print(f"[store_chunks] Successfully stored {len(journal_entries)} journal entries")
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
            """Intelligently retrieve and filter chunks based on LLM analysis with recency-aware filtering."""
            
            try:
                # Step 1: Initial similarity search (broader search)
                if state.patient_id:
                    q_vec = await embed(state.user_prompt, "query")
                    rows = await self._vec.similarity_search(
                        q_vec,
                        top_k=20,  # Increased to accommodate recency filtering
                        filter_={
                            "namespace": "clinical", 
                            "patient_id": str(state.patient_id)
                        },
                    )
                else:
                    rows = []

                if not rows and state.patient_ctx:
                    # Fallback to patient context
                    print("[intelligent_retrieve_chunks] fallback to patient context as no chunks found")
                    state.retrieved_chunks = [state.patient_ctx.model_dump_json(indent=2)]
                    state.chunk_analysis = {"method": "fallback", "reason": "No chunks found, using patient context"}
                    return state
                elif not rows and not state.patient_ctx:
                    print("[intelligent_retrieve_chunks] No chunks found and no patient context available")
                    state.retrieved_chunks = []
                    state.chunk_analysis = {"method": "fallback", "reason": "No chunks found and no patient context available"}
                    return state

                # Step 2: Apply recency-based filtering and prepare chunks
                current_time = time.time() * 1000  # Current time in milliseconds
                candidate_chunks = []
                
                # Define recency thresholds for different data types (in milliseconds)
                # Only vitals, labs, and medications have time-based filtering
                recency_thresholds = {
                    "vitals": 7 * 24 * 60 * 60 * 1000,        # 7 days - vitals change frequently
                    "labs": 14 * 24 * 60 * 60 * 1000,         # 14 days - lab values change regularly
                    "medications": 90 * 24 * 60 * 60 * 1000,   # 90 days - medication changes less frequent
                    "journal_entry": float('inf'),              # Always relevant - clinical notes don't expire
                    "demographics": float('inf'),               # Always relevant
                    "allergies": float('inf'),                  # Always relevant
                    "family_history": float('inf'),             # Always relevant
                    "immunizations": float('inf'),              # Always relevant
                    "complete_context": float('inf'),           # Always relevant as fallback
                    "unknown": float('inf')                     # Default to always relevant for unknown types
                }
                
                for i, row in enumerate(rows):
                    try:
                        # rows are (id, similarity, content)
                        chunk_text = row[2] if len(row) > 2 else row[1]
                        similarity_score = row[1] if len(row) > 1 else 0.0
                        
                        # Extract metadata if available (for data type identification)
                        metadata: dict[str, Any] = row[3] if len(row) > 3 else {}
                        data_type = metadata.get("data_type", "unknown") if isinstance(metadata, dict) else "unknown"
                        
                        # Get timestamp for recency evaluation
                        timestamp_str = metadata.get("timestamp") if isinstance(metadata, dict) else None
                        chunk_timestamp = None
                        is_recent = True  # Default to True for chunks without timestamps
                        days_old = None
                        
                        if timestamp_str:
                            try:
                                chunk_timestamp = int(timestamp_str)
                                time_diff = current_time - chunk_timestamp
                                threshold = recency_thresholds.get(data_type, recency_thresholds["unknown"])
                                is_recent = time_diff <= threshold
                                days_old = time_diff / (24 * 60 * 60 * 1000)
                                
                                # Log recency analysis for debugging
                                threshold_days = threshold / (24 * 60 * 60 * 1000) if threshold != float('inf') else "∞"
                                print(f"[recency] {data_type} chunk is {days_old:.1f} days old, threshold: {threshold_days} days, recent: {is_recent}")
                                
                            except (ValueError, TypeError) as e:
                                print(f"[recency] Could not parse timestamp '{timestamp_str}' for {data_type} chunk: {e}")
                                is_recent = True  # Default to including if timestamp parsing fails
                        
                        # Apply recency filter - skip old time-sensitive data
                        if not is_recent:
                            print(f"[recency] Skipping {data_type} chunk due to age ({chunk_timestamp})")
                            continue
                        
                        # Verify patient relevance
                        if state.patient_ctx:
                            patient_name = state.patient_ctx.name
                            if str(state.patient_id) in chunk_text or patient_name in chunk_text:
                                
                                # Calculate recency-adjusted similarity score
                                adjusted_score = similarity_score
                                if chunk_timestamp and data_type in ["vitals", "labs", "medications"]:
                                    # Boost score for more recent time-sensitive data (only for vitals, labs, medications)
                                    time_diff = current_time - chunk_timestamp
                                    threshold = recency_thresholds.get(data_type, recency_thresholds["unknown"])
                                    if threshold != float('inf') and time_diff < threshold:
                                        # Apply recency boost: more recent = higher boost
                                        recency_factor = 1.0 + (0.3 * (1.0 - time_diff / threshold))
                                        adjusted_score = similarity_score * recency_factor # type: ignore
                                        print(f"[recency] Applied recency boost to {data_type}: {similarity_score:.3f} -> {adjusted_score:.3f}")
                                
                                candidate_chunks.append({
                                    "id": f"chunk_{i}",
                                    "content": chunk_text[:600],  # Increased limit for journal entries
                                    "similarity_score": similarity_score,
                                    "adjusted_score": adjusted_score,
                                    "full_content": chunk_text,
                                    "data_type": data_type,
                                    "metadata": metadata,
                                    "timestamp": chunk_timestamp,
                                    "is_recent": is_recent,
                                    "days_old": days_old
                                })
                        
                    except Exception as e:
                        print(f"[intelligent_retrieve] Error processing chunk {i}: {e}")
                        continue

                if not candidate_chunks:
                    state.retrieved_chunks = []
                    state.chunk_analysis = {"method": "none", "reason": "No relevant or recent chunks found"}
                    return state

                # Step 3: Simplified LLM-based chunk analysis
                chunk_analysis_prompt = f"""
                You are analyzing medical data chunks to determine which ones are relevant for answering this query:

                QUERY: "{state.user_prompt}"
                
                PATIENT CONTEXT: {state.patient_ctx.name if state.patient_ctx else "Unknown"} (ID: {state.patient_id})
                
                AVAILABLE CHUNKS (including demographics, vitals, labs, and journal entries):
                {chr(10).join([f"CHUNK {chunk['id']} ({chunk.get('data_type', 'unknown')}): {chunk['content'][:400]}..." for chunk in candidate_chunks])}

                For each chunk, analyze:
                1. Relevance to the specific query (0-10 scale)
                2. Clinical importance for this case (0-10 scale)  
                3. Whether it contains information that directly helps answer the query
                4. Whether it provides necessary context or background

                CHUNK TYPES AVAILABLE:
                - demographics: Basic patient information
                - vitals: Current vital signs and measurements (recent values prioritized)
                - labs: Laboratory test results (recent values prioritized)
                - medications: Current medication regimen (recent changes prioritized)
                - journal_entry: Clinical notes, observations, treatments, diagnoses, assessments, and care plans
                - complete_context: Full patient overview

                Return a JSON response with:
                {{
                    "selected_chunks": ["chunk_1", "chunk_3", ...],
                    "reasoning": "Brief explanation of why these chunks were selected",
                    "relevance_analysis": {{
                        "chunk_1": {{"relevance": 8, "importance": 7, "reason": "Contains recent clinical assessment"}},
                        "chunk_2": {{"relevance": 3, "importance": 4, "reason": "General background, not specific to query"}},
                        ...
                    }},
                    "query_type": "diagnostic|follow_up|general_inquiry|medication|test_results|care_planning|clinical_notes"
                }}

                RULES:
                - Select 3-6 most relevant chunks maximum
                - For vitals, labs, medications: Recent values are automatically prioritized
                - Journal entries are always relevant regardless of age
                - Always include patient demographics for context
                - For diagnostic queries, include recent journal entries, symptoms, vitals, and test results
                - For medication queries, focus on current medications, allergies, and relevant journal notes
                - For follow-up queries, include previous treatments/outcomes from journal entries
                - For care planning, prioritize recent assessments and treatment notes
                """

                try:
                    analysis_response = await self._llm.chat([
                        ChatMessage(role=ChatRole.SYSTEM, content="You are a medical information analyst. Analyze and select the most relevant data chunks for clinical queries."),
                        ChatMessage(role=ChatRole.USER, content=chunk_analysis_prompt)
                    ], json_mode=True)

                    if not analysis_response or not analysis_response.content:
                        print("[intelligent_retrieve] Empty response from LLM, using fallback")
                        raise ValueError("Empty response from LLM")

                    # Strip whitespace and check if content is empty
                    response_content = analysis_response.content.strip()
                    if not response_content:
                        print("[intelligent_retrieve] Empty content in response, using fallback")
                        raise ValueError("Empty content in response")

                    # Remove markdown code block markers if present
                    if response_content.startswith("```json"):
                        start_idx = response_content.find('\n') + 1
                        end_idx = response_content.rfind("```")
                        if start_idx > 0 and end_idx > start_idx:
                            response_content = response_content[start_idx:end_idx].strip()
                    elif response_content.startswith("```"):
                        start_idx = response_content.find('\n') + 1
                        end_idx = response_content.rfind("```")
                        if start_idx > 0 and end_idx > start_idx:
                            response_content = response_content[start_idx:end_idx].strip()

                    analysis_data = json.loads(response_content)
                    
                    # Extract selected chunks
                    selected_chunk_ids = analysis_data.get("selected_chunks", [])
                    selected_chunks = []
                    
                    for chunk in candidate_chunks:
                        if chunk["id"] in selected_chunk_ids:
                            selected_chunks.append(chunk["full_content"])

                    state.retrieved_chunks = selected_chunks
                    state.chunk_analysis = analysis_data
                    state.retrieval_reasoning = analysis_data.get("reasoning", "")
                    
                    print(f"[intelligent_retrieve] Selected {len(selected_chunks)} chunks out of {len(candidate_chunks)} candidates")
                    print(f"[intelligent_retrieve] Reasoning: {state.retrieval_reasoning}")

                    # Log which data types were selected for debugging
                    selected_data_types = []
                    for chunk in candidate_chunks:
                        if chunk["id"] in selected_chunk_ids:
                            selected_data_types.append(chunk.get("data_type", "unknown"))
                    print(f"[intelligent_retrieve] Selected data types: {selected_data_types}")

                except Exception as e:
                    print(f"[intelligent_retrieve] Error in LLM analysis: {e}, falling back to similarity-based selection")
                    # Fallback to top similarity scores, but prioritize journal entries and recent data
                    journal_chunks = [chunk for chunk in candidate_chunks if chunk.get("data_type") == "journal_entry"]
                    recent_time_sensitive = [chunk for chunk in candidate_chunks if chunk.get("data_type") in ["vitals", "labs", "medications"] and chunk.get("is_recent", True)]
                    other_chunks = [chunk for chunk in candidate_chunks if chunk.get("data_type") not in ["journal_entry", "vitals", "labs", "medications"]]
                    
                    # Take top chunks from each category
                    top_journal = sorted(journal_chunks, key=lambda x: x["similarity_score"], reverse=True)[:2]
                    top_recent = sorted(recent_time_sensitive, key=lambda x: x.get("adjusted_score", x["similarity_score"]), reverse=True)[:2]
                    top_other = sorted(other_chunks, key=lambda x: x["similarity_score"], reverse=True)[:2]
                    
                    fallback_chunks = top_journal + top_recent + top_other
                    state.retrieved_chunks = [chunk["full_content"] for chunk in fallback_chunks]
                    state.chunk_analysis = {"method": "fallback_similarity", "error": str(e)}

            except Exception as e:
                print(f"[intelligent_retrieve] Critical error in chunk retrieval: {e}")
                # Ultimate fallback to patient context if everything fails
                if state.patient_ctx:
                    state.retrieved_chunks = [state.patient_ctx.model_dump_json(indent=2)]
                    state.chunk_analysis = {"method": "critical_fallback", "error": str(e)}
                else:
                    state.retrieved_chunks = []
                    state.chunk_analysis = {"method": "failure", "error": str(e)}

            return state
        
        async def store_user_message(state: FlowState) -> FlowState:
            """Store the user message in chat history."""
            if not state.user_prompt:
                return state
            
            try:
                # Create user message
                user_message = ChatMessage(
                    role=ChatRole.USER,
                    content=state.user_prompt,
                    timestamp=datetime.now(),
                    user_id=state.user_id,
                    metadata={}  # Keep metadata empty for user messages or ensure all values are strings
                )
                
                # Store user message - ALL METADATA VALUES MUST BE STRINGS
                await self._vec.upsert(
                    embedding_id=f"chat_{state.session_id}_{int(time.time() * 1000)}_{state.user_id}",
                    embedding=await embed(state.user_prompt, "passage"),
                    object_type="chat_message",
                    object_id=str(state.session_id),
                    content={
                        "role": user_message.role.value,
                        "content": user_message.content,
                        "timestamp": str(int(user_message.timestamp.timestamp() * 1000)),
                        "user_id": state.user_id or ""
                    },
                    metadata={
                        "namespace": "chat_history",
                        "patient_id": state.patient_id or "general_chat",
                        "session_id": state.session_id or "",
                        "timestamp": str(int(user_message.timestamp.timestamp() * 1000)),
                        "user_id": state.user_id or "",
                        "message_type": "user",
                        "language": detect_language_code(state.user_prompt or "")
                    }
                )
                
            except Exception as e:
                print(f"[store_user_message] Error: {e}")
                import traceback
                traceback.print_exc()
            
            return state

        async def store_assistant_response(state: FlowState) -> FlowState:
            """Store the assistant response and any generated image in chat history."""
            if not state.llm_response:
                return state
            
            try:
                # Prepare message content
                message_content = {
                    "role": state.llm_response.role.value,
                    "content": state.llm_response.content,
                    "timestamp": str(int(time.time() * 1000)),
                    "user_id": state.user_id,
                }
                
                # Add generated image info if available
                if state.generated_image:
                    image_info = {
                        "image_generated": True,
                        "image_id": state.generated_image.generation_id,
                        "image_prompt": state.generated_image.prompt,
                        "generation_metadata": state.generated_image.metadata,
                        "model_info": state.generated_image.model_info
                    }
                    message_content["generated_image"] = image_info # type: ignore
                
                # Add differential diagnoses if available
                if state.parsed_response and state.parsed_response.differential:
                    differential_diagnoses = [
                        {
                            "icd_code": diff.icd_code,
                            "diagnosis_name": diff.diagnosis_name,
                            "confidence": diff.confidence,
                            "reasoning": diff.reasoning,
                            "supporting_evidence": diff.supporting_evidence
                        }
                        for diff in state.parsed_response.differential
                    ]
                    message_content["differential_diagnoses"] = differential_diagnoses # type: ignore

                # Prepare metadata - ALL VALUES MUST BE STRINGS
                metadata = {
                    "namespace": "chat_history",
                    "patient_id": state.patient_id or "general_chat",
                    "session_id": state.session_id or "",
                    "timestamp": str(int(time.time() * 1000)),
                    "user_id": state.user_id or "",
                    "message_type": "assistant"
                }
                
                # Add reasoning steps as JSON string if available
                if hasattr(state, 'reasoning_steps') and state.reasoning_steps:
                    metadata["reasoning_steps"] = json.dumps(state.reasoning_steps)
                
                # Add web search info if available
                if state.web_search_response:
                    metadata["web_search_performed"] = "true"
                    metadata["source_count"] = str(len(state.web_search_response.results))
                
                # Add differential diagnosis count
                if state.parsed_response and state.parsed_response.differential:
                    metadata["differential_count"] = str(len(state.parsed_response.differential))
                    print("[Differential Diagnoses] saved differential diagnoses count:", metadata["differential_count"])
                # Store assistant message
                await self._vec.upsert(
                    embedding_id=f"chat_{state.session_id}_{int(time.time() * 1000)}_assistant",
                    embedding=await embed(state.llm_response.content, "passage"),
                    object_type="chat_message",
                    object_id=str(state.session_id),
                    content=message_content,
                    metadata={
                        **metadata,
                        "language": detect_language_code(state.llm_response.content or "")
                    }
                )
                
            except Exception as e:
                print(f"[store_assistant_response] Error: {e}")
                import traceback
                traceback.print_exc()
            
            return state

        @streaming_step("diagnose")
        async def diagnose(state: FlowState) -> FlowState:
            # Select system message based on diagnostic mode
            if state.diagnostic_mode == "pre_meet":
                messages = [SYSTEM_MSG_PRE_MEET]
            elif state.diagnostic_mode == "post_meet":
                messages = [SYSTEM_MSG_POST_MEET]
            elif state.diagnostic_mode == "research":
                messages = [SYSTEM_MSG_RESEARCH]
            else:  # chat mode or default
                messages = [SYSTEM_MSG_CHAT]

            # Language policy system message (answer in user's prompt language)
            try:
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
                    content="""You are CLARA, a helpful medical AI assistant. Provide clear, accurate medical information and advice. For general medical questions, draw on your medical knowledge. Keep responses concise and helpful.

Link policy (STRICT for EHR): For every EHR-derived item you mention (vital, lab value, medication, allergy, diagnosis, imaging finding, date, encounter, note), include a clickable markdown link immediately after that specific item, within the same sentence, e.g., "HbA1c 8.1% (2024‑04‑02) [EHR](URL)" or "lisinopril 10 mg daily [Meds](URL)". Do this for each individual item you list. Do not group EHR links in a separate Sources section. If no URL is available, write "(from EHR, no link available)" immediately after the item.
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
            # Only add complex context for full processing path
            if getattr(state, 'requires_full_processing', True):
                # Add mode-specific context
                mode_context = ChatMessage(
                    role=ChatRole.USER,
                    content=f"DIAGNOSTIC MODE: {state.diagnostic_mode.upper().replace('_', '-')}"
                )
                messages.append(mode_context)

                

                # Add cross-session relevant history if available
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

                if state.patient_ctx:
                    # NEW: Extract and format source information
                    source_info = self._extract_source_summary(state.patient_ctx)
                    
                    ctx_content = f"""Patient context: 
{state.patient_ctx.model_dump_json(indent=2)}

=== DATA SOURCE TRACEABILITY ===
{source_info}
=== END OF DATA SOURCES ===

IMPORTANT: When referencing specific patient data, you MUST provide the source of the information AND include links to the EHR from exactly where the data was retrieved from."""
                    
                    ctx = ChatMessage(
                        role=ChatRole.USER,
                        content=ctx_content,
                    )
                    messages.append(ctx)
                

                if state.retrieved_chunks:
                    chunk_context = "Relevant clinical notes"
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
                

                if state.generated_image:
                    image_context = ChatMessage(
                        role=ChatRole.USER,
                        content=f"""Generated Educational Image Available:
                        
An educational medical illustration has been generated to help visualize the concepts discussed:
- Image ID: {state.generated_image.generation_id}
- Generated from prompt: {state.generated_image.prompt}
- Purpose: Educational visualization to aid understanding

Please reference this generated image in your response when relevant and explain how it relates to the medical concepts being discussed. Let the user know they can view the image through the interface."""
                    )
                    messages.append(image_context)

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
                        # Ensure any raw URLs for EHR are formatted as markdown links on the fly
                        accumulated = update.get("accumulated_content", "")
                        state.streaming_response = self._format_ehr_links(accumulated)

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
                        # Finalize with hyperlink formatting and normalize markdown headings
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
                # Post-process to ensure EHR URLs are hyperlinks and normalize markdown headings
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


        @streaming_step("evaluate_icd_parsing_need")
        async def evaluate_icd_parsing_need(state: FlowState) -> FlowState:
            """Evaluate if ICD parsing should be performed based on diagnostic confidence."""
            if not state.llm_response or not state.llm_response.content:
                state.should_parse_icd_codes = False
                return state
            
            try:
                # For pre_meet mode, be extra strict about diagnostic content
                if state.diagnostic_mode == "pre_meet":
                    evaluation_prompt = f"""
                    Analyze this pre-consultation response to determine if it contains CONFIDENT differential diagnoses or established diagnoses:

                    RESPONSE TO ANALYZE:
                    "{state.llm_response.content}"

                    STRICT CRITERIA FOR ICD PARSING:
                    
                    PARSE ICD CODES (respond "YES") ONLY if the response contains:
                    - Explicitly stated diagnoses with high confidence
                    - Clear differential diagnoses with specific medical conditions named
                    - Definitive statements like "likely diagnosis is", "most probable condition", "confirmed diagnosis"
                    - Specific medical conditions with confidence indicators (probable, likely, definitive)
                    - ICD codes are explicitly mentioned
                    
                    DO NOT PARSE (respond "NO") if the response contains:
                    - General preparation advice without specific diagnoses
                    - Symptom descriptions without diagnostic conclusions
                    - Vague references to "possible conditions" without specifics
                    - General questions to ask the patient
                    - Examination recommendations without diagnostic certainty
                    - Educational content about conditions without diagnosing this patient
                    - Statements like "consider", "rule out", "screen for" without strong diagnostic confidence
                    
                    EXAMPLES:
                    - "The patient likely has pneumonia based on symptoms" → YES
                    - "Consider pneumonia in the differential" → NO (not confident enough)
                    - "Rule out pneumonia" → NO (not a diagnosis)
                    - "Ask patient about chest pain symptoms" → NO (preparation advice)
                    - "The most probable diagnosis is Type 2 diabetes" → YES
                    - "Screen for diabetes during the visit" → NO (screening, not diagnosis)
                    
                    Respond with only "YES" or "NO".
                    """
                else:
                    # For post_meet, research, and chat modes, be strict about diagnostic confidence
                    evaluation_prompt = f"""
                    Analyze this medical response to determine if it contains HIGH-CONFIDENCE diagnoses worthy of ICD code extraction:

                    RESPONSE TO ANALYZE:
                    "{state.llm_response.content}"

                    DIAGNOSTIC MODE: {state.diagnostic_mode}

                    STRICT CRITERIA FOR ICD PARSING:
                    
                    PARSE ICD CODES (respond "YES") ONLY if the response contains:
                    - Definitive or highly probable diagnoses (confidence >70%)
                    - Clear differential diagnoses with specific conditions and reasoning
                    - Statements indicating diagnostic certainty: "diagnosed with", "most likely", "primary diagnosis"
                    - Specific medical conditions with strong supporting evidence
                    - Treatment recommendations for established diagnoses
                    - Explicit ICD codes mentioned
                    
                    DO NOT PARSE (respond "NO") if the response contains:
                    - General medical education without patient-specific diagnosis
                    - Vague symptoms without diagnostic conclusions
                    - General health advice or wellness information
                    - Uncertain language: "might be", "could consider", "possibly"
                    - Screening recommendations without diagnosis
                    - General information about medical conditions
                    - Preparation or procedural advice
                    - Low-confidence speculation (confidence <70%)
                    
                    CONFIDENCE THRESHOLD: Only parse if the response demonstrates >70% confidence in at least one specific diagnosis.
                    
                    EXAMPLES:
                    - "Based on symptoms and labs, patient has Type 2 diabetes" → YES
                    - "What is diabetes?" → NO (educational, not diagnostic)
                    - "Consider screening for diabetes" → NO (screening, not diagnosis)
                    - "Differential includes pneumonia (high likelihood) and bronchitis" → YES
                    - "Patient might have a respiratory condition" → NO (too vague)
                    - "Hello, how can I help?" → NO (conversational)
                    
                    Respond with only "YES" or "NO".
                    """

                evaluation_msg = ChatMessage(role=ChatRole.USER, content=evaluation_prompt)
                response = await self._llm.chat([
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a clinical decision support system that determines when ICD code extraction is appropriate. Be STRICT - only approve ICD parsing when there are confident, specific diagnoses present. Err on the side of caution."),
                    evaluation_msg
                ])

                # Parse response
                response_text = response.content.strip().upper()
                should_parse = "YES" in response_text

                state.should_parse_icd_codes = should_parse
                
                print(f"[icd_evaluation] Mode: {state.diagnostic_mode}, Should parse ICD: {should_parse}")
                if should_parse:
                    print("[icd_evaluation] High-confidence diagnosis detected in response")
                else:
                    print("[icd_evaluation] No confident diagnosis found, skipping ICD parsing")

            except Exception as e:
                print(f"[icd_evaluation] Error evaluating ICD parsing need: {e}")
                # Default to False to be safe - don't parse unless we're certain
                state.should_parse_icd_codes = False
            
            return state

        @streaming_step("parse_icd")
        async def parse_icd(state: FlowState) -> FlowState:
            """
            Parse the ICD code and differential diagnoses from the response.
            Uses Bayesian logic to calculate robust confidence levels.
            """
            # Skip ICD parsing for pre_meet mode unless differential diagnoses are explicitly mentioned
            if state.diagnostic_mode == "pre_meet":
                if not state.llm_response or not state.llm_response.content:
                    return state
                
                # Check if the response contains differential diagnosis language
                response_lower = state.llm_response.content.lower()
                differential_keywords = [
                    "differential", "diagnosis", "diagnoses", "icd", "condition", 
                    "disease", "disorder", "syndrome", "pathology"
                ]
                
                contains_diagnostic_content = any(keyword in response_lower for keyword in differential_keywords)
                
                if not contains_diagnostic_content:
                    print("[parse_icd] Pre-meet mode: No diagnostic content detected, skipping ICD parsing")
                    return state
                else:
                    print("[parse_icd] Pre-meet mode: Diagnostic content detected, proceeding with ICD parsing")

            if state.patient_ctx and state.llm_response:
                try:
                    # Use a shorter, more focused prompt to avoid context issues
                    response_content = state.llm_response.content
                    
                    # Truncate response if too long to avoid API limits
                    if len(response_content) > 2000:
                        response_content = response_content[:2000] + "..."
                    
                    prompt = f"""MEDICAL DIAGNOSIS EXTRACTION TASK

SOURCE TEXT TO ANALYZE:
{response_content}

PATIENT CONTEXT:
Age: {state.patient_ctx.age}, Sex: {state.patient_ctx.sex}
Vitals: {state.patient_ctx.vitals}
Labs: {state.patient_ctx.labs}
Medications: {state.patient_ctx.medications}
Allergies: {state.patient_ctx.allergies}
Diagnoses: {state.patient_ctx.diagnoses}

INSTRUCTIONS:
Extract diagnoses mentioned in the source text. For each diagnosis, we will calculate Bayesian confidence separately.

REQUIRED JSON OUTPUT FORMAT:
{{
  "primary_icd": "ICD-10 code or 'Unknown' if no clear primary diagnosis",
  "differential": [
    {{
      "icd_code": "specific ICD-10 code",
      "diagnosis_name": "exact medical diagnosis name",
      "supporting_evidence": ["direct quote 1", "direct quote 2"],
      "reasoning": "brief explanation of why this diagnosis was extracted"
    }}
  ]
}}

RULES:
- Extract ONLY diagnoses explicitly mentioned or clearly diagnosed
- Do NOT assign confidence scores (we will calculate these using Bayesian methods)
- Use specific ICD-10 codes if mentioned, otherwise use appropriate standard codes
- Include all supporting evidence as direct quotes from source text

If no clear medical diagnoses are found, return: {{"primary_icd": "Unknown", "differential": []}}"""

                    # Use system message for diagnosis extraction only
                    extraction_system_msg = ChatMessage(
                        role=ChatRole.SYSTEM, 
                        content="""You are a medical diagnosis extraction specialist. Extract diagnoses from clinical text without assigning confidence scores. We will calculate confidence using Bayesian methods separately."""
                    )
                    
                    # Extract diagnoses first
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            parsed = await self._llm.chat([
                                extraction_system_msg, 
                                ChatMessage(role=ChatRole.USER, content=prompt)
                            ], json_mode=True)
                            
                            if parsed and parsed.content:
                                break
                                
                        except Exception as retry_error:
                            print(f"[parse_icd] Attempt {attempt + 1} failed: {retry_error}")
                            if attempt == max_retries - 1:
                                raise retry_error
                            await asyncio.sleep(2 ** attempt)
                    
                    if not parsed or not parsed.content:
                        print("[parse_icd] Failed to get valid response from LLM")
                        state.parsed_response = DiagnosisResult(
                            patient_id=state.patient_ctx.patient_id,
                            primary_icd="Unknown",
                            differential=[],
                            confidence=0.0
                        )
                        return state

                    # Clean up the response content
                    response_content = parsed.content.strip()
                    
                    # Remove markdown code block markers if present
                    if response_content.startswith("```json"):
                        start_idx = response_content.find('\n') + 1
                        end_idx = response_content.rfind("```")
                        if start_idx > 0 and end_idx > start_idx:
                            response_content = response_content[start_idx:end_idx].strip()
                    elif response_content.startswith("```"):
                        start_idx = response_content.find('\n') + 1
                        end_idx = response_content.rfind("```")
                        if start_idx > 0 and end_idx > start_idx:
                            response_content = response_content[start_idx:end_idx].strip()

                    try:
                        parsed_data = json.loads(response_content)
                    except json.JSONDecodeError as e:
                        print(f"[parse_icd] JSON decode error: {e}, content: {response_content[:200]}...")
                        parsed_data = {
                            "primary_icd": "Unknown",
                            "differential": []
                        }

                    # Now calculate Bayesian confidence for each diagnosis
                    differential_list = []
                    if parsed_data.get("differential") and isinstance(parsed_data["differential"], list):
                        
                        # Extract all diagnosis names first for batch prior retrieval
                        diagnosis_names = []
                        diagnosis_data = []
                        for diff in parsed_data["differential"]:
                            if isinstance(diff, dict):
                                diagnosis_name = diff.get("diagnosis_name", "Unknown Diagnosis")
                                diagnosis_names.append(diagnosis_name)
                                diagnosis_data.append(diff)
                        
                        # Emit initial progress update
                        if diagnosis_names:
                            await _emit_diagnosis_progress_update(
                                state, 
                                "Differential Diagnosis System", 
                                "Initializing analysis", 
                                f"Found {len(diagnosis_names)} potential diagnoses to analyze"
                            )
                        
                        # Batch retrieve priors for ALL diagnoses once (for consistency)
                        batch_priors = {}
                        if diagnosis_names:
                            await _emit_diagnosis_progress_update(
                                state, 
                                "Differential Diagnosis System", 
                                "Retrieving baseline probabilities", 
                                f"Searching medical literature for {len(diagnosis_names)} conditions"
                            )
                            print(f"[parse_icd] Batch retrieving priors for {len(diagnosis_names)} diagnoses")
                            batch_priors = await _batch_web_search_for_priors(diagnosis_names, state.patient_ctx)
                            await _emit_diagnosis_progress_update(
                                state, 
                                "Differential Diagnosis System", 
                                "Baseline probabilities retrieved", 
                                "Starting Bayesian analysis for each diagnosis"
                            )
                        
                        # Create concurrent tasks for all differential diagnoses
                        confidence_tasks = []
                        for i, (diagnosis_name, diff) in enumerate(zip(diagnosis_names, diagnosis_data)):
                            # Emit progress update for this specific diagnosis
                            await _emit_diagnosis_progress_update(
                                state, 
                                diagnosis_name, 
                                "Queued for analysis", 
                                f"Position {i+1} of {len(diagnosis_names)}"
                            )
                            
                            state.prelim_diagnosis_name = diagnosis_name  # Store for streaming updates
                            print(f"[parse_icd] Preparing Bayesian confidence calculation for: {diagnosis_name}")
                            
                            # Create async task for Bayesian confidence calculation
                            # Pass the batch_priors dict so it can use pre-computed values
                            task = _calculate_bayesian_confidence_with_batch_priors(
                                state=state,
                                diagnosis_name=diagnosis_name,
                                patient_context=state.patient_ctx,
                                supporting_evidence=diff.get("supporting_evidence", []),
                                batch_priors=batch_priors  # Pass all priors for consistency
                            )
                            confidence_tasks.append((task, diff))
                        
                        # Execute all confidence calculations concurrently
                        if confidence_tasks:
                            print(f"[parse_icd] Computing Bayesian confidence for {len(confidence_tasks)} diagnoses in parallel")
                            
                            # Emit start of concurrent processing
                            await _emit_diagnosis_progress_update(
                                state, 
                                "Bayesian Analysis Engine", 
                                "Computing all diagnoses", 
                                f"Processing {len(confidence_tasks)} diagnoses concurrently"
                            )
                            
                            # Run all tasks concurrently
                            task_results = await asyncio.gather(
                                *[task for task, _ in confidence_tasks],
                                return_exceptions=True
                            )
                            
                            # Emit completion of concurrent processing
                            await _emit_diagnosis_progress_update(
                                state, 
                                "Bayesian Analysis Engine", 
                                "Analysis complete", 
                                "Finalizing confidence scores and rankings"
                            )
                            
                            # Process results and create DifferentialDiagnosis objects
                            processed_count = 0
                            for i, (confidence_result, diff) in enumerate(zip(task_results, [diff for _, diff in confidence_tasks])):
                                try:
                                    if isinstance(confidence_result, Exception):
                                        print(f"[parse_icd] Error calculating confidence for {diff.get('diagnosis_name', 'Unknown')}: {confidence_result}")
                                        bayesian_confidence = 0.5  # Fallback confidence
                                    else:
                                        bayesian_confidence = confidence_result # type: ignore
                                    
                                    diagnosis_name = diff.get("diagnosis_name", "Unknown Diagnosis")
                                    differential_list.append(DifferentialDiagnosis(
                                        icd_code=diff.get("icd_code", "Unknown"),
                                        diagnosis_name=diagnosis_name,
                                        confidence=bayesian_confidence,
                                        reasoning=diff.get("reasoning", "No reasoning provided"),
                                        supporting_evidence=diff.get("supporting_evidence", [])
                                    ))
                                    
                                    processed_count += 1
                                    print(f"[parse_icd] {diagnosis_name}: Bayesian confidence = {bayesian_confidence:.3f}")
                                    
                                    # Emit progress for each processed diagnosis
                                    await _emit_diagnosis_progress_update(
                                        state, 
                                        diagnosis_name, 
                                        "Analysis complete", 
                                        f"Confidence: {bayesian_confidence:.1%} ({processed_count}/{len(task_results)})"
                                    )
                                    
                                except Exception as e:
                                    print(f"[parse_icd] Error processing result for differential {i}: {e}")
                                    continue

                    # Emit final completion update
                    if differential_list:
                        # Sort by confidence for display
                        sorted_diagnoses = sorted(differential_list, key=lambda x: x.confidence, reverse=True)
                        top_diagnosis = sorted_diagnoses[0]
                        await _emit_diagnosis_progress_update(
                            state, 
                            "Differential Diagnosis Complete", 
                            "Analysis finished", 
                            f"Top diagnosis: {top_diagnosis.diagnosis_name} ({top_diagnosis.confidence:.1%})"
                        )

                    # Calculate overall confidence as the maximum individual confidence
                    overall_confidence = max([diff.confidence for diff in differential_list]) if differential_list else 0.0

                    # Create the DiagnosisResult
                    state.parsed_response = DiagnosisResult(
                        patient_id=state.patient_ctx.patient_id,
                        primary_icd=parsed_data.get("primary_icd", "Unknown"),
                        differential=differential_list,
                        confidence=overall_confidence,
                        explanation=state.llm_response.content,
                        session_id=state.session_id,
                        created_by_user_id=state.user_id
                    )

                    print(f"[parse_icd] Successfully parsed with Bayesian confidence - Primary: {state.parsed_response.primary_icd}, Differential count: {len(state.parsed_response.differential)}")
                    for diff in differential_list:
                        print(f"[parse_icd] {diff.diagnosis_name}: Bayesian confidence = {diff.confidence:.3f}")

                except Exception as e:
                    print(f"[parse_icd] Error parsing ICD: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # Set minimal response on error
                    state.parsed_response = DiagnosisResult(
                        patient_id=state.patient_ctx.patient_id,
                        primary_icd="Unknown",
                        differential=[],
                        confidence=0.0
                    )

            return state

        async def _calculate_bayesian_confidence_with_batch_priors(
            state: FlowState,
            diagnosis_name: str, 
            patient_context: PatientContext,
            supporting_evidence: List[str],
            batch_priors: dict[str, float]
        ) -> float:
            """
            Calculate Bayesian posterior probability using pre-computed batch priors for consistency.
            P(Diagnosis|Evidence) = P(Evidence|Diagnosis) * P(Diagnosis) / P(Evidence)
            """
            try:
                # Emit update that we're starting this diagnosis
                await _emit_diagnosis_progress_update(state, diagnosis_name, "Retrieving baseline probability")
                
                # Step 1: Use the batch-computed prior (ensures consistency)
                prior_probability = batch_priors.get(diagnosis_name, 0.03)
                state.diff_diag_compute_step = f"Prior probability for {diagnosis_name}: {prior_probability:.3f}"
                
                await _emit_diagnosis_progress_update(state, diagnosis_name, "Calculating evidence likelihood", f"Prior: {prior_probability:.3f}")

                # Step 2: Get likelihood from patient evidence
                likelihood = await _calculate_likelihood(diagnosis_name, patient_context, supporting_evidence)
                state.diff_diag_compute_step = f"Likelihood for {diagnosis_name}: {likelihood:.3f}"
                
                await _emit_diagnosis_progress_update(state, diagnosis_name, "Computing marginal probability", f"Likelihood: {likelihood:.3f}")

                # Step 3: Estimate marginal probability using the SAME batch priors for consistency
                marginal_probability = await _estimate_marginal_probability_with_batch_priors(
                    patient_context, 
                    supporting_evidence, 
                    batch_priors
                )
                state.diff_diag_compute_step = f"Marginal probability for {diagnosis_name}: {marginal_probability:.3f}"
                
                # Step 4: Calculate posterior using Bayes' theorem
                if marginal_probability > 0:
                    posterior = (likelihood * prior_probability) / marginal_probability
                else:
                    posterior = prior_probability * likelihood
                
                # Ensure result is between 0 and 1
                posterior = max(0.0, min(1.0, posterior))
                
                await _emit_diagnosis_progress_update(state, diagnosis_name, "Diagnosis computed", f"Confidence: {posterior:.1%}")
                
                print(f"[bayesian] {diagnosis_name}: Prior={prior_probability:.3f}, Likelihood={likelihood:.3f}, Marginal={marginal_probability:.3f}, Posterior={posterior:.3f}")
                
                return posterior
                
            except Exception as e:
                print(f"[bayesian] Error calculating confidence for {diagnosis_name}: {e}")
                await _emit_diagnosis_progress_update(state, diagnosis_name, "Error in calculation", "Using fallback confidence")
                return 0.5
        
        async def _emit_diagnosis_progress_update(state: FlowState, diagnosis_name: str, step: str, details: str = ""):
            """Emit streaming update for differential diagnosis computation progress."""
            print(f"[DEBUG] Emitting differential diagnosis progress: {diagnosis_name} - {step} - {details}")
            if hasattr(state, 'stream_callback') and state.stream_callback:
                try:
                    update = {
                        "type": "differential_diagnosis_progress",
                        "diagnosis_name": diagnosis_name,
                        "step": step,
                        "details": details,
                        "timestamp": datetime.now().isoformat()
                    }
                    print(f"[DEBUG] Calling stream_callback with update: {update}")
                    await state.stream_callback(update)
                    print("[DEBUG] Successfully emitted differential diagnosis progress")
                except Exception as e:
                    print(f"[streaming] Error emitting diagnosis progress: {e}")
            else:
                print(f"[DEBUG] No stream_callback available, hasattr: {hasattr(state, 'stream_callback')}, callback: {getattr(state, 'stream_callback', None)}")

        async def _estimate_marginal_probability_with_batch_priors(
            patient_context: PatientContext,
            supporting_evidence: List[str],
            batch_priors: dict[str, float]
        ) -> float:
            """
            Estimate P(Evidence) using pre-computed batch priors for consistency.
            Uses the SAME prior values that were used for individual diagnoses.
            """
            try:
                # Use the diagnoses from batch_priors as candidate diagnoses
                candidate_diagnoses = list(batch_priors.keys())
                print(f"[marginal_batch] Processing {len(candidate_diagnoses)} candidate diagnoses with consistent priors")
                
                # Calculate marginal probability using law of total probability
                marginal_probability = 0.0
                
                for diagnosis in candidate_diagnoses:
                    try:
                        # Use the SAME prior probability from batch
                        prior_prob = batch_priors[diagnosis]
                        
                        # Get likelihood for this diagnosis
                        likelihood = await _calculate_likelihood_for_marginal(diagnosis, patient_context, supporting_evidence)
                        
                        # Add to total: P(E) += P(E|D_i) * P(D_i)
                        marginal_probability += likelihood * prior_prob
                        
                        print(f"[marginal_batch] {diagnosis}: P(D)={prior_prob:.3f}, P(E|D)={likelihood:.3f}, contribution={likelihood * prior_prob:.3f}")
                        
                    except Exception as e:
                        print(f"[marginal_batch] Error calculating for {diagnosis}: {e}")
                        continue
                
                # Add baseline for other conditions
                baseline_other_conditions = 0.01
                marginal_probability += baseline_other_conditions
                
                # Ensure result is reasonable
                marginal_probability = max(0.001, min(0.8, marginal_probability))
                
                print(f"[marginal_batch] Total marginal probability: {marginal_probability:.3f}")
                return marginal_probability
                
            except Exception as e:
                print(f"[marginal_batch] Error in marginal probability calculation: {e}")
                return 0.1
                

        async def _calculate_likelihood(
            diagnosis_name: str, 
            patient_context: PatientContext,
            supporting_evidence: List[str]
        ) -> float:
            """
            Calculate likelihood using proper Bayesian approach based on likelihood ratios.
            This calculates P(Evidence|Diagnosis) / P(Evidence|No Diagnosis) = Likelihood Ratio
            """
            try:
                # Prepare patient evidence
                patient_evidence = []
                
                # Add relevant vitals
                if patient_context.vitals:
                    patient_evidence.extend([f"Vital: {k}={v}" for k, v in patient_context.vitals.items()])
                
                # Add relevant labs
                if patient_context.labs:
                    patient_evidence.extend([f"Lab: {k}={v}" for k, v in patient_context.labs.items()])
                
                # Add medications (can indicate existing conditions)
                if patient_context.medications:
                    patient_evidence.extend([f"Medication: {k}={v}" for k, v in patient_context.medications.items()])
                
                # Add existing diagnoses
                if patient_context.diagnoses:
                    patient_evidence.extend([f"Existing diagnosis: {k}={v}" for k, v in patient_context.diagnoses.items()])
                
                # Add supporting evidence from clinical notes
                patient_evidence.extend(supporting_evidence)
                
                evidence_text = "; ".join(patient_evidence) if patient_evidence else "No specific evidence available"
                
                # First get sensitivity and specificity estimates for each piece of evidence
                likelihood_prompt = f"""
                For the diagnosis of {diagnosis_name}, estimate the sensitivity and specificity of the observed clinical evidence.
                
                Diagnosis: {diagnosis_name}
                Patient Evidence: {evidence_text}
                Patient Demographics: Age {patient_context.age}, Sex {patient_context.sex}
                
                For each significant piece of evidence, estimate:
                1. Sensitivity: What percentage of patients with {diagnosis_name} would have this finding?
                2. Specificity: What percentage of patients WITHOUT {diagnosis_name} would NOT have this finding?
                
                Consider the overall clinical picture and provide:
                - Overall Sensitivity (0.0-1.0): How likely is this evidence pattern in patients who DO have {diagnosis_name}?
                - Overall Specificity (0.0-1.0): How likely is this evidence pattern to be ABSENT in patients who DON'T have {diagnosis_name}?
                
                Guidelines:
                - High sensitivity (0.8-1.0): Very typical findings for this diagnosis
                - Moderate sensitivity (0.4-0.7): Somewhat typical findings
                - Low sensitivity (0.1-0.3): Atypical but possible findings
                - High specificity (0.8-1.0): Very specific to this diagnosis
                - Moderate specificity (0.5-0.7): Somewhat specific findings
                - Low specificity (0.1-0.4): Non-specific findings seen in many conditions
                
                Respond with only two decimal numbers: sensitivity,specificity (e.g., "0.75,0.85")
                """
                
                likelihood_response = await self._llm.chat([
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a clinical diagnostician estimating sensitivity and specificity of clinical findings. Provide only numerical estimates."),
                    ChatMessage(role=ChatRole.USER, content=likelihood_prompt)
                ])
                
                # Extract sensitivity and specificity
                likelihood_text = likelihood_response.content.strip()
                
                # Try to extract two decimal numbers
                numbers = re.findall(r'[01]?\.\d+', likelihood_text)
                if len(numbers) >= 2:
                    sensitivity = max(0.01, min(1.0, float(numbers[0])))  # Prevent 0 division
                    specificity = max(0.01, min(1.0, float(numbers[1])))  # Prevent 0 division
                    
                    # Calculate positive likelihood ratio: LR+ = sensitivity / (1 - specificity)
                    # This represents P(Evidence|Disease) / P(Evidence|No Disease)
                    likelihood_ratio = sensitivity / (1 - specificity)
                    
                    # Convert likelihood ratio to a normalized likelihood value
                    # For Bayes calculation: P(Evidence|Disease) = LR+ * P(Evidence|No Disease)
                    # We need to estimate P(Evidence|No Disease) based on specificity
                    # prob_evidence_no_disease = 1 - specificity
                    prob_evidence_given_disease = sensitivity
                    
                    print(f"[bayesian_likelihood] {diagnosis_name}: Sensitivity={sensitivity:.3f}, Specificity={specificity:.3f}")
                    print(f"[bayesian_likelihood] {diagnosis_name}: LR+={likelihood_ratio:.3f}, P(E|D)={prob_evidence_given_disease:.3f}")
                    
                    return prob_evidence_given_disease
                    
                else:
                    print(f"[bayesian_likelihood] Could not parse sensitivity/specificity from: {likelihood_text}")
                    # Fallback to moderate values
                    return 0.5
                    
            except Exception as e:
                print(f"[bayesian_likelihood] Error calculating likelihood: {e}")
                return 0.5  # Default likelihood

        async def _get_focused_candidate_diagnoses(
            patient_context: PatientContext,
            supporting_evidence: List[str]
        ) -> List[str]:
            """Get a smaller, more focused list of candidate diagnoses (3-5 instead of 8-10)."""
            try:
                evidence_text = "; ".join(supporting_evidence) if supporting_evidence else "No specific evidence"
                
                prompt = f"""
                Given this clinical presentation, list the TOP 5-7 MOST LIKELY diagnoses only:
                
                Patient: Age {patient_context.age}, Sex {patient_context.sex}
                Clinical Evidence: {evidence_text}
                Vitals: {patient_context.vitals}
                Labs: {patient_context.labs}
                
                Rules:
                - List ONLY the 5-7 most probable diagnoses
                - Focus on common conditions first
                - Include 1-2 "cannot-miss" diagnoses if relevant
                - Be specific with medical terminology
                - Order by likelihood (most likely first)
                
                Format as a simple list:
                - Most likely diagnosis
                - Second most likely 
                - Third most likely
                - Fourth most likely  
                - Fifth most likely
                """
                
                response = await self._llm.chat([
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a medical diagnostician creating a focused differential diagnosis list. Keep it to exactly 5 diagnoses."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ])
                
                # Parse the response to extract diagnosis names
                lines = response.content.strip().split('\n')
                diagnoses: list[Any] = []
                
                for line in lines:
                    line = line.strip()
                    if line.startswith('-') or line.startswith('•') or line.startswith(str(len(diagnoses) + 1)):
                        # Remove bullet points, numbers, etc.
                        diagnosis = line.lstrip('- •0123456789. ').strip()
                        if diagnosis and len(diagnosis) > 3:
                            diagnoses.append(diagnosis)
                
                # Ensure we have exactly 5 diagnoses, pad with common ones if needed
                if len(diagnoses) < 5:
                    common_fallbacks = [
                        "Viral upper respiratory infection",
                        "Hypertension", 
                        "Type 2 diabetes mellitus",
                        "Anxiety disorder",
                        "Gastroenteritis"
                    ]
                    
                    for fallback in common_fallbacks:
                        if len(diagnoses) >= 5:
                            break
                        if fallback not in diagnoses:
                            diagnoses.append(fallback)
                
                # Limit to exactly 5
                diagnoses = diagnoses[:5]
                
                print(f"[focused_candidates] Selected {len(diagnoses)} focused candidate diagnoses")
                return diagnoses
                
            except Exception as e:
                print(f"[focused_candidates] Error getting candidates: {e}")
                # Return minimal common diagnoses as fallback
                return [
                    "Viral upper respiratory infection",
                    "Hypertension",
                    "Type 2 diabetes mellitus", 
                    "Anxiety disorder",
                    "Gastroenteritis"
                ]

        async def _calculate_likelihood_for_marginal(
            diagnosis_name: str,
            patient_context: PatientContext,
            supporting_evidence: List[str]
        ) -> float:
            """
            Simplified likelihood calculation for marginal probability.
            Returns P(Evidence|Diagnosis) for use in law of total probability.
            """
            try:
                # Prepare patient evidence (simplified)
                patient_evidence = []
                
                if patient_context.vitals:
                    # Only include abnormal vitals to reduce noise
                    for k, v in patient_context.vitals.items():
                        if "high" in str(v).lower() or "low" in str(v).lower() or "abnormal" in str(v).lower():
                            patient_evidence.append(f"Vital: {k}={v}")
                
                if patient_context.labs:
                    # Only include abnormal labs
                    for k, v in patient_context.labs.items():
                        if "high" in str(v).lower() or "low" in str(v).lower() or "abnormal" in str(v).lower():
                            patient_evidence.append(f"Lab: {k}={v}")
                
                # Take only the most relevant supporting evidence
                relevant_evidence = supporting_evidence[:3]  # Limit to top 3 pieces of evidence
                patient_evidence.extend(relevant_evidence)
                
                evidence_text = "; ".join(patient_evidence) if patient_evidence else "No specific evidence"
                
                # Simplified, faster prompt
                prompt = f"""
                For {diagnosis_name}: How likely is this evidence if the patient has this diagnosis?
                
                Evidence: {evidence_text}
                Patient: Age {patient_context.age}, Sex {patient_context.sex}
                
                Rate 0.1-1.0:
                - 0.8-1.0: Very typical
                - 0.5-0.7: Moderately typical  
                - 0.2-0.4: Possible but uncommon
                - 0.1: Very unlikely
                
                Number only:
                """
                
                response = await self._llm.chat([
                    ChatMessage(role=ChatRole.SYSTEM, content="Estimate likelihood quickly. Respond with number only."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ])
                
                # Extract numerical value quickly
                response_text = response.content.strip()

                numbers = re.findall(r'[01]?\.\d+', response_text)
                
                if numbers:
                    likelihood = float(numbers[0])
                    return max(0.1, min(1.0, likelihood))
                else:
                    return 0.4  # Default moderate likelihood
                    
            except Exception as e:
                print(f"[likelihood_marginal] Error for {diagnosis_name}: {e}")
                return 0.4

        async def _batch_web_search_for_priors( # type: ignore
            diagnoses: List[str],
            patient_context: PatientContext
        ) -> dict[str, float]:
            """
            Perform batched web searches for prior probabilities of multiple diagnoses.
            This is much more efficient than sequential searches.
            """
            try:
                print(f"[batch_priors] Starting batch web search for {len(diagnoses)} diagnoses")
                
                # Prepare demographic context
                demographic_context = f"Age: {patient_context.age}, Sex: {patient_context.sex}"
                
                # Create a combined search query for all diagnoses
                diagnosis_list = ", ".join(diagnoses)
                combined_search_query = f"epidemiology prevalence incidence rates {diagnosis_list} age {patient_context.age} {patient_context.sex} population statistics medical literature"
                
                print(f"[batch_priors] Combined search query: {combined_search_query}")
                
                # Perform single web search for all diagnoses
                try:
                    active_lang = detect_language_code(combined_search_query or "")
                except Exception:
                    active_lang = "en"
                web_response = await self._web_search.search(
                    query=combined_search_query,
                    max_results=8,  # Get more results since we're searching for multiple conditions
                    patient_context=demographic_context,
                    search_intent="epidemiological_data",
                    target_language=(active_lang if active_lang and active_lang != "en" else None)
                )
                
                # Prepare web context for LLM analysis
                web_context = ""
                if web_response and web_response.results:
                    web_context = "\n".join([
                        f"Source {i+1}: {result.title}\nURL: {result.url}\nContent: {result.snippet}"
                        for i, result in enumerate(web_response.results)
                    ])
                    print(f"[batch_priors] Found {len(web_response.results)} web sources")
                else:
                    print("[batch_priors] No web results found, will use medical knowledge")
                
                # Use LLM to extract prior probabilities for all diagnoses at once
                batch_prior_prompt = f"""
                Extract epidemiological prior probabilities for multiple diagnoses based on web search results and medical knowledge.
                
                DIAGNOSES TO ANALYZE: {diagnoses}
                
                PATIENT DEMOGRAPHICS: {demographic_context}
                
                WEB SEARCH RESULTS:
                {web_context if web_context else "No specific web data available - use established medical knowledge"}
                
                For each diagnosis, estimate the prior probability (base rate) considering:
                1. General prevalence/incidence from search results or medical literature
                2. Age-specific and sex-specific rates for this demographic
                3. Population base rates from epidemiological studies
                4. Risk factors present in this demographic group
                
                REFERENCE RANGES:
                - Very common conditions (diabetes, hypertension): 0.1-0.3
                - Common conditions (pneumonia, UTI, viral infections): 0.05-0.15
                - Moderate conditions (autoimmune diseases, specific syndromes): 0.01-0.05
                - Rare conditions (genetic disorders, rare cancers): 0.001-0.01
                - Very rare conditions: 0.001-0.005
                
                Return ONLY a JSON object with diagnosis names as keys and probability numbers as values:
                {{
                    "diagnosis_1": 0.123,
                    "diagnosis_2": 0.045,
                    "diagnosis_3": 0.012,
                    ...
                }}
                
                Base estimates on web search results when available, otherwise use established medical knowledge.
                Ensure all probabilities are between 0.001 and 0.3.
                """
                
                try:
                    batch_response = await self._llm.chat([
                        ChatMessage(role=ChatRole.SYSTEM, content="You are a medical epidemiologist extracting disease prevalence data from web sources and medical knowledge. Return only JSON."),
                        ChatMessage(role=ChatRole.USER, content=batch_prior_prompt)
                    ], json_mode=True)
                    
                    if batch_response and batch_response.content:
                        # Parse JSON response
                        response_content = batch_response.content.strip()
                        
                        # Remove markdown code blocks if present
                        if response_content.startswith("```json"):
                            start_idx = response_content.find('\n') + 1
                            end_idx = response_content.rfind("```")
                            if start_idx > 0 and end_idx > start_idx:
                                response_content = response_content[start_idx:end_idx].strip()
                        elif response_content.startswith("```"):
                            start_idx = response_content.find('\n') + 1
                            end_idx = response_content.rfind("```")
                            if start_idx > 0 and end_idx > start_idx:
                                response_content = response_content[start_idx:end_idx].strip()
                        
                        priors_data = json.loads(response_content)
                        
                        # Validate and clean the results
                        validated_priors = {}
                        for diagnosis in diagnoses:
                            # Try exact match first
                            if diagnosis in priors_data:
                                prob = float(priors_data[diagnosis])
                                validated_priors[diagnosis] = max(0.001, min(0.3, prob))
                            else:
                                # Try partial matching
                                found_match = False
                                for key, value in priors_data.items():
                                    if diagnosis.lower() in key.lower() or key.lower() in diagnosis.lower():
                                        prob = float(value)
                                        validated_priors[diagnosis] = max(0.001, min(0.3, prob))
                                        found_match = True
                                        break
                                
                                if not found_match:
                                    # Default fallback
                                    validated_priors[diagnosis] = 0.03
                        
                        print(f"[batch_priors] Successfully extracted priors for {len(validated_priors)} diagnoses")
                        for diagnosis, prior in validated_priors.items():
                            print(f"[batch_priors] {diagnosis}: {prior:.3f}")
                        
                        return validated_priors
                        
                except json.JSONDecodeError as e:
                    print(f"[batch_priors] JSON parsing error: {e}")
                    # Fall back to individual searches for critical diagnoses
                    return await _fallback_individual_searches(diagnoses, patient_context)
                    
            except Exception as e:
                print(f"[batch_priors] Error in batch search: {e}")
                # Fall back to individual searches
                return await _fallback_individual_searches(diagnoses, patient_context)

        async def _fallback_individual_searches(
            diagnoses: List[str],
            patient_context: PatientContext
        ) -> dict[str, float]:
            """
            Fallback to individual web searches if batch search fails.
            Only search for the most critical diagnoses to save time.
            """
            print("[fallback_priors] Performing individual searches for top 3 diagnoses")
            
            priors = {}
            
            # Only search for top 3 most important diagnoses
            for diagnosis in diagnoses[:3]:
                try:
                    # Use default prior since individual web searches are removed
                    prior = 0.03
                    priors[diagnosis] = prior
                    print(f"[fallback_priors] {diagnosis}: {prior:.3f}")
                except Exception as e:
                    print(f"[fallback_priors] Error for {diagnosis}: {e}")
                    priors[diagnosis] = 0.03
            
            # Use defaults for remaining diagnoses to save time
            for diagnosis in diagnoses[3:]:
                priors[diagnosis] = 0.03
                print(f"[fallback_priors] {diagnosis}: 0.030 (default)")
            
            return priors


        @streaming_step("evaluate_query_complexity")
        async def evaluate_query_complexity(state: FlowState) -> FlowState:
            """Evaluate if the query needs patient data, web search, or can be answered directly."""
            try:
                # For research mode, always do full processing
                if state.diagnostic_mode == "research":
                    state.requires_full_processing = True
                    print("[query_complexity] Research mode: Full processing required")
                    return state

                # Create evaluation prompt based on diagnostic mode
                mode_context = {
                    "pre_meet": "preparing for a patient encounter",
                    "post_meet": "analyzing patient data for diagnosis", 
                    "chat": "general medical conversation"
                }.get(state.diagnostic_mode, "medical analysis")

                evaluation_prompt = f"""
                Analyze this query to determine if it requires patient data, web search, or can be answered directly:

                QUERY: "{state.user_prompt}"
                CONTEXT: User is in {state.diagnostic_mode} mode for {mode_context}
                PATIENT_ID_PROVIDED: {state.patient_id is not None}

                Classify the query type:

                REQUIRES_FULL_PROCESSING (needs patient data/web search):
                - Asks about specific patient symptoms, conditions, or medical history
                - Requests differential diagnoses or treatment plans
                - Asks about specific medications, lab results, or test interpretation
                - References "this patient", "my patient", patient-specific data
                - Asks for pre-visit preparation for a specific patient
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

        def should_parse_icd(state: FlowState) -> bool:
            """Conditional function to determine if ICD parsing should be performed."""
            # For pre_meet mode, only parse if differential diagnoses content is detected
            return getattr(state, 'should_parse_icd_codes', False)

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
        # Image generation nodes removed
        _builder.add_node("diagnose", diagnose)
        _builder.add_node("store_assistant_response", store_assistant_response)
        _builder.add_node("evaluate_icd_parsing_need", evaluate_icd_parsing_need)
        _builder.add_node("parse_icd", parse_icd)

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
                False: "diagnose"                        # Direct path - skip all heavy processing
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
        _builder.add_edge("intelligent_retrieve_chunks", "evaluate_web_search_need")


        # Image generation path removed; proceed directly to web search evaluation

        _builder.add_conditional_edges(
            "evaluate_web_search_need",
            needs_web_search,
            {
                True: "perform_web_search",
                False: "diagnose"
            }
        )

        _builder.add_edge("perform_web_search", "diagnose")
        _builder.add_edge("diagnose", "evaluate_icd_parsing_need")
        _builder.add_conditional_edges(
            "evaluate_icd_parsing_need",
            should_parse_icd,
            {
                True: "parse_icd",
                False: "store_assistant_response"
            }
        )
        
        _builder.add_edge("parse_icd", "store_assistant_response")
        _builder.add_edge("store_assistant_response", END)

        return _builder.compile()

    def _format_ehr_links(self, text: str) -> str:
        """Convert bare EHR URLs in parentheses to markdown links if preceded by a label.

        Examples converted:
        - Allergy (mould): https://... -> Allergy (mould): [EHR record](https://...)
        - According to the EHR record (Allergy Intolerance): https://... -> According to the EHR record ([Allergy Intolerance](https://...))
        - If already in [title](url) form, leave as-is.
        """
        if not text:
            return text

        # Already formatted [title](url) should be preserved
        # Pattern to find bare URLs
        url_pattern = r"(?P<url>https?://[\w\-\.\:/%#\?=&]+)"

        def repl(match: re.Match[str]) -> str:
            url = match.group("url")
            # If the url is already part of a markdown link, don't change
            # Look behind in a small window
            start = max(match.start() - 60, 0)
            context = text[start:match.start()]
            if "](" in context:  # naive safeguard
                return url
            # Try to capture a preceding label inside parentheses like (Label): URL or ([Label]): URL
            # We will replace just the URL with [EHR record](URL) if no better label
            return f"[EHR record]({url})"

        # Replace bare URLs not already markdown-formatted
        return re.sub(url_pattern, repl, text)

    def _normalize_markdown(self, text: str) -> str:
        """Normalize common markdown issues that can break rendering.

        - Ensure a blank line before headers (##, ###) if missing.
        - Promote common label lines that precede a list into real headers.
        - Remove trailing/duplicate spaces after header markers.
        """
        if not text:
            return text

        # Ensure blank line before headers and infer headers for standalone label lines
        lines = text.split('\n')
        normalized: list[str] = []
        for i, raw_line in enumerate(lines):
            line = raw_line
            is_header = line.startswith('## ') or line.startswith('### ')
            if is_header and normalized and normalized[-1].strip() != '':
                normalized.append('')  # insert blank line
            # Strip extra spaces/tabs after header markers
            if line.startswith('##'):
                line = line.replace('##\t', '## ').replace('##  ', '## ')
            if line.startswith('###'):
                line = line.replace('###\t', '### ').replace('###  ', '### ')

            # Heuristic: if this line looks like a section label and next line is a list, promote to header
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
        """Create a reasoning prompt based on the current context."""
        if state.diagnostic_mode == "pre_meet":
            return """Think through this pre-consultation preparation step by step:
1. What key information do I have about this patient from their EHR and previous conversations?
2. What are the main concerns or conditions I need to focus on?
3. What critical information is missing that I need to gather during the encounter?
4. What specific questions should I ask the patient to fill knowledge gaps?
5. What physical examinations or tests should I plan to perform?
6. Are there any red flags or urgent concerns I need to address immediately?
7. What preparation will help me provide the best care for this patient?"""
            
        elif state.diagnostic_mode == "post_meet":
            return """Think through this post-encounter diagnostic analysis step by step:
1. What are the key symptoms, findings, and patient history from all sources?
2. What are the most likely diagnostic possibilities based on the clinical picture?
3. What evidence supports or refutes each potential diagnosis?
4. What is my primary diagnosis and differential diagnoses with confidence levels?
5. What treatment plan is most appropriate if diagnosis is established?
6. What additional testing or specialist referrals are needed?
7. What follow-up care and monitoring should be implemented?"""
            
        elif state.diagnostic_mode == "research":
            return """Think through this complex case research analysis step by step:
1. Why does this case require deep research and what makes it complex?
2. What does current medical literature say about similar cases?
3. What are all possible diagnoses including rare and atypical presentations?
4. What are the various treatment approaches described in recent studies?
5. Are there any cutting-edge therapies or clinical trials relevant to this case?
6. What expert consultations or specialized testing should be considered?
7. What are the key learning points and clinical pearls from this research?"""
            
        else:  # chat mode
            return """Think through this medical conversation step by step:
1. What is the user asking about?
2. What relevant medical information do I have available?
3. What key points should I address in my response?
4. How can I provide helpful, accurate medical guidance?
5. Are there any important warnings or considerations to mention?"""

    async def get_or_create_session(
        self, 
        user_id: str, 
        patient_id: str | None, 
        mode: str,
        session_id: str | None = None,
        allow_join_existing: bool = True
    ) -> str:
        """Get existing session or create a new one, with multi-user support."""
        
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
                mode="chat" if chat_mode else "diagnose",
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
        
        if session_id and user_id:
            await self._vec.update_session_activity(session_id=session_id, user_id=user_id)
        
        if patient is not None:
            if hasattr(data, "model_dump"):
                return self._to_output(data.model_dump())
            else:
                return self._to_output(data)
        else:
            return self.chat_output(data)

    def run_stream(self, patient: PatientContext | None = None, user_prompt: str | None = None, chat_mode: bool = False, diagnostic_mode: str = "post_meet", user_id: str | None = None, session_id: str | None = None) -> AsyncGenerator[dict[str, Any], None]:
        """Return an async generator that yields chunks as they stream from the graph."""

        async def _stream_generator():
            if user_id:
                session_id_final = await self.get_or_create_session(
                    user_id=user_id,
                    patient_id=patient.patient_id if patient else None,
                    mode=diagnostic_mode if not chat_mode else "chat",
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
                    "diagnostic_mode": diagnostic_mode if not chat_mode else "chat",
                    "user_id": user_id,
                    "session_id": session_id_final,
                    "should_stream_response": True,  # Indicate we want streaming
                    "stream_callback": stream_callback  # Pass the callback
                }
            else:
                initial_input = {
                    "user_prompt": prompt,
                    "chat_mode": chat_mode,
                    "diagnostic_mode": diagnostic_mode if not chat_mode else "chat",
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
                                    if current_state.get("current_step") == "generate_image":
                                        if current_state.get("step_status") == "in_progress":
                                            status_update["is_long_running"] = True
                                            status_update["estimated_time"] = "30-60 seconds"
                                        elif current_state.get("step_status") == "completed" and current_state.get("generated_image"):
                                            status_update["image_generated"] = True
                                            status_update["image_id"] = current_state["generated_image"].generation_id
                                
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
                    
                    # Include structure differential diagnoses in completion if they exist
                    if previous_state and previous_state.get("parsed_response") and hasattr(previous_state["parsed_response"], 'differential'):
                        completion_update["differential_diagnoses"] = [
                            {
                                "icd_code": diff.icd_code,
                                "diagnosis_name": diff.diagnosis_name,
                                "confidence": diff.confidence,
                                "reasoning": diff.reasoning,
                                "supporting_evidence": diff.supporting_evidence
                            }
                            for diff in previous_state["parsed_response"].differential
                        ]
                        completion_update["diagnosis_result"] = previous_state["parsed_response"]

                    # Include image information in completion
                    if previous_state and previous_state.get("generated_image"):
                        completion_update["generated_image"] = {
                            "image_id": previous_state["generated_image"].generation_id,
                            "prompt": previous_state["generated_image"].prompt,
                            "created_at": previous_state["generated_image"].created_at.isoformat() if hasattr(previous_state["generated_image"], 'created_at') else None,
                            "metadata": previous_state["generated_image"].metadata if hasattr(previous_state["generated_image"], 'metadata') else {}
                        }
                    
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

    def _to_output(self, data: dict[str, Any]) -> DiagnosisResult:
        """Convert raw dict emitted by compiled_graph to DiagnosisResult."""
        
        # Handle web search info
        web_search_info = WebSearchInfo()
        if data.get("web_search_response"):
            web_response = data["web_search_response"]
            
            # Check if the response actually contains citations
            response_content = data["llm_response"].content if data["llm_response"] else ""
            citations_found = []
            
            for result in web_response.results[:5]:
                if result.url in response_content or result.title in response_content:
                    citations_found.append(result.url)
            
            web_search_info = WebSearchInfo(
                web_search_performed=True,
                sources_consulted=[result.url for result in web_response.results[:5]],
                sources_cited_in_response=citations_found,
                search_summary=web_response.summary,
                source_count=len(web_response.results),
                citations_included=len(citations_found) > 0
            )
        
        # Handle cross-session history info
        cross_session_info = CrossSessionHistoryInfo()
        if data.get("relevant_cross_session_history"):
            cross_session_info = CrossSessionHistoryInfo(
                cross_session_search_performed=True,
                historical_sessions_consulted=len(set(item.get("session_id") for item in data["relevant_cross_session_history"] if item.get("session_id"))),
                historical_messages_found=len(data["relevant_cross_session_history"]),
                oldest_reference=min((item.get("timestamp") for item in data["relevant_cross_session_history"] if item.get("timestamp")), default=None)
            )
        else:
            cross_session_info = CrossSessionHistoryInfo(
                cross_session_search_performed=data.get("needs_cross_session_search", False),
                historical_sessions_consulted=0,
                historical_messages_found=0,
                oldest_reference=None
            )
        
        # Handle generated image info
        generated_image_info = GeneratedImageInfo()
        if data.get("generated_image"):
            generated_image = data["generated_image"]
            generated_image_info = GeneratedImageInfo(
                image_generated=True,
                image_id=generated_image.generation_id,
                image_prompt=generated_image.prompt,
                generation_metadata=generated_image.metadata,
                model_info=generated_image.model_info
            )
        
        return DiagnosisResult(
            patient_id=data["patient_id"],
            primary_icd=data["primary_icd"], 
            differential=data["differential"],
            confidence=data["confidence"],
            explanation=self._format_ehr_links(data["llm_response"].content) if data["llm_response"] else "",
            created_by_user_id=data.get("user_id"),
            is_ai_generated=True,
            session_id=data.get("session_id"),
            web_search_info=web_search_info,
            cross_session_history_info=cross_session_info,
            generated_image=generated_image_info,
            retrieved_chunks=data.get("retrieved_chunks", []),
            retrieval_reasoning=data.get("retrieval_reasoning"),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )

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

        generated_image_info = {}
        if data.get("generated_image"):
            generated_image = data["generated_image"]
            generated_image_info = {
                "image_generated": True,
                "image_id": generated_image.generation_id,
                "image_prompt": generated_image.prompt,
                "generation_metadata": generated_image.metadata,
                "model_info": generated_image.model_info
            }
        else:
            generated_image_info = {
                "image_generated": False
            }

        return {
            "explanation": self._format_ehr_links(data["llm_response"].content) if data["llm_response"] else "",
            "created_by_user_id": data.get("user_id"),
            "is_ai_generated": True,
            "web_search_info": web_search_info,
            "cross_session_history_info": cross_session_info,
            "generated_image": generated_image_info,
            "session_id": data.get("session_id"),
        }
    
    def _extract_source_summary(self, patient_ctx: PatientContext) -> str:
        """Extract and format source information from patient context."""
        source_summary = []
        
        # Helper to format sources for a data type
        def format_sources(data_type: str, data_dict: dict, sources_dict: dict) -> list:
            sources = []
            for key, value in data_dict.items():
                if key in sources_dict:
                    source = sources_dict[key]
                    sources.append(f"  • {key}: {value}")
                    sources.append(f"    └─ Source: {source.resource_url}")
                    sources.append(f"    └─ Recorded: {source.timestamp.strftime('%Y-%m-%d %H:%M')}")
                    if source.category:
                        sources.append(f"    └─ Category: {source.category}")
                    sources.append("")  # Empty line for spacing
            return sources
        
        # Process each data type
        data_types = [
            ("Vital Signs", patient_ctx.vitals, patient_ctx.vitals_sources),
            ("Laboratory Results", patient_ctx.labs, patient_ctx.labs_sources),
            ("Medications", patient_ctx.medications, patient_ctx.medications_sources),
            ("Allergies", patient_ctx.allergies, patient_ctx.allergies_sources),
            ("Diagnoses", patient_ctx.diagnoses, patient_ctx.diagnoses_sources),
            ("Immunizations", patient_ctx.immunizations, patient_ctx.immunizations_sources),
            ("Medication Statements", patient_ctx.medication_statement, patient_ctx.medication_statement_sources),
            ("Questionnaire Responses", patient_ctx.questionnaire_response, patient_ctx.questionnaire_response_sources),
            ("Encounters", patient_ctx.encounters, patient_ctx.encounters_sources),
            ("Exams", patient_ctx.exam, patient_ctx.exam_sources),
            ("Procedures", patient_ctx.procedure, patient_ctx.procedure_sources),
            ("Social History", patient_ctx.social_history, patient_ctx.social_history_sources),
            ("Imaging", patient_ctx.imaging, patient_ctx.imaging_sources)
        ]
        
        for data_type_name, data_dict, sources_dict in data_types:
            if data_dict:
                source_summary.append(f"{data_type_name}:")
                source_summary.extend(format_sources(data_type_name.lower(), data_dict, sources_dict))
        
        if not source_summary:
            return "No specific data sources available for this patient."
        
        return "\n".join(source_summary)

    @property
    def vector_store(self) -> VectorStore:
        """Access to the underlying vector store."""
        return self._vec

    
