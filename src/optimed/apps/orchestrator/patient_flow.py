from __future__ import annotations

import uuid 
import json
import time
from typing import List, Any, Union, AsyncGenerator

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from optimed.core.domain import PatientContext, ChatMessage, DiagnosisResult, ChatRole, UserAction, User

from optimed.core.ports import DiagnosticEngine, FHIRRepository, LLMClient, VectorStore, UserRepository

from optimed.embeddings.minilm import embed
from optimed.embeddings.service import embed_and_store



SYSTEM_MSG_DIAGNOSE = ChatMessage(role=ChatRole.SYSTEM, 
                         content="""You are OptiMed‑AI, a clinical reasoning assistant and medical chat companion.
                                    
                                    IMPORTANT: If you see previous conversation history marked between === lines, YOU MUST acknowledge and reference it in your response. This shows continuity of care.
                                    
                                    When patient context is provided:
                                    - Use only the provided patient context to inform your responses
                                    - Do not reference other patients' data
                                    - Combine real‑time vitals, labs, and evidence to help physicians
                                    - Provide clinical diagnoses with explanations and cite sources
                                    - Focus on medical accuracy and clinical reasoning
                                    - Reference previous conversation history when available""")

SYSTEM_MSG_CHAT = ChatMessage(role=ChatRole.SYSTEM, 
                         content="""You are OptiMed‑AI, a clinical reasoning assistant and medical chat companion.
                         
                                    IMPORTANT: If you see previous conversation history marked between === lines, YOU MUST acknowledge and reference it in your response.
                                    
                                    - Engage in friendly conversation
                                    - Provide general health advice and wellness tips
                                    - Focus on being helpful and informative
                                    - Reference previous conversation history to maintain context
                                    - Continue conversations naturally based on chat history""") # Needs to be more specific and properly created to make the LLM function properly

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

    chat_mode: bool = False # If True, we are in chat mode and not diagnosing a patient

    chat_history: List[ChatMessage] = Field(default_factory=list)

    user_id: str | None = None  # Optional user ID for tracking who initiated the diagnosis
    user_context: User | None = None  # Optional user context for additional information
    session_id: str | None = None  # Optional session ID for tracking the conversation


class LangGraphDiagnosticEngine(DiagnosticEngine):
    """Concrete engine that streams or returns full result."""

    def __init__(self, fhir_repo: FHIRRepository, vector_store: VectorStore, llm_client: LLMClient, user_repo: UserRepository, default_prompt: str = "Provide the most likely diagnosis"):
        self._fhir = fhir_repo
        self._vec = vector_store
        self._llm = llm_client
        self._user_repo = user_repo
        self._default_prompt = default_prompt
        self._compiled_graph = self._build_graph()

    def _build_graph(self) -> Any:
        """Build the LangGraph state graph for diagnosis."""
        async def fetch_patient(state: FlowState) -> FlowState:
            state.patient_ctx = await self._fhir.get_patient(str(state.patient_id)) # Cast to str to avoid type errors
            return state


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
            

        async def load_chat_history(state: FlowState) -> FlowState:
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
                            print(f"[load_chat_history] Error parsing item: {e}")
                            continue
                            
                    state.chat_history = chat_messages
                except Exception as e:
                    print(f"[load_chat_history] Error loading chat history: {e}")
                    state.chat_history = []
            else:
                state.chat_history = []

            return state

        async def retrieve_chunks(state: FlowState) -> FlowState:
            # 0) If we have patient_ctx, ensure it’s in the vector DB under “clinical” + patient_id
            if state.patient_ctx:
                # serialize patient context once
                patient_json = state.patient_ctx.model_dump_json(indent=2)
                try:
                    # embed the patient JSON to get a real vector
                    patient_vec = await embed(patient_json)
                    existing = await self._vec.similarity_search(
                        patient_vec,
                        top_k=1,
                        filter_={"namespace": "clinical", "patient_id": str(state.patient_id)},
                    )
                except Exception as e:
                    # if embedding or search fails, log and treat as "not found"
                    print(f"[retrieve_chunks] existence check failed: {e}")
                    existing = []

                if not existing:
                    try:
                        await embed_and_store(
                            namespace="clinical",
                            object_type="PatientContext",
                            object_id=str(state.patient_id),
                            text={"content": patient_json},
                            metadata={"patient_id": state.patient_id},
                        )
                    except Exception as e:
                        print(f"[retrieve_chunks] embed_and_store failed: {e}")

            # 1) ONLY search for THIS patient's data
            if state.patient_id:
                q_vec = await embed(state.user_prompt)
                rows = await self._vec.similarity_search(
                    q_vec,
                    top_k=3,  # Reduced from 5
                    filter_={
                        "namespace": "clinical", 
                        "patient_id": str(state.patient_id)  # CRUCIAL: Only this patient
                    },
                )
            else:
                rows = []

            # 2) If no patient-specific rows, use patient context directly
            if not rows and state.patient_ctx:
                state.retrieved_chunks = [state.patient_ctx.model_dump_json(indent=2)]
                return state

            # 3) Extract text and ensure it's from the right patient
            patient_specific_chunks = []
            if state.patient_ctx:
                for row in rows:
                    chunk_text = row[2] if len(row) > 2 else row[1]
                    # Verify this chunk is actually about our patient
                    patient_name = state.patient_ctx.name if state.patient_ctx else ""
                    if str(state.patient_id) in chunk_text or patient_name in chunk_text:
                        patient_specific_chunks.append(chunk_text)
                    else:
                        print(f"[retrieve_chunks] Filtered out chunk not related to patient {state.patient_id}")
            
            state.retrieved_chunks = patient_specific_chunks
            return state


        async def diagnose(state: FlowState) -> FlowState:


            if state.chat_mode:
                messages = [SYSTEM_MSG_CHAT] 
            else:
                messages = [SYSTEM_MSG_DIAGNOSE] 

            if state.user_context:
                user_info = ChatMessage(
                    role=ChatRole.USER,
                    content=f"Current user: {state.user_context.display_name} ({state.user_context.role.value})"
                )
                messages.append(user_info)

            history = state.chat_history[-25:]

            if history:
                # Add a clear header
                history_header = ChatMessage(
                    role=ChatRole.USER,
                    content=f"=== PREVIOUS CONVERSATION HISTORY FOR PATIENT {state.patient_id} ==="
                )
                messages.append(history_header)
                
                # Add the actual history
                for i, msg in enumerate(history):
                    messages.append(msg)
                
                # Add footer to make it clear
                history_footer = ChatMessage(
                    role=ChatRole.USER,
                    content="=== END OF CONVERSATION HISTORY ==="
                )
                messages.append(history_footer)


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
                user_id=state.user_id,  # Include user ID if available
                user_role=state.user_context.role if state.user_context else None,  # Use user role from context
            )

            messages.append(user)

            state.llm_response = await self._llm.chat(messages)

            #state.chat_history.extend([user, state.llm_response])

            current_timestamp = str(int(time.time() * 1000))

            await embed_and_store(
                namespace="chat_history",
                object_type="ChatMessage",
                object_id=str(uuid.uuid4()),
                text={
                    "content": user.content, 
                    "role": user.role.value,
                    "timestamp": current_timestamp,  # Add timestamp to content
                    "session_id": state.session_id,  # Include session ID in metadata
                    "user_id": state.user_id,  # Include user ID in metadata
                    "user_role": state.user_context.role.value if state.user_context else None,  # Include user role
                    "user_name": state.user_context.display_name if state.user_context else "Unknown User"
                },
                metadata={
                    "patient_id": state.patient_id if state.patient_id else "general_chat",
                    "session_id": state.session_id,  # Include session ID in metadata
                    "role": user.role.value,
                    "timestamp": current_timestamp,
                    "namespace": "chat_history",
                    "user_id": state.user_id,  # Include user ID in metadata
                    "user_role": state.user_context.role.value if state.user_context else None,  # Include user role
                },
            )

            await embed_and_store(
                namespace="chat_history",
                object_type="AssistantReply",
                object_id=str(uuid.uuid4()),
                text={
                    "content": state.llm_response.content if state.llm_response else "", 
                    "role": ChatRole.ASSISTANT.value,
                    "timestamp": str(int(time.time() * 1000) + 1),  # Assistant comes after user
                    "session_id": state.session_id,  # Include session ID in metadata
                    "responding_to_user": state.user_id,  # Include user ID in metadata
                    "responding_to_role": state.user_context.role.value if state.user_context else None,  # Include user role
                },
                metadata={
                    "patient_id": state.patient_id if state.patient_id else "general_chat",
                    "session_id": state.session_id,  # Include session ID in metadata
                    "role": ChatRole.ASSISTANT.value,
                    "timestamp": str(int(time.time() * 1000) + 1),
                    "namespace": "chat_history",
                    "responding_to_user": state.user_id,  # Include user ID in metadata
                }
            )

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
                        "session_id": state.session_id
                    }
                )
                await self._user_repo.log_action(action)

            return state


        async def parse_icd(state: FlowState) -> FlowState:
            """
            Currently uses claude to parse the ICD code from the response but can be replaced 
            with a proper regex or a more sophisticated parsing method in the future.
            """
            if state.patient_ctx:
                try:
                    prompt = (
                        "Return JSON with fields primary_icd, differential (list), "
                        f"confidence (0-1) for the following medical diagnosis:\n\n{state.llm_response.content if state.llm_response else ''}\n\n"
                    )
                    parsed = await self._llm.chat([SYSTEM_MSG_DIAGNOSE, ChatMessage(role=ChatRole.USER, content=prompt)], json_mode=True)
                    data = json.loads(parsed.content)
                    state.primary_icd = data["primary_icd"] or "Unknown"
                    state.differential = data["differential"] or []
                    state.confidence = data["confidence"] or 0.0
                except Exception as e:
                    print(f"[parse_icd] Error parsing ICD: {e}")
                    # Fallback values in case of error
                    state.primary_icd = "Unknown"
                    state.differential = []
                    state.confidence = 0.0
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
        _builder.add_node("load_user_context", load_user_context)  # Load user context if available
        _builder.add_node("load_chat_history", load_chat_history)
        _builder.add_node("fetch_patient", fetch_patient)
        _builder.add_node("retrieve_chunks", retrieve_chunks)
        _builder.add_node("diagnose", diagnose)
        _builder.add_node("parse_icd", parse_icd)

        _builder.set_entry_point("load_user_context")  # Start with loading user context

        # Add edges for user context loading
        _builder.add_edge("load_user_context", "check_patient")

        # Conditional logic right at the start
        _builder.add_conditional_edges(
            "check_patient",
            has_patient,
            {
                True: "load_chat_history",      # Patient ID provided -> fetch details
                False: "retrieve_chunks"    # No patient ID -> skip to chunks
            }
        )

        # Linear flow after patient fetch
        _builder.add_edge("load_chat_history", "fetch_patient")
        _builder.add_edge("fetch_patient", "retrieve_chunks")
        _builder.add_edge("retrieve_chunks", "diagnose")
        _builder.add_edge("diagnose", "parse_icd")
        _builder.add_edge("parse_icd", END)

        return _builder.compile()


    async def run(self, patient: PatientContext | None = None, user_prompt: str | None = None, chat_mode: bool = False, user_id: str | None = None, session_id: str | None = None) -> Union[DiagnosisResult,  dict]:

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
        
        if patient is not None:
            if hasattr(data, "model_dump"):
                return self._to_output(data.model_dump())
            else:
                return self._to_output(data)
        else:
            return self.chat_output(data)

    def run_stream(self, patient: PatientContext, user_prompt: str | None = None) -> AsyncGenerator[dict[str, Any], None]:
        """Return an async generator that yields chunks as they stream from the graph."""

        async def _stream_generator():
            prompt = user_prompt or self._default_prompt

            async for update in self._compiled_graph.astream({
                "patient_id": patient.patient_id,
                "user_prompt": prompt,
            }):
                yield update

        return _stream_generator()

    def _to_output(self, data: dict[str, Any]) -> DiagnosisResult:
        """Convert raw dict emitted by compiled_graph to DiagnosisResult."""
        return DiagnosisResult(
            patient_id=data["patient_id"],
            primary_icd=data["primary_icd"], 
            differential=data["differential"],
            confidence=data["confidence"],
            explanation=data["llm_response"].content if data["llm_response"] else "",
            created_by_user_id=data.get("user_id"),  # Use user_id from state if available
            is_ai_generated=True,  # Always true for LangGraph engine
        )

    def chat_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert raw dict emitted by compiled_graph to a chat output format."""
        return {
            "explanation": data["llm_response"].content if data["llm_response"] else "",
            "created_by_user_id": data.get("user_id"),  # Use user_id from state if available
            "is_ai_generated": True,  # Always true for LangGraph engine
        }
    
    @property
    def vector_store(self) -> VectorStore:
        """Access to the underlying vector store."""
        return self._vec

    
