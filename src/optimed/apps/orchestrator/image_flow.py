from __future__ import annotations

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph
from optimed.core.domain import PatientContext, ImagePixelData, DICOMMetadata
from optimed.core.ports import LLMClient, FHIRRepository, VectorStore, ImageEmbeddingService, ImageAnalysisEngine, UserRepository
from optimed.adapters.anthropic_claude.client import AnthropicClaudeClient
from optimed.apps.orchestrator.connection_service import UserEHRConnectionService
from optimed.core.logging_utils import get_logger, sanitize_user_id, sanitize_patient_id, sanitize_session_id, log_error

logger = get_logger(__name__)


class ImageAnalysisState(BaseModel):
    """State for image analysis flow."""
    pixel_data: Optional[ImagePixelData] = None
    metadata: Optional[DICOMMetadata] = None
    patient_context: Optional[PatientContext] = None
    query: str = ""
    user_id: Optional[str] = None
    patient_id: Optional[str] = None
    session_id: Optional[str] = None
    
    # Analysis results
    image_analysis: str = ""
    similar_cases: list[Dict[str, Any]] = Field(default_factory=list)
    final_response: str = ""
    
    # Patient-specific context
    retrieved_chunks: list[str] = Field(default_factory=list)
    chat_history: list[Dict[str, Any]] = Field(default_factory=list)
    user_context: Optional[Any] = None
    
    # Flow control
    error: Optional[str] = None


class LangGraphImageAnalysisEngine(ImageAnalysisEngine):
    """Engine for analyzing DICOM images with AI."""
    
    def __init__(
        self,
        llm_client: LLMClient,
        fhir_repo: FHIRRepository,
        vector_store: VectorStore,
        embedding_service: ImageEmbeddingService,
        user_repo: UserRepository,
        connection_service: Optional[UserEHRConnectionService] = None   
    ):
        self.llm_client = llm_client
        self.fhir_repo = fhir_repo
        self.vector_store = vector_store
        self.embedding_service = embedding_service
        self.user_repo = user_repo
        self.connection_service = connection_service

        # Build the graph
        self.graph = self._build_graph()
    
    def _build_graph(self) -> Any:
        """Build the LangGraph flow for image analysis."""
        graph = StateGraph(ImageAnalysisState)
        
        # Add nodes
        graph.add_node("load_user_context", self._load_user_context)
        graph.add_node("check_patient", self._check_patient_exists)
        graph.add_node("load_chat_history", self._load_chat_history)
        graph.add_node("fetch_patient", self._fetch_patient)
        graph.add_node("retrieve_chunks", self._retrieve_chunks)
        graph.add_node("analyze_image", self._analyze_image)
        graph.add_node("find_similar_cases", self._find_similar_cases)
        graph.add_node("synthesize_response", self._synthesize_response)
        graph.add_node("handle_error", self._handle_error)
        
        # Define flow - similar to patient flow
        graph.set_entry_point("load_user_context")
        
        # Linear flow for patient context
        graph.add_edge("load_user_context", "check_patient")
        
        # Conditional logic for patient handling
        graph.add_conditional_edges(
            "check_patient",
            self._has_patient,
            {
                True: "load_chat_history",   # Patient ID provided -> fetch details
                False: "analyze_image"       # No patient ID -> skip to analysis
            }
        )
        
        # Patient context flow
        graph.add_edge("load_chat_history", "fetch_patient")
        graph.add_edge("fetch_patient", "retrieve_chunks")
        graph.add_edge("retrieve_chunks", "analyze_image")
        
        # Analysis flow
        graph.add_edge("analyze_image", "find_similar_cases")
        graph.add_edge("find_similar_cases", "synthesize_response")
        
        # Error handling
        graph.add_conditional_edges(
            "analyze_image",
            self._check_for_errors,
            {
                "error": "handle_error",
                "continue": "find_similar_cases"
            }
        )
        
        graph.add_conditional_edges(
            "find_similar_cases", 
            self._check_for_errors,
            {
                "error": "handle_error",
                "continue": "synthesize_response"
            }
        )
        
        graph.set_finish_point("synthesize_response")
        graph.set_finish_point("handle_error")
        
        return graph.compile()
    
    async def analyze(
        self,
        pixel_data: ImagePixelData,
        metadata: DICOMMetadata,
        query: str,
        user_id: Optional[str] = None,
        patient_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> str:
        """Run the image analysis flow."""
        
        # Initialize state
        initial_state = ImageAnalysisState(
            pixel_data=pixel_data,
            metadata=metadata,
            query=query,
            user_id=user_id,
            patient_id=patient_id,
            session_id=session_id
        )
        
        # Run the flow
        result = await self.graph.ainvoke(initial_state)
        
        # Access the state properly
        if hasattr(result, 'final_response'):
            return result.final_response
        elif isinstance(result, dict) and 'final_response' in result:
            return result['final_response']
        else:
            logger.warning(f"Unexpected result type: {type(result)}")
            return "Analysis completed but response format was unexpected."
    
    async def _analyze_image(self, state: ImageAnalysisState) -> ImageAnalysisState:
        """Analyze the DICOM image with Claude using patient context."""
        try:
            if not isinstance(self.llm_client, AnthropicClaudeClient):
                state.error = "Vision analysis requires Claude client"
                return state
            
            if state.pixel_data is None:
                state.error = "No pixel data available for analysis"
                return state
                
            if state.metadata is None:
                state.error = "No metadata available for analysis"
                return state

            # Enhanced analysis with patient context and history
            analysis = await self.llm_client.analyze_dicom_image(
                pixel_data=state.pixel_data,
                metadata=state.metadata,
                query=state.query,
                patient_context=state.patient_context
            )
            
            state.image_analysis = analysis
            return state
            
        except Exception as e:
            state.error = f"Error in image analysis: {str(e)}"
            return state
    
    async def _find_similar_cases(self, state: ImageAnalysisState) -> ImageAnalysisState:
        """Find similar cases using embeddings."""
        try:
            if not state.pixel_data or not state.metadata:
                return state
            
            # Create embedding for the current image
            image_embedding = await self.embedding_service.create_image_embedding(state.pixel_data)
            metadata_embedding = await self.embedding_service.create_metadata_embedding(state.metadata)
            
            # Combine embeddings (simple average)
            combined_embedding = [
                (img + meta) / 2 for img, meta in zip(image_embedding, metadata_embedding)
            ]
            
            # Search for similar images
            similar_results = await self.vector_store.search_similar_dicom(
                combined_embedding,
                limit=3,
                similarity_threshold=0.7
            )
            
            state.similar_cases = similar_results
            return state
            
        except Exception as e:
            logger.warning(f"Could not find similar cases: {e}")
            # Don't fail the entire flow for this
            state.similar_cases = []
            return state
    
    async def _synthesize_response(self, state: ImageAnalysisState) -> ImageAnalysisState:
        """Synthesize final response combining analysis, patient context, and similar cases."""
        try:
            response_parts = []
            
            # Add patient context if available
            if state.patient_context:
                response_parts.append("## Patient Context")
                response_parts.append(f"Patient: {state.patient_context.name}")
                if hasattr(state.patient_context, 'demographics') and state.patient_context.demographics:
                    demo = state.patient_context.demographics
                    if demo.get('age'):
                        response_parts.append(f"Age: {demo['age']}")
                    if demo.get('gender'):
                        response_parts.append(f"Gender: {demo['gender']}")
            
            # Add chat history context if relevant
            if state.chat_history:
                recent_context = [msg for msg in state.chat_history[-3:] if msg.get('role') == 'user']
                if recent_context:
                    response_parts.append("## Recent Clinical Context")
                    for msg in recent_context:
                        response_parts.append(f"- {msg.get('content', '')[:100]}...")
            
            # Add main analysis
            if state.image_analysis:
                response_parts.append("## Image Analysis")
                response_parts.append(state.image_analysis)
            
            # Add relevant clinical notes if found
            if state.retrieved_chunks:
                response_parts.append("## Relevant Clinical Notes")
                for i, chunk in enumerate(state.retrieved_chunks[:2], 1):
                    response_parts.append(f"**Note {i}:** {chunk[:200]}...")
            
            # Add similar cases if found
            if state.similar_cases:
                response_parts.append("## Similar Cases Found")
                response_parts.append(f"Found {len(state.similar_cases)} similar cases in the database:")
                
                for i, case in enumerate(state.similar_cases, 1):
                    similarity = case.get('similarity', 0) * 100
                    metadata = case.get('metadata', {})
                    response_parts.append(
                        f"{i}. {metadata.get('modality', 'Unknown')} - "
                        f"{metadata.get('body_part', 'Unknown body part')} "
                        f"(Similarity: {similarity:.1f}%)"
                    )
            
            # Combine all parts
            state.final_response = "\n\n".join(response_parts)
            return state
            
        except Exception as e:
            state.error = f"Error synthesizing response: {str(e)}"
            return state
    
    async def _handle_error(self, state: ImageAnalysisState) -> ImageAnalysisState:
        """Handle errors in the flow."""
        state.final_response = f"I encountered an error while analyzing the image: {state.error}. Please try again or consult with a radiologist directly."
        return state
    
    def _check_for_errors(self, state: ImageAnalysisState) -> str:
        """Check if there are errors in the state."""
        return "error" if state.error else "continue"
    
    async def _load_user_context(self, state: ImageAnalysisState) -> ImageAnalysisState:
        """Load user context if available."""
        if state.user_id:
            try:
                state.user_context = await self.user_repo.get_user_by_id(state.user_id)
                if not state.user_context:
                    logger.info(f"No user found with ID {sanitize_user_id(state.user_id)}")
            except Exception as e:
                log_error(logger, "load_user_context", e)
                state.user_context = None

        return state

    async def _check_patient_exists(self, state: ImageAnalysisState) -> ImageAnalysisState:
        """Check if patient_id is provided in the state."""
        # This node doesn't need to do anything - just pass through
        return state

    def _has_patient(self, state: ImageAnalysisState) -> bool:
        """Check if patient ID is provided."""
        return state.patient_id is not None and state.patient_id.strip() != ""

    async def _load_chat_history(self, state: ImageAnalysisState) -> ImageAnalysisState:
        """Load chat history for the patient if available."""
        if state.patient_id and state.session_id:
            try:
                # Get history for this specific session
                history_data = await self.vector_store.get_chat_history(
                    patient_id=str(state.patient_id), 
                    session_id=state.session_id,
                    limit=10  # Limit for image analysis context
                )

                chat_messages = []
                
                for item in history_data:
                    try:
                        role = item.get("role", "user")
                        content = item.get("content", "")
                        chat_messages.append({
                            "role": role,
                            "content": content,
                            "timestamp": item.get("timestamp", "")
                        })
                    except Exception as e:
                        log_error(logger, "parse_chat_history_item", e)
                        continue

                state.chat_history = chat_messages
            except Exception as e:
                log_error(logger, "load_chat_history", e)
                state.chat_history = []
        else:
            state.chat_history = []

        return state

    async def _fetch_patient(self, state: ImageAnalysisState) -> ImageAnalysisState:
        """Fetch patient context using FHIR repository."""
        if not state.patient_id:
            return state
            
        # Try to use user's EHR connection first (like in patient flow)
        fhir_repo = self.fhir_repo
        
        if state.user_id and self.connection_service:
            try:
                user_fhir_repo = await self.connection_service.create_fhir_repository(
                    state.user_id, 
                    "smart_fhir"
                )
                if user_fhir_repo:
                    fhir_repo = user_fhir_repo
                    logger.info("Using user's SMART on FHIR connection for image analysis")
            except Exception as e:
                logger.warning(f"Failed to use SMART connection: {e}, falling back to default")
        
        try:
            state.patient_context = await fhir_repo.get_patient(str(state.patient_id))
        except Exception as e:
            logger.warning(f"Could not fetch patient context for {sanitize_patient_id(str(state.patient_id))}: {e}")
            state.patient_context = None

        return state

    async def _retrieve_chunks(self, state: ImageAnalysisState) -> ImageAnalysisState:
        """Retrieve relevant patient-specific chunks for image analysis."""
        if not state.patient_id:
            return state
            
        try:
            # Create a search query combining image analysis query with patient context
            search_query = f"Image analysis: {state.query}"
            if state.patient_context:
                search_query += f" Patient: {state.patient_context.name}"
            
            # Search for patient-specific data
            from optimed.embeddings.minilm import embed
            q_vec = await embed(search_query)
            rows = await self.vector_store.similarity_search(
                q_vec,
                top_k=3,
                filter_={
                    "namespace": "clinical", 
                    "patient_id": str(state.patient_id)
                },
            )

            # Extract relevant chunks
            patient_specific_chunks = []
            if state.patient_context:
                for row in rows:
                    chunk_text = row[2] if len(row) > 2 else row[1]
                    # Verify this chunk is actually about our patient
                    patient_name = state.patient_context.name if state.patient_context else ""
                    if str(state.patient_id) in chunk_text or patient_name in chunk_text:
                        patient_specific_chunks.append(chunk_text)
            
            state.retrieved_chunks = patient_specific_chunks

        except Exception as e:
            log_error(logger, "retrieve_chunks", e)
            state.retrieved_chunks = []

        return state