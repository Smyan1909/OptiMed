from __future__ import annotations
from .streaming_decorators import streaming_step
from .streaming_llm import StreamingLLMWrapper

import uuid 
import json
import time
from typing import List, Any, Union, AsyncGenerator, Optional
from datetime import datetime

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from optimed.core.domain import PatientContext, ChatMessage, DiagnosisResult, ChatRole, UserAction, User, WebSearchResponse, ImageGenerationRequest, GeneratedImage, ImageGenerationContext, WebSearchInfo, CrossSessionHistoryInfo, GeneratedImageInfo, GeneratedImagePurpose

from optimed.core.ports import DiagnosticEngine, FHIRRepository, LLMClient, VectorStore, UserRepository, WebSearchService, ImageGenerationService, GeneratedImageRepository

from optimed.apps.orchestrator.connection_service import UserEHRConnectionService

from optimed.embeddings.minilm import embed
from optimed.embeddings.service import embed_and_store



# Single system message for information relay only
SYSTEM_MSG_INFO_RELAY = ChatMessage(role=ChatRole.SYSTEM, 
                         content="""You are CLARA, a clinical information assistant that helps healthcare professionals access and understand patient information and medical knowledge.

                                    IMPORTANT INSTRUCTIONS:
                                    1. If you see previous conversation history marked between === lines, YOU MUST acknowledge and reference it in your response.
                                    2. If web search results are provided, YOU MUST cite the specific sources by including the titles and URLs in your response.
                                    3. When citing web sources, use this format: "According to [Source Title](URL)" or "As reported in [Source Title](URL)"
                                    4. Always include at least 2-3 source citations when web search results are available.
                                    5. DO NOT add source citations when web search results are not used.
                                    
                                    YOUR ROLE:
                                    - Answer questions about patient demographics, medical history, and records
                                    - Provide information about medications, dosages, and interactions
                                    - Explain medical procedures and terminology
                                    - Share factual medical information from reliable sources
                                    - Help locate and understand information in patient records
                                    - Engage in helpful medical conversations and provide general health guidance
                                    - Reference previous conversation history to maintain context
                                    
                                    IMPORTANT RESTRICTIONS:
                                    - You provide information and educational content, not diagnostic conclusions
                                    - You do not generate differential diagnoses or treatment recommendations
                                    - You do not interpret symptoms for diagnostic purposes
                                    - Always refer clinical decision-making to qualified healthcare providers
                                    
                                    Keep responses helpful, informative, and factual while emphasizing that clinical decisions should be made by qualified healthcare providers.""")


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
    total_steps: int = 10  # Reduced from 12 since we removed ICD parsing steps
    completed_steps: int = 0
    streaming_updates: List[dict] = Field(default_factory=list)

    # Remove diagnostic-specific streaming fields
    # prelim_diagnosis_name: str = ""
    # diff_diag_compute_step: str = ""


class LangGraphInformationEngine(DiagnosticEngine):
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
                
                # Perform search
                search_response = await self._web_search.search(
                    query=search_query,
                    max_results=8,
                    patient_context=patient_context_str,
                    search_intent="clinical_information"
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

        @streaming_step("evaluate_image_generation_need")
        async def evaluate_image_generation_need(state: FlowState) -> FlowState:
            """Evaluate if image generation would be helpful for this query."""
            if not self._image_generation:
                state.image_generation_needed = False
                return state
            
            try:
                # Check if service is available
                if not await self._image_generation.is_available():
                    print("[image_generation] Service not available")
                    state.image_generation_needed = False
                    return state
                
                # Convert chat history from ChatMessage objects to dictionaries
                chat_history_dicts = []
                if state.chat_history:
                    for chat_msg in state.chat_history:
                        if hasattr(chat_msg, 'role') and hasattr(chat_msg, 'content'):
                            # It's a ChatMessage object, convert to dict
                            chat_dict = {
                                "role": chat_msg.role.value if hasattr(chat_msg.role, 'value') else str(chat_msg.role),
                                "content": chat_msg.content,
                                "timestamp": chat_msg.timestamp.isoformat() if hasattr(chat_msg, 'timestamp') and chat_msg.timestamp else None,
                                "user_id": getattr(chat_msg, 'user_id', None),
                                "metadata": getattr(chat_msg, 'metadata', {})
                            }
                            chat_history_dicts.append(chat_dict)
                        elif isinstance(chat_msg, dict):
                            # It's already a dict, use as-is
                            chat_history_dicts.append(chat_msg)
                
                # Create context for evaluation
                context = ImageGenerationContext(
                    user_query=state.user_prompt,
                    patient_context=state.patient_ctx,
                    chat_history=chat_history_dicts,
                    medical_context=state.retrieved_chunks[0] if state.retrieved_chunks else None,
                    generation_purpose=GeneratedImagePurpose.EDUCATIONAL  # Default purpose, can be changed later
                )
                
                state.image_generation_context = context
                
                # Evaluate need
                should_generate, image_prompt = await self._image_generation.evaluate_generation_need(context)
                
                state.image_generation_needed = should_generate
                state.image_generation_prompt = image_prompt or ""
                
                print(f"[image_generation] Generation needed: {should_generate}")
                if should_generate:
                    print(f"[image_generation] Prompt: {image_prompt}")
                
            except Exception as e:
                print(f"[image_generation] Error evaluating generation need: {e}")
                import traceback
                traceback.print_exc()
                state.image_generation_needed = False
            
            return state
        
        @streaming_step("generate_image",  is_long_running=True, estimated_time="30-60 seconds")
        async def generate_image(state: FlowState) -> FlowState:
            """Generate an image if needed."""
            if not state.image_generation_needed or not state.image_generation_prompt:
                return state
            
            try:
                # Create generation request
                request = ImageGenerationRequest(
                    prompt=state.image_generation_prompt,
                    width=1024,  # Higher resolution for Stability AI
                    height=1024,
                    guidance_scale=7.5,
                    num_inference_steps=30,  # Good balance of quality vs speed
                    user_id=state.user_id,
                    patient_id=state.patient_id,
                    session_id=state.session_id
                )
                
                # Generate image
                generated_image = await self._image_generation.generate_image(request) if self._image_generation else None
                state.generated_image = generated_image
                
                # Store image if repository is available
                if self._generated_image_repo and generated_image:
                    await self._generated_image_repo.store_generated_image(generated_image)

                print(f"[image_generation] Successfully generated image: {generated_image.generation_id}") if generated_image else print("[image_generation] No image generated")

            except Exception as e:
                print(f"[image_generation] Error generating image: {e}")
                # Don't fail the entire flow for image generation errors
                state.generated_image = None
            
            return state

        def needs_image_generation(state: FlowState) -> bool:
            """Conditional function to determine if image generation should be performed."""
            return state.image_generation_needed

        @streaming_step("load_current_session_history")
        async def load_current_session_history(state: FlowState) -> FlowState:
            """Load chat history for the patient if available."""
            if state.patient_id and state.session_id:
                try:
                    # Get history for this specific session
                    history_data = await self._vec.get_chat_history(
                        patient_id=str(state.patient_id), 
                        session_id=state.session_id,
                        limit=20
                    )

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
                query_embedding = await embed(state.user_prompt)
                
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
                            "similarity_score": row[0] if len(row) > 0 else 0.0
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
                    await embed("patient context"),
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
                    q_vec = await embed(state.user_prompt)
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
                        chunk_text = row[2] if len(row) > 2 else row[1]
                        similarity_score = row[0] if len(row) > 0 else 0.0
                        
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
                    embedding=await embed(state.user_prompt),
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
                        "message_type": "user"
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
                
                # Store assistant message
                await self._vec.upsert(
                    embedding_id=f"chat_{state.session_id}_{int(time.time() * 1000)}_assistant",
                    embedding=await embed(state.llm_response.content),
                    object_type="chat_message",
                    object_id=str(state.session_id),
                    content=message_content,
                    metadata=metadata
                )
                
            except Exception as e:
                print(f"[store_assistant_response] Error: {e}")
                import traceback
                traceback.print_exc()
            
            return state

        @streaming_step("provide_information")
        async def provide_information(state: FlowState) -> FlowState:
            # Use the single system message for information relay
            messages = [SYSTEM_MSG_INFO_RELAY]

            # For direct path (simple queries), use a simplified system message
            if not getattr(state, 'requires_full_processing', True):
                simple_system_msg = ChatMessage(
                    role=ChatRole.SYSTEM, 
                    content="""You are CLARA, a helpful medical information assistant. Provide clear, accurate medical information. For general medical questions, draw on your medical knowledge. Keep responses concise and helpful."""
                )
                messages = [simple_system_msg]

            if state.user_context:
                user_info = ChatMessage(
                    role=ChatRole.USER,
                    content=f"Current user: {state.user_context.display_name} ({state.user_context.role.value})"
                )
                messages.append(user_info)

            # Only add complex context for full processing path
            if getattr(state, 'requires_full_processing', True):
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
                    ctx = ChatMessage(
                        role=ChatRole.USER,
                        content="Patient context: \n" + state.patient_ctx.model_dump_json(indent=2),
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

            state.llm_response = await self._streaming_llm.chat_with_reasoning(messages=messages, state=state, reasoning_prompt=reasoning_prompt)

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
        _builder.add_node("evaluate_image_generation_need", evaluate_image_generation_need)
        _builder.add_node("generate_image", generate_image)
        _builder.add_node("provide_information", provide_information)
        _builder.add_node("store_assistant_response", store_assistant_response)

        _builder.set_entry_point("load_user_context")  # Start with loading user context

        # Add edges for user context loading
        _builder.add_edge("load_user_context", "evaluate_query_complexity")
        _builder.add_edge("evaluate_query_complexity", "store_user_message")
        # Branch based on query complexity
        _builder.add_conditional_edges(
            "store_user_message",
            requires_full_processing,
            {
                True: "check_patient",     # Full processing path
                False: "provide_information"               # Direct to information for simple queries
            }
        )

        # Conditional logic right at the start
        _builder.add_conditional_edges(
            "check_patient",
            has_patient,
            {
                True: "load_current_session_history",      # Patient ID provided -> fetch details
                False: "evaluate_cross_session_history_need"    # No patient ID -> skip to chunks
            }
        )

        # Linear flow after patient fetch
        _builder.add_edge("load_current_session_history", "fetch_patient")
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
        _builder.add_edge("intelligent_retrieve_chunks", "evaluate_image_generation_need")


        _builder.add_conditional_edges(
            "evaluate_image_generation_need",
            needs_image_generation,
            {
                True: "generate_image",
                False: "evaluate_web_search_need"
            }
        )

        _builder.add_edge("generate_image", "evaluate_web_search_need")

        _builder.add_conditional_edges(
            "evaluate_web_search_need",
            needs_web_search,
            {
                True: "perform_web_search",
                False: "provide_information"
            }
        )

        _builder.add_edge("perform_web_search", "provide_information")
        _builder.add_edge("provide_information", "store_assistant_response")
        _builder.add_edge("store_assistant_response", END)

        return _builder.compile()


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

    def run_stream(self, patient: PatientContext | None = None, user_prompt: str | None = None, chat_mode: bool = False, diagnostic_mode: str = "info_retrieval", user_id: str | None = None, session_id: str | None = None) -> AsyncGenerator[dict[str, Any], None]:
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
            
            # Create initial input
            if patient is not None:
                initial_input = {
                    "patient_id": patient.patient_id,
                    "user_prompt": prompt,
                    "chat_mode": chat_mode,
                    "info_retrieval_mode": diagnostic_mode if not chat_mode else "chat",
                    "user_id": user_id,
                    "session_id": session_id_final
                }
            else:
                initial_input = {
                    "user_prompt": prompt,
                    "chat_mode": chat_mode,
                    "info_retrieval_mode": diagnostic_mode if not chat_mode else "chat",
                    "user_id": user_id,
                    "session_id": session_id_final
                }

            previous_state = None
            reasoning_emitted = set()  # Track which reasoning steps we've emitted
            
            async for update in self._compiled_graph.astream(initial_input):
                # Extract the current state from the update
                for node_name, node_output in update.items():
                    if isinstance(node_output, dict):
                        current_state = node_output
                        
                        # Emit status updates for step changes with auto-generated detailed descriptions
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
                            
                            yield status_update
                        
                        # NEW: Emit reasoning steps as they become available from the streaming LLM
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
                                    yield reasoning_update
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
                            yield reasoning_complete_update
                        
                        previous_state = current_state
            
            # Emit final completion with image info
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
            

            # Include image information in completion
            if previous_state and previous_state.get("generated_image"):
                completion_update["generated_image"] = {
                    "image_id": previous_state["generated_image"].generation_id,
                    "prompt": previous_state["generated_image"].prompt,
                    "created_at": previous_state["generated_image"].created_at.isoformat() if hasattr(previous_state["generated_image"], 'created_at') else None,
                    "metadata": previous_state["generated_image"].metadata if hasattr(previous_state["generated_image"], 'metadata') else {}
                }
            
            yield completion_update

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
            explanation=data["llm_response"].content if data["llm_response"] else "",
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
            "explanation": data["llm_response"].content if data["llm_response"] else "",
            "created_by_user_id": data.get("user_id"),
            "is_ai_generated": True,
            "web_search_info": web_search_info,
            "cross_session_history_info": cross_session_info,
            "generated_image": generated_image_info,
            "session_id": data.get("session_id"),
        }
    
    @property
    def vector_store(self) -> VectorStore:
        """Access to the underlying vector store."""
        return self._vec

    
