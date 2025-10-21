from __future__ import annotations
from .streaming_decorators import streaming_step
from .streaming_llm import StreamingLLMWrapper

import uuid
import json
import time
import math
import asyncio
import re
from typing import List, Any, Union, AsyncGenerator, Optional, Dict
from datetime import datetime, timezone

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from optimed.core.domain import PatientContext, ChatMessage, DiagnosisResult, ChatRole, UserAction, User, WebSearchResponse, JournalEntry, Chunk, NoteTemplate
from optimed.core.domain.pdf_document import PDFDocument
from optimed.core.domain.xml_document import XMLDocument
from optimed.core.lang import detect_language_code

from optimed.core.ports import DiagnosticEngine, FHIRRepository, LLMClient, VectorStore, UserRepository, WebSearchService, PDFService, XMLService, AuditRepository

from optimed.apps.orchestrator.connection_service import UserEHRConnectionService
from optimed.apps.orchestrator.ml_adapters import MultilingualCrossEncoder
from optimed.apps.orchestrator.llm_classifier import LLMZeroShotClassifier

from optimed.embeddings.minilm import embed_batch
from optimed.adapters.security.e2e_encryption_middleware import get_session_encryption_manager
from optimed.apps.orchestrator.chunking_orchestrator import ChunkingOrchestrator
from optimed.apps.orchestrator.chunking_config import STRATEGY_REGISTRY as CHUNK_STRATEGY_REGISTRY, POLICY_PRESETS as CHUNK_POLICY_PRESETS
from optimed.adapters.outbound.tokenizer.whitespace_tokenizer import WhitespaceTokenizer
from optimed.core.logging_utils import get_logger, sanitize_user_id, sanitize_patient_id, sanitize_session_id, log_error

logger = get_logger(__name__)

# Global session memory store to persist across instances
_GLOBAL_SESSION_MEMORY: dict[str, list[dict[str, Any]]] = {}

# Global chunk cache to avoid re-chunking on every query
# Format: {session_id: {"chunks": [...], "doc_signature": "...", "timestamp": ...}}
_GLOBAL_CHUNK_CACHE: dict[str, dict[str, Any]] = {}


# =========================
# RAM-only mode and retrieval params
# =========================
# Global flag to disable any persistence (DB/files/caches). All writes are gated.
PERSISTENCE_ENABLED: bool = False

# Retrieval parameters
TOPK_INITIAL: int = 100
TOPK_RERANK: int = 30
N_MIN: int = 3
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

                                    **CRITICAL - RESPONSE FORMAT**:
                                    - Organize response with `##` headers to divide sections
                                    - **1-4 sections depending on need**, with **up to 10 bullet points per section**
                                    - **10-15 words per bullet point** - be extremely concise
                                    - Use bullet points (`-`) for all information, no long paragraphs
                                    - Each bullet must be a single, focused fact with citation

                                    General response guideline:
                                    - Use previous conversation history (between === lines) when relevant.
                                    - **Always output in valid GitHub-flavored Markdown** to ensure clean rendering in the application.
                                    - **DATE/TIME STAMPS**: Only include dates (YYYY-MM-DD or YYYY-MM-DD HH:MM) when referencing specific journal entries, documents, or when temporal context is essential for the query.
                                    - **CRITICAL**: Use **bold** markdown formatting to highlight important clinical terms:
                                        - **Diagnoses** and disease names (e.g., **Type 2 Diabetes**, **Hypertension**)
                                        - **Medications** and doses (e.g., **Metformin 1000mg**, **Enalapril 20mg**)
                                        - **Vital signs** and lab values (e.g., **BP 145/85**, **HbA1c 68 mmol/mol**, **eGFR 52**)
                                        - **Symptoms** and clinical findings (e.g., **chest pain**, **dyspnea**, **wheezing**)
                                        - **Risk levels** and severity descriptors (e.g., **moderate risk**, **stable**, **worsening**)
                                        - **Key clinical terms** that are important for decision-making
                                    - Format all URLs as **clickable Markdown links**: [Link Text](URL)
                                    - For web sources, use format: [Source Title](URL) immediately after the information
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
    journal_entries: List[JournalEntry] = Field(default_factory=list)  # Store fetched journal entries
    uploaded_pdfs: List[PDFDocument] = Field(default_factory=list)  # Store PDF documents
    uploaded_xmls: List[XMLDocument] = Field(default_factory=list)  # Store XML documents
    retrieved_chunks: List[Dict[str, Any]] = Field(default_factory=list)  # Chunk dicts with chunk_id, content, metadata

    # Chunking cache to avoid re-chunking on every query
    chunks_cached: bool = False  # Flag indicating if chunks are already in vector store
    cached_chunk_ids: List[str] = Field(default_factory=list)  # IDs of cached chunks for this session

    # Citation tracking for compact inline citations
    citations: Dict[str, Dict[str, Any]] = Field(default_factory=dict)  # { "1": { "document": "...", "page": "...", "excerpt": "...", "url": "..." } }
    chunk_id_to_number: Dict[str, str] = Field(default_factory=dict)  # { "chunk-id-123": "1", "chunk-id-456": "2" }

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
    user_language: str = "en"  # Detected language from user prompt (en, sv, etc.)


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
    classification_query: Optional[str] = None  # Contextualized query for classification
    is_sbar_flow: bool = False

    # Separate fields for each SBAR component to avoid concurrent updates
    sbar_situation_chunks: Optional[List[Dict[str, Any]]] = None
    sbar_background_chunks: Optional[List[Dict[str, Any]]] = None
    sbar_assessment_chunks: Optional[List[Dict[str, Any]]] = None
    sbar_recommendation_chunks: Optional[List[Dict[str, Any]]] = None

    sbar_situation_result: Optional[str] = None
    sbar_background_result: Optional[str] = None
    sbar_assessment_result: Optional[str] = None
    sbar_recommendation_result: Optional[str] = None

    # Cited chunk IDs from LLM for each SBAR component
    sbar_situation_cited_ids: Optional[List[str]] = None
    sbar_background_cited_ids: Optional[List[str]] = None
    sbar_assessment_cited_ids: Optional[List[str]] = None
    sbar_recommendation_cited_ids: Optional[List[str]] = None

    # SBAR retrieval cache for performance optimization
    sbar_retrieval_cache: Optional[Dict[str, Any]] = None

    # Timeline flow fields
    is_timeline_flow: bool = False
    timeline_events: Optional[List[Dict[str, Any]]] = None  # Generated timeline events
    timeline_chunks: Optional[Dict[str, List[Dict[str, Any]]]] = None  # Chunks per event
    timeline_results: Optional[List[Dict[str, Any]]] = None  # Final timeline bubbles
    timeline_retrieval_cache: Optional[Dict[str, Any]] = None

    # Note generation flow fields
    is_note_generation_flow: bool = False
    note_template: Optional[Any] = None  # NoteTemplate object
    note_template_type_preference: Optional[str] = None  # For auto-selected templates
    note_generation_id: Optional[str] = None
    note_context_prompt: Optional[str] = None
    note_sections: Dict[str, str] = Field(default_factory=dict)
    note_final_content: Optional[str] = None
    note_sources: List[str] = Field(default_factory=list)

    # General summary flow fields
    is_general_summary_flow: bool = False

    # Separate fields for each general summary component to avoid concurrent updates
    general_snapshot_chunks: Optional[List[Dict[str, Any]]] = None
    general_problems_chunks: Optional[List[Dict[str, Any]]] = None
    general_medications_chunks: Optional[List[Dict[str, Any]]] = None
    general_trends_chunks: Optional[List[Dict[str, Any]]] = None
    general_history_chunks: Optional[List[Dict[str, Any]]] = None  # Now used for encounters
    general_risks_chunks: Optional[List[Dict[str, Any]]] = None
    general_encounters_chunks: Optional[List[Dict[str, Any]]] = None

    general_snapshot_result: Optional[str] = None
    general_problems_result: Optional[str] = None
    general_medications_result: Optional[str] = None
    general_trends_result: Optional[str] = None
    general_history_result: Optional[str] = None  # Now stores encounters markdown
    general_risks_result: Optional[str] = None
    general_encounters_result: Optional[str] = None

    # Structured encounter data for clickable detailed summaries
    general_encounters_structured: Optional[List[Dict[str, Any]]] = None

    # Cited chunk IDs from LLM for each general summary component
    general_snapshot_cited_ids: Optional[List[str]] = None
    general_problems_cited_ids: Optional[List[str]] = None
    general_medications_cited_ids: Optional[List[str]] = None
    general_trends_cited_ids: Optional[List[str]] = None
    general_history_cited_ids: Optional[List[str]] = None  # Now stores encounters citations
    general_risks_cited_ids: Optional[List[str]] = None
    general_encounters_cited_ids: Optional[List[str]] = None

    # General summary retrieval cache for performance optimization
    general_retrieval_cache: Optional[Dict[str, Any]] = None

    # Focused summary flow fields
    is_focused_summary_flow: bool = False
    focused_aspect: Optional[str] = None  # e.g., "heart disease", "lung history"
    focused_aspect_icon: Optional[str] = None  # Icon for the aspect

    # General knowledge flow fields (medical knowledge, not patient-specific)
    is_general_knowledge_flow: bool = False

    # Separate fields for each focused summary component to avoid concurrent updates
    focused_diagnoses_chunks: Optional[List[Dict[str, Any]]] = None
    focused_events_chunks: Optional[List[Dict[str, Any]]] = None
    focused_medications_chunks: Optional[List[Dict[str, Any]]] = None
    focused_objective_data_chunks: Optional[List[Dict[str, Any]]] = None
    focused_assessment_chunks: Optional[List[Dict[str, Any]]] = None
    focused_next_steps_chunks: Optional[List[Dict[str, Any]]] = None

    focused_diagnoses_result: Optional[str] = None
    focused_events_result: Optional[str] = None
    focused_medications_result: Optional[str] = None
    focused_objective_data_result: Optional[str] = None
    focused_assessment_result: Optional[str] = None
    focused_next_steps_result: Optional[str] = None

    # Cited chunk IDs from LLM for each focused summary component
    focused_diagnoses_cited_ids: Optional[List[str]] = None
    focused_events_cited_ids: Optional[List[str]] = None
    focused_medications_cited_ids: Optional[List[str]] = None
    focused_objective_data_cited_ids: Optional[List[str]] = None
    focused_assessment_cited_ids: Optional[List[str]] = None
    focused_next_steps_cited_ids: Optional[List[str]] = None

    # Focused summary retrieval cache for performance optimization
    focused_retrieval_cache: Optional[Dict[str, Any]] = None


class LangGraphRAMInformationEngine(DiagnosticEngine):
    """Concrete engine that streams or returns full result."""

    def __init__(self, fhir_repo: FHIRRepository,
                 vector_store: VectorStore,
                 llm_client: LLMClient,
                 user_repo: UserRepository,
                 connection_service: UserEHRConnectionService,
                 web_search_service: WebSearchService,
                 cross_encoder: MultilingualCrossEncoder,
                 zero_shot_classifier: LLMZeroShotClassifier,
                 pdf_service: Optional[PDFService] = None,
                 xml_service: Optional[XMLService] = None,
                 audit_repo: Optional[AuditRepository] = None,
                 default_prompt: str = "Provide the most likely diagnosis"):
        self._fhir = fhir_repo
        self._vec = vector_store
        self._llm = llm_client
        self._streaming_llm = StreamingLLMWrapper(llm_client=llm_client)

        self._user_repo = user_repo
        self._connection_service = connection_service
        self._web_search = web_search_service
        self._pdf_service = pdf_service
        self._xml_service = xml_service
        self._audit_repo = audit_repo
        self._default_prompt = default_prompt

        # ML models for intelligent retrieval
        self._cross_encoder = cross_encoder
        self._zero_shot_classifier = zero_shot_classifier

        self._compiled_graph = self._build_graph()
        # Use global session memory that persists across instances
        self._session_memory = _GLOBAL_SESSION_MEMORY

    def _get_language_policy_message(self, state: FlowState) -> ChatMessage:
        """
        Create language policy system message based on detected language.
        Detects language from current query + recent chat history for better accuracy.
        Also sets state.user_language for use by streaming decorators and other components.
        """
        try:
            from optimed.core.lang import detect_language_code

            # Detect from current query + recent history for better accuracy
            detection_text = state.user_prompt
            if state.chat_history and len(state.chat_history) > 0:
                last_user_msgs = [msg.content for msg in state.chat_history[-3:] if msg.role == ChatRole.USER]
                if last_user_msgs:
                    detection_text = " ".join(last_user_msgs[-2:] + [state.user_prompt])

            active_lang = detect_language_code(detection_text or "")
        except Exception:
            active_lang = "en"

        # Set the language in state for streaming decorators and other components
        state.user_language = active_lang

        return ChatMessage(
            role=ChatRole.SYSTEM,
            content=(
                f"Language policy: Respond in '{active_lang}'. Use clinically appropriate terminology in this language. "
                f"If citing or quoting sources in another language, translate faithfully and include the original term in parentheses if relevant."
            )
        )

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (rough: 1 token ≈ 4 characters)."""
        return len(text) // 4

    def _limit_chunks_for_context(self, chunks: List[Dict[str, Any]], max_tokens: int = 200000, max_chunk_chars: int = 50000) -> List[Dict[str, Any]]:
        """
        Limit chunks to prevent context window overflow.

        Args:
            chunks: List of chunk dicts with chunk_id, content, and metadata
            max_tokens: Maximum total tokens for all chunks
            max_chunk_chars: Maximum characters per individual chunk

        Returns:
            Limited and truncated chunks that fit within constraints
        """
        limited_chunks: List[Dict[str, Any]] = []
        total_tokens = 0

        for chunk in chunks:
            content = chunk.get("content", "")

            # Truncate individual chunks that are too large
            if len(content) > max_chunk_chars:
                truncated = content[:max_chunk_chars] + "\n... [truncated for length]"
                logger.warning(f"Truncated chunk from {len(content)} to {max_chunk_chars} chars")
                # Create new chunk with truncated content
                chunk = {**chunk, "content": truncated}

            # Estimate tokens based on content
            chunk_tokens = self._estimate_tokens(content)

            # Stop adding chunks if we'd exceed the limit
            if total_tokens + chunk_tokens > max_tokens:
                logger.warning(f"Stopping at {len(limited_chunks)} chunks to avoid context overflow (would exceed {max_tokens} tokens)")
                break

            limited_chunks.append(chunk)
            total_tokens += chunk_tokens

        logger.info(f"Limited chunks: {len(chunks)} → {len(limited_chunks)}, estimated tokens: ~{total_tokens}")
        return limited_chunks

    def _build_citations_from_chunks(self, chunks: List[Dict[str, Any]]) -> tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
        """
        Build numbered citations dictionary from chunk metadata.

        Assigns sequential numbers (1, 2, 3...) to each chunk upfront.
        This ensures the model sees the correct citation numbers from the start.

        Args:
            chunks: List of chunk dicts with chunk_id, content, and metadata

        Returns:
            Tuple of:
            - citations: Dictionary mapping citation NUMBER to citation metadata:
              { "1": { "id": "chunk-id-123", "document": "...", "excerpt": "..." }, "2": {...} }
            - chunk_id_to_number: Mapping from chunk_id to citation number:
              { "chunk-id-123": "1", "chunk-id-456": "2" }
        """
        citations = {}
        chunk_id_to_number = {}
        citation_number = 1

        for chunk in chunks:
            chunk_id = chunk.get("chunk_id")
            if not chunk_id:
                logger.warning("Chunk missing chunk_id, skipping citation")
                continue

            metadata = chunk.get("metadata", {})
            content = chunk.get("content", "")

            # Clean content (remove old embedded source links if any)
            import re
            clean_content = re.sub(r'\*\*Source:\*\*\s*\[([^\]]+)\]\([^\)]+\)', '', content)
            clean_content = re.sub(r'\[EHR Source\]\([^\)]+\)', '', clean_content)
            clean_content = re.sub(r'\(from EHR, no link available\)', '', clean_content)
            clean_content = clean_content.strip()

            # Assign sequential number
            number_str = str(citation_number)
            chunk_id_to_number[chunk_id] = number_str

            citations[number_str] = {
                "id": chunk_id,  # Keep original chunk_id for reference
                "document": metadata.get("document", "Clinical Record"),
                "page": metadata.get("page"),
                "excerpt": clean_content,  # Full chunk content
                "url": metadata.get("url"),
            }

            citation_number += 1

        logger.info(f"Built {len(citations)} numbered citations from {len(chunks)} chunks")
        return citations, chunk_id_to_number

    def _format_chunks_with_citations(self, chunks: List[Dict[str, Any]], chunk_id_to_number: Dict[str, str]) -> str:
        """
        Format chunks with citation numbers for LLM to cite.

        The LLM will see each chunk with its assigned citation number clearly displayed.
        This method formats chunks as:
        [Citation: 1]
        <chunk content>
        [End Citation 1]

        Args:
            chunks: List of chunk dicts with chunk_id, content, and metadata
            chunk_id_to_number: Mapping from chunk_id to citation number

        Returns:
            Formatted string with citation numbers visible
        """
        import re
        formatted_parts = []

        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", "unknown")
            content = chunk.get("content", "")

            # Get the assigned citation number
            citation_number = chunk_id_to_number.get(chunk_id, "?")

            # Clean content (remove old verbose citations if any)
            clean_content = re.sub(r'\*\*Source:\*\*\s*\[([^\]]+)\]\([^\)]+\)', '', content)
            clean_content = re.sub(r'\[EHR Source\]\([^\)]+\)', '', clean_content)
            clean_content = re.sub(r'\(from EHR, no link available\)', '', clean_content)
            clean_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', clean_content)
            clean_content = clean_content.strip()

            if clean_content:
                # Format with citation number prominently displayed
                formatted_parts.append(f"[Citation: {citation_number}]\n{clean_content}\n[End Citation {citation_number}]")

        return "\n\n".join(formatted_parts)

    def _extract_cited_chunk_ids(self, content: str) -> set:
        """
        Extract citation numbers that were actually cited in the content.
        Looks for numbered citations like [1], [2], [3] in the content.

        Args:
            content: The generated content text

        Returns:
            Set of citation numbers (as strings) that were cited
        """
        import re
        cited_ids = set()

        # Pattern to match numbered citations [1], [2], [3], etc.
        pattern = r'\[(\d+)\]'
        matches = re.findall(pattern, content)

        for match in matches:
            cited_ids.add(match)  # match is already a string like "1", "2", "3"

        return cited_ids

    def _convert_citations_to_numbered(self, content: str, citations: Dict[str, Dict[str, Any]]) -> tuple[str, Dict[str, Dict[str, Any]]]:
        """
        Convert [cite: chunk_id] markers to numbered citations [1], [2], etc.
        and renumber the citations dict accordingly.

        Args:
            content: Content with [cite: chunk_id] markers
            citations: Citations dict keyed by chunk_id

        Returns:
            Tuple of (updated_content, numbered_citations_dict)
        """
        import re

        # Extract all cited chunk IDs in order of appearance
        pattern = r'\[cite:\s*([^\]]+)\]'
        matches = re.findall(pattern, content)

        # Create ordered mapping from chunk_id to number
        chunk_id_to_number = {}
        number = 1
        for match in matches:
            chunk_id = match.strip()
            if chunk_id not in chunk_id_to_number:
                chunk_id_to_number[chunk_id] = number
                number += 1

        # Replace [cite: chunk_id] with [number] in content
        def replace_citation(match):
            chunk_id = match.group(1).strip()
            citation_num = chunk_id_to_number.get(chunk_id, "?")
            return f"[{citation_num}]"

        updated_content = re.sub(pattern, replace_citation, content)

        # Renumber citations dict from chunk_id keys to number keys
        numbered_citations = {}
        for chunk_id, citation_num in chunk_id_to_number.items():
            if chunk_id in citations:
                numbered_citations[str(citation_num)] = citations[chunk_id]

        return updated_content, numbered_citations

    async def _validate_and_correct_citations(self, content: str, citations: Dict[str, Dict[str, Any]]) -> str:
        """
        Validate that all numbered citations in content exist in citations dict.
        Remove or correct invalid citations.

        Args:
            content: Content with numbered citations [1], [2], [3]
            citations: Citations dict keyed by citation number "1", "2", "3"

        Returns:
            Content with validated citations
        """
        import re

        # Find all numbered citations [1], [2], [3] in content
        pattern = r'\[(\d+)\]'

        def validate_citation(match):
            citation_num = match.group(1)
            # Keep citation if it exists in citations dict
            if citation_num in citations:
                return match.group(0)  # Keep as-is
            else:
                return ""  # Remove invalid citation

        validated_content = re.sub(pattern, validate_citation, content)
        return validated_content

    async def _log_data_lineage(
        self,
        session_id: Optional[str],
        flow_id: str,
        source_system: str,
        source_type: str,
        destination_system: str,
        destination_type: str,
        transformations: List[str],
        data_quality_score: Optional[float] = None
    ) -> None:
        """
        Safely log data lineage without breaking the flow.

        This is a fire-and-forget logging operation - failures are logged but don't propagate.
        """
        if not self._audit_repo:
            return  # Audit logging not configured

        try:
            await self._audit_repo.log_data_flow(
                session_id=session_id,
                flow_id=flow_id,
                source_system=source_system,
                source_type=source_type,
                destination_system=destination_system,
                destination_type=destination_type,
                transformations=transformations,
                data_quality_score=data_quality_score
            )
        except Exception as e:
            # Never fail the flow due to logging errors
            log_error(logger, "DATA_LINEAGE", e)

    async def _run_parallel_cross_encoder_operations(self, state: FlowState, chunks: list[dict[str, Any]], initial_indices: list[int], query_vecs: list[list[float]]) -> tuple[list[tuple[int, float]], list[int], list[float]]:
        """Optimized cross-encoder operations with single GPU pass.

        This method performs cross-encoder scoring once and reuses scores for both
        reranking and gating, eliminating redundant GPU calls.

        Returns:
            Tuple of (reranked_chunks, selected_indices, gate_scores)
        """
        cross = self._cross_encoder
        rerank_passages = [chunks[i]["content"] for i in initial_indices]

        logger.info(f"Starting optimized cross-encoder scoring for {len(initial_indices)} chunks")
        start_time = time.time()

        # OPTIMIZATION: Single cross-encoder pass for all initial chunks
        # This batches all operations together for maximum GPU utilization
        all_pairs = [(state.user_prompt, passage) for passage in rerank_passages]
        all_scores = await cross.predict_async(all_pairs)

        end_time = time.time()
        logger.info(f"Cross-encoder scoring completed in {end_time - start_time:.3f}s for {len(all_pairs)} pairs")

        # Create index-to-score mapping for efficient lookup
        score_map = {initial_indices[i]: all_scores[i] for i in range(len(initial_indices))}

        # Process reranking results (top-K from scored chunks)
        reranked = list(zip(initial_indices, all_scores))
        reranked.sort(key=lambda x: x[1], reverse=True)
        reranked = reranked[:TOPK_RERANK]

        # Log reranking results
        logger.info(f"Reranked top {len(reranked)} chunks")
        for i, (idx, score) in enumerate(reranked[:5]):
            chunk_type = chunks[idx]["data_type"]
            logger.info(f"  {i+1}. Chunk {idx} ({chunk_type}): {score:.4f}")

        # Compute dynamic n and MMR selection
        rerank_only_scores = [s for _, s in reranked]
        # Pass pre-classification from state to avoid redundant classification
        pre_classification = getattr(state, 'query_classification', None)
        n_dynamic = self._compute_dynamic_n(state.user_prompt, rerank_only_scores, pre_classification)
        logger.info(f"Dynamic n: {n_dynamic}")

        # MMR selection for diversity
        candidate_vecs = [chunks[i]["embedding"] for i, _ in reranked]
        best_q_idx = max(range(len(query_vecs)), key=lambda qi: sum(self._cosine(query_vecs[qi], v) for v in candidate_vecs) / max(len(candidate_vecs), 1))
        best_q_vec = query_vecs[best_q_idx]
        mmr_local_indices = self._mmr(candidate_vecs, best_q_vec, n_dynamic, lambda_=MMR_LAMBDA)
        selected_indices = [reranked[j][0] for j in mmr_local_indices]

        logger.info(f"MMR selected {len(selected_indices)} diverse chunks")

        # OPTIMIZATION: Reuse cross-encoder scores from the initial pass for gating
        # No need for second GPU call - just lookup the scores we already computed
        gate_scores = [score_map[idx] for idx in selected_indices]

        logger.info("✓ Optimized pipeline: 1 GPU pass instead of 2 (saved ~50% GPU time)")

        return reranked, selected_indices, gate_scores

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
                        logger.info("Using user's SMART on FHIR connection")
                except Exception as e:
                    logger.info(f"Failed to use SMART connection: {e}, falling back to default")
            
            state.patient_ctx = await fhir_repo.get_patient(str(state.patient_id))
            
            # Also fetch journal entries for this patient
            try:
                journal_entries = await fhir_repo.get_patient_journal_entries(str(state.patient_id))
                state.journal_entries = list(journal_entries)
                logger.info(f"Fetched {len(state.journal_entries)} journal entries for patient {sanitize_patient_id(str(state.patient_id))}")
            except Exception as e:
                logger.info(f"Failed to fetch journal entries: {e}")
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
                    patient_id=state.patient_id
                )

                # Filter to only include ready documents with extracted text
                ready_pdfs = [
                    doc for doc in pdf_documents
                    if doc.status.value == "READY" and doc.extracted_text
                ]

                state.uploaded_pdfs = ready_pdfs
                logger.info(f"Fetched {len(state.uploaded_pdfs)} ready PDF documents for session {state.session_id} (patient_id={sanitize_patient_id(str(state.patient_id))})")

            except Exception as e:
                logger.info(f"Failed to fetch PDF documents: {e}")
                state.uploaded_pdfs = []

            return state

        @streaming_step("fetch_xmls")
        async def fetch_xmls(state: FlowState) -> FlowState:
            """Fetch XML documents relevant for the current context."""

            if not self._xml_service or not state.user_id or not state.session_id:
                state.uploaded_xmls = []
                return state

            try:
                # Get XML documents for the current session (patient-specific or general)
                xml_documents = await self._xml_service.get_documents_for_context(
                    user_id=state.user_id,
                    session_id=state.session_id,
                    patient_id=state.patient_id
                )

                # Filter to only include ready documents with extracted text
                ready_xmls = [
                    doc for doc in xml_documents
                    if doc.status.value == "READY" and doc.extracted_text
                ]

                state.uploaded_xmls = ready_xmls
                logger.info(f"Fetched {len(state.uploaded_xmls)} ready XML documents for session {state.session_id} (patient_id={sanitize_patient_id(str(state.patient_id))})")

            except Exception as e:
                logger.info(f"Failed to fetch XML documents: {e}")
                state.uploaded_xmls = []

            return state

        @streaming_step("load_user_context")
        async def load_user_context(state: FlowState) -> FlowState:
            """Load user context if available."""
            if state.user_id:
                try: 
                    state.user_context = await self._user_repo.get_user_by_id(state.user_id)
                    if not state.user_context:
                        logger.info(f"No user found with ID {sanitize_user_id(state.user_id)}")
                except Exception as e:
                    log_error(logger, "load_user_context", e)
                    state.user_context = None
            
            return state

        @streaming_step("evaluate_web_search_need")
        async def evaluate_web_search_need(state: FlowState) -> FlowState:
            """Evaluate if web search is needed for medical information."""
            try:
                # ALWAYS use web search for factoid/guideline questions (general medical knowledge)
                # This prevents hallucinations and ensures current medical information
                classification = getattr(state, 'query_classification', None)

                # Force web search for general medical knowledge questions
                factoid_classifications = ["guideline", "general", "comparative"]
                if classification in factoid_classifications:
                    logger.info(f"Factoid question detected ({classification}) - FORCING web search for credible sources")
                    state.web_search_performed = True
                    return state

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
                logger.info(f"Web search needed: {needs_search}")

            except Exception as e:
                log_error(logger, "web_search", e)
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
                
                logger.info(f"Found {len(search_response.results)} results")
                
            except Exception as e:
                log_error(logger, "web_search", e)
                state.web_search_response = None
                state.retrieved_web = []
            
            return state

        def needs_web_search(state: FlowState) -> bool:
            """Conditional function to determine if web search should be performed."""
            return state.web_search_performed


        @streaming_step("load_current_session_history")
        async def load_current_session_history(state: FlowState) -> FlowState:
            """Load current session chat history from in-memory session store with decryption and deduplication."""
            logger.info(f"📚 Loading history for session_id={sanitize_session_id(state.session_id)}")
            logger.info(f"🆔 Session memory ID: {id(self._session_memory)}")
            try:
                history = self._session_memory.get(state.session_id or "", []) if state.session_id else []
                total_sessions = len(self._session_memory)
                logger.info(f"🗄️ Found {len(history)} raw messages in session memory")
                logger.info(f"🗂️ Global memory tracking {total_sessions} sessions total")

                chat_messages: list[ChatMessage] = []
                session_manager = get_session_encryption_manager()

                for i, item in enumerate(history):
                    try:
                        logger.info(f"🔍 Processing message {i+1}: encrypted={item.get('encrypted', False)}")

                        # Handle both encrypted and unencrypted messages
                        if item.get("encrypted", False):
                            # Decrypt the message
                            encrypted_data = item.get("data", "")
                            if state.session_id and encrypted_data:
                                try:
                                    decrypted_message = session_manager.decrypt_session_data(state.session_id, encrypted_data)
                                    role = ChatRole(decrypted_message.get("role", "user"))
                                    content = decrypted_message.get("content", "")
                                    chat_messages.append(ChatMessage(role=role, content=content))
                                    logger.info(f"✅ Decrypted {role.value} message (length={len(content)} chars)")
                                except Exception as decrypt_error:
                                    logger.info(f"❌ Decryption failed for message {i+1}: {decrypt_error}")
                                    continue
                        else:
                            # Handle legacy unencrypted messages
                            role = ChatRole(item.get("role", "user"))
                            content = item.get("content", "")
                            chat_messages.append(ChatMessage(role=role, content=content))
                            logger.info(f"✅ Loaded unencrypted {role.value} message (length={len(content)} chars)")
                    except Exception as e:
                        logger.info(f"❌ Error parsing message {i+1}: {e}")
                        continue

                logger.info(f"📋 Total decrypted messages: {len(chat_messages)}")

                # Remove the last user message to avoid duplication with current prompt
                # The current user message was stored in store_user_message before this function
                if chat_messages and chat_messages[-1].role == ChatRole.USER:
                    removed_msg = chat_messages[-1].content[:50]
                    logger.info(f"🗑️ Removing duplicate user message: '{removed_msg}...'")
                    chat_messages = chat_messages[:-1]

                state.chat_history = chat_messages
                logger.info(f"✅ Final chat history: {len(chat_messages)} messages")

                # Debug: Show the final messages
                for i, msg in enumerate(chat_messages):
                    logger.info(f"  {i+1}. {msg.role.value}: '{msg.content[:50]}...'")

            except Exception as e:
                logger.info(f"❌ Error loading in-memory chat history: {e}")
                import traceback
                traceback.print_exc()
                state.chat_history = []
            return state
        

        

        async def intelligent_retrieve_chunks(state: FlowState) -> FlowState:
            """In-RAM retrieval: chunk, embed, paraphrase, bi-encoder, cross-encoder rerank, dynamic-N MMR, gate, retry."""
            try:
                logger.info(f"Starting retrieval for patient_id: {sanitize_patient_id(str(state.patient_id))}")
                logger.info(f"User prompt length: {len(state.user_prompt)} chars")

                # 1) Chunking via ChunkingOrchestrator (policy-driven)
                # OPTIMIZATION: Chunk only once per session, not on every query
                # Use Presidio multilingual redactor with Swedish default for Sweden Central deployment
                patient_id_str = str(state.patient_id) if state.patient_id else ""

                # Check global cache for this session
                session_cache_key = state.session_id or "default_session"
                global _GLOBAL_CHUNK_CACHE

                # Detect if documents have changed (new uploads)
                current_doc_ids = (
                    [state.patient_ctx.patient_id if state.patient_ctx else ""] +
                    [j.entry_id for j in state.journal_entries] +
                    [pdf.document_id for pdf in state.uploaded_pdfs] +
                    [xml.document_id for xml in state.uploaded_xmls]
                )
                current_doc_signature = "|".join(sorted(current_doc_ids))

                # Check if we have cached chunks for this session with same document signature
                needs_chunking = True
                cached_chunks = None

                if session_cache_key in _GLOBAL_CHUNK_CACHE:
                    cache_entry = _GLOBAL_CHUNK_CACHE[session_cache_key]
                    if cache_entry.get("doc_signature") == current_doc_signature:
                        logger.info("Found cached chunks with matching document signature")
                        needs_chunking = False
                        cached_chunks = cache_entry.get("chunks", [])
                    else:
                        logger.info("Document signature changed - invalidating cache and re-chunking")
                        del _GLOBAL_CHUNK_CACHE[session_cache_key]

                if needs_chunking:
                    logger.info(f"CHUNKING: Processing documents for patient: {patient_id_str}")
                    logger.info("This is a one-time operation per session - subsequent queries will reuse these chunks")
                    logger.info("NO PHI REDACTION - Healthcare professionals need complete clinical data (GDPR Art. 9(2)(h))")

                    tokenizer = WhitespaceTokenizer()

                    # NO PHI redaction during chunking
                    # GDPR compliance achieved through:
                    # - RAM-only processing (no persistence)
                    # - Access controls (RLS, authentication)
                    # - Audit logging (metadata only)
                    # - Auto-cleanup on session end
                    # - Article 9(2)(h): Healthcare professionals may process health data with identifiers

                    orchestrator = ChunkingOrchestrator(
                        tokenizer=tokenizer,
                        strategy_registry=CHUNK_STRATEGY_REGISTRY,
                        policies=CHUNK_POLICY_PRESETS,
                    )

                    # Chunk patient context if available
                    produced = []
                    if state.patient_ctx:
                        logger.info("Chunking patient context...")
                        produced = orchestrator.chunk_patient(state.patient_ctx, CHUNK_POLICY_PRESETS)
                        logger.info(f"Patient context chunking produced {len(produced)} chunks")
                    else:
                        logger.info("No patient context available - proceeding with PDF-only mode")

                    # Also chunk journal entries if available
                    journal_chunks = []
                    if state.journal_entries:
                        logger.info(f"Chunking {len(state.journal_entries)} journal entries...")
                        journal_chunks = await self._chunk_journal_entries(state.journal_entries, orchestrator, patient_id_str)
                        logger.info(f"Journal entries chunking produced {len(journal_chunks)} chunks")

                    # Also chunk PDF documents if available
                    pdf_chunks = []
                    if state.uploaded_pdfs:
                        logger.info(f"Chunking {len(state.uploaded_pdfs)} PDF documents...")
                        pdf_chunks = await self._chunk_pdf_documents(state.uploaded_pdfs, orchestrator, patient_id_str)
                        logger.info(f"PDF documents chunking produced {len(pdf_chunks)} chunks")

                    # Also chunk XML documents if available
                    xml_chunks = []
                    if state.uploaded_xmls:
                        logger.info(f"Chunking {len(state.uploaded_xmls)} XML documents...")
                        xml_chunks = await self._chunk_xml_documents(state.uploaded_xmls, orchestrator, patient_id_str)
                        logger.info(f"XML documents chunking produced {len(xml_chunks)} chunks")

                    # Combine all chunks
                    all_chunks = produced + journal_chunks + pdf_chunks + xml_chunks
                    logger.info(f"Total chunks produced: {len(all_chunks)} (patient: {len(produced)}, journal: {len(journal_chunks)}, pdf: {len(pdf_chunks)}, xml: {len(xml_chunks)})")
                else:
                    logger.info("SKIPPING CHUNKING: Chunks already cached for this session")
                    logger.info(f"Reusing {len(state.cached_chunk_ids)} pre-chunked documents")
                    # We'll retrieve directly from vector store below
                    all_chunks = []

                # Log data lineage: FHIR/PDF/XML → Chunking (only if we actually chunked)
                if needs_chunking and all_chunks:
                    await self._log_data_lineage(
                        session_id=state.session_id,
                        flow_id=str(uuid.uuid4()),
                        source_system="fhir_server" if produced else ("document_upload" if (pdf_chunks or xml_chunks) else "journal"),
                        source_type="Patient" if produced else ("PDFDocument" if pdf_chunks else ("XMLDocument" if xml_chunks else "JournalEntry")),
                        destination_system="chunking_orchestrator",
                        destination_type="Chunk",
                        transformations=["policy_driven_chunking"],  # NO phi_redaction
                        data_quality_score=1.0 if all_chunks else 0.0
                    )

                    # Log chunk details (GDPR-safe)
                    for i, chunk in enumerate(all_chunks):
                        logger.info(f"Chunk {i+1}: type={chunk.resource_type}, id={chunk.id}, length={len(chunk.text)} chars")

                # Adapt to local chunk dicts (only if we chunked)
                if needs_chunking:
                    chunks: list[dict[str, Any]] = [{
                        "chunk_id": c.id,
                        "id": c.id,  # Keep for backward compatibility
                        "content": c.text,
                        "metadata": {
                            "patient_id": patient_id_str,
                            "data_type": c.resource_type,
                            "resource_type": c.resource_type,
                            "timestamp": c.timestamp.isoformat() if c.timestamp else str(int(time.time()*1000)),
                            "document": c.meta.get("document_name", "Clinical Record") if c.meta else "Clinical Record",
                            "page": c.meta.get("page") if c.meta else None,
                            "url": c.meta.get("url") if c.meta else None,
                        },
                        "data_type": c.resource_type,
                    } for c in all_chunks]
                else:
                    # Chunks already cached - we'll retrieve from vector store below
                    chunks = []

                if needs_chunking and not chunks:
                    logger.info("No chunks produced")
                    if state.patient_ctx:
                        logger.info("Using fallback to full patient context")
                        state.retrieved_chunks = [{"content": state.patient_ctx.model_dump_json(indent=2), "chunk_id": "fallback-patient-context"}]
                        state.chunk_analysis = {"method": "fallback", "reason": "No chunks from patient context"}
                    else:
                        logger.info("No patient context or PDF content available")
                        state.retrieved_chunks = []
                        state.chunk_analysis = {"method": "none", "reason": "No content available for chunking"}
                    return state

                # 2) Embed chunks (only if we just chunked them)
                if needs_chunking and chunks:
                    logger.info(f"Embedding {len(chunks)} chunks...")
                    chunk_texts = [c["content"] for c in chunks]
                    chunk_vecs = await self._embed_many(chunk_texts, mode="passage")
                    for i, vec in enumerate(chunk_vecs):
                        chunks[i]["embedding"] = vec
                    logger.info(f"Successfully embedded {len(chunk_vecs)} chunks")

                # Log data lineage: Chunks → Embeddings (only if we just embedded)
                if needs_chunking and chunks:
                    await self._log_data_lineage(
                        session_id=state.session_id,
                        flow_id=str(uuid.uuid4()),
                        source_system="chunking_orchestrator",
                        source_type="Chunk",
                        destination_system="embedding_service",
                        destination_type="VectorEmbedding",
                        transformations=["sentence_transformer_minilm", "normalization"],
                        data_quality_score=1.0
                    )

                    # Cache chunks globally for this session
                    _GLOBAL_CHUNK_CACHE[session_cache_key] = {
                        "chunks": chunks,
                        "doc_signature": current_doc_signature,
                        "timestamp": time.time()
                    }
                    logger.info(f"Cached {len(chunks)} chunks for session {sanitize_session_id(session_cache_key)}")
                elif not needs_chunking and cached_chunks:
                    # Use cached chunks from previous query
                    logger.info(f"Reusing {len(cached_chunks)} cached chunks (skipping chunking & embedding)")
                    chunks = cached_chunks

                # 3) Query variants
                logger.info("Generating query variants...")
                try:
                    paraphrases = await self._paraphrase_query_variants(state.user_prompt)
                    logger.info(f"Generated {len(paraphrases)} paraphrases: {paraphrases}")
                except Exception as e:
                    logger.info(f"Failed to generate paraphrases: {e}")
                    paraphrases = []
                
                # If in refinement loop, include refined queries at front
                refinements = getattr(state, 'refined_queries', []) or []
                base_variants = [state.user_prompt] + paraphrases[:2]
                query_variants = refinements + base_variants
                logger.info(f"Using {len(query_variants)} query variants (content redacted for GDPR compliance)")
                
                query_vecs = await self._embed_many(query_variants, mode="query")
                logger.info(f"Successfully embedded {len(query_vecs)} query variants")

                # 4) Bi-encoder scoring (max cosine)
                logger.info(f"Computing bi-encoder scores for {len(chunks)} chunks...")
                def bi_score(vec: list[float]) -> float:
                    return max(self._cosine(vec, qv) for qv in query_vecs)
                from typing import cast
                bi_scored = [(i, bi_score(cast(list[float], chunks[i]["embedding"]))) for i in range(len(chunks))]
                bi_scored.sort(key=lambda x: x[1], reverse=True)
                
                # Log top bi-encoder scores
                logger.info("Top 5 bi-encoder scores:")
                for i, (idx, score) in enumerate(bi_scored[:5]):
                    chunk_type = chunks[idx]["data_type"]
                    logger.info(f"  {i+1}. Chunk {idx} ({chunk_type}): {score:.4f}")
                
                # Log bi-encoder score range
                if bi_scored:
                    bi_scores = [score for _, score in bi_scored]
                    logger.info(f"Bi-encoder score range: [{min(bi_scores):.4f}, {max(bi_scores):.4f}]")
                
                initial_indices = [idx for idx, _ in bi_scored[:TOPK_INITIAL]]
                logger.info(f"Selected top {len(initial_indices)} chunks for cross-encoder reranking")

                # 5-8) Cross-encoder operations (reranking, MMR, gating) - MAXIMUM PARALLEL EXECUTION
                lang = detect_language_code(state.user_prompt or "")
                logger.info(f"Detected language: {lang}")
                logger.info("Running optimized parallel cross-encoder operations...")

                # Use the new parallel method for all cross-encoder operations
                reranked, selected_indices, gate_scores = await self._run_parallel_cross_encoder_operations(
                    state, chunks, initial_indices, query_vecs
                )
                
                # Apply gating threshold
                logger.info(f"Applying binary gate with threshold {GATE_THRESH}")
                gate_results = [s >= GATE_THRESH for s in gate_scores]
                final_selected = [i for i, ok in zip(selected_indices, gate_results) if ok]
                
                # Log gating results
                logger.info("Gate results:")
                for i, (idx, score, passed) in enumerate(zip(selected_indices, gate_scores, gate_results)):
                    chunk_type = chunks[idx]["data_type"]
                    status = "PASSED" if passed else "FILTERED"
                    logger.info(f"  Chunk {idx} ({chunk_type}): {score:.4f} - {status}")
                
                logger.info(f"Final selected chunks after gating: {len(final_selected)}")
                
                # If no chunks pass gating, try with a lower threshold
                if not final_selected and gate_scores:
                    max_score = max(gate_scores)
                    logger.info(f"No chunks passed gating (max score: {max_score:.4f}), trying with lower threshold")
                    lower_threshold = min(0.3, max_score * 0.8)  # Use 80% of max score or 0.3, whichever is lower
                    logger.info(f"Using lower threshold: {lower_threshold:.4f}")
                    gate_results_lower = [s >= lower_threshold for s in gate_scores]
                    final_selected = [i for i, ok in zip(selected_indices, gate_results_lower) if ok]
                    logger.info(f"Final selected chunks with lower threshold: {len(final_selected)}")
                    
                    # Log the new results
                    for i, (idx, score, passed) in enumerate(zip(selected_indices, gate_scores, gate_results_lower)):
                        chunk_type = chunks[idx]["data_type"]
                        status = "PASSED" if passed else "FILTERED"
                        logger.info(f"  Chunk {idx} ({chunk_type}): {score:.4f} - {status}")

                # 9) Retry if too few
                # Agentic refinement handoff: if too few, set state and branch in the graph
                min_required = max(N_MIN, min(N_MAX, len(chunks)))
                state.needs_refinement = len(final_selected) < min_required and state.retrieval_retry_attempts < RETRY_MAX
                
                logger.info(f"Retry check: {len(final_selected)} < {min_required} and attempts {state.retrieval_retry_attempts} < {RETRY_MAX}")
                
                if state.needs_refinement:
                    logger.info(f"Too few chunks selected ({len(final_selected)}), attempting refinement...")
                    try:
                        refinements = await self._refine_queries(state.user_prompt, [cast(str, chunks[i]["content"]) for i in final_selected])
                        logger.info(f"Generated {len(refinements)} refined queries: {refinements}")
                        
                        # If we have refined queries, we could potentially run them in parallel here
                        # but for now, we'll use them in the next iteration
                        state.refined_queries = [r for r in refinements if r][:2]
                    except Exception as e:
                        logger.info(f"Refinement failed: {e}")
                        refinements = []
                        state.refined_queries = []
                    state.retrieval_retry_attempts += 1

                    # Set partial state for streaming decorator to show progress
                    state.retrieved_chunks = [
                        {
                            "chunk_id": chunks[i]["chunk_id"],
                            "content": chunks[i]["content"],
                            "metadata": chunks[i]["metadata"]
                        }
                        for i in final_selected
                    ] if final_selected else []

                    # Build citations from chunk metadata with sequential numbers
                    if state.retrieved_chunks:
                        state.citations, state.chunk_id_to_number = self._build_citations_from_chunks(state.retrieved_chunks)

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
                    
                    logger.info(f"Setting up for retry with {len(state.refined_queries)} refined queries")
                    # Do not finalize retrieved_chunks yet; upstream conditional edge will loop
                    return state

                if not final_selected:
                    logger.info("No chunks passed gating, using fallback selection")
                    fallback_n = min(max(N_MIN, 1), len(reranked))
                    final_selected = [idx for idx, _ in reranked[:fallback_n]]
                    logger.info(f"Fallback selected {len(final_selected)} chunks: {final_selected}")

                # Log final selected chunks (GDPR-safe)
                logger.info(f"Final selected chunks ({len(final_selected)}):")
                for i, idx in enumerate(final_selected):
                    chunk_type = chunks[idx]["data_type"]
                    chunk_length = len(cast(str, chunks[idx]["content"]))
                    logger.info(f"  {i+1}. Chunk {idx} ({chunk_type}): {chunk_length} chars")

                # Log data lineage: Embeddings → Retrieval (bi-encoder + cross-encoder + MMR + gating)
                if final_selected:
                    # Calculate data quality score based on retrieval metrics
                    avg_gate_score = sum(gate_scores) / len(gate_scores) if gate_scores else 0.0
                    selection_rate = len(final_selected) / len(chunks) if chunks else 0.0
                    quality_score = (avg_gate_score + selection_rate) / 2  # Average of gate score and selection rate

                    await self._log_data_lineage(
                        session_id=state.session_id,
                        flow_id=str(uuid.uuid4()),
                        source_system="embedding_service",
                        source_type="VectorEmbedding",
                        destination_system="retrieval_engine",
                        destination_type="RetrievedContext",
                        transformations=[
                            "bi_encoder_similarity",
                            "cross_encoder_reranking",
                            "mmr_diversification",
                            "binary_gating",
                            f"dynamic_n_selection_{len(final_selected)}"
                        ],
                        data_quality_score=min(1.0, max(0.0, quality_score))
                    )

                # Set state variables early so streaming decorator can access them
                state.retrieved_chunks = [
                    {
                        "chunk_id": chunks[i]["chunk_id"],
                        "content": chunks[i]["content"],
                        "metadata": chunks[i]["metadata"]
                    }
                    for i in final_selected
                ]

                # Build citations from chunk metadata with sequential numbers
                state.citations, state.chunk_id_to_number = self._build_citations_from_chunks(state.retrieved_chunks)
                logger.info(f"🔖 Built citations: {len(state.citations)} total")
                logger.info(f"🔖 Citation IDs: {list(state.citations.keys())}")
                if state.citations:
                    first_citation = list(state.citations.values())[0]
                    logger.info(f"🔖 First citation sample: {first_citation}")

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
                
                logger.info(f"Retrieval complete: {len(state.retrieved_chunks)} chunks selected")
                logger.info(f"Chunk analysis: {state.chunk_analysis}")
            except Exception as e:
                logger.info(f"Error: {e}")
                state.retrieved_chunks = []
                state.chunk_analysis = {"method": "error", "reason": str(e)}
                return state

            return state

        async def _fast_sbar_retrieve(state: FlowState, focus: str, queries: List[str]) -> List[Dict[str, Any]]:
            """Fast SBAR retrieval using only bi-encoder similarity (no cross-encoder)."""
            try:
                logger.info(f"{focus} - Starting fast bi-encoder retrieval")

                # Get chunks from state - try multiple sources
                chunks = []
                chunk_contents = []  # For embedding
                if state.retrieved_chunks:
                    chunks = state.retrieved_chunks[:50]  # Use cached chunks if available
                    # Extract content from chunk dictionaries
                    chunk_contents = [chunk.get("content", "") if isinstance(chunk, dict) else chunk for chunk in chunks]
                    logger.info(f"{focus} - Using {len(chunks)} cached chunks")
                else:
                    # Fall back to doing quick retrieval ourselves
                    logger.info(f"{focus} - No cached chunks, doing quick retrieval")
                    if state.patient_ctx and state.journal_entries:
                        # Quick retrieval from journal entries (most relevant for SBAR)
                        import hashlib
                        for idx, entry in enumerate(state.journal_entries[:15]):  # Limit for speed
                            content = ""
                            if hasattr(entry, 'content') and entry.content:
                                content = entry.content
                            elif hasattr(entry, 'text') and entry.text:
                                content = entry.text

                            if content:
                                # Wrap in minimal chunk dict structure
                                chunk_id = hashlib.md5(content.encode()).hexdigest()[:16]
                                chunk_dict = {
                                    "chunk_id": chunk_id,
                                    "content": content,
                                    "metadata": {"source": "journal_entry", "index": idx}
                                }
                                chunks.append(chunk_dict)
                                chunk_contents.append(content)

                    if not chunk_contents:
                        logger.info(f"{focus} - No chunks available")
                        return []

                # Bi-encoder retrieval using semantic similarity
                # Embed the queries
                query_vecs = await self._embed_many(queries, mode="query")
                logger.info(f"{focus} - Embedded {len(query_vecs)} queries")

                # Embed the chunk contents (strings)
                chunk_vecs = await self._embed_many(chunk_contents, mode="passage")
                logger.info(f"{focus} - Embedded {len(chunk_vecs)} chunks")

                # Compute bi-encoder scores (max cosine similarity across all queries)
                scored_chunks = []
                for i, chunk_vec in enumerate(chunk_vecs):
                    max_score = max(self._cosine(chunk_vec, qv) for qv in query_vecs)
                    if max_score > 0.0:  # Only include chunks with some similarity
                        # Return full chunk dict (if available) or wrap content string as dict (fallback)
                        if i < len(chunks):
                            chunk_data = chunks[i]
                        else:
                            chunk_data = {"content": chunk_contents[i], "chunk_id": f"chunk-{i}"}
                        scored_chunks.append((max_score, chunk_data))

                # Sort by score and return top chunks
                scored_chunks.sort(key=lambda x: x[0], reverse=True)
                result_chunks = [chunk for _, chunk in scored_chunks[:15]]

                logger.info(f"{focus} - Retrieved {len(result_chunks)} chunks using bi-encoder similarity")
                return result_chunks

            except Exception as e:
                logger.info(f"{focus} - Error: {e}")
                return []

        async def _generate_sbar_queries(state: FlowState, sbar_component: str, focus_instruction: str) -> List[str]:
            """Generate focused queries for each SBAR component based on the user's original query."""
            try:
                logger.info(f"Generating {sbar_component} queries (prompt_length={len(state.user_prompt)} chars)")

                # Define SBAR component specific instructions
                component_prompts = {
                    "situation": "Current symptoms, vital signs, immediate presentation, active problems, most recent encounter, most recent note",
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

                logger.info(f"Generated {len(queries)} {sbar_component} queries: {queries}")
                return queries[:3]  # Limit to 3 queries

            except Exception as e:
                log_error(logger, "_generate_sbar_queries", e)
                # Return fallback queries
                fallback_queries = {
                    "situation": ["current symptoms complaints", "vital signs measurements", "active problems"],
                    "background": ["medical history", "past conditions", "medications"],
                    "assessment": ["clinical findings", "test results", "observations"],
                    "recommendation": ["treatment plans", "medications", "follow-up"]
                }
                return fallback_queries.get(sbar_component, ["medical information"])

        async def _generate_general_summary_queries(state: FlowState, component: str, focus_instruction: str) -> List[str]:
            """Generate focused queries for each general summary component based on the user's original query."""
            try:
                logger.info(f"Generating {component} queries (prompt_length={len(state.user_prompt)} chars)")

                # Define component-specific instructions
                component_prompts = {
                    "snapshot": "Age, sex, living situation, social context, smoking/alcohol/substance use history, top 3-5 chronic conditions",
                    "problems": "Chronic diseases with onset dates, active problems, diagnosed conditions, current visit reason",
                    "medications": "Current medications with dosages, high-risk drugs (anticoagulants, opioids, insulin)",
                    "trends": "Lab values and vital signs trends over 6-12 months (HbA1c, eGFR, weight, blood pressure)",
                    "history": "Recent encounters - hospitalizations, ER visits, GP appointments, specialist consultations, procedures",
                    "risks": "Allergies, fall risk, bleeding risk, DNR status, cognitive impairment, medication side-effects"
                }

                # Add chat history context if available for better query generation
                history_context = ""
                recent_history = state.chat_history[-5:] if state.chat_history else []
                if recent_history:
                    history_lines = []
                    for msg in recent_history:
                        if msg.content and msg.content.strip():
                            role = "User" if msg.role == ChatRole.USER else "CLARA"
                            history_lines.append(f"{role}: {msg.content[:100]}")
                    if history_lines:
                        history_context = "\n\nRecent conversation:\n" + "\n".join(history_lines) + "\n"

                prompt = f"""
Based on this user query: "{state.user_prompt}"{history_context}

Generate 3 specific search queries focused on the {component.upper()} component of a comprehensive patient summary.

{component.upper()} should focus on: {component_prompts.get(component, focus_instruction)}

Return only the 3 queries, one per line, without numbers or bullets.
Keep queries concise and medical terminology appropriate.
"""

                messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a medical information specialist generating focused search queries for patient summary components."),
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
                        "snapshot": ["demographics age sex", "living situation social smoking alcohol", "chronic conditions"],
                        "problems": ["active problems", "chronic diseases", "diagnosis onset date"],
                        "medications": ["current medications", "high-risk drugs", "anticoagulants insulin"],
                        "trends": ["HbA1c trend", "eGFR kidney function", "weight vital signs"],
                        "history": ["recent hospitalizations ER visits", "GP appointments consultations", "recent procedures encounters"],
                        "risks": ["allergies", "fall risk DNR", "bleeding risk cognitive"]
                    }
                    queries.extend(fallback.get(component, ["medical information"])[:3-len(queries)])

                logger.info(f"Generated {len(queries)} {component} queries: {queries}")
                return queries[:3]  # Limit to 3 queries

            except Exception as e:
                log_error(logger, "_generate_general_summary_queries", e)
                # Return fallback queries
                fallback_queries = {
                    "snapshot": ["demographics", "social history smoking alcohol", "chronic conditions"],
                    "problems": ["active problems", "chronic diseases", "diagnosis"],
                    "medications": ["current medications", "high-risk drugs"],
                    "trends": ["lab trends", "vital signs trends"],
                    "history": ["recent hospitalizations ER visits", "GP appointments", "recent procedures"],
                    "risks": ["allergies", "fall risk", "DNR"]
                }
                return fallback_queries.get(component, ["medical information"])

        def _format_encounters_as_markdown(encounters_data: Dict[str, Any], is_swedish: bool = False) -> str:
            """Convert structured encounters JSON to markdown for card display."""
            encounters = encounters_data.get("encounters", [])
            if not encounters:
                if is_swedish:
                    return "Inga senaste vårdtillfällen dokumenterade"
                return "No recent encounters documented"

            # Group by category
            major = [e for e in encounters if e.get("category") == "major"]
            minor = [e for e in encounters if e.get("category") == "minor"]

            lines = []

            if major:
                major_header = "**Större vårdtillfällen**\n" if is_swedish else "**Major Encounters**\n"
                lines.append(major_header)
                for enc in major:
                    # Format: • **Type** (date) - brief
                    lines.append(f"• **{enc.get('encounter_type', 'Unknown')}** ({enc.get('date', 'Date unknown')}) - {enc.get('brief', 'No summary')}\n")
                lines.append("")  # Blank line between sections

            if minor:
                minor_header = "**Mindre vårdtillfällen**\n" if is_swedish else "**Minor Encounters**\n"
                lines.append(minor_header)
                for enc in minor:
                    lines.append(f"• **{enc.get('encounter_type', 'Unknown')}** ({enc.get('date', 'Date unknown')}) - {enc.get('brief', 'No summary')}\n")

            return "\n".join(lines)

        async def _fast_general_summary_retrieve(state: FlowState, focus: str, queries: List[str]) -> List[Dict[str, Any]]:
            """Fast general summary retrieval using only bi-encoder similarity (same pattern as SBAR)."""
            try:
                logger.info(f"{focus} - Starting fast bi-encoder retrieval")

                # Get chunks from state - try multiple sources
                chunks = []
                chunk_contents = []  # For embedding
                if state.retrieved_chunks:
                    chunks = state.retrieved_chunks[:50]  # Use cached chunks if available
                    # Extract content from chunk dictionaries
                    chunk_contents = [chunk.get("content", "") if isinstance(chunk, dict) else chunk for chunk in chunks]
                    logger.info(f"{focus} - Using {len(chunks)} cached chunks")
                else:
                    logger.info(f"{focus} - No cached chunks available, using keyword matching only")

                if not chunk_contents and not chunks:
                    logger.info(f"{focus} - No chunks available for retrieval")
                    return []

                # Bi-encoder retrieval using semantic similarity (same as _fast_sbar_retrieve)
                # Embed the queries
                query_vecs = await self._embed_many(queries, mode="query")
                logger.info(f"{focus} - Embedded {len(query_vecs)} queries")

                # Embed the chunk contents (strings)
                chunk_vecs = await self._embed_many(chunk_contents, mode="passage")
                logger.info(f"{focus} - Embedded {len(chunk_vecs)} chunks")

                # Compute bi-encoder scores (max cosine similarity across all queries)
                scored_chunks = []
                for i, chunk_vec in enumerate(chunk_vecs):
                    max_score = max(self._cosine(chunk_vec, qv) for qv in query_vecs)
                    if max_score > 0.0:  # Only include chunks with some similarity
                        # Return full chunk dict (if available) or wrap content string as dict (fallback)
                        if i < len(chunks):
                            chunk_data = chunks[i]
                        else:
                            chunk_data = {"content": chunk_contents[i], "chunk_id": f"chunk-{i}"}
                        scored_chunks.append((max_score, chunk_data))

                # Sort by score and return top chunks
                scored_chunks.sort(key=lambda x: x[0], reverse=True)
                result_chunks = [chunk for _, chunk in scored_chunks[:15]]

                logger.info(f"{focus} - Retrieved {len(result_chunks)} chunks using bi-encoder similarity")
                return result_chunks

            except Exception as e:
                logger.info(f"{focus} - Error: {e}")
                return []

        async def _generate_timeline_queries(state: FlowState, event_description: str, time_period: str) -> List[str]:
            """Generate focused temporal queries for each timeline event."""
            try:
                logger.info(f"Generating queries for event: '{event_description}' at '{time_period}'")

                prompt = f"""
Based on this user request: "{state.user_prompt}"

Generate 2-3 specific search queries to find information about this medical event:
Event: {event_description}
Time Period: {time_period}

Focus on:
- What happened at this specific time
- Clinical findings and observations from this period
- Treatments, medications, or interventions during this time
- Results or outcomes from this time period

Return only the queries, one per line, without numbers or bullets.
Keep queries concise and focused on the temporal aspect.
"""

                messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a medical information specialist generating temporal search queries for timeline events."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                response = await self._llm.chat(messages)

                # Parse response into individual queries
                queries = []
                for line in response.content.strip().split('\n'):
                    query = line.strip()
                    if query and not query.startswith(('1.', '2.', '3.', '-', '•')):
                        queries.append(query)

                if len(queries) < 2:
                    # Fallback queries if LLM didn't generate enough
                    fallback = [
                        f"{event_description} at {time_period}",
                        f"clinical findings {time_period}",
                        f"treatment during {time_period}"
                    ]
                    queries.extend(fallback[:3-len(queries)])

                logger.info(f"Generated {len(queries)} queries: {queries}")
                return queries[:3]  # Limit to 3 queries

            except Exception as e:
                log_error(logger, "_generate_timeline_queries", e)
                # Return fallback queries
                return [
                    f"{event_description} {time_period}",
                    f"medical events {time_period}",
                    f"clinical findings {time_period}"
                ]

        async def _extract_aspect_from_query(state: FlowState) -> tuple[str, str]:
            """Extract the medical aspect from user query and determine appropriate icon.

            Returns:
                tuple[str, str]: (aspect name, icon name)
            """
            try:
                logger.info(f"Extracting medical aspect from query: {state.user_prompt}")

                prompt = f"""
Based on this user query: "{state.user_prompt}"

Extract the specific medical aspect or condition that the user wants a focused summary about.

For example:
- "Give me a summary of the patient's heart disease" → "Heart Disease"
- "Explain the patient's lung history to me" → "Lung Conditions"
- "Summarize the diabetes management" → "Diabetes"
- "What's going on with the kidneys?" → "Kidney Health"

Return ONLY the aspect name (2-4 words maximum), nothing else.
Make it clear, concise, and clinically appropriate.
"""

                messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a medical information specialist extracting specific medical aspects from queries."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                response = await self._llm.chat(messages)
                aspect = response.content.strip().strip('"').strip("'")

                # Determine icon based on aspect (simple keyword matching)
                aspect_lower = aspect.lower()
                if any(word in aspect_lower for word in ["heart", "cardiac", "cardio"]):
                    icon = "heart"
                elif any(word in aspect_lower for word in ["lung", "pulmonary", "respiratory"]):
                    icon = "activity"
                elif any(word in aspect_lower for word in ["kidney", "renal"]):
                    icon = "droplet"
                elif any(word in aspect_lower for word in ["liver", "hepatic"]):
                    icon = "hexagon"
                elif any(word in aspect_lower for word in ["brain", "neuro", "cognitive"]):
                    icon = "brain"
                elif any(word in aspect_lower for word in ["diabetes", "glucose", "insulin"]):
                    icon = "trending-up"
                elif any(word in aspect_lower for word in ["cancer", "oncology", "tumor"]):
                    icon = "alert-circle"
                else:
                    icon = "file-text"  # Default icon

                logger.info(f"Extracted aspect: '{aspect}' with icon: '{icon}'")
                return (aspect, icon)

            except Exception as e:
                log_error(logger, "_extract_aspect_from_query", e)
                # Fallback
                return ("Medical Condition", "file-text")

        async def _generate_focused_summary_queries(state: FlowState, section: str, focus_instruction: str) -> List[str]:
            """Generate focused queries for each focused summary section based on the user's query and extracted aspect.

            Args:
                state: Flow state containing user prompt and focused aspect
                section: Section name (diagnoses, events, medications, objective_data, assessment, next_steps)
                focus_instruction: Instruction for what to focus on

            Returns:
                List[str]: List of 2-3 search queries
            """
            try:
                logger.info(f"Generating {section} queries for aspect: {state.focused_aspect}")

                # Define section-specific instructions
                section_prompts = {
                    "diagnoses": "Formal diagnoses, ICD codes, disease classifications related to the aspect",
                    "events": "Key clinical events, hospitalizations, surgeries, major interventions, disease milestones",
                    "medications": "Current and past medications, dosages, treatment regimens for the aspect",
                    "objective_data": "Lab results, vital signs, imaging findings, test results, measurements",
                    "assessment": "Clinical assessments, provider notes, current disease status, prognosis",
                    "next_steps": "Follow-up plans, pending tests, medication reviews, specialist referrals, outstanding issues"
                }

                prompt = f"""
Based on this user query: "{state.user_prompt}"

The user wants a focused summary about: {state.focused_aspect}

Generate 2-3 specific search queries to find information for the "{section}" section.

Focus on: {section_prompts.get(section, focus_instruction)}

IMPORTANT: All queries should be specific to "{state.focused_aspect}" - don't include unrelated conditions.

Return only the queries, one per line, without numbers or bullets.
Keep queries concise and medically precise.
"""

                messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a medical information specialist generating focused search queries for aspect-specific summaries."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                response = await self._llm.chat(messages)

                # Parse response into individual queries
                queries = []
                for line in response.content.strip().split('\n'):
                    query = line.strip()
                    if query and not query.startswith(('1.', '2.', '3.', '-', '•', '*')):
                        queries.append(query)

                if len(queries) < 2:
                    # Fallback queries if LLM didn't generate enough
                    fallback = {
                        "diagnoses": [f"{state.focused_aspect} diagnosis", f"{state.focused_aspect} ICD code", "disease classification"],
                        "events": [f"{state.focused_aspect} events", f"{state.focused_aspect} hospitalization", "clinical milestones"],
                        "medications": [f"{state.focused_aspect} medications", f"{state.focused_aspect} treatment", "drug regimen"],
                        "objective_data": [f"{state.focused_aspect} labs", f"{state.focused_aspect} imaging", "test results"],
                        "assessment": [f"{state.focused_aspect} assessment", f"{state.focused_aspect} status", "clinical evaluation"],
                        "next_steps": [f"{state.focused_aspect} follow-up", f"{state.focused_aspect} pending", "outstanding issues"]
                    }
                    queries.extend(fallback.get(section, [f"{state.focused_aspect} {section}"])[:3-len(queries)])

                logger.info(f"Generated {len(queries)} {section} queries: {queries}")
                return queries[:3]  # Limit to 3 queries

            except Exception as e:
                log_error(logger, "_generate_focused_summary_queries", e)
                # Return fallback queries
                return [
                    f"{state.focused_aspect or 'condition'} {section}",
                    f"medical {section}",
                    f"clinical {section}"
                ]

        @streaming_step("retrieve_situation_chunks")
        async def retrieve_situation_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on current patient situation (fast SBAR version)."""
            try:
                logger.info("Generating situation-focused queries from user prompt")

                # Generate SBAR-focused queries from the original user query
                situation_queries = await _generate_sbar_queries(state, "situation",
                    "Generate queries focused on the current patient situation and immediate concerns")

                chunks = await _fast_sbar_retrieve(state, "situation", situation_queries)
                state.sbar_situation_chunks = chunks[:10]  # Limit for speed
                logger.info(f"Retrieved {len(state.sbar_situation_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.sbar_situation_chunks = []

            return state

        @streaming_step("retrieve_background_chunks")
        async def retrieve_background_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on patient background and history (fast SBAR version)."""
            try:
                logger.info("Generating background-focused queries from user prompt")

                # Generate SBAR-focused queries from the original user query
                background_queries = await _generate_sbar_queries(state, "background",
                    "Generate queries focused on patient medical history and background")

                chunks = await _fast_sbar_retrieve(state, "background", background_queries)
                state.sbar_background_chunks = chunks[:10]  # Limit for speed
                logger.info(f"Retrieved {len(state.sbar_background_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.sbar_background_chunks = []

            return state

        @streaming_step("retrieve_assessment_chunks")
        async def retrieve_assessment_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on clinical assessment data (fast SBAR version)."""
            try:
                logger.info("Generating assessment-focused queries from user prompt")

                # Generate SBAR-focused queries from the original user query
                assessment_queries = await _generate_sbar_queries(state, "assessment",
                    "Generate queries focused on clinical assessment and diagnostic findings")

                chunks = await _fast_sbar_retrieve(state, "assessment", assessment_queries)
                state.sbar_assessment_chunks = chunks[:10]  # Limit for speed
                logger.info(f"Retrieved {len(state.sbar_assessment_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.sbar_assessment_chunks = []

            return state

        @streaming_step("retrieve_recommendation_chunks")
        async def retrieve_recommendation_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on treatment and recommendations (fast SBAR version)."""
            try:
                logger.info("Generating recommendation-focused queries from user prompt")

                # Generate SBAR-focused queries from the original user query
                recommendation_queries = await _generate_sbar_queries(state, "recommendation",
                    "Generate queries focused on treatment recommendations and next steps")

                chunks = await _fast_sbar_retrieve(state, "recommendation", recommendation_queries)
                state.sbar_recommendation_chunks = chunks[:10]  # Limit for speed
                logger.info(f"Retrieved {len(state.sbar_recommendation_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.sbar_recommendation_chunks = []

            return state

        @streaming_step("retrieve_snapshot_chunks")
        async def retrieve_snapshot_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on patient snapshot (demographics, social context, top conditions)."""
            try:
                logger.info("Generating snapshot-focused queries from user prompt")

                snapshot_queries = await _generate_general_summary_queries(state, "snapshot",
                    "Generate queries focused on patient demographics, living situation, and chronic conditions")

                chunks = await _fast_general_summary_retrieve(state, "snapshot", snapshot_queries)
                state.general_snapshot_chunks = chunks[:10]
                logger.info(f"Retrieved {len(state.general_snapshot_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_snapshot_chunks = []

            return state

        @streaming_step("retrieve_problems_chunks")
        async def retrieve_problems_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on active problems and chronic diseases."""
            try:
                logger.info("Generating problems-focused queries from user prompt")

                problems_queries = await _generate_general_summary_queries(state, "problems",
                    "Generate queries focused on active medical problems and chronic diseases")

                chunks = await _fast_general_summary_retrieve(state, "problems", problems_queries)
                state.general_problems_chunks = chunks[:10]
                logger.info(f"Retrieved {len(state.general_problems_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_problems_chunks = []

            return state

        @streaming_step("retrieve_medications_chunks")
        async def retrieve_medications_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on current medications and high-risk drugs."""
            try:
                logger.info("Generating medications-focused queries from user prompt")

                medications_queries = await _generate_general_summary_queries(state, "medications",
                    "Generate queries focused on current medications and high-risk drugs")

                chunks = await _fast_general_summary_retrieve(state, "medications", medications_queries)
                state.general_medications_chunks = chunks[:10]
                logger.info(f"Retrieved {len(state.general_medications_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_medications_chunks = []

            return state

        @streaming_step("retrieve_trends_chunks")
        async def retrieve_trends_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on lab and vital sign trends."""
            try:
                logger.info("Generating trends-focused queries from user prompt")

                trends_queries = await _generate_general_summary_queries(state, "trends",
                    "Generate queries focused on lab values and vital signs trends")

                chunks = await _fast_general_summary_retrieve(state, "trends", trends_queries)
                state.general_trends_chunks = chunks[:10]
                logger.info(f"Retrieved {len(state.general_trends_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_trends_chunks = []

            return state

        @streaming_step("retrieve_history_chunks")
        async def retrieve_history_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on past medical history (surgeries, hospitalizations)."""
            try:
                logger.info("Generating history-focused queries from user prompt")

                history_queries = await _generate_general_summary_queries(state, "history",
                    "Generate queries focused on major hospitalizations and surgeries")

                chunks = await _fast_general_summary_retrieve(state, "history", history_queries)
                state.general_history_chunks = chunks[:10]
                logger.info(f"Retrieved {len(state.general_history_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_history_chunks = []

            return state

        @streaming_step("retrieve_risks_chunks")
        async def retrieve_risks_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on patient risks and alerts (allergies, falls, DNR)."""
            try:
                logger.info("Generating risks-focused queries from user prompt")

                risks_queries = await _generate_general_summary_queries(state, "risks",
                    "Generate queries focused on allergies, fall risk, and clinical alerts")

                chunks = await _fast_general_summary_retrieve(state, "risks", risks_queries)
                state.general_risks_chunks = chunks[:10]
                logger.info(f"Retrieved {len(state.general_risks_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_risks_chunks = []

            return state

        def _categorize_prompt(prompt: str) -> str:
            """Categorize user prompt for GDPR-safe analytics."""
            prompt_lower = prompt.lower()
            
            # Medical/Clinical categories
            if any(word in prompt_lower for word in ['diagnose', 'diagnosis', 'what is', 'what are', 'disease', 'condition']):
                return "Diagnosis"
            elif any(word in prompt_lower for word in ['summary', 'summarize', 'overview', 'brief']):
                return "Summary"
            elif any(word in prompt_lower for word in ['search', 'find', 'look for', 'locate']):
                return "Search"
            elif any(word in prompt_lower for word in ['explain', 'what does', 'how does', 'why']):
                return "Explanation"
            elif any(word in prompt_lower for word in ['treatment', 'therapy', 'medication', 'drug', 'prescription']):
                return "Treatment"
            elif any(word in prompt_lower for word in ['symptom', 'signs', 'presentation', 'manifestation']):
                return "Symptoms"
            elif any(word in prompt_lower for word in ['test', 'lab', 'blood', 'imaging', 'scan', 'x-ray', 'mri', 'ct']):
                return "Testing"
            elif any(word in prompt_lower for word in ['history', 'background', 'past', 'previous']):
                return "History"
            elif any(word in prompt_lower for word in ['compare', 'difference', 'versus', 'vs', 'contrast']):
                return "Comparison"
            elif any(word in prompt_lower for word in ['risk', 'complication', 'side effect', 'adverse']):
                return "Risk Assessment"
            else:
                return "General"

        async def store_user_message(state: FlowState) -> FlowState:
            """Store the user message in ephemeral memory with end-to-end encryption and GDPR-safe metrics."""
            if not state.user_prompt:
                return state

            try:
                logger.info(f"🔐 Storing user message for session_id={sanitize_session_id(state.session_id)}")
                logger.info(f"📝 Message length: {len(state.user_prompt)} chars")

                # Generate session encryption key if not exists
                session_manager = get_session_encryption_manager()
                if state.session_id and not session_manager.get_session_key(state.session_id):
                    session_manager.generate_session_key(state.session_id)
                    logger.info(f"🔑 Generated new session key for {sanitize_session_id(state.session_id)}")

                # Encrypt user message for secure storage
                encrypted_message = {
                    "role": "user",
                    "content": state.user_prompt,
                    "timestamp": str(int(time.time() * 1000)),
                    "user_id": state.user_id or ""
                }

                # Store encrypted message in session memory
                if state.session_id:
                    self._session_memory.setdefault(state.session_id, [])
                    # Encrypt the entire message
                    encrypted_data = session_manager.encrypt_session_data(state.session_id, encrypted_message)
                    self._session_memory[state.session_id].append({
                        "encrypted": True,
                        "data": encrypted_data,
                        "timestamp": str(int(time.time() * 1000))
                    })

                    # Debug: Show current session memory size
                    current_size = len(self._session_memory[state.session_id])
                    total_sessions = len(self._session_memory)
                    logger.info(f"💾 Session memory now has {current_size} messages")
                    logger.info(f"🗂️ Global memory tracking {total_sessions} sessions total")
                    logger.info(f"🆔 Session memory ID: {id(self._session_memory)}")
                else:
                    logger.info("⚠️ No session_id provided, message not stored")

                # Store GDPR-safe user metrics for analytics (not encrypted - no PHI)
                if state.user_id:
                    prompt_category = _categorize_prompt(state.user_prompt)
                    
                    # Create user action for metrics
                    user_action = UserAction(
                        action_id=str(uuid.uuid4()),
                        user_id=state.user_id,
                        action_type="chat_message",
                        resource_type="prompt",
                        resource_id=str(uuid.uuid4()),
                        description=f"User sent {prompt_category.lower()} prompt",
                        metadata={
                            "prompt_category": prompt_category,
                            "prompt_length": len(state.user_prompt),
                            "session_id": state.session_id or "",
                            "has_patient_id": bool(state.patient_id),
                            "timestamp": str(int(time.time() * 1000)),
                            "mode": "info_flow",
                            "encrypted": True
                        }
                    )
                    
                    # Store metrics in database
                    await self._user_repo.create_user_action(user_action)
                    logger.info(f"Stored encrypted GDPR-safe metrics: {prompt_category} prompt from user {sanitize_user_id(state.user_id)}")
                
            except Exception as e:
                logger.info(f"Error: {e}")
                import traceback
                traceback.print_exc()
            
            return state

        async def store_assistant_response(state: FlowState) -> FlowState:
            """Store the assistant response in ephemeral memory with encryption and GDPR-safe metrics."""
            if not state.llm_response:
                logger.info("⚠️ No LLM response to store")
                return state

            try:
                logger.info(f"🤖 Storing assistant response for session_id={sanitize_session_id(state.session_id)}")
                logger.info(f"📝 Response: '{state.llm_response.content[:100]}...'")

                # Generate session encryption key if not exists
                session_manager = get_session_encryption_manager()
                if state.session_id and not session_manager.get_session_key(state.session_id):
                    session_manager.generate_session_key(state.session_id)
                    logger.info(f"🔑 Generated new session key for {sanitize_session_id(state.session_id)}")

                # Use the assistant message content as-is
                clean_content = state.llm_response.content

                logger.info(f"🧹 Cleaned content: {len(clean_content)} chars (was {len(state.llm_response.content)} chars)")

                # Encrypt assistant message for secure storage
                encrypted_message = {
                    "role": state.llm_response.role.value,
                    "content": clean_content,
                    "timestamp": str(int(time.time() * 1000)),
                    "user_id": state.user_id or ""
                }

                # Store encrypted message in session memory
                if state.session_id:
                    self._session_memory.setdefault(state.session_id, [])
                    # Encrypt the entire message
                    encrypted_data = session_manager.encrypt_session_data(state.session_id, encrypted_message)
                    self._session_memory[state.session_id].append({
                        "encrypted": True,
                        "data": encrypted_data,
                        "timestamp": str(int(time.time() * 1000))
                    })

                    # Debug: Show current session memory size
                    current_size = len(self._session_memory[state.session_id])
                    logger.info(f"💾 Session memory now has {current_size} messages")
                else:
                    logger.info("⚠️ No session_id provided, response not stored")

            except Exception as e:
                logger.info(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()

            return state

        @streaming_step("generate_sbar_situation")
        async def generate_sbar_situation(state: FlowState) -> FlowState:
            """Generate SBAR Situation component."""
            try:
                logger.info("Starting SBAR Situation generation")

                # Get situation-specific chunks
                situation_chunks = state.sbar_situation_chunks or []

                # Build prompt for situation
                situation_prompt = f"""
                Generate a concise SBAR Situation summary with 5-7 bullet points.

                USER QUERY: {state.user_prompt}

                Format as 5-7 bullet points covering:
                • **Chief complaint**: [concise description with key symptoms]
                • **Current presentation**: [current status and vital signs]
                • **Acute symptoms**: [most pressing symptoms/concerns]
                • **Pain/distress level**: [if applicable]
                • **Recent changes**: [any deterioration or improvement]
                • **Immediate concerns**: [urgent issues requiring attention]
                • **Patient awareness**: [patient's understanding/concern level]

                Example:
                • **Chief complaint**: Patient presenting with **chest pain** radiating to left arm, started 2 hours ago [1]
                • **Current presentation**: **BP 145/90**, HR 92, **diaphoretic**, appears anxious [2]
                • **Acute symptoms**: **Crushing substernal pain** 7/10, worse with exertion, not relieved by rest [1]
                • **Recent changes**: Pain intensity **increased** from 5/10 to 7/10 in last hour [3]
                • **Immediate concerns**: **Possible ACS**, needs urgent ECG and troponin [2]

                Add blank line between each bullet point for readability.

                MANDATORY:
                - Use **bold** markdown for symptoms, vital signs, and key clinical terms
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                CRITICAL: 5-7 concise bullet points. Keep focused on current situation only.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA, a clinical information assistant. Create SBAR situation summaries with 5-7 bullet points. Use **bold** for symptoms, vital signs, and key clinical terms.\n\nIMPORTANT: Information system only - NOT a medical device. Provide general educational information, not patient-specific diagnostic advice. Users must make their own decisions.")
                ]

                # Add conversation history for context (excluding current message)
                recent_history = state.chat_history[-10:] if state.chat_history else []
                if recent_history:
                    # Use text-based summary to avoid Azure API issues
                    conversation_lines = []
                    for msg in recent_history:
                        if not msg.content or not msg.content.strip():
                            continue
                        content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                        role_name = "You" if msg.role == ChatRole.USER else "CLARA"
                        conversation_lines.append(f"{role_name}: {content}")

                    if conversation_lines:
                        conversation_summary = "\n".join(conversation_lines)
                        history_context = ChatMessage(
                            role=ChatRole.USER,
                            content=f"Recent conversation context:\n{conversation_summary}"
                        )
                        messages.append(history_context)

                # Add the main prompt
                messages.append(ChatMessage(role=ChatRole.USER, content=situation_prompt))

                # Add chunks if available
                if situation_chunks:
                    # Limit chunks to prevent context overflow
                    limited_chunks = self._limit_chunks_for_context(situation_chunks, max_tokens=200000, max_chunk_chars=50000)
                    # Format chunks with citation references
                    chunk_content = "Relevant patient information:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                # Generate response
                response = await self._llm.chat(messages, enable_chunk_citations=True)

                # Store in SBAR results
                state.sbar_situation_result = response.content.strip()
                state.sbar_situation_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated situation summary: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.sbar_situation_result = f"Error generating situation summary: {str(e)}"

            return state

        @streaming_step("generate_sbar_background")
        async def generate_sbar_background(state: FlowState) -> FlowState:
            """Generate SBAR Background component."""
            try:
                logger.info("Starting SBAR Background generation")

                # Get background-specific chunks
                background_chunks = state.sbar_background_chunks or []

                # Build prompt for background
                background_prompt = f"""
                Generate a concise SBAR Background summary with 5-7 bullet points.

                USER QUERY: {state.user_prompt}

                Format as 5-7 bullet points covering:
                • **Patient demographics**: [age, sex, living situation]
                • **Major diagnoses**: [key chronic conditions with dates]
                • **Critical medications**: [important meds especially high-risk ones]
                • **Important allergies**: [drug allergies and reactions]
                • **Past procedures/surgeries**: [relevant surgical history]
                • **Recent admissions**: [hospitalizations in last 6-12 months]
                • **Baseline function**: [usual activity level and independence]

                Example:
                • **Patient demographics**: **73M**, lives alone, retired, has home care 2x/week [1]
                • **Major diagnoses**: **T2DM** (2010), **HTN** (2005), **CKD Stage 3a** (2018), **COPD GOLD II** (2015) [2]
                • **Critical medications**: **Warfarin 5mg** (INR target 2-3), **Metformin 1000mg 2x/day**, **Enalapril 20mg** [3]
                • **Important allergies**: **Penicillin** (rash and angioedema 2008) [4]
                • **Past procedures**: **Hip replacement** (2015), **Cholecystectomy** (2001) [5]
                • **Recent admissions**: **COPD exacerbation** (3 months ago), treated with antibiotics and steroids [6]
                • **Baseline function**: **Independent** with ADLs, uses walker for mobility, cognitively intact [1]

                Add blank line between each bullet point for readability.

                MANDATORY:
                - Use **bold** markdown for key diagnoses, medications, allergies, and functional descriptors
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                CRITICAL: 5-7 concise bullet points. Focus on context relevant to current situation.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA, a clinical information assistant. Create SBAR background summaries with 5-7 bullet points. Use **bold** for diagnoses, medications, allergies, and key descriptors.\n\nIMPORTANT: Information system only - NOT a medical device. Provide general educational information, not patient-specific diagnostic advice. Users must make their own decisions.\n\nMANDATORY: Include citations after each statement - NOT verbose citations. Keep concise and contextually relevant.")
                ]

                # Add conversation history for context (excluding current message)
                recent_history = state.chat_history[-10:] if state.chat_history else []
                if recent_history:
                    # Use text-based summary to avoid Azure API issues
                    conversation_lines = []
                    for msg in recent_history:
                        if not msg.content or not msg.content.strip():
                            continue
                        content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                        role_name = "You" if msg.role == ChatRole.USER else "CLARA"
                        conversation_lines.append(f"{role_name}: {content}")

                    if conversation_lines:
                        conversation_summary = "\n".join(conversation_lines)
                        history_context = ChatMessage(
                            role=ChatRole.USER,
                            content=f"Recent conversation context:\n{conversation_summary}"
                        )
                        messages.append(history_context)

                # Add the main prompt
                messages.append(ChatMessage(role=ChatRole.USER, content=background_prompt))

                # Add chunks if available
                if background_chunks:
                    # Limit chunks to prevent context overflow
                    limited_chunks = self._limit_chunks_for_context(background_chunks, max_tokens=200000, max_chunk_chars=50000)
                    chunk_content = "Relevant patient information:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                # Generate response
                response = await self._llm.chat(messages, enable_chunk_citations=True)

                # Store in SBAR results
                state.sbar_background_result = response.content.strip()
                state.sbar_background_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated background summary: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.sbar_background_result = f"Error generating background summary: {str(e)}"

            return state

        @streaming_step("generate_sbar_assessment")
        async def generate_sbar_assessment(state: FlowState) -> FlowState:
            """Generate SBAR Assessment component."""
            try:
                logger.info("Starting SBAR Assessment generation")

                # Get assessment-specific chunks
                assessment_chunks = state.sbar_assessment_chunks or []

                # Build prompt for assessment
                assessment_prompt = f"""
                Generate a concise SBAR Assessment summary with 5-7 bullet points in narrative style.

                USER QUERY: {state.user_prompt}

                Format as 5-7 bullet points with free-text narrative descriptions:
                • **Clinical impression**: [narrative description with key observations]
                • **Current status**: [narrative summary of patient's condition]
                • **Key findings**: [narrative of significant clinical findings]
                • **Trend analysis**: [narrative of improvement/deterioration]
                • **Risk assessment**: [narrative of current risk level and factors]
                • **Stability**: [narrative of patient stability and prognosis]
                • **Critical concerns**: [narrative of urgent issues if any]

                Example:
                • **Clinical impression**: Patient with **multimorbidity** showing signs of **worsening diabetic control** with HbA1c rising from 62 to 68 mmol/mol over 6 months [1]
                • **Current status**: Generally **stable** but requires medication adjustment and closer monitoring of renal function given declining eGFR [2]
                • **Key findings**: **Declining kidney function** (eGFR 64→52), **elevated blood pressure** (145/85), and **worsening glycemic control** suggest need for therapeutic review [1]
                • **Risk assessment**: **Moderate-to-high risk** for cardiovascular events given uncontrolled HTN, T2DM, and CKD Stage 3a [3]
                • **Critical concerns**: Patient on **warfarin** with recent **INR fluctuations**, requires close monitoring to prevent bleeding complications [4]

                Add blank line between each bullet point for readability.

                MANDATORY:
                - Use **bold** markdown for important clinical terms, values, and risk levels
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                - Write in narrative free-text style within each bullet point
                CRITICAL: 5-7 bullet points with narrative descriptions. Each bullet contains a flowing sentence, not just keywords. Keep concise but informative.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA, a clinical information assistant. Create SBAR assessment summaries with 5-7 bullet points in narrative style. Use **bold** for important clinical terms and values. Write flowing sentences within each bullet point.\n\nIMPORTANT: Information system only - NOT a medical device. Provide general educational information about clinical findings, not patient-specific diagnostic advice. Users must make their own decisions.\n\nMANDATORY: Include citations after each statement - NOT verbose citations. Keep concise but informative.")
                ]

                # Add conversation history for context (excluding current message)
                recent_history = state.chat_history[-10:] if state.chat_history else []
                if recent_history:
                    # Use text-based summary to avoid Azure API issues
                    conversation_lines = []
                    for msg in recent_history:
                        if not msg.content or not msg.content.strip():
                            continue
                        content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                        role_name = "You" if msg.role == ChatRole.USER else "CLARA"
                        conversation_lines.append(f"{role_name}: {content}")

                    if conversation_lines:
                        conversation_summary = "\n".join(conversation_lines)
                        history_context = ChatMessage(
                            role=ChatRole.USER,
                            content=f"Recent conversation context:\n{conversation_summary}"
                        )
                        messages.append(history_context)

                # Add the main prompt
                messages.append(ChatMessage(role=ChatRole.USER, content=assessment_prompt))

                # Add chunks if available
                if assessment_chunks:
                    # Limit chunks to prevent context overflow
                    limited_chunks = self._limit_chunks_for_context(assessment_chunks, max_tokens=200000, max_chunk_chars=50000)
                    chunk_content = "Relevant patient information:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                # Generate response
                response = await self._llm.chat(messages, enable_chunk_citations=True)

                # Store in SBAR results
                state.sbar_assessment_result = response.content.strip()
                state.sbar_assessment_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated assessment summary: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.sbar_assessment_result = f"Error generating assessment summary: {str(e)}"

            return state

        @streaming_step("generate_sbar_recommendation")
        async def generate_sbar_recommendation(state: FlowState) -> FlowState:
            """Generate SBAR Recommendation component."""
            try:
                logger.info("Starting SBAR Recommendation generation")

                # Get recommendation-specific chunks
                recommendation_chunks = state.sbar_recommendation_chunks or []

                # Build prompt for recommendation
                recommendation_prompt = f"""
                Generate a concise SBAR Recommendation summary with 5-7 bullet points.

                USER QUERY: {state.user_prompt}

                Format as 5-7 bullet points covering:
                • **Urgent interventions**: [immediate actions needed]
                • **Diagnostic workup**: [tests/imaging required]
                • **Treatment adjustments**: [medication/therapy changes]
                • **Monitoring plan**: [what to watch and frequency]
                • **Consultation needs**: [specialists to involve]
                • **Follow-up timing**: [when to reassess]
                • **Safety measures**: [precautions and risk mitigation]

                Example:
                • **Urgent interventions**: Obtain **12-lead ECG** immediately, establish **IV access**, give **aspirin 300mg** if not contraindicated [1]
                • **Diagnostic workup**: **Troponin** at 0 and 3 hours, **chest X-ray**, continuous **cardiac monitoring** [2]
                • **Treatment adjustments**: Consider **nitroglycerin SL** for chest pain, hold **metformin** if contrast study needed [3]
                • **Monitoring plan**: **Vital signs q15min**, monitor for **arrhythmias**, assess **pain response** to treatment [4]
                • **Consultation needs**: **Cardiology** consult for possible ACS, consider **interventional** if STEMI criteria met [5]
                • **Follow-up timing**: Reassess after **troponin results**, plan disposition based on findings [6]
                • **Safety measures**: Keep patient **NPO**, ensure **resuscitation equipment** at bedside, discuss **code status** if not documented [7]

                Add blank line between each bullet point for readability.

                MANDATORY:
                - Use **bold** markdown for interventions, tests, medications, and key actions
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                CRITICAL: 5-7 concise bullet points. Educational information only - refer complex decisions to healthcare providers. Keep actionable.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA, a clinical information assistant. Create SBAR recommendation summaries with 5-7 bullet points. Use **bold** for interventions, tests, medications, and key actions.\n\nIMPORTANT: Information system only - NOT a medical device. Provide general educational information about treatment approaches, not patient-specific recommendations. Users must make their own decisions.\n\nMANDATORY: Include citations after each statement - NOT verbose citations. Keep concise and actionable.")
                ]

                # Add conversation history for context (excluding current message)
                recent_history = state.chat_history[-10:] if state.chat_history else []
                if recent_history:
                    # Use text-based summary to avoid Azure API issues
                    conversation_lines = []
                    for msg in recent_history:
                        if not msg.content or not msg.content.strip():
                            continue
                        content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                        role_name = "You" if msg.role == ChatRole.USER else "CLARA"
                        conversation_lines.append(f"{role_name}: {content}")

                    if conversation_lines:
                        conversation_summary = "\n".join(conversation_lines)
                        history_context = ChatMessage(
                            role=ChatRole.USER,
                            content=f"Recent conversation context:\n{conversation_summary}"
                        )
                        messages.append(history_context)

                # Add the main prompt
                messages.append(ChatMessage(role=ChatRole.USER, content=recommendation_prompt))

                # Add chunks if available
                if recommendation_chunks:
                    # Limit chunks to prevent context overflow
                    limited_chunks = self._limit_chunks_for_context(recommendation_chunks, max_tokens=200000, max_chunk_chars=50000)
                    chunk_content = "Relevant patient information:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                # Generate response
                response = await self._llm.chat(messages, enable_chunk_citations=True)

                # Store in SBAR results
                state.sbar_recommendation_result = response.content.strip()
                state.sbar_recommendation_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated recommendation summary: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.sbar_recommendation_result = f"Error generating recommendation summary: {str(e)}"

            return state

        @streaming_step("generate_snapshot_summary")
        async def generate_snapshot_summary(state: FlowState) -> FlowState:
            """Generate Patient Snapshot component."""
            try:
                logger.info("Starting Snapshot generation")

                chunks = state.general_snapshot_chunks or []

                prompt = f"""
                Create a concise Patient Snapshot with 5 bullet points with headers:

                USER QUERY: {state.user_prompt}

                Format as 5 bullet points with the following bold headers:
                • **Demographics:** [Age, sex]
                • **Living Situation:** [Living arrangement, occupation/status]
                • **Functional Status:** [Mobility and independence level]
                • **Social Support:** [Care situation]
                • **Lifestyle Factors:** [Smoking, alcohol, substance use, diet, exercise]

                Example:
                • **Demographics:** **73 Male** (recorded 2024-01-15) [1]
                • **Living Situation:** Lives alone, **retired teacher** (recorded 2023-12-10) [2]
                • **Functional Status:** **Independent** with ADLs, uses walker (assessed 2023-11-20) [3]
                • **Social Support:** **Home care** 2x/week (started 2023-10-01) [4]
                • **Lifestyle Factors:** **Ex-smoker**, quit 2010; **occasional alcohol**; low exercise (2024-01-10) [5]

                MANDATORY:
                - Each bullet must have a bold header followed by colon
                - Use **bold** markdown for important clinical terms, values, and key phrases
                - CRITICAL: Include date/time stamp in parentheses (YYYY-MM-DD or YYYY-MM-DD HH:MM) showing when the information was recorded
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                - Add blank line between each bullet point for readability
                CRITICAL: 5 bullet points with headers. 6-12 words each. Each bullet point one line. Include dates. Keep very concise and scannable.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA. Create concise snapshots with 5-7 bullet points, each with a bold header. Use **bold** for important clinical terms and values. CRITICAL: Include date/time stamps (YYYY-MM-DD or YYYY-MM-DD HH:MM) in parentheses for when each piece of information was recorded. One line per bullet point. No explanations.\n\nMANDATORY: Include citations after each statement - NOT verbose citations. Add blank lines between bullets. Always include dates.\n\nInformation system only - NOT a medical device.")
                ]

                # Add conversation history for context (excluding current message)
                recent_history = state.chat_history[-10:] if state.chat_history else []
                if recent_history:
                    conversation_lines = []
                    for msg in recent_history:
                        if not msg.content or not msg.content.strip():
                            continue
                        content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                        role_name = "You" if msg.role == ChatRole.USER else "CLARA"
                        conversation_lines.append(f"{role_name}: {content}")

                    if conversation_lines:
                        conversation_summary = "\n".join(conversation_lines)
                        history_context = ChatMessage(
                            role=ChatRole.USER,
                            content=f"Recent conversation context:\n{conversation_summary}"
                        )
                        messages.append(history_context)

                # Add the main prompt
                messages.append(ChatMessage(role=ChatRole.USER, content=prompt))

                # Add chunks if available
                if chunks:
                    # Limit chunks to prevent context overflow (max 50k chars per chunk, 200k tokens total)
                    limited_chunks = self._limit_chunks_for_context(chunks, max_tokens=200000, max_chunk_chars=50000)
                    chunk_content = "Relevant patient information:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                response = await self._llm.chat(messages, enable_chunk_citations=True)
                state.general_snapshot_result = response.content.strip()
                state.general_snapshot_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated snapshot summary: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_snapshot_result = f"Error generating snapshot: {str(e)}"

            return state

        @streaming_step("generate_problems_summary")
        async def generate_problems_summary(state: FlowState) -> FlowState:
            """Generate Active Problems component."""
            try:
                logger.info("Starting Active Problems generation")

                chunks = state.general_problems_chunks or []

                prompt = f"""
                List the top 5-7 problems divided into two subsections - EXACTLY 6-12 words per bullet.

                USER QUERY: {state.user_prompt}

                Format with TWO subsections (most relevant and frequently mentioned at the top of each list):

                # Current Conditions
                • **Disease name** (year) - status

                # Previous Conditions
                • **Disease name** (year) - status

                Example (count the words - each is 6-12 words):
                # Current Conditions
                • **T2DM** (diagnosed 2012) **HbA1c 68** moderate control (2024-01-15) [1]

                • **HTN** (since 2005) **BP 145/85** on treatment (2024-01-15 09:00) [2] 

                • **CKD Stage 3a** (2020) **eGFR 52** monitored (2024-01-15 08:30) [3]

                # Previous Conditions
                • **COPD GOLD II** (2018) stable uses inhaler (reviewed 2024-01-10) [4]

                • **Osteoarthritis** bilateral knees uses walker (assessed 2023-12-20) [5] 

                Add blank line between each bullet point for readability.

                If there are MORE problems in the data (beyond 5-7), add at the end:
                "_Fråga om fler diagnoser_" (Swedish) or "_Ask for more diagnoses_" (English)

                MANDATORY:
                - Divide into **Current Conditions** (active/ongoing) and **Previous Conditions** (resolved/historical)
                - Sort by relevance and frequency - most mentioned/relevant at the top of each subsection
                - Use **bold** markdown for disease names and key values
                - CRITICAL: Include date/time stamp in parentheses (YYYY-MM-DD or YYYY-MM-DD HH:MM) showing when the information was recorded/updated
                - Each bullet MUST be between 6-12 words (excluding date and citation) - COUNT THEM
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                CRITICAL: 5-7 problems total across both subsections. 6-12 words each. Include dates. Blank lines between bullets. Very scannable.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA. List top 5-7 problems divided into two subsections: **Current Conditions** and **Previous Conditions**. Sort by relevance and frequency within each subsection. Use **bold** for disease names and key values. CRITICAL: Include date/time stamps (YYYY-MM-DD or YYYY-MM-DD HH:MM) in parentheses. Each bullet point must be EXACTLY 6-12 words (excluding date and citation). Count words carefully. Add 'ask for more' hint if additional problems exist.\n\nMANDATORY: Include citations after each statement - NOT verbose citations. Always include dates.\n\nInformation system only - NOT a medical device."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                if chunks:
                    # Limit chunks to prevent context overflow (max 50k chars per chunk, 200k tokens total)
                    limited_chunks = self._limit_chunks_for_context(chunks, max_tokens=200000, max_chunk_chars=50000)
                    chunk_content = "Relevant patient information:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                response = await self._llm.chat(messages, enable_chunk_citations=True)
                state.general_problems_result = response.content.strip()
                state.general_problems_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated problems summary: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_problems_result = f"Error generating problems: {str(e)}"

            return state

        @streaming_step("generate_medications_summary")
        async def generate_medications_summary(state: FlowState) -> FlowState:
            """Generate Medications Overview component."""
            try:
                logger.info("Starting Medications generation")

                chunks = state.general_medications_chunks or []

                prompt = f"""
                List 5-7 most important/recent medications divided into two subsections - EXACTLY 6-12 words per bullet.

                USER QUERY: {state.user_prompt}

                Format with TWO subsections (most relevant at the top of each list):

                # Current Medications
                • **Drug name dose** (started YYYY-MM-DD) - purpose
                • **Drug 250mg→500mg** ↑ (increased YYYY-MM-DD) - purpose/reason for change
                • 🔺 **Drug dose** (dates) - purpose ALLERGY NOTED  ← Add 🔺 if patient has documented allergy
                • ⚠️ **High-risk drug dose** (dates) - purpose  ← Mark anticoagulants, opioids, insulin with ⚠️

                # Prior Medications
                • **Drug dose** (started YYYY-MM-DD, stopped YYYY-MM-DD) - reason for discontinuation

                Example (count the words - each is 6-12 words):
                # Current Medications
                • **Metformin 1000mg 2x/day** (started 2024-01-10) - diabetes control **HbA1c 68** [1] (10 words)

                • **Enalapril 5mg→10mg** ↑ (increased 2024-01-15) - BP control dose adjustment [2] (10 words)

                • 🔺 **Penicillin 250mg→500mg** ↑ (increased 2024-01-05) - infection worsened ALLERGY NOTED [3] (11 words)

                • ⚠️ **Warfarin 5mg** (started 2023-11-01) - anticoagulation **INR 2.5** [4] (9 words)

                # Prior Medications
                • **Simvastatin 20mg** (2020-05-15 to 2023-12-20) - switched to atorvastatin [5] (10 words)

                Add blank line between each bullet point for readability.

                If there are MORE medications (beyond 5-7), add at the end:
                "_Fråga om fler läkemedel_" (Swedish) or "_Ask for more medications_" (English)

                MANDATORY:
                - Divide into **Current Medications** (active) and **Prior Medications** (discontinued, only if relevant to user query)
                - Sort by relevance - most relevant at the top of each subsection
                - Use **bold** markdown for drug names, doses, and key values
                - Show dose changes as **OldDose→NewDose** with ↑ (increase) or ↓ (decrease) arrows
                - Add 🔺 if patient has documented allergy to that medication (check allergy mentions in data)
                - CRITICAL: Include start date for all medications; include end date for discontinued medications
                - For dose changes, include the date of change and brief explanation
                - Each bullet MUST be between 6-12 words (excluding dates and citation) - COUNT THEM
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                CRITICAL: 5-7 most important meds total. 6-12 words each. Include dates. Blank lines between bullets. Prior medications only if relevant. Very scannable.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA. List 5-7 most important medications divided into two subsections: **Current Medications** (active) and **Prior Medications** (discontinued, only if relevant to user query). Sort by relevance within each subsection. Use **bold** for drug names, doses, and key values. Mark high-risk with ⚠️. Add 🔺 if patient has documented allergy to the medication (check allergy mentions in data). Show dose changes as **OldDose→NewDose** with ↑/↓ arrows. CRITICAL: Include start dates for all medications, end dates for discontinued ones, and change dates for dose adjustments. Each bullet point must be EXACTLY 6-12 words (excluding dates and citation). Count words carefully. Explain why doses or medications were changed.\n\nMANDATORY: Include citations after each statement - NOT verbose citations. Always include dates. Prior medications only if relevant to query.\n\nInformation system only - NOT a medical device."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                if chunks:
                    # Limit chunks to prevent context overflow (max 50k chars per chunk, 200k tokens total)
                    limited_chunks = self._limit_chunks_for_context(chunks, max_tokens=200000, max_chunk_chars=50000)
                    chunk_content = "Relevant patient information:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                response = await self._llm.chat(messages, enable_chunk_citations=True)
                state.general_medications_result = response.content.strip()
                state.general_medications_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated medications summary: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_medications_result = f"Error generating medications: {str(e)}"

            return state

        @streaming_step("generate_trends_summary")
        async def generate_trends_summary(state: FlowState) -> FlowState:
            """Generate Lab/Vital Trends component."""
            try:
                logger.info("Starting Trends generation")

                chunks = state.general_trends_chunks or []

                prompt = f"""
                Show 5-7 key lab/vital trends - EXACTLY 6-12 words per bullet. Use arrows: ↑ ↓ →

                USER QUERY: {state.user_prompt}

                Format (ONE line per value, 6-12 words ONLY):
                • **Lab/Vital**: old → **new** (arrow) note

                Example (count the words - each is 6-12 words):
                • **HbA1c**: 62 (2023-07-10) → **68 mmol/mol** (2024-01-15) (↑) worsening control [1] (12 words)
                • **eGFR**: 64 (2023-06-15) → **52** (2024-01-15 08:30) (↓) declining kidney function [2] (12 words)
                • **Weight**: 98 (2023-12-01) → **96 kg** (2024-01-15 09:00) (↓) intentional loss [3] (12 words)
                • **BP**: 135/80 (2023-11-10) → **145/85** (2024-01-15 09:00) (↑) target 140/90 [4] (12 words)
                • **INR**: 2.8 (2024-01-08) → **2.5** (2024-01-15 09:00) (↓) now in range [5] (12 words)

                Add blank line between each bullet point for readability.

                If there are MORE lab values/trends available, add at the end:
                "_Fråga om fler trender_" (Swedish) or "_Ask for more trends_" (English)

                MANDATORY:
                - Use **bold** markdown for parameter names and current values
                - CRITICAL: Include date/time stamps (YYYY-MM-DD or YYYY-MM-DD HH:MM) in parentheses for BOTH old and new values
                - Each bullet MUST be between 6-12 words (excluding dates and citation) - COUNT THEM
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                CRITICAL: 5-7 most important trends. 6-12 words each. Include dates for both values. Blank lines between bullets. Very scannable.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA. Show 5-7 key trends. Use **bold** for parameter names and current values. CRITICAL: Include date/time stamps (YYYY-MM-DD or YYYY-MM-DD HH:MM) in parentheses for BOTH old and new values. Each bullet point must be EXACTLY 6-12 words (excluding dates and citation). Count words carefully. Add 'ask for more' if additional trends exist.\n\nMANDATORY: Include citations after each statement - NOT verbose citations. Always include dates.\n\nInformation system only - NOT a medical device."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                if chunks:
                    # Limit chunks to prevent context overflow (max 50k chars per chunk, 200k tokens total)
                    limited_chunks = self._limit_chunks_for_context(chunks, max_tokens=200000, max_chunk_chars=50000)
                    chunk_content = "Relevant patient information:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                response = await self._llm.chat(messages, enable_chunk_citations=True)
                state.general_trends_result = response.content.strip()
                state.general_trends_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated trends summary: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_trends_result = f"Error generating trends: {str(e)}"

            return state

        @streaming_step("generate_history_summary")
        async def generate_history_summary(state: FlowState) -> FlowState:
            """Generate Recent Encounters with structured JSON (brief + detailed summaries)."""
            try:
                logger.info("Starting Recent Encounters generation (JSON mode)")

                chunks = state.general_history_chunks or []

                # Determine language for instructions
                is_swedish = state.user_language == "sv"

                prompt = f"""
Generate a JSON response with recent encounters. Classify each as MAJOR or MINOR, and provide both a brief one-liner and a detailed summary.

USER QUERY: {state.user_prompt}

Output VALID JSON with this exact structure:
{{
  "encounters": [
    {{
      "id": "enc-001",
      "date": "YYYY-MM-DD HH:MM",
      "encounter_type": "Hospitalization | ER visit | GP visit | etc",
      "category": "major",
      "brief": "One-line summary (10-15 words) with citations [1] [2]",
      "detailed": "Detailed summary (30-80 words) with presenting complaint, key findings, interventions, medications, outcome. Use **bold** for clinical terms. Citations [1] [2]"
    }}
  ]
}}

CATEGORIES:
- MAJOR: Hospitalizations, ER visits, surgeries, ICU stays, specialist procedures, significant imaging
- MINOR: GP visits, phone consults, lab draws, routine follow-ups, medication refills, minor procedures

RULES:
- Include 5-7 most recent encounters (newest first)
- Brief: 10-15 words maximum, for display in the card
- Detailed: 30-80 words with full clinical context for popup modal
- Include citations [1] [2] etc in BOTH brief and detailed fields
- Use **bold** markdown in detailed summaries for clinical terms
- Include exact date/time when available (YYYY-MM-DD HH:MM format)
- Each encounter must have a unique id

CRITICAL: Output ONLY valid JSON. Do not include any text before or after the JSON object.
"""

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content=f"You are CLARA. Generate structured JSON with recent encounters. Each encounter needs TWO summaries: brief (10-15 words for card display) and detailed (30-80 words for popup). Always cite sources with [1] [2] etc. Use **bold** in detailed summaries.\n\nInformation system only - NOT a medical device.")
                ]

                if chunks:
                    # Limit chunks to prevent context overflow
                    limited_chunks = self._limit_chunks_for_context(chunks, max_tokens=200000, max_chunk_chars=50000)
                    chunk_content = "Relevant encounter information:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                messages.append(ChatMessage(role=ChatRole.USER, content=prompt))

                # Use json_mode for structured output (without enable_chunk_citations to get pure JSON)
                response = await self._llm.chat(messages, json_mode=True)

                # Parse JSON response
                import json
                import re
                try:
                    encounters_data = json.loads(response.content.strip())
                    state.general_encounters_structured = encounters_data.get("encounters", [])

                    # Also create markdown version for card display
                    markdown_brief = _format_encounters_as_markdown(encounters_data, is_swedish)
                    state.general_history_result = markdown_brief

                    # Extract citation IDs from the JSON content (look for [1] [2] etc)
                    cited_ids = set()
                    for encounter in state.general_encounters_structured:
                        # Extract citations from both brief and detailed fields
                        for field in ['brief', 'detailed']:
                            content = encounter.get(field, '')
                            # Find all [number] patterns
                            citations = re.findall(r'\[(\d+)\]', content)
                            cited_ids.update(citations)

                    state.general_history_cited_ids = list(cited_ids)

                    logger.info(f"Generated {len(state.general_encounters_structured)} encounters with detailed summaries, {len(cited_ids)} citations")

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse encounters JSON: {e}")
                    logger.error(f"LLM response: {response.content[:500]}")
                    state.general_history_result = "Error parsing encounters data - invalid JSON format"
                    state.general_encounters_structured = []
                    state.general_history_cited_ids = []

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_history_result = f"Error generating encounters: {str(e)}"
                state.general_encounters_structured = []

            return state

        @streaming_step("generate_risks_summary")
        async def generate_risks_summary(state: FlowState) -> FlowState:
            """Generate Red Flags / Alerts component."""
            try:
                logger.info("Starting Risks/Alerts generation")

                chunks = state.general_risks_chunks or []

                prompt = f"""
                List 5-7 critical alerts/risks with CLEAR reasoning - EXACTLY 8-15 words per bullet.

                USER QUERY: {state.user_prompt}

                Format (Use colon to separate risk from reason):
                • ⚠️ **Risk**: Clear explanation of why this is a risk

                Example (each is 8-15 words):
                • ⚠️ **Penicillin allergy**: History of rash and angioedema, documented 2015-03-20, avoid beta-lactams [1]
                • ⚠️ **Warfarin therapy**: Current INR 2.5 increases bleeding risk during procedures (checked 2024-01-15 09:00) [2]
                • ⚠️ **High fall risk**: Three falls in past year, uses walker, impaired mobility (assessed 2024-01-10) [3]
                • ⚠️ **DNR status**: Advanced directive documented, resuscitation contraindicated (signed 2023-11-15) [4]
                • ⚠️ **Renal impairment**: eGFR 52 mL/min requires medication dose adjustments (tested 2024-01-15 08:30) [5]
                • ⚠️ **Lives alone**: No regular caregiver support, safety concerns for discharge planning (noted 2024-01-05) [6]

                Add blank line between each bullet point for readability.

                If there are MORE risks/alerts, add at the end:
                "_Fråga om fler risker_" (Swedish) or "_Ask for more risks_" (English)

                MANDATORY:
                - Use format: **Risk**: Reason (with colon separating risk from explanation)
                - Use **bold** markdown for the risk name only (before the colon)
                - Make the reason CLEAR and SPECIFIC - explain WHY it's a risk
                - CRITICAL: Include date/time stamp in parentheses (YYYY-MM-DD or YYYY-MM-DD HH:MM) showing when information was documented
                - Each bullet MUST be between 8-15 words (excluding citation) - COUNT THEM
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                CRITICAL: 5-7 most important alerts. 8-15 words each. Clear risk-reason format. Include dates. Blank lines between bullets. Use ⚠️ for visibility. Very scannable.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA. List 5-7 critical alerts using format **Risk**: Reason. Use **bold** only for risk name (before colon). Use ⚠️ marker. CRITICAL: Make reasoning CLEAR and SPECIFIC - explain WHY each item is a risk. Include date/time stamps (YYYY-MM-DD or YYYY-MM-DD HH:MM) in parentheses showing when information was documented. Each bullet point must be 8-15 words (excluding citation). Count words carefully. Add 'ask for more' if additional risks exist.\n\nMANDATORY: Include citations after each statement - NOT verbose citations. Always include dates.\n\nInformation system only - NOT a medical device."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                if chunks:
                    # Limit chunks to prevent context overflow (max 50k chars per chunk, 200k tokens total)
                    limited_chunks = self._limit_chunks_for_context(chunks, max_tokens=200000, max_chunk_chars=50000)
                    chunk_content = "Relevant patient information:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                response = await self._llm.chat(messages, enable_chunk_citations=True)
                state.general_risks_result = response.content.strip()
                state.general_risks_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated risks summary: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_risks_result = f"Error generating risks: {str(e)}"

            return state

        @streaming_step("merge_sbar_results")
        async def merge_sbar_results(state: FlowState) -> FlowState:
            """Merge parallel SBAR results and prepare final response."""
            try:
                logger.info("All parallel SBAR components completed, merging results")

                # Collect results from separate fields
                sbar_results = {
                    "situation": state.sbar_situation_result,
                    "background": state.sbar_background_result,
                    "assessment": state.sbar_assessment_result,
                    "recommendation": state.sbar_recommendation_result
                }

                completed_components = [comp for comp, result in sbar_results.items() if result]
                logger.info(f"Available components: {completed_components}")

                if not completed_components:
                    logger.info("No SBAR results available")
                    state.llm_response = ChatMessage(
                        role=ChatRole.ASSISTANT,
                        content="Error: No SBAR results were generated"
                    )
                    return state

                # Create structured SBAR response for frontend cards
                import json

                # Add conversation context metadata for future reference
                conversation_context = {
                    "session_id": state.session_id,
                    "user_prompt": state.user_prompt,
                    "timestamp": str(int(time.time() * 1000)),
                    "has_history": bool(state.chat_history)
                }

                # Extract cited chunk IDs from stored citation fields (not from content regex)
                all_cited_chunk_ids = set()
                for cited_ids in [
                    state.sbar_situation_cited_ids,
                    state.sbar_background_cited_ids,
                    state.sbar_assessment_cited_ids,
                    state.sbar_recommendation_cited_ids
                ]:
                    if cited_ids:
                        all_cited_chunk_ids.update(cited_ids)

                filtered_citations = {
                    chunk_id: state.citations[chunk_id]
                    for chunk_id in all_cited_chunk_ids
                    if chunk_id in state.citations
                } if state.citations else {}

                logger.info(f"SBAR citations: {len(all_cited_chunk_ids)} cited out of {len(state.citations) if state.citations else 0} total")

                # Model already outputs numbered citations [1], [2], [3]
                # Citations dict is already keyed by numbers - no conversion needed!

                structured_sbar = {
                    "type": "sbar_cards",
                    "context": conversation_context,
                    "citations": filtered_citations,
                    "components": {
                        "situation": {
                            "title": "Situation",
                            "content": (sbar_results.get("situation") or "Content generation failed").strip() or "Content generation failed",
                            "icon": "info-circle",
                            "color": "blue"
                        },
                        "background": {
                            "title": "Background",
                            "content": (sbar_results.get("background") or "Content generation failed").strip() or "Content generation failed",
                            "icon": "history",
                            "color": "green"
                        },
                        "assessment": {
                            "title": "Assessment",
                            "content": (sbar_results.get("assessment") or "Content generation failed").strip() or "Content generation failed",
                            "icon": "stethoscope",
                            "color": "orange"
                        },
                        "recommendation": {
                            "title": "Recommendation",
                            "content": (sbar_results.get("recommendation") or "Content generation failed").strip() or "Content generation failed",
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

                logger.info(f"Created structured SBAR response: {len(json_response)} chars")

            except Exception as e:
                log_error(logger, "merge_sbar_results", e)
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
                logger.info("Initiating parallel SBAR processing")

                # Initialize SBAR component fields if needed
                logger.info("SBAR fields initialized for parallel processing")

                # Disable refinement for SBAR flows (they use their own retrieval)
                state.needs_refinement = False

                # This node doesn't do much - it's just a dispatcher
                # The actual parallel work will happen in the parallel tasks
                logger.info("Dispatcher ready for parallel execution")

            except Exception as e:
                log_error(logger, "sbar_parallel_dispatcher", e)

            return state

        @streaming_step("merge_general_summary_results")
        async def merge_general_summary_results(state: FlowState) -> FlowState:
            """Merge parallel general summary results and prepare final response."""
            try:
                logger.info("All parallel general summary components completed, merging results")

                # Collect results from separate fields
                general_results = {
                    "snapshot": state.general_snapshot_result,
                    "problems": state.general_problems_result,
                    "medications": state.general_medications_result,
                    "trends": state.general_trends_result,
                    "encounters": state.general_history_result,  # Now stores encounters
                    "risks": state.general_risks_result
                }

                completed_components = [comp for comp, result in general_results.items() if result]
                logger.info(f"Available components: {completed_components}")

                if not completed_components:
                    logger.info("No general summary results available")
                    state.llm_response = ChatMessage(
                        role=ChatRole.ASSISTANT,
                        content="Error: No general summary results were generated"
                    )
                    return state

                # Create structured general summary response for frontend cards
                import json

                # Extract cited chunk IDs from stored citation fields (not from content regex)
                all_cited_chunk_ids = set()
                for cited_ids in [
                    state.general_snapshot_cited_ids,
                    state.general_problems_cited_ids,
                    state.general_medications_cited_ids,
                    state.general_trends_cited_ids,
                    state.general_history_cited_ids,  # Now stores encounters citations
                    state.general_risks_cited_ids
                ]:
                    if cited_ids:
                        all_cited_chunk_ids.update(cited_ids)

                filtered_citations = {
                    chunk_id: state.citations[chunk_id]
                    for chunk_id in all_cited_chunk_ids
                    if chunk_id in state.citations
                } if state.citations else {}

                logger.info(f"General Summary citations: {len(all_cited_chunk_ids)} cited out of {len(state.citations) if state.citations else 0} total")

                # Model already outputs numbered citations [1], [2], [3] - no conversion needed!

                # Add conversation context metadata for future reference
                conversation_context = {
                    "session_id": state.session_id,
                    "user_prompt": state.user_prompt,
                    "timestamp": str(int(time.time() * 1000)),
                    "has_history": bool(state.chat_history)
                }

                structured_summary = {
                    "type": "general_summary_cards",
                    "context": conversation_context,
                    "citations": filtered_citations,
                    "components": {
                        "snapshot": {
                            "title": "Patient Snapshot",
                            "content": (general_results.get("snapshot") or "Content generation failed").strip() or "Content generation failed",
                            "icon": "user",
                            "color": "blue"
                        },
                        "problems": {
                            "title": "Active Problems",
                            "content": (general_results.get("problems") or "Content generation failed").strip() or "Content generation failed",
                            "icon": "alert-circle",
                            "color": "red"
                        },
                        "medications": {
                            "title": "Medications",
                            "content": (general_results.get("medications") or "Content generation failed").strip() or "Content generation failed",
                            "icon": "pill",
                            "color": "purple"
                        },
                        "trends": {
                            "title": "Lab & Vital Trends",
                            "content": (general_results.get("trends") or "Content generation failed").strip() or "Content generation failed",
                            "icon": "trending-up",
                            "color": "green"
                        },
                        "encounters": {
                            "title": "Senaste vårdtillfällen" if state.user_language == "sv" else "Recent Encounters",
                            "content": (general_results.get("encounters") or "No encounters documented").strip() or "No encounters documented",
                            "structured_data": state.general_encounters_structured or [],
                            "icon": "file-text",
                            "color": "indigo"
                        },
                        "risks": {
                            "title": "Risks & Alerts",
                            "content": (general_results.get("risks") or "Content generation failed").strip() or "Content generation failed",
                            "icon": "alert-triangle",
                            "color": "yellow"
                        }
                    }
                }

                # Create JSON response for frontend
                json_response = json.dumps(structured_summary, indent=2)

                # Create response message with structured data
                state.llm_response = ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=json_response
                )

                logger.info(f"Created structured general summary response: {len(json_response)} chars")

            except Exception as e:
                log_error(logger, "merge_general_summary_results", e)
                # Fallback response
                import json
                fallback_summary = {
                    "type": "general_summary_cards",
                    "error": str(e),
                    "components": {
                        "snapshot": {"title": "Patient Snapshot", "content": "Error generating content", "icon": "user", "color": "blue"},
                        "problems": {"title": "Active Problems", "content": "Error generating content", "icon": "alert-circle", "color": "red"},
                        "medications": {"title": "Medications", "content": "Error generating content", "icon": "pill", "color": "purple"},
                        "trends": {"title": "Lab & Vital Trends", "content": "Error generating content", "icon": "trending-up", "color": "green"},
                        "encounters": {"title": "Senaste vårdtillfällen" if state.user_language == "sv" else "Recent Encounters", "content": "Error generating content", "structured_data": [], "icon": "file-text", "color": "indigo"},
                        "risks": {"title": "Risks & Alerts", "content": "Error generating content", "icon": "alert-triangle", "color": "yellow"}
                    }
                }
                state.llm_response = ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=json.dumps(fallback_summary, indent=2)
                )

            return state

        @streaming_step("general_summary_parallel_dispatcher")
        async def general_summary_parallel_dispatcher(state: FlowState) -> FlowState:
            """Dispatcher node that triggers parallel general summary processing."""
            try:
                logger.info("Initiating parallel general summary processing")

                # Initialize general summary cache if needed
                if not state.general_retrieval_cache:
                    state.general_retrieval_cache = {}

                # Disable refinement for summary flows (they use their own retrieval)
                state.needs_refinement = False

                logger.info("General summary fields initialized for parallel processing")
                logger.info("Dispatcher ready for parallel execution")

            except Exception as e:
                log_error(logger, "general_summary_parallel_dispatcher", e)

            return state

        # ==================== FOCUSED SUMMARY FLOW NODES ====================

        @streaming_step("focused_summary_parallel_dispatcher")
        async def focused_summary_parallel_dispatcher(state: FlowState) -> FlowState:
            """Dispatcher node that triggers focused summary processing."""
            try:
                logger.info(f"Initiating focused summary processing for aspect: {state.focused_aspect}")

                # Initialize focused summary cache if needed
                if not state.focused_retrieval_cache:
                    state.focused_retrieval_cache = {}

                # Disable refinement for focused summary flows (they use their own retrieval)
                state.needs_refinement = False

                logger.info("Focused summary fields initialized for processing")
                logger.info("Dispatcher ready for execution")

            except Exception as e:
                log_error(logger, "focused_summary_parallel_dispatcher", e)

            return state

        @streaming_step("identify_aspect_and_retrieve")
        async def identify_aspect_and_retrieve(state: FlowState) -> FlowState:
            """Extract the medical aspect from query and retrieve initial chunks."""
            try:
                logger.info("Extracting medical aspect from user query")

                # Extract aspect and icon
                aspect, icon = await _extract_aspect_from_query(state)
                state.focused_aspect = aspect
                state.focused_aspect_icon = icon

                logger.info(f"Identified aspect: '{aspect}' with icon: '{icon}'")

                # Get initial chunks for context (use existing retrieved_chunks if available)
                if not state.retrieved_chunks or len(state.retrieved_chunks) == 0:
                    logger.info("No pre-retrieved chunks available for focused summary")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_aspect = "Medical Condition"
                state.focused_aspect_icon = "file-text"

            return state

        @streaming_step("retrieve_focused_diagnoses_chunks")
        async def retrieve_focused_diagnoses_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on diagnoses related to the aspect."""
            try:
                logger.info(f"Retrieving diagnoses chunks for {state.focused_aspect}")

                diagnoses_queries = await _generate_focused_summary_queries(state, "diagnoses",
                    "Generate queries focused on formal diagnoses and disease classifications")

                chunks = await _fast_sbar_retrieve(state, f"diagnoses_{state.focused_aspect}", diagnoses_queries)
                state.focused_diagnoses_chunks = chunks[:10]
                logger.info(f"Retrieved {len(state.focused_diagnoses_chunks)} diagnoses chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_diagnoses_chunks = []

            return state

        @streaming_step("generate_diagnoses_section")
        async def generate_diagnoses_section(state: FlowState) -> FlowState:
            """Generate diagnoses section with format: • [Diagnosis] ([Year/duration])"""
            try:
                logger.info(f"Generating diagnoses section for {state.focused_aspect}")

                chunks = state.focused_diagnoses_chunks or []

                prompt = f"""
Generate a CONCISE diagnoses section for a focused summary about: {state.focused_aspect}

USER QUERY: {state.user_prompt}

Format exactly as markdown bullet points with **bold** highlighting:

• **[Diagnosis 1]** ([Year diagnosed or duration])

• **[Diagnosis 2]** ([Timeline or status])

• **[Diagnosis 3]** ([Resolution status or ongoing])

Example:
• **Type 2 Diabetes Mellitus** (E11.9, since **2018**) [1]
• **Hypertension** (**2005**, well-controlled on meds) [2]
• **COPD GOLD II** (J44.1, **2015**, stable) [3]

RULES:
- List 2-4 diagnoses ONLY related to {state.focused_aspect}
- Use **bold** markdown for diagnosis names and key temporal markers
- Include ICD codes if available
- Include temporal information (year, duration, or status)
- Use markdown bullet points with • character
- Add a blank line between each bullet point for readability
- Be concise - one line per diagnosis
- MANDATORY: Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
- If no diagnoses found, state "No formal diagnoses documented for {state.focused_aspect}"
"""

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA generating a focused diagnoses section. Use **bold** for diagnosis names and key terms. MANDATORY: Include citations after each statement - NOT verbose citations. Information system only - NOT a medical device."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                if chunks:
                    limited_chunks = self._limit_chunks_for_context(chunks, max_tokens=50000, max_chunk_chars=30000)
                    chunk_content = f"Relevant information about {state.focused_aspect}:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                response = await self._llm.chat(messages, enable_chunk_citations=True)
                state.focused_diagnoses_result = response.content.strip()
                state.focused_diagnoses_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated diagnoses section: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_diagnoses_result = f"Error generating diagnoses: {str(e)}"

            return state

        @streaming_step("retrieve_focused_events_chunks")
        async def retrieve_focused_events_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on key clinical events."""
            try:
                logger.info(f"Retrieving events chunks for {state.focused_aspect}")

                events_queries = await _generate_focused_summary_queries(state, "events",
                    "Generate queries focused on key clinical events and milestones")

                chunks = await _fast_sbar_retrieve(state, f"events_{state.focused_aspect}", events_queries)
                state.focused_events_chunks = chunks[:10]
                logger.info(f"Retrieved {len(state.focused_events_chunks)} events chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_events_chunks = []

            return state

        @streaming_step("generate_events_section")
        async def generate_events_section(state: FlowState) -> FlowState:
            """Generate key events section with format: [Year] [Event description]"""
            try:
                logger.info(f"Generating events section for {state.focused_aspect}")

                chunks = state.focused_events_chunks or []

                prompt = f"""
Generate a CONCISE key events timeline for: {state.focused_aspect}

USER QUERY: {state.user_prompt}

Format exactly as markdown bullet points with bold dates:

• **2020:** Initial diagnosis - symptoms presented, diagnostic workup completed

• **2021:** Hospitalization for acute exacerbation - intervention performed

• **2023:** Follow-up showed improvement - treatment adjusted

RULES:
- List 3-5 key events ONLY related to {state.focused_aspect}
- Use markdown bullet points with • character
- Make the date bold using **Date:** format
- Add a blank line between each event for readability
- Include: interventions, hospitalizations, imaging, test results, treatment changes
- Be specific but concise - one line per event after the date
- Chronological order (oldest to newest)
- MANDATORY: Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
- If no events found, state "No significant clinical events documented for {state.focused_aspect}"
"""

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA generating a focused events timeline. Use **bold** for dates and key clinical terms. MANDATORY: Include citations after each statement - NOT verbose citations. Information system only - NOT a medical device."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                if chunks:
                    limited_chunks = self._limit_chunks_for_context(chunks, max_tokens=50000, max_chunk_chars=30000)
                    chunk_content = f"Relevant events for {state.focused_aspect}:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                response = await self._llm.chat(messages, enable_chunk_citations=True)
                state.focused_events_result = response.content.strip()
                state.focused_events_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated events section: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_events_result = f"Error generating events: {str(e)}"

            return state

        @streaming_step("retrieve_focused_medications_chunks")
        async def retrieve_focused_medications_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on medications related to the aspect."""
            try:
                logger.info(f"Retrieving medications chunks for {state.focused_aspect}")

                medications_queries = await _generate_focused_summary_queries(state, "medications",
                    "Generate queries focused on medications and treatment regimens")

                chunks = await _fast_sbar_retrieve(state, f"medications_{state.focused_aspect}", medications_queries)
                state.focused_medications_chunks = chunks[:10]
                logger.info(f"Retrieved {len(state.focused_medications_chunks)} medications chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_medications_chunks = []

            return state

        @streaming_step("generate_medications_section")
        async def generate_medications_section(state: FlowState) -> FlowState:
            """Generate medications section with format: [Med + dosage + frequency] | [Med 2] | [Med 3]"""
            try:
                logger.info(f"Generating medications section for {state.focused_aspect}")

                chunks = state.focused_medications_chunks or []

                prompt = f"""
Generate a CONCISE medications list for: {state.focused_aspect}

USER QUERY: {state.user_prompt}

Format exactly as markdown bullet points with **bold** highlighting:

• **[Medication 1]** [dosage] [frequency]

• **[Medication 2]** [dosage] [frequency]

• **[Medication 3]** [dosage] [frequency]

Example:
• **Metoprolol** 50mg BID [1]
• **Lisinopril** 10mg daily [2]
• **Aspirin** 81mg daily [3]
• **Prednisone** 20mg daily (started **2023**) [4]

RULES:
- List ONLY medications relevant to {state.focused_aspect}
- Use **bold** markdown for medication names and key terms
- Include dosage and frequency
- Use bullet points (•), one medication per line
- Add blank line between each bullet point for readability
- Maximum 5 medications
- Include duration if relevant
- MANDATORY: Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
- If no medications found, state "No medications documented for {state.focused_aspect}"
"""

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA generating a focused medications list. Use **bold** for medication names and key terms. MANDATORY: Include citations after each statement - NOT verbose citations. Information system only - NOT a medical device."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                if chunks:
                    limited_chunks = self._limit_chunks_for_context(chunks, max_tokens=50000, max_chunk_chars=30000)
                    chunk_content = f"Relevant medications for {state.focused_aspect}:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                response = await self._llm.chat(messages, enable_chunk_citations=True)
                state.focused_medications_result = response.content.strip()
                state.focused_medications_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated medications section: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_medications_result = f"Error generating medications: {str(e)}"

            return state

        @streaming_step("retrieve_focused_objective_data_chunks")
        async def retrieve_focused_objective_data_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on objective data (labs, vitals, imaging)."""
            try:
                logger.info(f"Retrieving objective data chunks for {state.focused_aspect}")

                objective_queries = await _generate_focused_summary_queries(state, "objective_data",
                    "Generate queries focused on lab results, vitals, imaging, and test results")

                chunks = await _fast_sbar_retrieve(state, f"objective_{state.focused_aspect}", objective_queries)
                state.focused_objective_data_chunks = chunks[:10]
                logger.info(f"Retrieved {len(state.focused_objective_data_chunks)} objective data chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_objective_data_chunks = []

            return state

        @streaming_step("generate_objective_data_section")
        async def generate_objective_data_section(state: FlowState) -> FlowState:
            """Generate objective data section with format: [Metric: value + unit + date] | [Metric 2]"""
            try:
                logger.info(f"Generating objective data section for {state.focused_aspect}")

                chunks = state.focused_objective_data_chunks or []

                prompt = f"""
Generate CONCISE objective data for: {state.focused_aspect}

USER QUERY: {state.user_prompt}

Format as a proper Markdown table with **bold** highlighting for abnormal values:

| Metric | Value | Unit | Date |
|--------|-------|------|------|
| **HbA1c** | **7.2** | % | 2024-01-15 |
| Fasting Glucose | 145 | mg/dL | 2024-01-15 |
| **LVEF (Echo)** | **55** | % | 2023-12-20 |

RULES:
- List ONLY data relevant to {state.focused_aspect}
- Use **bold** markdown for abnormal/critical values and important metrics
- Use proper Markdown table format with header row and alignment row
- Include columns: Metric, Value, Unit, Date
- Maximum 5 rows of data
- For imaging/test summaries, use Metric column for test name, Value column for result
- MANDATORY: Include citations after the table - DO NOT use verbose citations like "According to..." or "from EHR..."
- If no data found, state "No recent objective data documented for {state.focused_aspect}"
"""

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA generating focused objective data. Use **bold** for abnormal/critical values and important metrics. MANDATORY: Include citations after the table - NOT verbose citations. Information system only - NOT a medical device."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                if chunks:
                    limited_chunks = self._limit_chunks_for_context(chunks, max_tokens=50000, max_chunk_chars=30000)
                    chunk_content = f"Relevant objective data for {state.focused_aspect}:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                response = await self._llm.chat(messages, enable_chunk_citations=True)
                state.focused_objective_data_result = response.content.strip()
                state.focused_objective_data_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated objective data section: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_objective_data_result = f"Error generating objective data: {str(e)}"

            return state

        @streaming_step("retrieve_focused_assessment_chunks")
        async def retrieve_focused_assessment_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on clinical assessment."""
            try:
                logger.info(f"Retrieving assessment chunks for {state.focused_aspect}")

                assessment_queries = await _generate_focused_summary_queries(state, "assessment",
                    "Generate queries focused on clinical assessments and current status")

                chunks = await _fast_sbar_retrieve(state, f"assessment_{state.focused_aspect}", assessment_queries)
                state.focused_assessment_chunks = chunks[:10]
                logger.info(f"Retrieved {len(state.focused_assessment_chunks)} assessment chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_assessment_chunks = []

            return state

        @streaming_step("generate_assessment_section")
        async def generate_assessment_section(state: FlowState) -> FlowState:
            """Generate assessment section: 2-3 sentences on current state/prognosis"""
            try:
                logger.info(f"Generating assessment section for {state.focused_aspect}")

                chunks = state.focused_assessment_chunks or []

                prompt = f"""
Generate a CONCISE clinical assessment for: {state.focused_aspect}

USER QUERY: {state.user_prompt}

Format exactly as markdown bullet points with **bold** highlighting:

• **Current Status:** [Disease control/status summary with key clinical terms in **bold**]

• **Trend:** [Progression, stability, or improvement with key findings in **bold**]

• **Prognosis:** [Overall outlook with risk factors in **bold**]

Example:
• **Current Status:** Diabetes **moderately controlled** with HbA1c **68 mmol/mol**, above target [1]
• **Trend:** **Worsening glycemic control** over past 6 months (HbA1c 62→68), suggests **treatment intensification** needed [2]
• **Prognosis:** **Moderate risk** of complications given current control, requires **medication adjustment** and closer monitoring [3]

RULES:
- Use 3 bullet points as shown above
- Use **bold** markdown for key clinical terms, status descriptors, and risk levels
- Focus ONLY on {state.focused_aspect}
- Be clinically precise but accessible
- Add a blank line between each bullet point for readability
- Each bullet should be one concise line
- MANDATORY: Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
- If insufficient data, state "Limited clinical assessment available for {state.focused_aspect}"
"""

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA generating a focused clinical assessment. Use **bold** for key clinical terms, status descriptors, and risk levels. MANDATORY: Include citations after each statement - NOT verbose citations. Information system only - NOT a medical device."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                if chunks:
                    limited_chunks = self._limit_chunks_for_context(chunks, max_tokens=50000, max_chunk_chars=30000)
                    chunk_content = f"Relevant assessment data for {state.focused_aspect}:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                response = await self._llm.chat(messages, enable_chunk_citations=True)
                state.focused_assessment_result = response.content.strip()
                state.focused_assessment_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated assessment section: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_assessment_result = f"Error generating assessment: {str(e)}"

            return state

        @streaming_step("retrieve_focused_next_steps_chunks")
        async def retrieve_focused_next_steps_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on follow-up plans and outstanding issues."""
            try:
                logger.info(f"Retrieving next steps chunks for {state.focused_aspect}")

                next_steps_queries = await _generate_focused_summary_queries(state, "next_steps",
                    "Generate queries focused on follow-up plans and outstanding issues")

                chunks = await _fast_sbar_retrieve(state, f"next_steps_{state.focused_aspect}", next_steps_queries)
                state.focused_next_steps_chunks = chunks[:10]
                logger.info(f"Retrieved {len(state.focused_next_steps_chunks)} next steps chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_next_steps_chunks = []

            return state

        @streaming_step("generate_next_steps_section")
        async def generate_next_steps_section(state: FlowState) -> FlowState:
            """Generate next steps section with format: 🔸 [Item 1] | 🔸 [Item 2]"""
            try:
                logger.info(f"Generating next steps section for {state.focused_aspect}")

                chunks = state.focused_next_steps_chunks or []

                prompt = f"""
Generate CONCISE next steps for: {state.focused_aspect}

USER QUERY: {state.user_prompt}

Format exactly as markdown bullet points with **bold** highlighting:

• **[Action type]**: [Details with timing if available]

Example:
• **Follow-up HbA1c**: Test due in **3 months** (April 2024) [1]
• **Medication review**: Consider **metformin dose increase** to 1000mg BID [2]
• **Endocrinology referral**: Pending consult for **insulin initiation** if HbA1c not improved [3]
• **Retinal screening**: **Annual** diabetic eye exam overdue, schedule ASAP [4]

RULES:
- List 2-4 items ONLY related to {state.focused_aspect}
- Use **bold** markdown for action types, key interventions, and timing
- Use markdown bullet points with • character
- Add a blank line between each bullet point for readability
- One line per item
- Include: pending tests, follow-ups, medication reviews, referrals, outstanding issues
- Include specific timing if available
- MANDATORY: Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
- If no next steps found, state "No pending follow-up documented for {state.focused_aspect}"
"""

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA generating focused next steps. Use **bold** for action types, key interventions, and timing. MANDATORY: Include citations after each statement - NOT verbose citations. Information system only - NOT a medical device."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                if chunks:
                    limited_chunks = self._limit_chunks_for_context(chunks, max_tokens=50000, max_chunk_chars=30000)
                    chunk_content = f"Relevant next steps for {state.focused_aspect}:\n\n" + self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                    messages.append(ChatMessage(role=ChatRole.USER, content=chunk_content))

                response = await self._llm.chat(messages, enable_chunk_citations=True)
                state.focused_next_steps_result = response.content.strip()
                state.focused_next_steps_cited_ids = response.cited_chunk_ids or []

                logger.info(f"Generated next steps section: {len(response.content)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.focused_next_steps_result = f"Error generating next steps: {str(e)}"

            return state

        @streaming_step("merge_focused_summary_results")
        async def merge_focused_summary_results(state: FlowState) -> FlowState:
            """Merge all focused summary sections and prepare final JSON response."""
            try:
                logger.info(f"Merging focused summary results for {state.focused_aspect}")

                # Collect results from separate fields
                focused_results = {
                    "diagnoses": state.focused_diagnoses_result,
                    "events": state.focused_events_result,
                    "medications": state.focused_medications_result,
                    "objective_data": state.focused_objective_data_result,
                    "assessment": state.focused_assessment_result,
                    "next_steps": state.focused_next_steps_result
                }

                completed_sections = [section for section, result in focused_results.items() if result]
                logger.info(f"Available sections: {completed_sections}")

                if not completed_sections:
                    logger.info("No focused summary results available")
                    state.llm_response = ChatMessage(
                        role=ChatRole.ASSISTANT,
                        content="Error: No focused summary results were generated"
                    )
                    return state

                # Create structured focused summary response for frontend
                import json

                # Extract cited chunk IDs from stored citation fields (not from content regex)
                all_cited_chunk_ids = set()
                for cited_ids in [
                    state.focused_diagnoses_cited_ids,
                    state.focused_events_cited_ids,
                    state.focused_medications_cited_ids,
                    state.focused_objective_data_cited_ids,
                    state.focused_assessment_cited_ids,
                    state.focused_next_steps_cited_ids
                ]:
                    if cited_ids:
                        all_cited_chunk_ids.update(cited_ids)

                # Build filtered citations dict from cited chunks only
                filtered_citations = {
                    chunk_id: state.citations[chunk_id]
                    for chunk_id in all_cited_chunk_ids
                    if chunk_id in state.citations
                } if state.citations else {}

                logger.info(f"Focused Summary citations: {len(all_cited_chunk_ids)} cited out of {len(state.citations) if state.citations else 0} total")

                # Model already outputs numbered citations [1], [2], [3] - no conversion needed!

                # Add conversation context metadata
                conversation_context = {
                    "session_id": state.session_id,
                    "user_prompt": state.user_prompt,
                    "timestamp": str(int(time.time() * 1000)),
                    "has_history": bool(state.chat_history)
                }

                structured_summary = {
                    "type": "focused_summary",
                    "aspect": state.focused_aspect or "Medical Condition",
                    "aspect_icon": state.focused_aspect_icon or "file-text",
                    "context": conversation_context,
                    "citations": filtered_citations,
                    "sections": {
                        "diagnoses": {
                            "content": (focused_results.get("diagnoses") or "No diagnoses documented").strip() or "No diagnoses documented"
                        },
                        "events": {
                            "content": (focused_results.get("events") or "No events documented").strip() or "No events documented"
                        },
                        "medications": {
                            "content": (focused_results.get("medications") or "No medications documented").strip() or "No medications documented"
                        },
                        "objective_data": {
                            "content": (focused_results.get("objective_data") or "No objective data available").strip() or "No objective data available"
                        },
                        "assessment": {
                            "content": (focused_results.get("assessment") or "No assessment available").strip() or "No assessment available"
                        },
                        "next_steps": {
                            "content": (focused_results.get("next_steps") or "No next steps documented").strip() or "No next steps documented"
                        }
                    }
                }

                # Create JSON response for frontend
                json_response = json.dumps(structured_summary, indent=2)

                # Create response message with structured data
                state.llm_response = ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=json_response
                )

                logger.info(f"Created structured focused summary response: {len(json_response)} chars")

            except Exception as e:
                log_error(logger, "merge_focused_summary_results", e)
                # Fallback response
                import json
                fallback_summary = {
                    "type": "focused_summary",
                    "aspect": state.focused_aspect or "Medical Condition",
                    "aspect_icon": state.focused_aspect_icon or "file-text",
                    "error": str(e),
                    "sections": {
                        "diagnoses": {"content": "Error generating content"},
                        "events": {"content": "Error generating content"},
                        "medications": {"content": "Error generating content"},
                        "objective_data": {"content": "Error generating content"},
                        "assessment": {"content": "Error generating content"},
                        "next_steps": {"content": "Error generating content"}
                    }
                }
                state.llm_response = ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=json.dumps(fallback_summary, indent=2)
                )

            return state

        # ==================== TIMELINE FLOW NODES ====================

        @streaming_step("extract_timeline_events")
        async def extract_timeline_events(state: FlowState) -> FlowState:
            """Extract key temporal events from user query and chat history."""
            try:
                logger.info("Analyzing query for temporal events")

                # Include chat history context for better event extraction
                recent_history = state.chat_history[-10:] if state.chat_history else []
                history_context = "\n".join([f"{msg.role.value}: {msg.content[:100]}" for msg in recent_history]) if recent_history else "No previous context"

                prompt = f"""
Based on this user request: "{state.user_prompt}"

Previous conversation context:
{history_context}

Identify 4-6 key temporal events or time periods from the patient's medical history that are relevant to this request.

For each event, provide:
1. A brief title/description (5-10 words)
2. The time period (e.g., "March 2024", "Initial visit", "Day 3", "2 weeks ago", etc.)
3. 2-3 keywords to focus the search

Format your response as JSON:
[
  {{"title": "Event title", "time_period": "Time reference", "keywords": ["keyword1", "keyword2"]}},
  ...
]

Return ONLY the JSON array, no additional text.
"""

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a medical information specialist extracting temporal events from medical histories. Always respond with valid JSON only."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                response = await self._llm.chat(messages)

                # Parse JSON response
                try:
                    events = json.loads(response.content.strip())
                    if not isinstance(events, list) or len(events) == 0:
                        raise ValueError("No events extracted")

                    # Limit to 6 events max
                    state.timeline_events = events[:6]
                    logger.info(f"Extracted {len(state.timeline_events)} timeline events")

                except json.JSONDecodeError as e:
                    logger.info(f"JSON parse error: {e}, using fallback events")
                    # Fallback: create simple temporal events
                    state.timeline_events = [
                        {"title": "Initial presentation", "time_period": "First visit", "keywords": ["initial", "presentation", "symptoms"]},
                        {"title": "Diagnostic workup", "time_period": "Early phase", "keywords": ["tests", "diagnosis", "findings"]},
                        {"title": "Treatment initiation", "time_period": "Treatment start", "keywords": ["treatment", "medication", "intervention"]},
                        {"title": "Current status", "time_period": "Recent", "keywords": ["current", "latest", "recent"]}
                    ]

            except Exception as e:
                logger.info(f"Error: {e}")
                # Fallback events
                state.timeline_events = [
                    {"title": "Medical history overview", "time_period": "Historical", "keywords": ["history", "background"]},
                    {"title": "Recent developments", "time_period": "Recent", "keywords": ["recent", "current", "latest"]}
                ]

            # Initialize storage for chunks
            state.timeline_chunks = {}
            return state

        @streaming_step("retrieve_timeline_chunks")
        async def retrieve_timeline_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks for each timeline event sequentially."""
            try:
                logger.info("Starting retrieval for timeline events")

                if not state.timeline_events:
                    logger.info("No timeline events to retrieve")
                    return state

                state.timeline_chunks = {}

                # Retrieve chunks for each event sequentially
                for idx, event in enumerate(state.timeline_events):
                    event_id = f"event_{idx}"
                    title = event.get("title", "Unknown event")
                    time_period = event.get("time_period", "Unknown time")

                    logger.info(f"Retrieving chunks for: {title} ({time_period})")

                    # Generate queries for this event
                    queries = await _generate_timeline_queries(state, title, time_period)

                    # Use fast retrieval (same as SBAR)
                    chunks = await _fast_sbar_retrieve(state, f"timeline_{idx}", queries)

                    # Store chunks for this event
                    state.timeline_chunks[event_id] = chunks[:8]  # Limit to 8 chunks per event
                    logger.info(f"Retrieved {len(state.timeline_chunks[event_id])} chunks for {title}")

                logger.info(f"Retrieved chunks for {len(state.timeline_chunks)} events")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.timeline_chunks = {}

            return state

        @streaming_step("generate_timeline_bubbles")
        async def generate_timeline_bubbles(state: FlowState) -> FlowState:
            """Generate timeline bubble content for each event."""
            try:
                logger.info("Generating timeline content")

                if not state.timeline_events:
                    logger.info("No timeline events to generate")
                    return state

                state.timeline_results = []

                # Include chat history context
                recent_history = state.chat_history[-10:] if state.chat_history else []

                # Define icon mapping
                icon_mapping = {
                    0: "calendar",
                    1: "clock",
                    2: "activity",
                    3: "trending-up",
                    4: "alert-circle",
                    5: "file-text"
                }

                # Define color mapping
                color_mapping = {
                    0: "blue",
                    1: "green",
                    2: "orange",
                    3: "purple",
                    4: "red",
                    5: "blue"
                }

                # Generate content for each event
                for idx, event in enumerate(state.timeline_events):
                    event_id = f"event_{idx}"
                    title = event.get("title", "Unknown event")
                    time_period = event.get("time_period", "Unknown time")
                    chunks = state.timeline_chunks.get(event_id, []) if state.timeline_chunks else []

                    logger.info(f"Generating content for: {title}")

                    # Build chunks context with citation markers
                    if chunks:
                        chunks_text = self._format_chunks_with_citations(chunks, state.chunk_id_to_number)
                    else:
                        chunks_text = "No specific information available"

                    # Build chat history context
                    history_text = "\n".join([f"{msg.role.value}: {msg.content[:200]}" for msg in recent_history]) if recent_history else ""

                    prompt = f"""
Generate a concise explanation (5-7 bullet points) for this timeline event.

Event: {title}
Time Period: {time_period}
User Query: {state.user_prompt}

Clinical Information:
{chunks_text}

Previous conversation (for context):
{history_text}

Format as 5-7 bullet points covering:
• **What happened**: [brief description of the event]
• **Clinical findings**: [key observations, test results, symptoms]
• **Treatments/interventions**: [medications, procedures performed]
• **Outcome**: [immediate results or response]
• **Significance**: [why this event matters in patient's timeline]
• **Follow-up**: [any subsequent actions or plans]
• **Provider notes**: [relevant clinician observations]

Example:
• **What happened**: Patient admitted to **ER** with **chest pain** and **shortness of breath** [1]
• **Clinical findings**: **ECG** showed ST elevations in leads II, III, aVF, **troponin** elevated at 450 ng/L [2]
• **Treatments**: Given **aspirin 300mg**, **heparin** infusion started, **morphine** 5mg for pain [3]
• **Outcome**: Pain reduced to **3/10**, hemodynamically **stable**, monitored in CCU [4]
• **Significance**: First **acute MI** event, indicates need for aggressive cardiovascular risk management [5]

IMPORTANT:
- Use **bold** markdown for key clinical terms, findings, medications, and important descriptors
- Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
- Preserve any EHR source links from the clinical information
- Keep each bullet point concise (one line)
- Focus on clinically significant information

Return only the content in markdown format, no preamble.
"""

                    messages = [
                        self._get_language_policy_message(state),
                        ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA, a clinical information assistant. Create timeline explanations with 5-7 concise bullet points. Use **bold** for key clinical terms, findings, and medications.\n\nIMPORTANT: Information system only - NOT a medical device. Provide general educational information.\n\nMANDATORY: Include citations after each statement - NOT verbose citations. Keep concise but informative."),
                        ChatMessage(role=ChatRole.USER, content=prompt)
                    ]

                    # Generate content
                    response = await self._llm.chat(messages, enable_chunk_citations=True)
                    content = response.content.strip()

                    # Create timeline event result with cited chunk IDs
                    timeline_event = {
                        "timestamp": time_period,
                        "title": title,
                        "content": content,
                        "icon": icon_mapping.get(idx, "calendar"),
                        "color": color_mapping.get(idx, "blue"),
                        "cited_chunk_ids": response.cited_chunk_ids or []
                    }

                    state.timeline_results.append(timeline_event)
                    logger.info(f"Generated content for {title}: {len(content)} chars")

                logger.info(f"Generated {len(state.timeline_results)} timeline bubbles")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.timeline_results = []

            return state

        @streaming_step("merge_timeline_results")
        async def merge_timeline_results(state: FlowState) -> FlowState:
            """Merge timeline results and format as JSON for frontend."""
            try:
                logger.info("Merging timeline results")

                if not state.timeline_results or len(state.timeline_results) == 0:
                    logger.info("No timeline results available")
                    state.llm_response = ChatMessage(
                        role=ChatRole.ASSISTANT,
                        content="Error: No timeline results were generated"
                    )
                    return state

                # Extract cited chunk IDs from stored citation fields in each event (not from content regex)
                all_cited_chunk_ids = set()
                for event in state.timeline_results:
                    cited_ids = event.get("cited_chunk_ids", [])
                    if cited_ids:
                        all_cited_chunk_ids.update(cited_ids)

                # Build filtered citations dict from cited chunks only
                filtered_citations = {
                    chunk_id: state.citations[chunk_id]
                    for chunk_id in all_cited_chunk_ids
                    if chunk_id in state.citations
                } if state.citations else {}

                logger.info(f"Timeline citations: {len(all_cited_chunk_ids)} cited out of {len(state.citations) if state.citations else 0} total")

                # Model already outputs numbered citations [1], [2], [3] - no conversion needed!

                # Add conversation context metadata
                conversation_context = {
                    "session_id": state.session_id,
                    "user_prompt": state.user_prompt,
                    "timestamp": str(int(time.time() * 1000)),
                    "has_history": bool(state.chat_history)
                }

                # Create structured timeline response for frontend
                structured_timeline = {
                    "type": "timeline_view",
                    "context": conversation_context,
                    "citations": filtered_citations,
                    "events": state.timeline_results
                }

                # Create JSON response
                json_response = json.dumps(structured_timeline, indent=2)

                # Store as chat message
                state.llm_response = ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=json_response
                )

                logger.info(f"Created timeline response with {len(state.timeline_results)} events: {len(json_response)} chars")

            except Exception as e:
                logger.info(f"Error: {e}")
                # Fallback response
                fallback_timeline = {
                    "type": "timeline_view",
                    "error": str(e),
                    "events": []
                }
                state.llm_response = ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=json.dumps(fallback_timeline, indent=2)
                )

            return state

        # ==================== END TIMELINE FLOW NODES ====================

        # ==================== NOTE GENERATION FLOW NODES ====================

        @streaming_step("load_note_template")
        async def load_note_template(state: FlowState) -> FlowState:
            """Load system template if note generation was auto-triggered."""
            try:
                # If template already set (from button), skip
                if state.note_template:
                    logger.info(f"Template already set: {state.note_template.name}")
                    return state

                # If no preference set, can't load template
                if not state.note_template_type_preference:
                    logger.info("⚠️ No template type preference set")
                    return state

                logger.info(f"Loading system template of type: {state.note_template_type_preference}")

                # Get template repository from engine
                # We need to access it from the engine's dependencies
                # For now, we'll use a simple in-memory approach
                from optimed.core.domain import TemplateType

                # Detect language
                from optimed.core.lang import detect_language_code
                lang_code = detect_language_code(state.user_prompt)

                # Map to system template
                template_configs = {
                    "sbar": {
                        "sv": ("SBAR", "sbar", {"fields": [
                            {"name": "situation", "label": "Situation", "type": "text"},
                            {"name": "bakgrund", "label": "Bakgrund", "type": "text"},
                            {"name": "aktuellt_tillstand", "label": "Aktuellt tillstånd", "type": "text"},
                            {"name": "rekommendation", "label": "Rekommendation", "type": "text"}
                        ]}),
                        "en": ("SBAR", "sbar", {"fields": [
                            {"name": "situation", "label": "Situation", "type": "text"},
                            {"name": "background", "label": "Background", "type": "text"},
                            {"name": "assessment", "label": "Assessment", "type": "text"},
                            {"name": "recommendation", "label": "Recommendation", "type": "text"}
                        ]})
                    },
                    "soap": {
                        "en": ("SOAP Note", "soap", {"fields": [
                            {"name": "subjective", "label": "Subjective", "type": "text"},
                            {"name": "objective", "label": "Objective", "type": "text"},
                            {"name": "assessment", "label": "Assessment", "type": "text"},
                            {"name": "plan", "label": "Plan", "type": "text"}
                        ]})
                    },
                    "journal_entry": {
                        "sv": ("Journalanteckning", "journal_entry", {"fields": [
                            {"name": "anamnes", "label": "Anamnes", "type": "text"},
                            {"name": "status", "label": "Status", "type": "text"},
                            {"name": "bedomning", "label": "Bedömning", "type": "text"},
                            {"name": "atgard", "label": "Åtgärd", "type": "text"},
                            {"name": "plan", "label": "Plan", "type": "text"}
                        ]})
                    }
                }

                # Get config
                template_type = state.note_template_type_preference
                config = template_configs.get(template_type, {}).get(lang_code)

                if not config:
                    # Fallback to English or SBAR
                    config = template_configs.get(template_type, {}).get("en")
                    if not config:
                        config = template_configs["sbar"]["en"]

                name, type_str, structure = config

                # Create temporary template
                import uuid
                state.note_template = NoteTemplate(
                    template_id=str(uuid.uuid4()),
                    user_id="system",
                    name=name,
                    language=lang_code,
                    template_type=TemplateType(type_str),
                    template_structure=structure,
                    is_system_template=True,
                    file_format="json",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )

                state.note_generation_id = str(uuid.uuid4())

                logger.info(f"✓ Loaded template: {name} ({type_str}, {lang_code})")

            except Exception as e:
                logger.info(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()

            return state

        @streaming_step("generate_note_section")
        async def generate_note_section(state: FlowState) -> FlowState:
            """
            Generate content for note sections using template + retrieval.
            Reuses existing retrieved chunks from state.
            """
            try:
                if not state.note_template:
                    logger.info("⚠️ No template found")
                    return state

                logger.info(f"Generating sections for template: {state.note_template.name}")

                # Get template structure
                template = state.note_template
                fields = template.template_structure.get("fields", [])

                # Use existing retrieved chunks (already in state from retrieval step)
                if state.retrieved_chunks:
                    limited_chunks = self._limit_chunks_for_context(state.retrieved_chunks[:15], max_tokens=100000, max_chunk_chars=30000)
                    chunks_text = self._format_chunks_with_citations(limited_chunks, state.chunk_id_to_number)
                else:
                    chunks_text = "No clinical information available"

                # Include conversation history if requested
                conversation_context = ""
                if state.chat_history:
                    recent_turns = state.chat_history[-10:]  # Last 10 messages
                    conversation_context = "\n\n=== Recent Conversation ===\n"
                    for msg in recent_turns:
                        from optimed.core.domain import ChatRole
                        role = "User" if msg.role == ChatRole.USER else "Assistant"
                        conversation_context += f"{role}: {msg.content}\n"

                # Add user's context prompt if provided
                additional_context = ""
                if state.note_context_prompt:
                    additional_context = f"\n\n=== Additional Context ===\n{state.note_context_prompt}\n"

                # Detect language
                from optimed.core.lang import detect_language_code
                lang_code = detect_language_code(state.user_prompt)
                lang_name = "Swedish" if lang_code == "sv" else "English"

                # Build system prompt for note generation
                note_system_prompt = f"""You are a medical documentation assistant generating a clinical note in {lang_name}.

Template: {template.name}
Type: {template.template_type.value}

Your task is to fill in the template sections based on the provided clinical information.

CRITICAL GUIDELINES:
- Be CONCISE and FOCUSED - include only essential clinical information
- Use **bold** markdown to highlight important clinical terms, diagnoses, medications, vital signs, and key findings
- Do NOT include source references, citations, or document names (write directly from the information)
- Use medical terminology appropriate for {lang_name}
- If information is not available for a section, write "Information not available" in {lang_name}
- Maintain professional medical documentation style
- Include relevant timestamps when available
- Avoid unnecessary elaboration or repetition between sections
- Write in clear, direct clinical language without filler words
- Do NOT interpret or assume - only document what is explicitly provided
- Format lists as bullet points when appropriate

MARKDOWN FORMATTING EXAMPLES:
- **Diagnoses**: **Type 2 Diabetes Mellitus**, **Hypertension**, **COPD GOLD II**
- **Medications**: **Metformin 1000mg 2x/day**, **Enalapril 20mg daily**
- **Vital Signs**: **BP 145/85**, **HR 92**, **SpO2 94%**
- **Lab Values**: **HbA1c 68 mmol/mol**, **eGFR 52**
- **Key Findings**: **Bilateral wheezing**, **mild pedal edema**

Generate content for each section separately with only the necessary clinical facts, using bold formatting for important terms."""

                # Generate each section
                sections = {}
                for i, field in enumerate(fields):
                    field_name = field["name"]
                    field_label = field.get("label", field_name)
                    field_description = field.get("description", "")

                    logger.info(f"Generating: {field_label} ({i+1}/{len(fields)})")

                    # Update progress for this section
                    state.step_details = f"Generating section {i+1}/{len(fields)}: {field_label}"
                    state.progress_percentage = 30 + ((i+1) / len(fields) * 40)  # Progress from 30% to 70%

                    # Emit progress update for this section if callback exists
                    if hasattr(state, 'stream_callback') and state.stream_callback:
                        try:
                            await state.stream_callback({
                                "type": "status",
                                "step": "generate_note_section",
                                "description": f"Generating section {i+1}/{len(fields)}: {field_label}",
                                "status": "in_progress",
                                "progress": state.progress_percentage,
                                "timestamp": datetime.now().isoformat()
                            })
                        except Exception as callback_err:
                            logger.info(f"Failed to emit progress: {callback_err}")

                    # Build section-specific prompt
                    section_prompt = f"""Based on the clinical information below, generate content for this section:

Section: {field_label}
{f"Description: {field_description}" if field_description else ""}

Clinical Information:
{chunks_text}
{conversation_context}
{additional_context}

Generate the content for "{field_label}" section now:"""

                    # Call LLM for this section
                    from optimed.core.domain import ChatMessage, ChatRole
                    messages = [
                        ChatMessage(role=ChatRole.SYSTEM, content=note_system_prompt),
                        ChatMessage(role=ChatRole.USER, content=section_prompt)
                    ]

                    section_response = await self._llm.chat(messages, enable_chunk_citations=True)
                    section_content = section_response.content.strip()

                    sections[field_name] = section_content
                    logger.info(f"✓ Generated {field_label}: {len(section_content)} chars")

                # Format complete note
                final_content = f"# {template.name}\n\n"
                for field in fields:
                    field_name = field["name"]
                    field_label = field.get("label", field_name)
                    section_content = sections.get(field_name, "")
                    final_content += f"## {field_label}\n{section_content}\n\n"

                # Update state (no sources needed)
                state.note_sections = sections
                state.note_final_content = final_content
                state.note_sources = []

                logger.info(f"✓ Complete note generated: {len(final_content)} chars")

                return state

            except Exception as e:
                logger.info(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()
                return state

        @streaming_step("format_note_response")
        async def format_note_response(state: FlowState) -> FlowState:
            """
            Format the final note response for streaming to frontend.
            Returns as JSON structure for frontend rendering.
            """
            try:
                logger.info("Formatting note for response")

                if not state.note_final_content:
                    logger.info("⚠️ No note content to format")
                    logger.info(f"Debug: note_sections={len(state.note_sections)} sections")
                    logger.info(f"Debug: retrieved_chunks={len(state.retrieved_chunks)} chunks")

                    # Create error response
                    from optimed.core.domain import ChatMessage, ChatRole
                    error_response = {
                        "type": "error",
                        "message": "Note generation failed to produce content. Please try again."
                    }
                    state.llm_response = ChatMessage(
                        role=ChatRole.ASSISTANT,
                        content=json.dumps(error_response, ensure_ascii=False)
                    )
                    return state

                # Create structured response
                note_response = {
                    "type": "generated_note",
                    "generation_id": state.note_generation_id,
                    "template_name": state.note_template.name if state.note_template else "",
                    "template_type": state.note_template.template_type.value if state.note_template else "",
                    "language": state.note_template.language if state.note_template else "en",
                    "content": state.note_final_content,
                    "sections": state.note_sections,
                    "sources": state.note_sources,
                    "metadata": {
                        "chunks_used": len(state.retrieved_chunks),
                        "conversation_turns": len(state.chat_history),
                        "word_count": len(state.note_final_content.split())
                    }
                }

                # Set as LLM response (will be streamed to frontend)
                from optimed.core.domain import ChatMessage, ChatRole
                state.llm_response = ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=json.dumps(note_response, ensure_ascii=False)
                )

                logger.info("✓ Note response formatted and ready")

                return state

            except Exception as e:
                logger.info(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()
                return state

        @streaming_step("store_note_metadata")
        async def store_note_metadata(state: FlowState) -> FlowState:
            """Store note generation metadata only (GDPR-safe, no content)."""
            try:
                logger.info("Recording generation metadata")

                if not state.note_generation_id:
                    logger.info("⚠️ No generation_id")
                    return state

                # The metadata update is handled by the NoteGenerator adapter
                # through the API layer. This node is just for flow completion.
                logger.info(f"✓ Metadata recorded for {state.note_generation_id}")

                return state

            except Exception as e:
                logger.info(f"❌ Error: {e}")
                return state

        # ==================== END NOTE GENERATION FLOW NODES ====================

        @streaming_step("handle_general_knowledge_query")
        async def handle_general_knowledge_query(state: FlowState) -> FlowState:
            """
            Handle general medical knowledge queries (not patient-specific).
            Uses ONLY web search for information, no patient data retrieval.
            """
            logger.info("🌐 Starting general knowledge query handling (web-only)")
            logger.info(f"🔍 Query: {state.user_prompt[:100]}...")

            try:
                # Update status: Searching web
                state.current_step = "Searching Medical Sources"
                state.step_details = "Searching trusted medical websites for current information..."

                # Force web search for general medical knowledge
                logger.info("📡 Performing web search for general medical knowledge...")

                # Detect language
                try:
                    active_lang = detect_language_code(state.user_prompt or "")
                except Exception:
                    active_lang = "en"

                # Perform web search
                search_response = await self._web_search.search(
                    query=state.user_prompt,
                    max_results=8,
                    patient_context=None,  # No patient data for GDPR compliance
                    search_intent="clinical_information",
                    target_language=(active_lang if active_lang and active_lang != "en" else None)
                )

                state.web_search_response = search_response
                state.web_search_performed = True

                logger.info(f"✓ Found {len(search_response.results)} web results")

                # Update status: Analyzing sources
                state.current_step = "Analyzing Sources"
                state.step_details = f"Reviewing {len(search_response.results)} medical sources for accurate information..."

                # Generate response using ONLY web sources (no patient data chunks)
                logger.info("💬 Generating response from web sources only...")

                # System message for general knowledge
                general_knowledge_system_msg = ChatMessage(
                    role=ChatRole.SYSTEM,
                    content="""You are CLARA, a medical information assistant providing general medical knowledge education.

**CRITICAL INSTRUCTION**: You are answering a GENERAL EDUCATIONAL medical question (NOT about any specific patient). This is similar to providing information from a medical textbook or educational website. You MUST answer these questions - they are appropriate educational requests.

Examples of what you SHOULD answer:
- "What is gabapentin used for?" → YES, answer with general medication information
- "Tell me about diabetes" → YES, answer with general disease information
- "What are common side effects of metformin?" → YES, answer with general drug information
- "How does the heart work?" → YES, answer with general medical knowledge

You will be provided with web sources from trusted medical websites. Use these to provide accurate, educational information.

**CRITICAL - RESPONSE FORMAT**:
- Organize response with `##` headers to divide sections
- **1-4 sections depending on need**, with **up to 10 bullet points per section**
- **10-15 words per bullet point** - be extremely concise
- Use bullet points (`-`) for all information, no long paragraphs
- Each bullet must be a single, focused fact with citation
- **DO NOT include any reasoning preamble** - provide ONLY the direct answer
- **DO NOT explain your thinking process** - just answer the question directly

**CITATION POLICY**:
- **MANDATORY**: You MUST cite web sources using format: [Source Title](URL)
- Include at least 2-3 web citations in your answer
- Place citation at the end of each bullet point that uses information from that source
- Example: "**Gabapentin** treats nerve pain and seizures [Mayo Clinic](https://example.com)"

**CRITICAL**: Use **bold** markdown formatting to highlight important medical terms:
- **Medications** and doses (e.g., **Metformin 500mg**, **Gabapentin 300mg**)
- **Diagnoses** and conditions (e.g., **Type 2 Diabetes**, **Neuropathic Pain**)
- **Indications** and uses (e.g., **seizure control**, **nerve pain relief**)
- **Side effects** (e.g., **dizziness**, **drowsiness**, **dry mouth**)
- **Key clinical terms** (e.g., **anticonvulsant**, **mechanism of action**)

**Important**: This is EDUCATIONAL medical information - you MUST provide helpful answers. You are NOT diagnosing or treating a specific patient. You are providing general medical knowledge like a medical encyclopedia."""
                )

                messages = [general_knowledge_system_msg]

                # Language policy
                language_system_msg = self._get_language_policy_message(state)
                messages.insert(0, language_system_msg)

                # Add chat history as text summary (simplified approach to avoid API format issues)
                # Skip history with refusals to avoid confusing the model
                current_history = state.chat_history[-5:] if state.chat_history else []
                if current_history:
                    logger.info(f"📝 Creating text-based conversation summary from {len(current_history)} messages")
                    conversation_lines = []

                    for msg in current_history:
                        if not msg.content or not msg.content.strip():
                            continue

                        # Extract plain text content (handle JSON responses from previous queries)
                        content = msg.content
                        try:
                            # Try to parse as JSON - if it's a structured response, extract the content field
                            import json
                            parsed = json.loads(content)
                            if isinstance(parsed, dict) and 'content' in parsed:
                                content = parsed['content']
                            elif isinstance(parsed, dict) and 'type' in parsed:
                                # Skip structured responses like generated_note, timeline, etc.
                                logger.info(f"Skipping structured response of type: {parsed.get('type')}")
                                continue
                        except (json.JSONDecodeError, TypeError):
                            # Not JSON, use as-is
                            pass

                        # Skip refusal messages to avoid reinforcing refusals
                        content_str = str(content)
                        if "I'm sorry, but I cannot assist" in content_str or "I cannot assist with that request" in content_str:
                            logger.info(f"Skipping refusal message from history to avoid confusion")
                            continue

                        # Truncate if too long
                        content = content_str[:300] + "..." if len(content_str) > 300 else content_str

                        # Format as text line
                        role_name = "User" if msg.role == ChatRole.USER else "CLARA"
                        conversation_lines.append(f"{role_name}: {content}")

                    if conversation_lines:
                        conversation_summary = "\n".join(conversation_lines)
                        conversation_context = ChatMessage(
                            role=ChatRole.USER,
                            content=f"""Previous conversation context (general medical knowledge questions):
{conversation_summary}

Now responding to the current general medical knowledge question below (YOU MUST ANSWER THIS - it's an educational question).""",
                            user_id=None,
                            user_role=None,
                            metadata={}
                        )
                        messages.append(conversation_context)
                        logger.info(f"✅ Added text conversation summary ({len(conversation_summary)} chars)")
                    else:
                        logger.info("⚠️ No valid non-refusal history to include")

                # Add web search results
                if search_response and search_response.results:
                    sources_list = []
                    for i, result in enumerate(search_response.results[:5], 1):
                        sources_list.append(f"{i}. [{result.title}]({result.url})\n   - {result.snippet[:200]}...")

                    web_info = ChatMessage(
                        role=ChatRole.USER,
                        content=f"""=== WEB SEARCH RESULTS FOR: '{state.user_prompt}' ===

SEARCH SUMMARY: {search_response.summary}

SOURCES TO CITE IN YOUR RESPONSE:
{chr(10).join(sources_list)}

INSTRUCTION: You MUST cite these sources in your response using the format [Source Title](URL).
- Use format: "Information here [Source Title](URL)" in each bullet point
- Include at least 2-3 web citations in your answer
- Remember: Maximum 10 bullet points, 10-15 words per bullet
- This is general medical knowledge, NOT patient-specific information

=== END OF WEB SEARCH RESULTS ===""")
                    messages.append(web_info)

                # Add user query
                user_msg = ChatMessage(
                    role=ChatRole.USER,
                    content=state.user_prompt,
                    user_id=state.user_id,
                    user_role=state.user_context.role if state.user_context else None,
                )
                messages.append(user_msg)

                # Update status: Generating response
                state.current_step = "Generating Response"
                state.step_details = "AI synthesizing information from medical sources..."

                # Check if streaming is requested
                if getattr(state, 'should_stream_response', False):
                    logger.info("🚀 Starting simple streaming LLM call for general knowledge (no reasoning wrapper)")
                    state.streaming_response = ""  # Reset streaming response

                    # Initialize streaming callback
                    if not hasattr(state, 'streaming_updates'):
                        state.streaming_updates = []

                    # Use simple streaming without reasoning wrapper (avoids confusing the model)
                    async for chunk in self._streaming_llm.chat_stream(messages):
                        state.streaming_response += chunk

                        chunk_update = {
                            "type": "response_chunk",
                            "content": chunk,
                            "accumulated_content": state.streaming_response,
                            "timestamp": datetime.now().isoformat(),
                        }
                        state.streaming_updates.append(chunk_update)

                        state.current_step = "Generating Response"
                        state.step_details = f"Generated {len(state.streaming_response)} characters..."

                        # Call streaming callback if exists
                        if hasattr(state, 'stream_callback') and state.stream_callback:
                            await state.stream_callback(chunk_update)

                    # Return as plain text
                    state.llm_response = ChatMessage(
                        role=ChatRole.ASSISTANT,
                        content=self._normalize_markdown(self._format_ehr_links(state.streaming_response)),
                        metadata={}
                    )

                    logger.info(f"✓ Streaming complete: {len(state.llm_response.content)} chars")

                else:
                    # Non-streaming mode - use simple chat without reasoning
                    logger.info("🤖 Starting simple LLM call for general knowledge (no reasoning wrapper)")
                    response = await self._streaming_llm.chat(messages)

                    state.llm_response = response
                    logger.info(f"✓ Generated response: {len(response.content)} chars")

            except Exception as e:
                log_error(logger, "handle_general_knowledge_query", e)
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
                # Fallback: simple error message
                state.llm_response = ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content="I encountered an error while searching for general medical information. Please try again."
                )

            return state

        @streaming_step("provide_information")
        async def provide_information(state: FlowState) -> FlowState:
            logger.info("🎯 Starting information provision")
            logger.info(f"🔍 Query length: {len(state.user_prompt)} chars")
            logger.info(f"🚀 Full processing: {getattr(state, 'requires_full_processing', True)}")
            logger.info(f"🆔 Session ID: {sanitize_session_id(state.session_id)}")
            logger.info(f"👤 User ID: {sanitize_user_id(state.user_id)}")

            # Update status: Preparing context
            state.current_step = "Preparing Context"
            state.step_details = "Setting up language and system instructions..."

            # Use the single system message for information relay
            messages = [SYSTEM_MSG_INFO_RELAY]

            # Language policy system message (answer in user's prompt language)
            language_system_msg = self._get_language_policy_message(state)
            messages.insert(0, language_system_msg)

            # For direct path (simple queries), use a simplified system message
            if not getattr(state, 'requires_full_processing', True):
                simple_system_msg = ChatMessage(
                    role=ChatRole.SYSTEM,
                    content="""You are CLARA, a helpful medical information assistant. Provide clear, accurate medical information. For general medical questions, draw on your medical knowledge.

**CRITICAL - RESPONSE FORMAT**:
- Organize response with `##` headers to divide sections
- **1-4 sections depending on need**, with **up to 10 bullet points per section**
- **10-15 words per bullet point** - be extremely concise
- Use bullet points (`-`) for all information, no long paragraphs
- Each bullet must be a single, focused fact with citation

**DATE/TIME STAMPS**: Only include dates (YYYY-MM-DD or YYYY-MM-DD HH:MM) when referencing specific journal entries, documents, or when temporal context is essential for the query.

**CRITICAL**: Use **bold** markdown formatting to highlight important clinical terms throughout your response:
- **Diagnoses** and disease names (e.g., **Type 2 Diabetes**, **Hypertension**)
- **Medications** and doses (e.g., **Metformin 1000mg**, **Enalapril 20mg**)
- **Vital signs** and lab values (e.g., **BP 145/85**, **HbA1c 68 mmol/mol**)
- **Symptoms** and clinical findings (e.g., **chest pain**, **dyspnea**)
- **Risk levels** and severity descriptors (e.g., **moderate risk**, **stable**)
- **Key clinical terms** that are important for decision-making

Link policy (STRICT for EHR): When referencing patient data from clinical information chunks, preserve the source links that are embedded in the chunk content:
- For atomic data: Use the format "value [EHR Source](URL)" as it appears in the chunks
- For narrative data: Include the "**Source:** [EHR Record](URL)" information from the chunks
- For web sources: Use format [Source Title](URL) immediately after the information
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

            # Update status: Loading conversation history
            state.current_step = "Loading History"
            state.step_details = f"Loading {len(state.chat_history)} previous messages from session..."

            current_history = state.chat_history[-15:]  # Recent current session history
            logger.info(f"💬 Chat history available: {len(state.chat_history)} total, {len(current_history)} recent")

            # Disable ChatMessage history due to Azure API serialization issues
            # Use alternative text-based conversation history instead
            ENABLE_CONVERSATION_HISTORY = False
            ENABLE_TEXT_CONVERSATION_SUMMARY = True

            # Filter out any problematic messages and limit content length
            safe_history = []
            total_history_length = 0
            MAX_HISTORY_LENGTH = 4000  # Limit to prevent token overflow

            if current_history and ENABLE_CONVERSATION_HISTORY:
                logger.info("📋 Processing conversation history:")
                for i, msg in enumerate(current_history):
                    # Skip empty or None content
                    if not msg.content or not msg.content.strip():
                        logger.info(f"  {i+1}. SKIPPED - Empty content")
                        continue

                    # Use message content as-is
                    content = msg.content

                    # Truncate very long messages
                    content = content[:1000] + "..." if len(content) > 1000 else content

                    # Check if adding this message would exceed limit
                    if total_history_length + len(content) > MAX_HISTORY_LENGTH:
                        logger.info(f"  {i+1}. SKIPPED - Would exceed {MAX_HISTORY_LENGTH} char limit")
                        break

                    # Create a completely new ChatMessage with only essential fields
                    # This ensures no metadata or other fields cause API issues
                    clean_msg = ChatMessage(
                        role=msg.role,
                        content=str(content),  # Ensure it's definitely a string
                        user_id=None,  # Clear any user metadata
                        user_role=None,  # Clear any role metadata
                        metadata={}  # Clear any metadata
                    )
                    safe_history.append(clean_msg)
                    total_history_length += len(content)
                    logger.info(f"  {i+1}. {msg.role.value} ({len(content)} chars): '{content[:50]}...'")

                    # Debug: Check message structure
                    logger.info(f"     Message type: {type(clean_msg.content)}, content preview: '{str(clean_msg.content)[:50]}...'")

                if safe_history:
                    history_header = ChatMessage(
                        role=ChatRole.USER,
                        content="=== CURRENT SESSION HISTORY ===",
                        user_id=None,
                        user_role=None,
                        metadata={}
                    )
                    messages.append(history_header)
                    for msg in safe_history:
                        messages.append(msg)

                    history_footer = ChatMessage(
                        role=ChatRole.USER,
                        content="=== END OF CURRENT SESSION HISTORY ===",
                        user_id=None,
                        user_role=None,
                        metadata={}
                    )
                    messages.append(history_footer)
                    logger.info(f"✅ Added {len(safe_history)} safe history messages ({total_history_length} chars)")
                else:
                    logger.info("⚠️ No safe conversation history to include")
            else:
                if not ENABLE_CONVERSATION_HISTORY and ENABLE_TEXT_CONVERSATION_SUMMARY and current_history:
                    # Alternative approach: Create a text summary of conversation history
                    logger.info("📝 Creating text-based conversation summary")
                    conversation_lines = []
                    for msg in current_history:
                        if not msg.content or not msg.content.strip():
                            continue

                        # Use message content as-is
                        content = msg.content

                        # Truncate if too long
                        content = content[:300] + "..." if len(content) > 300 else content

                        # Format as text line
                        role_name = "You" if msg.role == ChatRole.USER else "CLARA"
                        conversation_lines.append(f"{role_name}: {content}")

                    if conversation_lines:
                        conversation_summary = "\n".join(conversation_lines)
                        conversation_context = ChatMessage(
                            role=ChatRole.USER,
                            content=f"Previous conversation context:\n{conversation_summary}\n\nCurrent question:",
                            user_id=None,
                            user_role=None,
                            metadata={}
                        )
                        messages.append(conversation_context)
                        logger.info(f"✅ Added text conversation summary ({len(conversation_summary)} chars)")
                    else:
                        logger.info("⚠️ No valid conversation content to summarize")
                elif not ENABLE_CONVERSATION_HISTORY:
                    logger.info("⚠️ Conversation history disabled temporarily to prevent API errors")
                else:
                    logger.info("⚠️ No conversation history to include in model prompt")
            
            # Ensure intelligent retrieval results are available for direct path as well
            try:
                if not getattr(state, 'requires_full_processing', True):
                    logger.info("Direct path - checking if retrieval needed")
                    logger.info(f"Patient context available: {state.patient_ctx is not None}")
                    logger.info(f"Retrieved chunks available: {len(state.retrieved_chunks) if state.retrieved_chunks else 0}")

                    if state.patient_ctx and not state.retrieved_chunks:
                        # Update status: Retrieving patient information
                        state.current_step = "Retrieving Information"
                        state.step_details = "Searching patient records for relevant clinical data..."

                        logger.info("Direct path - running intelligent retrieval for patient context")
                        # Populate retrieval using the new intelligent retrieval within this node
                        await intelligent_retrieve_chunks(state)
                        logger.info(f"Direct path - retrieval complete, got {len(state.retrieved_chunks) if state.retrieved_chunks else 0} chunks")
                    else:
                        logger.info(f"Direct path - no retrieval needed (patient_ctx: {state.patient_ctx is not None}, chunks: {len(state.retrieved_chunks) if state.retrieved_chunks else 0})")
            except Exception as e:
                logger.info(f"Retrieval attempt failed on direct path: {e}")
                import traceback
                traceback.print_exc()


            # Add retrieved chunks (this is now the primary source of patient data)
            logger.info(f"Retrieved chunks count: {len(state.retrieved_chunks) if state.retrieved_chunks else 0}")
            if state.retrieved_chunks:
                # Update status: Processing clinical data
                state.current_step = "Processing Clinical Data"
                state.step_details = f"Analyzing {len(state.retrieved_chunks)} relevant clinical records..."

                logger.info(f"Adding {len(state.retrieved_chunks)} chunks to LLM context")
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

                # Log chunk info (GDPR-safe)
                for i, chunk in enumerate(state.retrieved_chunks):
                    chunk_len = len(chunk.get("content", "")) if isinstance(chunk, dict) else len(chunk)
                    logger.info(f"Chunk {i+1}: {chunk_len} chars")

                # Build citations dict from all retrieved chunks with sequential numbers
                if not state.citations:
                    state.citations, state.chunk_id_to_number = self._build_citations_from_chunks(state.retrieved_chunks)
                    logger.info(f"Built {len(state.citations)} numbered citations for provide_information")

                # Format chunks with citation markers (sentence-level)
                formatted_chunks = self._format_chunks_with_citations(state.retrieved_chunks, state.chunk_id_to_number)

                # Add citation policy to system messages for regular chat
                citation_policy_msg = ChatMessage(
                    role=ChatRole.SYSTEM,
                    content="""**CITATION POLICY** (**CRITICAL**):
    - The clinical information is labeled with citation numbers like "[Citation: 1]", "[Citation: 2]", etc.
    - When you use information from a source, cite it immediately after the statement using the number you see
    - **IMPORTANT**: Use the EXACT number shown in the "[Citation: X]" marker
    - **DO NOT** make up citation numbers - only use numbers from the "[Citation: X]" markers you see
    - Format: Place [X] immediately after the statement, where X is the number from the source
    - Example: If you see "[Citation: 3]\\nPatient age: 87 years", write "Patient is 87 years old [3]"
    - Example: If you see "[Citation: 5]\\nBlood pressure: 145/90", write "**BP 145/90** [5]"
"""
                )
                messages.append(citation_policy_msg)

                docs = ChatMessage(
                    role=ChatRole.USER,
                    content=f"{chunk_context}:{temporal_context}\n{formatted_chunks}",
                )
                messages.append(docs)
                logger.info(f"Added chunks message to LLM context (total length: {len(docs.content)} chars)")

                # Include chunk analysis metadata for transparency
                if state.chunk_analysis and state.chunk_analysis.get("query_type"):
                    analysis_info = ChatMessage(
                        role=ChatRole.USER,
                        content=f"Query type identified: {state.chunk_analysis['query_type']}"
                    )
                    messages.append(analysis_info)
            else:
                logger.info("No retrieved chunks available - LLM will rely on general knowledge and other context")

            # Add web search results if available
            if state.web_search_response and state.web_search_response.results:
                # Update status: Adding web sources
                state.current_step = "Integrating Web Sources"
                state.step_details = f"Including {len(state.web_search_response.results)} external medical sources..."

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

INSTRUCTION: You MUST cite these sources in your response using the format [Source Title](URL).
- Use format: "Information here [Source Title](URL)" in each bullet point
- Include at least 2-3 web citations in your answer
- Remember: Maximum 10 bullet points, 10-15 words per bullet

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

            # Debug: Log final message structure before sending to LLM
            logger.info("🔍 Final prompt structure:")
            logger.info(f"📊 Total messages: {len(messages)}")
            total_content_length = 0
            for i, msg in enumerate(messages):
                content_preview = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                content_length = len(msg.content)
                total_content_length += content_length
                logger.info(f"  {i+1}. {msg.role.value} ({content_length} chars): '{content_preview}'")
            logger.info(f"📏 Total content length: {total_content_length} characters")

            # Update status: Generating response
            state.current_step = "Generating Response"
            state.step_details = "AI model analyzing information and formulating answer..."

            if getattr(state, 'should_stream_response', False):
                state.streaming_response = ""  # Reset streaming response

                # Initialize streaming callback to emit chunks in real-time
                if not hasattr(state, 'streaming_updates'):
                    state.streaming_updates = []

                logger.info("🚀 Starting streaming LLM call")
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
                        # Get the full content
                        full_content = update.get("full_content", state.streaming_response)

                        # Validate and correct citations
                        if state.citations:
                            logger.info("Validating citations in streaming response")
                            full_content = await self._validate_and_correct_citations(
                                full_content,
                                state.citations
                            )

                        # Process citations if available
                        if state.citations and state.retrieved_chunks:
                            # Extract cited chunk IDs from response
                            cited_ids = self._extract_cited_chunk_ids(full_content)

                            # Filter citations to only cited chunks
                            filtered_citations = {
                                chunk_id: state.citations[chunk_id]
                                for chunk_id in cited_ids
                                if chunk_id in state.citations
                            }

                            # Model already outputs numbered citations [1], [2], [3] - no conversion needed!

                            # Build JSON response with numbered citations for frontend
                            import json
                            response_with_citations = {
                                "type": "general_response",
                                "content": self._normalize_markdown(self._format_ehr_links(full_content)),
                                "citations": filtered_citations,
                                "context": {
                                    "session_id": state.session_id,
                                    "user_prompt": state.user_prompt,
                                    "timestamp": str(int(time.time() * 1000)),
                                    "has_history": bool(state.chat_history)
                                }
                            }

                            state.llm_response = ChatMessage(
                                role=ChatRole.ASSISTANT,
                                content=json.dumps(response_with_citations, indent=2),
                                metadata={
                                    "reasoning": update.get("reasoning", ""),
                                    "reasoning_steps": update.get("reasoning_steps", []),
                                }
                            )
                        else:
                            # No citations - return as plain text
                            state.llm_response = ChatMessage(
                                role=ChatRole.ASSISTANT,
                                content=self._normalize_markdown(
                                    self._format_ehr_links(full_content)
                                ),
                                metadata={
                                    "reasoning": update.get("reasoning", ""),
                                    "reasoning_steps": update.get("reasoning_steps", []),
                                }
                            )
                        break
            else:
                logger.info("🚀 Starting non-streaming LLM call")
                llm_resp = await self._streaming_llm.chat_with_reasoning(messages=messages, state=state, reasoning_prompt=reasoning_prompt)
                logger.info(f"📝 LLM response received: {len(llm_resp.content) if llm_resp and llm_resp.content else 0} characters")
                if llm_resp and llm_resp.content:
                    logger.info(f"📄 Response preview: '{llm_resp.content[:200]}...'")
                else:
                    logger.info("⚠️ Empty or null LLM response!")

                # Validate and correct citations in non-streaming response
                response_content = llm_resp.content
                if state.citations:
                    logger.info("Validating citations in non-streaming response")
                    response_content = await self._validate_and_correct_citations(
                        response_content,
                        state.citations
                    )

                # Process citations if available
                if state.citations and state.retrieved_chunks:
                    # Extract cited chunk IDs from response
                    cited_ids = self._extract_cited_chunk_ids(response_content)

                    # Filter citations to only cited chunks
                    filtered_citations = {
                        chunk_id: state.citations[chunk_id]
                        for chunk_id in cited_ids
                        if chunk_id in state.citations
                    }

                    # Model already outputs numbered citations [1], [2], [3] - no conversion needed!

                    # Build JSON response with numbered citations for frontend
                    import json
                    response_with_citations = {
                        "type": "general_response",
                        "content": self._normalize_markdown(self._format_ehr_links(response_content)),
                        "citations": filtered_citations,
                        "context": {
                            "session_id": state.session_id,
                            "user_prompt": state.user_prompt,
                            "timestamp": str(int(time.time() * 1000)),
                            "has_history": bool(state.chat_history)
                        }
                    }

                    state.llm_response = ChatMessage(
                        role=llm_resp.role,
                        content=json.dumps(response_with_citations, indent=2),
                        metadata=llm_resp.metadata
                    )
                else:
                    # No citations - return as plain text
                    state.llm_response = ChatMessage(
                        role=llm_resp.role,
                        content=self._normalize_markdown(self._format_ehr_links(response_content)),
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

                logger.info(f"Query complexity decision: {'FULL_PROCESSING' if requires_full_processing else 'DIRECT'} (query_length={len(state.user_prompt)} chars)")
                
            except Exception as e:
                log_error(logger, "query_complexity", e)
                # Default to full processing on error to be safe
                state.requires_full_processing = True
                
            return state

        @streaming_step("contextualize_query_for_classification")
        async def contextualize_query_for_classification(state: FlowState) -> FlowState:
            """
            Use LLM to intelligently add conversation context to query for better classification.
            Only runs if chat history exists.
            """
            try:
                if not state.chat_history or len(state.chat_history) < 2:
                    # No context needed for first message
                    state.classification_query = state.user_prompt
                    logger.info("No history - using original query")
                    return state

                # Get recent conversation context (last 5 messages)
                recent_messages = state.chat_history[-5:]
                history_text = "\n".join([
                    f"{msg.role.value}: {msg.content[:300]}"
                    for msg in recent_messages
                ])

                # Use LLM to create classification-optimized query
                prompt = f"""Given this conversation history and the user's latest query, create a single reformulated query that includes necessary context for intent classification.

Conversation history:
{history_text}

User's current query: "{state.user_prompt}"

Task: If the current query references previous context (e.g., "yes", "show timeline", "that one"), reformulate it to be self-contained. If it's already clear, return it unchanged.

Examples:
- "yes" after "Would you like a timeline?" → "Show me a timeline view"
- "timeline please" → "Show me a timeline view"
- "What medications is the patient on?" → "What medications is the patient on?" (unchanged)

Return ONLY the reformulated query, nothing else."""

                messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content="You reformulate user queries to include conversation context for better intent classification. Return only the reformulated query."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                response = await self._llm.chat(messages)
                state.classification_query = response.content.strip()

                logger.info(f"Original query length: {len(state.user_prompt)} chars")
                logger.info(f"Contextualized query length: {len(state.classification_query)} chars")

            except Exception as e:
                logger.info(f"Error: {e}, using original query")
                state.classification_query = state.user_prompt

            return state

        @streaming_step("classify_query_intent")
        async def classify_query_intent(state: FlowState) -> FlowState:
            """Classify the query to determine flow type including note generation."""
            try:
                logger.info(f"Classifying query (length={len(state.user_prompt)} chars)")

                # Skip classification if already in note generation flow
                if hasattr(state, 'is_note_generation_flow') and state.is_note_generation_flow:
                    logger.info("Already in note generation flow, skipping classification")
                    return state

                # Use contextualized query if available (from contextualize_query_for_classification node)
                query_to_classify = getattr(state, 'classification_query', state.user_prompt)

                logger.info(f"Classifying query (length={len(query_to_classify)} chars)")

                # Use the LLM-based classifier (async)
                classifier = self._zero_shot_classifier
                label = await classifier.classify(query_to_classify, [
                    "lookup", "temporal-trend", "comparative", "general", "general_summary", "focused_summary", "sbar_handoff", "guideline", "timeline", "note_generation", "discharge_summary"
                ], llm_client=self._llm)

                logger.info(f"Query classified as: {label}")

                # Store classification in state
                state.query_classification = label

                # Check for note generation intent (high precision)
                if label == "note_generation" or label == "discharge_summary":
                    logger.info("Note generation detected!")
                    state.is_note_generation_flow = True

                    # Determine template type from query content
                    query_lower = state.user_prompt.lower()

                    # Template detection with keywords
                    if any(word in query_lower for word in ["sbar", "situation", "bakgrund", "background"]):
                        template_type = "sbar"
                    elif any(word in query_lower for word in ["soap", "subjective", "objective", "assessment", "plan"]):
                        template_type = "soap"
                    elif any(word in query_lower for word in ["remiss", "referral", "refer"]):
                        template_type = "referral"
                    elif any(word in query_lower for word in ["journal", "progress", "anteckning"]):
                        template_type = "journal_entry"
                    elif any(word in query_lower for word in ["consultation", "konsultation"]):
                        template_type = "consultation"
                    else:
                        # Default to SBAR for general note requests
                        template_type = "sbar"

                    logger.info(f"Auto-selected template type: {template_type}")

                    # Store template type preference for later retrieval
                    state.note_template_type_preference = template_type

                    # Don't set SBAR or timeline flows
                    state.is_sbar_flow = False
                    state.is_timeline_flow = False
                    return state

                # Determine if this should use SBAR flow (handoff/transition of care)
                # SBAR is triggered by the classifier detecting handoff intent
                state.is_sbar_flow = (label == "sbar_handoff")
                logger.info(f"SBAR flow (classifier): {state.is_sbar_flow}")

                # General summary flow is triggered by "general_summary" classification
                state.is_general_summary_flow = (label == "general_summary")
                logger.info(f"General summary flow (classifier): {state.is_general_summary_flow}")

                # Focused summary flow is triggered by "focused_summary" classification
                state.is_focused_summary_flow = (label == "focused_summary")
                logger.info(f"Focused summary flow (classifier): {state.is_focused_summary_flow}")

                # General knowledge flow is triggered by "general" classification (medical knowledge, not patient-specific)
                state.is_general_knowledge_flow = (label == "general")
                logger.info(f"General knowledge flow (classifier): {state.is_general_knowledge_flow}")

                # Determine if this should use Timeline flow (temporal sequence queries)
                timeline_query_types = ["timeline", "temporal-trend"]
                state.is_timeline_flow = label in timeline_query_types

                logger.info(f"Timeline flow: {state.is_timeline_flow}")

                # Override DIRECT routing if any specialized flow is detected
                # NOTE: general_knowledge_flow is NOT included here - it should skip patient processing
                if state.is_sbar_flow or state.is_timeline_flow or state.is_general_summary_flow or state.is_focused_summary_flow:
                    state.requires_full_processing = True
                    logger.info(f"⚠️ Overriding DIRECT → FULL_PROCESSING (SBAR: {state.is_sbar_flow}, General Summary: {state.is_general_summary_flow}, Focused Summary: {state.is_focused_summary_flow}, Timeline: {state.is_timeline_flow})")

                # Initialize SBAR cache if using SBAR flow
                if state.is_sbar_flow:
                    state.sbar_retrieval_cache = {}

                # Initialize general summary cache if using general summary flow
                if state.is_general_summary_flow:
                    state.general_retrieval_cache = {}

                # Initialize focused summary cache if using focused summary flow
                if state.is_focused_summary_flow:
                    state.focused_retrieval_cache = {}

                # Initialize Timeline cache if using Timeline flow
                if state.is_timeline_flow:
                    state.timeline_retrieval_cache = {}

            except Exception as e:
                logger.info(f"Classification failed: {e}, defaulting to regular flow")
                state.query_classification = "lookup"  # Default fallback
                state.is_sbar_flow = False
                state.is_timeline_flow = False
                state.is_note_generation_flow = False
                state.is_general_summary_flow = False
                state.is_focused_summary_flow = False
                state.is_general_knowledge_flow = False

            return state

        def requires_full_processing(state: FlowState) -> bool:
            """
            Conditional function to determine if full processing is needed.

            Returns True if:
            - Query complexity evaluation marked it as needing full processing, OR
            - SBAR flow is detected (needs specialized retrieval), OR
            - General summary flow is detected (needs specialized retrieval), OR
            - Focused summary flow is detected (needs specialized retrieval), OR
            - Timeline flow is detected (needs specialized retrieval)
            """
            base_requirement = getattr(state, 'requires_full_processing', True)
            is_sbar = getattr(state, 'is_sbar_flow', False)
            is_general_summary = getattr(state, 'is_general_summary_flow', False)
            is_focused_summary = getattr(state, 'is_focused_summary_flow', False)
            is_timeline = getattr(state, 'is_timeline_flow', False)

            # Override DIRECT routing if any specialized flow is detected
            if is_sbar or is_general_summary or is_focused_summary or is_timeline:
                logger.info(f"Overriding DIRECT - SBAR: {is_sbar}, General Summary: {is_general_summary}, Focused Summary: {is_focused_summary}, Timeline: {is_timeline}")
                return True

            return base_requirement

        def is_sbar_flow(state: FlowState) -> bool:
            """Conditional function to determine if SBAR flow should be used."""
            return getattr(state, 'is_sbar_flow', False)

        def is_general_summary_flow(state: FlowState) -> bool:
            """Conditional function to determine if general summary flow should be used."""
            return getattr(state, 'is_general_summary_flow', False)

        def is_focused_summary_flow(state: FlowState) -> bool:
            """Conditional function to determine if focused summary flow should be used."""
            return getattr(state, 'is_focused_summary_flow', False)

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
        _builder.add_node("contextualize_query_for_classification", contextualize_query_for_classification)
        _builder.add_node("classify_query_intent", classify_query_intent)
        _builder.add_node("store_user_message", store_user_message)
        _builder.add_node("load_current_session_history", load_current_session_history)
        _builder.add_node("fetch_patient", fetch_patient)
        _builder.add_node("fetch_pdfs", fetch_pdfs)
        _builder.add_node("fetch_xmls", fetch_xmls)
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
        # General summary parallel retrieval nodes
        _builder.add_node("retrieve_snapshot_chunks", retrieve_snapshot_chunks)
        _builder.add_node("retrieve_problems_chunks", retrieve_problems_chunks)
        _builder.add_node("retrieve_medications_chunks", retrieve_medications_chunks)
        _builder.add_node("retrieve_trends_chunks", retrieve_trends_chunks)
        _builder.add_node("retrieve_history_chunks", retrieve_history_chunks)  # Now used for encounters
        _builder.add_node("retrieve_risks_chunks", retrieve_risks_chunks)
        # General summary parallel generation nodes
        _builder.add_node("generate_snapshot_summary", generate_snapshot_summary)
        _builder.add_node("generate_problems_summary", generate_problems_summary)
        _builder.add_node("generate_medications_summary", generate_medications_summary)
        _builder.add_node("generate_trends_summary", generate_trends_summary)
        _builder.add_node("generate_history_summary", generate_history_summary)  # Now generates encounters with JSON
        _builder.add_node("generate_risks_summary", generate_risks_summary)
        _builder.add_node("merge_general_summary_results", merge_general_summary_results)
        _builder.add_node("general_summary_parallel_dispatcher", general_summary_parallel_dispatcher)
        # Focused summary flow nodes
        _builder.add_node("focused_summary_parallel_dispatcher", focused_summary_parallel_dispatcher)
        _builder.add_node("identify_aspect_and_retrieve", identify_aspect_and_retrieve)
        _builder.add_node("retrieve_focused_diagnoses_chunks", retrieve_focused_diagnoses_chunks)
        _builder.add_node("generate_diagnoses_section", generate_diagnoses_section)
        _builder.add_node("retrieve_focused_events_chunks", retrieve_focused_events_chunks)
        _builder.add_node("generate_events_section", generate_events_section)
        _builder.add_node("retrieve_focused_medications_chunks", retrieve_focused_medications_chunks)
        _builder.add_node("generate_medications_section", generate_medications_section)
        _builder.add_node("retrieve_focused_objective_data_chunks", retrieve_focused_objective_data_chunks)
        _builder.add_node("generate_objective_data_section", generate_objective_data_section)
        _builder.add_node("retrieve_focused_assessment_chunks", retrieve_focused_assessment_chunks)
        _builder.add_node("generate_assessment_section", generate_assessment_section)
        _builder.add_node("retrieve_focused_next_steps_chunks", retrieve_focused_next_steps_chunks)
        _builder.add_node("generate_next_steps_section", generate_next_steps_section)
        _builder.add_node("merge_focused_summary_results", merge_focused_summary_results)
        # Timeline flow nodes
        _builder.add_node("extract_timeline_events", extract_timeline_events)
        _builder.add_node("retrieve_timeline_chunks", retrieve_timeline_chunks)
        _builder.add_node("generate_timeline_bubbles", generate_timeline_bubbles)
        _builder.add_node("merge_timeline_results", merge_timeline_results)
        # Note generation flow nodes
        _builder.add_node("load_note_template", load_note_template)
        _builder.add_node("generate_note_section", generate_note_section)
        _builder.add_node("format_note_response", format_note_response)
        _builder.add_node("store_note_metadata", store_note_metadata)
        _builder.add_node("handle_general_knowledge_query", handle_general_knowledge_query)  # General knowledge (web-only) node
        _builder.add_node("evaluate_web_search_need", evaluate_web_search_need)
        _builder.add_node("perform_web_search", perform_web_search)
        _builder.add_node("provide_information", provide_information)
        _builder.add_node("store_assistant_response", store_assistant_response)

        _builder.set_entry_point("load_user_context")  # Start with loading user context

        # Add edges for user context loading and classification
        _builder.add_edge("load_user_context", "evaluate_query_complexity")
        _builder.add_edge("evaluate_query_complexity", "contextualize_query_for_classification")
        _builder.add_edge("contextualize_query_for_classification", "classify_query_intent")
        _builder.add_edge("classify_query_intent", "store_user_message")
        _builder.add_edge("store_user_message", "load_current_session_history")

        # Route after loading session history: check for general knowledge, full processing, or direct path
        def route_after_session_history(state):
            """Route based on query type: general knowledge, full processing, or direct."""
            is_general = getattr(state, 'is_general_knowledge_flow', False)
            needs_full = getattr(state, 'requires_full_processing', True)

            if is_general:
                logger.info("🌐 Routing to general knowledge handler (web-only)")
                return "handle_general_knowledge_query"
            elif needs_full:
                logger.info("📊 Routing to full processing (patient data)")
                return "check_patient"
            else:
                logger.info("⚡ Routing to direct simple answer")
                return "provide_information"

        # Branch based on query classification and complexity
        _builder.add_conditional_edges(
            "load_current_session_history",
            route_after_session_history,
            {
                "handle_general_knowledge_query": "handle_general_knowledge_query",  # General knowledge (web-only)
                "check_patient": "check_patient",    # Full processing starts with patient data
                "provide_information": "provide_information"  # Direct path - skip all heavy processing
            }
        )

        # SESSION HISTORY LOADING (now happens for both patient and general chat)
        # After loading session history, decide if we need patient data
        _builder.add_conditional_edges(
            "check_patient",
            has_patient,
            {
                True: "fetch_patient",                   # Patient ID provided -> fetch patient details
                False: "fetch_pdfs"  # No patient ID -> fetch general PDFs and XMLs, then continue
            }
        )

        # PATIENT PROCESSING PATH (only when patient_id exists)
        # Always fetch PDFs and XMLs after fetching patient data
        _builder.add_edge("fetch_patient", "fetch_pdfs")

        # BOTH PATIENT AND GENERAL MODES: Always fetch XMLs after PDFs
        _builder.add_edge("fetch_pdfs", "fetch_xmls")

        # Route after fetching XMLs - different paths for patient vs general mode
        def route_after_xmls(state) -> str:
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
            "fetch_xmls",
            route_after_xmls,
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

        # Sequential general summary execution to avoid concurrent state updates
        _builder.add_edge("general_summary_parallel_dispatcher", "retrieve_snapshot_chunks")

        # Sequential retrieval and generation chain for general summary
        _builder.add_edge("retrieve_snapshot_chunks", "generate_snapshot_summary")
        _builder.add_edge("generate_snapshot_summary", "retrieve_problems_chunks")
        _builder.add_edge("retrieve_problems_chunks", "generate_problems_summary")
        _builder.add_edge("generate_problems_summary", "retrieve_medications_chunks")
        _builder.add_edge("retrieve_medications_chunks", "generate_medications_summary")
        _builder.add_edge("generate_medications_summary", "retrieve_trends_chunks")
        _builder.add_edge("retrieve_trends_chunks", "generate_trends_summary")
        _builder.add_edge("generate_trends_summary", "retrieve_history_chunks")
        _builder.add_edge("retrieve_history_chunks", "generate_history_summary")
        _builder.add_edge("generate_history_summary", "retrieve_risks_chunks")
        _builder.add_edge("retrieve_risks_chunks", "generate_risks_summary")

        # Final generation node goes to merge
        _builder.add_edge("generate_risks_summary", "merge_general_summary_results")

        # General summary merge to store response
        _builder.add_edge("merge_general_summary_results", "store_assistant_response")

        # Focused summary flow edges - sequential processing
        _builder.add_edge("focused_summary_parallel_dispatcher", "identify_aspect_and_retrieve")
        _builder.add_edge("identify_aspect_and_retrieve", "retrieve_focused_diagnoses_chunks")
        _builder.add_edge("retrieve_focused_diagnoses_chunks", "generate_diagnoses_section")
        _builder.add_edge("generate_diagnoses_section", "retrieve_focused_events_chunks")
        _builder.add_edge("retrieve_focused_events_chunks", "generate_events_section")
        _builder.add_edge("generate_events_section", "retrieve_focused_medications_chunks")
        _builder.add_edge("retrieve_focused_medications_chunks", "generate_medications_section")
        _builder.add_edge("generate_medications_section", "retrieve_focused_objective_data_chunks")
        _builder.add_edge("retrieve_focused_objective_data_chunks", "generate_objective_data_section")
        _builder.add_edge("generate_objective_data_section", "retrieve_focused_assessment_chunks")
        _builder.add_edge("retrieve_focused_assessment_chunks", "generate_assessment_section")
        _builder.add_edge("generate_assessment_section", "retrieve_focused_next_steps_chunks")
        _builder.add_edge("retrieve_focused_next_steps_chunks", "generate_next_steps_section")
        _builder.add_edge("generate_next_steps_section", "merge_focused_summary_results")
        _builder.add_edge("merge_focused_summary_results", "store_assistant_response")

        # Timeline flow edges - sequential processing
        _builder.add_edge("extract_timeline_events", "retrieve_timeline_chunks")
        _builder.add_edge("retrieve_timeline_chunks", "generate_timeline_bubbles")
        _builder.add_edge("generate_timeline_bubbles", "merge_timeline_results")
        _builder.add_edge("merge_timeline_results", "store_assistant_response")

        # Note generation flow edges - sequential processing
        _builder.add_edge("load_note_template", "generate_note_section")
        _builder.add_edge("generate_note_section", "format_note_response")
        _builder.add_edge("format_note_response", "store_note_metadata")
        _builder.add_edge("store_note_metadata", "store_assistant_response")

        # Route after chunk retrieval: check flow type
        def route_after_chunks(state):
            logger.info(f"🔀 route_after_chunks called - is_general_summary_flow: {getattr(state, 'is_general_summary_flow', False)}, is_focused_summary_flow: {getattr(state, 'is_focused_summary_flow', False)}, is_sbar_flow: {getattr(state, 'is_sbar_flow', False)}, is_timeline_flow: {getattr(state, 'is_timeline_flow', False)}, needs_refinement: {getattr(state, 'needs_refinement', False)}")

            # Check special flows FIRST (they have priority and don't need refinement)
            if hasattr(state, 'is_note_generation_flow') and state.is_note_generation_flow:
                logger.info("📝 Routing to note generation flow")
                return "load_note_template"
            elif hasattr(state, 'is_timeline_flow') and state.is_timeline_flow:
                logger.info("📅 Routing to timeline flow")
                return "extract_timeline_events"
            elif hasattr(state, 'is_sbar_flow') and state.is_sbar_flow:
                logger.info("📋 Routing to SBAR flow")
                return "sbar_parallel_dispatcher"
            elif hasattr(state, 'is_general_summary_flow') and state.is_general_summary_flow:
                logger.info("📊 Routing to general summary flow")
                return "general_summary_parallel_dispatcher"
            elif hasattr(state, 'is_focused_summary_flow') and state.is_focused_summary_flow:
                logger.info("🎯 Routing to focused summary flow")
                return "focused_summary_parallel_dispatcher"
            # Only check refinement if NOT in a special flow
            elif hasattr(state, 'needs_refinement') and state.needs_refinement and state.retrieval_retry_attempts < RETRY_MAX:
                # Increment retry attempts to prevent infinite loop
                state.retrieval_retry_attempts += 1
                logger.info(f"🔄 Retrieval refinement needed, attempt {state.retrieval_retry_attempts}/{RETRY_MAX}")
                return "intelligent_retrieve_chunks"
            else:
                # Clear refinement flag for next query
                state.needs_refinement = False
                logger.info("➡️ Routing to web search evaluation")
                return "evaluate_web_search_need"

        _builder.add_conditional_edges(
            "intelligent_retrieve_chunks",
            route_after_chunks,
            {
                "load_note_template": "load_note_template",
                "extract_timeline_events": "extract_timeline_events",
                "sbar_parallel_dispatcher": "sbar_parallel_dispatcher",
                "general_summary_parallel_dispatcher": "general_summary_parallel_dispatcher",
                "focused_summary_parallel_dispatcher": "focused_summary_parallel_dispatcher",
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
        _builder.add_edge("handle_general_knowledge_query", "store_assistant_response")  # General knowledge → store response
        _builder.add_edge("provide_information", "store_assistant_response")
        _builder.add_edge("store_assistant_response", END)

        # Compile the graph
        # Note: recursion_limit is passed at runtime in ainvoke/astream config
        # General summary flow: ~35 steps, SBAR: ~20, Timeline: ~15, Note generation: ~25
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
        
        # NO PHI redaction - healthcare professionals need complete clinical data
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

        # Apply chunking strategy - NO redaction
        chunks = strategy.apply(records, policy, orchestrator._tokenizer)
        
        logger.info(f"Created {len(chunks)} chunks from {len(journal_entries)} journal entries")
        
        return chunks

    async def _chunk_pdf_documents(self, pdf_documents: List[PDFDocument], orchestrator: ChunkingOrchestrator, patient_id_str: Optional[str]) -> List[Chunk]:
        """Chunk PDF documents using the narrative strategy with orchestrator's redactor (Presidio)."""
        from optimed.core.domain import Record
        from optimed.adapters.chunking.strategies.narrative_v1 import NarrativeV1
        from optimed.core.services.hash_utils import stable_hash

        if not pdf_documents:
            return []

        # Create records from PDF documents
        records = []

        # Use semantic chunking for better PDF processing
        from optimed.adapters.pdf.semantic_chunker import SemanticPDFChunker

        chunker = SemanticPDFChunker(
            target_chunk_size=800,
            overlap_ratio=0.15,
            preserve_medical_context=True
        )

        for pdf in pdf_documents:
            if not pdf.extracted_text:
                continue

            # Create semantic chunks from the PDF
            semantic_chunks = chunker.chunk_pdf_text(
                pdf.extracted_text,
                pdf.document_id,
                {
                    "title": pdf.metadata.title,
                    "author": pdf.metadata.author,
                    "subject": pdf.metadata.subject,
                    "patient_id": pdf.patient_id,
                    "user_id": pdf.user_id,
                    "filename": pdf.filename,
                    "uploaded_at": pdf.uploaded_at.strftime('%Y-%m-%d %H:%M')
                }
            )

            logger.info(f"PDF {pdf.filename} -> {len(semantic_chunks)} semantic chunks")

            # Use appropriate patient reference
            if pdf.patient_id:
                pseudo_patient = stable_hash({"pid": pdf.patient_id}, namespace="patient")
            else:
                pseudo_patient = stable_hash({"uid": pdf.user_id}, namespace="user")

            # Create a record for each semantic chunk
            for i, chunk in enumerate(semantic_chunks):
                # Create document header for context
                doc_header = f"PDF Document: {pdf.get_display_name()}\n"
                doc_header += f"Filename: {pdf.filename}\n"
                if pdf.metadata.title:
                    doc_header += f"Title: {pdf.metadata.title}\n"
                if pdf.metadata.author:
                    doc_header += f"Author: {pdf.metadata.author}\n"
                doc_header += f"Upload Date: {pdf.uploaded_at.strftime('%Y-%m-%d %H:%M')}\n"
                doc_header += f"{'Patient ID: ' + pdf.patient_id if pdf.patient_id else 'General Document'}\n"

                if chunk.metadata.section_title:
                    doc_header += f"Section: {chunk.metadata.section_title}\n"

                # Include page numbers for citation
                if chunk.metadata.start_page == chunk.metadata.end_page:
                    doc_header += f"Page: {chunk.metadata.start_page}\n"
                else:
                    doc_header += f"Pages: {chunk.metadata.start_page}-{chunk.metadata.end_page}\n"

                doc_header += f"Chunk {i+1}/{len(semantic_chunks)}\n---\n"

                full_text = doc_header + chunk.text

                record = Record(
                    patient_ref=pseudo_patient,
                    encounter_ref=None,
                    resource_type="pdf_document",
                    key=chunk.metadata.chunk_id,
                    text=full_text
                )
                records.append(record)

        if not records:
            return []

        # NO PHI redaction - healthcare professionals need complete clinical data
        strategy = NarrativeV1()
        policy = CHUNK_POLICY_PRESETS.get("narrative_default")

        # Apply chunking strategy - NO redaction
        chunks = strategy.apply(records, policy, orchestrator._tokenizer)

        logger.info(f"Created {len(chunks)} chunks from {len(pdf_documents)} PDF documents (NO redaction - complete clinical data)")

        return chunks

    async def _chunk_xml_documents(self, xml_documents: List[XMLDocument], orchestrator: ChunkingOrchestrator, patient_id_str: Optional[str]) -> List[Chunk]:
        """Chunk XML documents using simple text-based chunking with NarrativeV1 strategy and orchestrator's redactor (Presidio)."""
        from optimed.core.domain import Record
        from optimed.adapters.chunking.strategies.narrative_v1 import NarrativeV1
        from optimed.core.services.hash_utils import stable_hash

        if not xml_documents:
            return []

        # Create records from XML documents with improved text chunking
        records = []

        for xml in xml_documents:
            if not xml.extracted_text:
                logger.info(f"Skipping XML document {xml.filename} - no extracted text")
                continue

            # Use appropriate patient reference
            if xml.patient_id:
                pseudo_patient = stable_hash({"pid": xml.patient_id}, namespace="patient")
            else:
                pseudo_patient = stable_hash({"uid": xml.user_id}, namespace="user")

            # Split the extracted text into logical sections
            sections = self._split_xml_text_into_sections(xml.extracted_text)
            logger.info(f"XML {xml.filename} -> {len(sections)} logical sections")

            # Further split large sections into smaller pieces (target ~3k chars)
            all_pieces = []
            for section in sections:
                if len(section) > 5000:  # If section is larger than 5k chars
                    # Split into smaller pieces
                    pieces = self._split_large_section(section, target_size=3000)
                    all_pieces.extend(pieces)
                else:
                    all_pieces.append(section)

            logger.info(f"XML {xml.filename} -> {len(all_pieces)} text pieces (from {len(sections)} sections)")

            # Create a record for each piece
            for piece_idx, piece in enumerate(all_pieces):
                if not piece or not piece.strip():
                    continue

                # Create document header for context
                doc_header = f"XML Document: {xml.filename}\n"
                if xml.metadata and xml.metadata.document_type:
                    doc_header += f"Document Type: {xml.metadata.document_type}\n"
                doc_header += f"Part: {piece_idx + 1} of {len(all_pieces)}\n"
                doc_header += "---\n\n"

                # Combine header with piece content
                full_text = doc_header + piece.strip()

                # Create a record for this piece
                record = Record(
                    patient_ref=pseudo_patient,
                    encounter_ref=None,
                    resource_type="xml_document",
                    key=f"xml_{xml.document_id}_piece_{piece_idx}",
                    text=full_text,
                    timestamp=xml.updated_at
                )
                records.append(record)

        if not records:
            return []

        logger.info(f"Created {len(records)} records from {len(xml_documents)} XML documents")

        # NO PHI redaction - healthcare professionals need complete clinical data
        strategy = NarrativeV1()
        policy = CHUNK_POLICY_PRESETS.get("narrative_default")

        if not policy:
            # Fallback policy if narrative_default is not available
            from optimed.core.domain import ChunkPolicy
            policy = ChunkPolicy(
                name="xml_fallback",
                max_tokens=800,
                overlap=0.12,
                boundary_rules={"sentence": True}
            )

        # Apply chunking strategy - NO redaction
        chunks = strategy.apply(records, policy, orchestrator._tokenizer)

        logger.info(f"Created {len(chunks)} final chunks from {len(xml_documents)} XML documents (NO redaction - complete clinical data)")

        return chunks

    def _split_large_section(self, text: str, target_size: int = 3000) -> list[str]:
        """Split a large section into smaller pieces around target_size characters."""
        if len(text) <= target_size:
            return [text]

        pieces = []
        lines = text.split('\n')
        current_piece: list[str] = []
        current_length = 0

        for line in lines:
            line_length = len(line) + 1  # +1 for newline

            # If adding this line would exceed target and we have content, save current piece
            if current_length + line_length > target_size and current_piece:
                pieces.append('\n'.join(current_piece))
                current_piece = []
                current_length = 0

            # If single line is longer than target, split it further
            if line_length > target_size * 2:
                # Split by sentences
                sentences = line.split('. ')
                for sent in sentences:
                    if current_length + len(sent) > target_size and current_piece:
                        pieces.append('\n'.join(current_piece))
                        current_piece = []
                        current_length = 0
                    current_piece.append(sent)
                    current_length += len(sent)
            else:
                current_piece.append(line)
                current_length += line_length

        # Add remaining content
        if current_piece:
            pieces.append('\n'.join(current_piece))

        return pieces

    def _split_xml_text_into_sections(self, text: str) -> list[str]:
        """Split XML extracted text into logical sections for better chunking."""
        if not text or not text.strip():
            return [text]

        # Split on section headers (lines with --- markers)
        sections = []
        lines = text.split('\n')
        current_section: List[str] = []

        for line in lines:
            line_stripped = line.strip()

            # Check if this is a section header (starts/ends with ---)
            if line_stripped.startswith('---') and line_stripped.endswith('---'):
                # Finish the current section
                if current_section:
                    section_text = '\n'.join(current_section).strip()
                    if section_text:
                        sections.append(section_text)
                    current_section = []

                # Start new section with the header
                current_section = [line]
            else:
                # Add to current section
                current_section.append(line)

        # Add the final section
        if current_section:
            section_text = '\n'.join(current_section).strip()
            if section_text:
                sections.append(section_text)

        # If no sections found (no --- markers), split by double newlines
        if not sections:
            paragraphs = text.split('\n\n')
            sections = [p.strip() for p in paragraphs if p.strip()]

        # If still only one large section, split it further
        if len(sections) == 1 and len(sections[0]) > 2000:
            large_section = sections[0]
            # Split by single newlines and group into smaller chunks
            lines = large_section.split('\n')
            chunk_size = len(lines) // 4  # Aim for ~4 chunks
            if chunk_size < 10:
                chunk_size = 10

            sections = []
            current_chunk = []
            for line in lines:
                current_chunk.append(line)
                if len(current_chunk) >= chunk_size:
                    sections.append('\n'.join(current_chunk))
                    current_chunk = []

            if current_chunk:
                sections.append('\n'.join(current_chunk))

        return sections

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
        """Embed multiple texts using efficient batch encoding.

        Uses embed_batch for 10-100x speedup compared to individual encoding.
        Critical for performance when embedding 100-800 chunks.
        """
        from typing import cast, Literal
        mode_literal = cast(Literal["query", "passage"], mode)

        # Use batch encoding for massive speedup
        # For 800 chunks: batch encoding ~5 seconds vs individual encoding ~5 minutes!
        return await embed_batch(texts, mode_literal)

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

    def _compute_dynamic_n(self, query: str, scores: list[float], pre_classification: Optional[str] = None) -> int:
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

        # Use pre-stored classification if available, otherwise use heuristic fallback
        try:
            if pre_classification:
                label = pre_classification
                logger.info(f"Using pre-stored classification: {label}")
            else:
                # Fallback to heuristic if classification not available
                # (This should rarely happen as classification is done earlier in the flow)
                logger.warning("No pre-classification available, using heuristic fallback")
                n_class = self._classify_query(query)
                return max(N_MIN, min(N_MAX, n_class))

            # Map classification to dynamic n based on query complexity
            if label == "lookup":
                n_class = min(8, N_MAX)        # ~5–8
            elif label == "temporal-trend":
                n_class = min(20, N_MAX)       # ~12–20
            elif label == "comparative":
                n_class = min(28, N_MAX)       # ~18–28
            elif label == "general":
                n_class = min(25, N_MAX)       # ~20–25 for general medical knowledge questions
            elif label in ("summary", "general_summary", "focused_summary"):
                n_class = min(30, N_MAX)       # ~40–80, capped at 30
            elif label == "guideline":
                n_class = min(12, N_MAX)       # ~6–12
            else:
                n_class = 8  # Default fallback
        except Exception as e:
            logger.info(f"Classification mapping failed: {e}, using heuristic fallback")
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
            # Handle ephemeral session management
            sid = session_id or str(uuid.uuid4())
            # Only clear session memory if this is a truly new session (no existing data)
            if sid not in self._session_memory:
                logger.info(f"🆕 Creating new ephemeral session {sid}")
                self._session_memory[sid] = []
            else:
                logger.info(f"🔄 Reusing existing ephemeral session {sid} with {len(self._session_memory[sid])} messages")
                # Validate session memory integrity
                try:
                    # Check if session memory contains valid data
                    for i, item in enumerate(self._session_memory[sid]):
                        if not isinstance(item, dict) or 'data' not in item:
                            logger.info(f"⚠️ Invalid item {i} in session memory, clearing session")
                            self._session_memory[sid] = []
                            break
                except Exception as e:
                    logger.info(f"❌ Session memory corrupted, clearing: {e}")
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
                            logger.info(f"User {sanitize_user_id(user_id)} joined existing session {session_id}")
                        else:
                            logger.info(f"Failed to add user {sanitize_user_id(user_id)} to session {session_id}")
                    else:
                        logger.info(f"User {sanitize_user_id(user_id)} not allowed to join session {session_id}")
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

        # Detect language from user prompt for localized streaming messages
        try:
            from optimed.core.lang import detect_language_code
            detected_language = detect_language_code(prompt or "")
        except Exception:
            detected_language = "en"

        # Increase recursion limit for long flows (general summary has ~35 steps)
        config = {"recursion_limit": 50}

        if patient is not None:
            data = await self._compiled_graph.ainvoke({
                "patient_id": patient.patient_id,
                "user_prompt": prompt,
                "chat_mode": chat_mode,
                "user_id": user_id,
                "session_id": session_id,
                "user_language": detected_language
            }, config=config)
        else:
            data = await self._compiled_graph.ainvoke({
                "user_prompt": prompt,
                "chat_mode": chat_mode,
                "user_id": user_id,
                "session_id": session_id,
                "user_language": detected_language
            }, config=config)

        if PERSISTENCE_ENABLED and session_id and user_id:
            await self._vec.update_session_activity(session_id=session_id, user_id=user_id)

        # Clear GPU memory after flow completes
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("Cleared GPU cache after LangGraph flow completion")
        except (ImportError, Exception) as e:
            logger.warning(f"Could not clear GPU cache: {e}")

        # Always return the same completion-shaped output as run_stream's final chunk
        if hasattr(data, "model_dump"):
            return self._to_output(data.model_dump())
        return self._to_output(data)

    def run_stream(self, patient: PatientContext | None = None, user_prompt: str | None = None, chat_mode: bool = False, diagnostic_mode: str = "info_retrieval", user_id: str | None = None, session_id: str | None = None, note_template: NoteTemplate | None = None, note_generation_id: str | None = None, note_context_prompt: str | None = None) -> AsyncGenerator[dict[str, Any], None]:
        """Return an async generator that yields chunks as they stream from the graph."""

        async def _stream_generator():
            # Derive is_note_generation_flow from note_template parameter
            is_note_generation_flow = note_template is not None

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

            # Detect language from user prompt for localized streaming messages
            try:
                from optimed.core.lang import detect_language_code
                detected_language = detect_language_code(prompt or "")
            except Exception:
                detected_language = "en"

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
                    "user_language": detected_language,
                    "should_stream_response": True,  # Indicate we want streaming
                    "stream_callback": stream_callback,  # Pass the callback
                    "is_note_generation_flow": is_note_generation_flow,
                    "note_template": note_template,
                    "note_generation_id": note_generation_id,
                    "note_context_prompt": note_context_prompt
                }
            else:
                initial_input = {
                    "user_prompt": prompt,
                    "chat_mode": chat_mode,
                    "info_retrieval_mode": diagnostic_mode if not chat_mode else "chat",
                    "user_id": user_id,
                    "session_id": session_id_final,
                    "user_language": detected_language,
                    "should_stream_response": True,  # Indicate we want streaming
                    "stream_callback": stream_callback,  # Pass the callback
                    "is_note_generation_flow": is_note_generation_flow,
                    "note_template": note_template,
                    "note_generation_id": note_generation_id,
                    "note_context_prompt": note_context_prompt
                }

            graph_task = None
            
            try:
                # Start the graph processing as a background task
                async def run_graph():
                    # Move these variables inside the function to avoid scope issues
                    previous_state = None
                    reasoning_emitted = set()  # Track which reasoning steps we've emitted
                    
                    # Increase recursion limit for long flows (general summary has ~35 steps)
                    config = {"recursion_limit": 50}
                    async for update in self._compiled_graph.astream(initial_input, config=config):
                        # Extract the current state from the update
                        for node_name, node_output in update.items():
                            if isinstance(node_output, dict):
                                current_state = node_output
                                
                                # Handle status updates (including progress within steps)
                                if (previous_state is None or
                                    current_state.get("current_step") != previous_state.get("current_step") or
                                    current_state.get("step_status") != previous_state.get("step_status") or
                                    current_state.get("step_details") != previous_state.get("step_details") or
                                    current_state.get("progress_percentage") != previous_state.get("progress_percentage")):

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

                    logger.info("🎯 Emitting completion event")
                    logger.info(f"📦 final_response length: {len(final_response_content)} chars")
                    if final_response_content:
                        try:
                            parsed = json.loads(final_response_content)
                            logger.info(f"📋 Response type: {parsed.get('type')}")
                            if parsed.get('type') == 'generated_note':
                                logger.info(f"✅ Note content length: {len(parsed.get('content', ''))} chars")
                        except Exception:
                            logger.info("⚠️ Response is not JSON")

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

                    # Include citations in completion
                    if previous_state and previous_state.get("citations"):
                        completion_update["citations"] = previous_state["citations"]
                        logger.info(f"🔖 Adding citations to completion event: {len(previous_state['citations'])} citations")
                        logger.info(f"🔖 Citation keys in completion: {list(previous_state['citations'].keys())}")
                    else:
                        logger.warning("🔖 No citations found in previous_state for completion event")
                    


                    logger.info("🚀 Putting completion event in queue")
                    await chunk_queue.put(completion_update)
                    logger.info("🏁 Putting end signal in queue")
                    await chunk_queue.put(None)  # Signal end of stream
                    logger.info("✅ Stream generation complete")
                
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

                # Clear GPU memory after streaming completes
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        logger.info("Cleared GPU cache after streaming flow completion")
                except (ImportError, Exception) as cleanup_error:
                    logger.warning(f"Could not clear GPU cache: {cleanup_error}")

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

        # Include citations if available
        if data.get("citations"):
            completion_update["citations"] = data.get("citations")
            logger.info(f"🔖 _to_output: Adding {len(data['citations'])} citations to completion")
        else:
            logger.warning("🔖 _to_output: No citations in data")

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

        result = {
            "explanation": data["llm_response"].content if data["llm_response"] else "",
            "created_by_user_id": data.get("user_id"),
            "is_ai_generated": True,
            "web_search_info": web_search_info,
            "cross_session_history_info": cross_session_info,
            "session_id": data.get("session_id"),
        }

        # Include citations if available
        if data.get("citations"):
            result["citations"] = data.get("citations")
            logger.info(f"🔖 chat_output: Adding {len(data['citations'])} citations to result")
        else:
            logger.warning("🔖 chat_output: No citations in data")

        return result
    

    @property
    def vector_store(self) -> VectorStore:
        """Access to the underlying vector store."""
        return self._vec

    
