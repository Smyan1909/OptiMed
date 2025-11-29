from __future__ import annotations
from .streaming_decorators import streaming_step
from .streaming_llm import StreamingLLMWrapper

import uuid
import json
import time
import math
import asyncio
import re
from typing import List, Any, Union, AsyncGenerator, Optional, Dict, Tuple
from datetime import datetime, timezone

from langgraph.types import Send
from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from optimed.core.domain import PatientContext, ChatMessage, DiagnosisResult, ChatRole, UserAction, User, WebSearchResponse, JournalEntry, Chunk, NoteTemplate
from optimed.core.domain.pdf_document import PDFDocument
from optimed.core.domain.xml_document import XMLDocument
from optimed.core.lang import detect_language_code
from optimed.core.streaming_messages import get_message

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
from optimed.utils.background_tasks import create_background_task
from optimed.utils.pdf_table_parser import PDFTableParser, ParsedTable

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
N_MAX: int = 30  # Increased from 25 for better coverage on general queries
MMR_LAMBDA: float = 0.5
GATE_THRESH: float = 0.5
RETRY_MAX: int = 2



def get_system_msg_info_relay() -> ChatMessage:
    """Generate the system message for information relay with current date."""
    current_date = datetime.now().strftime('%Y-%m-%d')
    return ChatMessage(role=ChatRole.SYSTEM,
                       content=f"""You are CLARA, a clinical information assistant.

**Current Date**: {current_date}

**IMPORTANT - NOT A MEDICAL DEVICE**:
You are NOT a doctor or a medical device. You cannot provide clinical advice, diagnostic conclusions, or treatment recommendations from your own knowledge. You can ONLY:
1. Paraphrase and summarize information retrieved from the patient's medical records (with citations)
2. Present information from trusted web sources (viss.nu, socialstyrelsen.se, 1177.se, vardhandboken.se, medical databases) for guidelines and general medical knowledge
3. Always state that the user should make their decisions independently and review the sources

The primary users of this service are doctors and nurses.

**RESPONSE STRUCTURE**:
- Keep answers concise - if one sentence suffices, use one sentence
- If more detail is needed, use `##` and `###` headers to organize sections
- Use bullet points (`-`) for lists, 10-15 words per bullet
- Each statement referencing patient data MUST include a citation

**TEMPORAL RELEVANCE**:
- Prioritize recent information but include historical data when relevant to the query
- Note the recency of information when clinically significant (e.g., "as of 2024-01-15")
- If old information is specifically relevant to the query, include it with clear date context

**FORMATTING**:
- Use **bold** for: diagnoses, medications, vital signs, lab values, symptoms, key clinical terms, key dates, or other key information
- Format URLs as clickable Markdown links: [Link Text](URL)
- For web sources: [Source Title](URL) immediately after the information
- Output valid GitHub-flavored Markdown

**STRUCTURED CHUNK INTERPRETATION**:
- JSON chunks represent tables from medical records (medications, vitals, lab results)
- Format: {{"item": "name", "attributes": {{...}}, "values": {{"date": "value"}}}}
- Value symbols: "---->" = same dose continues, "" = no value recorded, "?" = unclear, "X" = taken (medications)
- Numeric values are actual doses; "+" separates multiple doses (e.g., "1 + 1 + 1" = 3 doses/day, "500+500+500" = 3 doses of 500/day)

**CRITICAL**:
- Independent of the information you recieve your PRIMARY GOAL is to answer the user's question
- If you cannot answer the user's question, you should say so and suggest that the user should ask a different question
- Provide ONLY information that DIRECTLY answers the user's question and avoid providing information that is not directly related to the user's question.

**RESTRICTIONS**:
- Provide information and education only - NO diagnostic conclusions or treatment recommendations from your own knowledge
- Treatment/guideline information must come from web sources (viss.nu, socialstyrelsen.se, 1177.se, vardhandboken.se, or trusted medical databases)
- Refer all clinical decision-making to qualified healthcare providers
""")


# =========================
# Document-Specific System Prompts (Referrals & Medical Certificates)
# =========================

REFERRAL_SYSTEM_PROMPT = """You are generating a medical referral in telegram-style clinical note format.

SECTIONS (translate headers to user's language):
1. Diagnostic Question - ONE word or short phrase. The suspected diagnosis or question to answer.
2. Background - Brief relevant history. Age, relevant medical history, heredity if applicable.
3. Current Status - Current symptoms, findings, observations. Brief factual statements.
4. Functional Level - ONE sentence on how condition affects daily function/work/life.
5. Previous Interventions - What investigations/treatments already done. Results.
6. Assessment - ONE sentence with recommendation for further action.

STYLE - THIS IS CRITICAL:
- Write like clinical shorthand/notes, NOT prose
- Short factual statements separated by periods
- No connecting words like "and", "because", "therefore"
- No elaboration or interpretation
- Example: "45 year old male. Diabetes since 2015. Increasing chest pain 3 months. ECG normal. Stress test pending."

RULES:
- Write in SAME LANGUAGE as user's query
- PLAIN TEXT only
- NEVER include citations or references
- If information unavailable, omit that fact
"""

MEDICAL_CERTIFICATE_SYSTEM_PROMPT = """You are generating a medical certificate document.

SECTIONS (translate headers to user's language):
1. Certificate Purpose - What the certificate is for
2. Diagnosis - Diagnosis with ICD code, or main symptoms if unclear
3. Functional Impairment - Objective findings on impaired function, degree of impairment
4. Activity Limitation - What patient cannot do in relation to work (critical section)
5. Work Capacity - Sick leave percentage (100/75/50/25%), justify if full-time
6. Time Period - Start and end dates (no open-ended)
7. Prognosis and Plan - Expected recovery, planned treatments
8. Additional Information - Other relevant details

RULES:
- Write in SAME LANGUAGE as user's query
- PLAIN TEXT only - no markdown, no formatting
- Be CONCISE - 2-4 sentences per section
- NEVER include citations, references, or source markers
- Write clearly for non-medical readers
- Distinguish observations ("Upon examination...") from patient reports ("Patient states...")
- If information unavailable: "Information not available"
"""


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

    # Query classification fields
    query_classification: Optional[str] = None
    classification_query: Optional[str] = None  # Contextualized query for classification

    # Note generation flow fields
    is_note_generation_flow: bool = False
    note_template: Optional[Any] = None  # NoteTemplate object
    note_template_type_preference: Optional[str] = None  # For auto-selected templates
    note_generation_id: Optional[str] = None
    note_context_prompt: Optional[str] = None
    note_sections: Dict[str, str] = Field(default_factory=dict)
    note_final_content: Optional[str] = None
    note_sources: List[str] = Field(default_factory=list)

    # Document generation flow fields (referrals, medical certificates)
    is_document_generation_flow: bool = False
    document_type: Optional[str] = None  # "referral" or "medical_certificate"
    document_primary_focus: str = ""  # The main diagnostic question/topic - ALL sections must be relevant to this
    document_sections: List[Dict[str, Any]] = Field(default_factory=list)  # Model-determined sections with name/label/description
    document_section_chunks: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)  # Retrieved chunks per section

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

    def _parse_json_response_to_string(self, content: str) -> str:
        """
        Parse JSON-formatted assistant responses into human-readable strings.
        Used when loading chat history to convert structured responses (like generated notes)
        into readable text for conversation context.
        
        Args:
            content: The raw message content (possibly JSON)
            
        Returns:
            A human-readable string representation of the content
        """
        if not content or not content.strip():
            return content
            
        content = content.strip()
        
        # Check if it looks like a JSON response
        if not (content.startswith('{"type":') or content.startswith('{"error":')):
            return content
            
        try:
            json_data = json.loads(content)
            msg_type = json_data.get("type", "response")
            
            if msg_type == "generated_note":
                template_name = json_data.get("template_name", "document")
                note_content = json_data.get("content", "")
                # Extract a readable summary from the note content
                if note_content:
                    # Take first 500 chars to preserve context
                    summary = note_content[:500] + "..." if len(note_content) > 500 else note_content
                    return f"[Generated {template_name}]: {summary}"
                else:
                    return f"[Generated {template_name}]"
                    
            elif msg_type == "error":
                error_msg = json_data.get("message", "Unknown error")
                return f"[Error]: {error_msg}"
                
            else:
                # For other JSON types, provide a descriptive summary
                return f"[{msg_type} response]"
                
        except json.JSONDecodeError:
            # If JSON parsing fails, return the original content
            # but escape curly braces to prevent format specifier issues
            return content.replace("{", "{{").replace("}", "}}")

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
                f"DO NOT state this is in your response 'Information system only - NOT a medical device'"
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
            # Skip patient fetching if no patient_id is provided (general chat mode)
            if not state.patient_id:
                logger.info("No patient_id provided - skipping patient fetch (general chat mode)")
                state.patient_ctx = None
                state.journal_entries = []
                return state

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
                logger.info(f"Fetched {len(state.journal_entries)} journal entries for patient {sanitize_patient_id(state.patient_id) if state.patient_id else 'None'}")
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
                    patient_id=state.patient_id,
                    session_id=state.session_id
                )

                # Filter to only include ready documents (with or without text - OCR will be added later)
                # TODO: Add OCR support for image-based PDFs
                ready_pdfs = [
                    doc for doc in pdf_documents
                    if doc.status.value == "READY"
                ]

                state.uploaded_pdfs = ready_pdfs
                logger.info(f"Fetched {len(state.uploaded_pdfs)} ready PDF documents for session {state.session_id} (patient_id={sanitize_patient_id(state.patient_id) if state.patient_id else 'None'})")

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
                logger.info(f"Fetched {len(state.uploaded_xmls)} ready XML documents for session {state.session_id} (patient_id={sanitize_patient_id(state.patient_id) if state.patient_id else 'None'})")

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
            """Evaluate if web search is needed for medical information.
            
            Web search is triggered for queries about:
            - Treatment plans, protocols, and guidelines
            - Drug interactions, side effects, dosing
            - General medical knowledge not patient-specific
            - Clinical guidelines and best practices
            """
            try:

                chat_history_str = None
                if state.chat_history:
                    chat_history_str = [msg.content for msg in state.chat_history[-3:]]

                needs_search = await self._web_search.evaluate_search_need(
                    user_query=state.user_prompt,
                    patient_context=state.retrieved_chunks if state.retrieved_chunks else None,
                    chat_history=chat_history_str
                )

                state.web_search_performed = needs_search
                logger.info(f"Web search needed (service evaluation): {needs_search}")

            except Exception as e:
                log_error(logger, "web_search", e)
                state.web_search_performed = False

            return state

        @streaming_step("perform_web_search")
        async def perform_web_search(state: FlowState) -> FlowState:
            """Perform web search if needed using trusted medical sources.
            
            Combines results from:
            - viss.nu (Swedish clinical guidelines)
            - General trusted medical databases
            """
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
                
                # Search with combined intent (viss.nu + general medical sources)
                search_response = await self._web_search.search(
                    query=search_query,
                    max_results=10,  # Increased to get more sources
                    patient_context=state.retrieved_chunks if state.retrieved_chunks else None,  # No patient data sent to external APIs
                    search_intent="clinical_guideline",  # Prioritizes trusted sources
                    target_language=(active_lang if active_lang and active_lang != "en" else None)
                )
                
                state.web_search_response = search_response
                
                if state.stream_callback:
                    language = getattr(state, 'user_language', 'en')

                    description = get_message(
                        "perform_web_search",
                        "completed",
                        language
                    )

                    await state.stream_callback({
                        "type": "status",
                        "step": "perform_web_search",
                        "description": description,
                        "status": "completed",
                        "timestamp": datetime.now().isoformat(),
                        "count": len(state.web_search_response.results)
                    })
                # Also populate the legacy retrieved_web field for compatibility
                if search_response.results:
                    state.retrieved_web = [
                        f"Source: {result.title}\nURL: {result.url}\nContent: {result.snippet}"
                        for result in search_response.results  # Include more results
                    ]
                
                logger.info(f"Found {len(search_response.results)} results from trusted medical sources")
                
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
                                    
                                    # Parse JSON responses (like generated notes) to readable strings for assistant messages
                                    if role == ChatRole.ASSISTANT:
                                        original_len = len(content)
                                        content = self._parse_json_response_to_string(content)
                                        if len(content) != original_len:
                                            logger.info(f"📝 Parsed JSON response to readable format ({original_len} -> {len(content)} chars)")
                                    
                                    chat_messages.append(ChatMessage(role=role, content=content))
                                    logger.info(f"✅ Decrypted {role.value} message (length={len(content)} chars)")
                                except Exception as decrypt_error:
                                    logger.info(f"❌ Decryption failed for message {i+1}: {decrypt_error}")
                                    continue
                        else:
                            # Handle legacy unencrypted messages
                            role = ChatRole(item.get("role", "user"))
                            content = item.get("content", "")
                            
                            # Parse JSON responses (like generated notes) to readable strings for assistant messages
                            if role == ChatRole.ASSISTANT:
                                original_len = len(content)
                                content = self._parse_json_response_to_string(content)
                                if len(content) != original_len:
                                    logger.info(f"📝 Parsed JSON response to readable format ({original_len} -> {len(content)} chars)")
                            
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

            retrieval_start_time = time.time()

            # Note: We always do chunking and embedding, even for specialized flows
            # Specialized flows skip the retrieval logic at the end of this function

            # Log audit event: START retrieval
            if self._audit_repo and state.session_id:
                logger.info(f"[audit] Logging FETCH_CHUNKS_START for session {state.session_id}")
                create_background_task(
                    self._audit_repo.log_audit_event(
                        session_id=state.session_id,
                        action="FETCH_CHUNKS_START",
                        resource_type="chunk",
                        outcome="in_progress",
                        user_id=state.user_id
                    ),
                    "log_audit_event_fetch_start",
                    session_id=state.session_id,
                    user_id=state.user_id
                )
            else:
                if not self._audit_repo:
                    logger.warning("[audit] Audit repo is None - cannot log events")
                if not state.session_id:
                    logger.warning("[audit] Session ID is None - cannot log events")

            try:
                logger.info(f"Starting retrieval for patient_id: {sanitize_patient_id(state.patient_id) if state.patient_id else 'None'}")
                logger.info(f"User prompt length: {len(state.user_prompt)} chars")

                # 1) Chunking via ChunkingOrchestrator (policy-driven)
                # OPTIMIZATION: Chunk only once per session, not on every query
                # Use Presidio multilingual redactor with Swedish default for Sweden Central deployment
                patient_id_str = str(state.patient_id) if state.patient_id else ""

                # Check global cache for this session
                session_cache_key = state.session_id or "default_session"
                global _GLOBAL_CHUNK_CACHE

                if state.stream_callback:
                    language = getattr(state, 'user_language', 'en')

                    description = get_message(
                    "intelligent_retrieve_chunks",
                    "processing",
                    language
                )

                await state.stream_callback({
                                    "type": "status",
                                    "step": "intelligent_retrieve_chunks",
                                    "description": description,
                                    "status": "processing",
                                    "timestamp": datetime.now().isoformat()
                                })

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
                            "chunk_level": c.meta.get("chunk_level") if c.meta else "child",
                            "parent_chunk_id": c.meta.get("parent_chunk_id") if c.meta else None
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

                # 2) Separate parent and child chunks for hierarchical retrieval
                if needs_chunking and chunks:
                    # Separate parent and child chunks
                    parent_chunks_list = [c for c in chunks if c.get("metadata", {}).get("chunk_level") == "parent"]
                    child_chunks_list = [c for c in chunks if c.get("metadata", {}).get("chunk_level") == "child"]

                    # If no chunk_level metadata (backward compatibility), treat all as child chunks
                    if not parent_chunks_list and not child_chunks_list:
                        logger.info(f"No parent-child structure detected, treating all {len(chunks)} chunks as retrieval chunks")
                        child_chunks_list = chunks
                        parent_chunks_list = []

                    logger.info(f"Parent-child chunking: {len(parent_chunks_list)} parent chunks, {len(child_chunks_list)} child chunks")

                    # Embed ONLY child chunks (for precise retrieval)
                    logger.info(f"Embedding {len(child_chunks_list)} child chunks...")
                    child_chunk_texts = [c["content"] for c in child_chunks_list]
                    child_chunk_vecs = await self._embed_many(child_chunk_texts, mode="passage")
                    for i, vec in enumerate(child_chunk_vecs):
                        child_chunks_list[i]["embedding"] = vec
                    logger.info(f"Successfully embedded {len(child_chunk_vecs)} child chunks")

                    # Store parent chunks in lookup dict (no embeddings needed)
                    parent_chunks_dict = {}
                    for parent_chunk in parent_chunks_list:
                        parent_id = parent_chunk.get("chunk_id") or parent_chunk.get("id")
                        if parent_id:
                            parent_chunks_dict[parent_id] = parent_chunk

                    # Update chunks variable to only contain child chunks for retrieval
                    chunks = child_chunks_list

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

                    # Cache child chunks (for retrieval) + parent chunks (for context delivery)
                    cache_entry = {
                        "chunks": chunks,  # Child chunks with embeddings
                        "doc_signature": current_doc_signature,
                        "timestamp": time.time()
                    }

                    # Add parent chunks lookup if they exist
                    if parent_chunks_dict:
                        cache_entry["parent_chunks"] = parent_chunks_dict
                        logger.info(f"Cached {len(chunks)} child chunks + {len(parent_chunks_dict)} parent chunks for session {sanitize_session_id(session_cache_key)}")
                    else:
                        logger.info(f"Cached {len(chunks)} chunks for session {sanitize_session_id(session_cache_key)}")

                    _GLOBAL_CHUNK_CACHE[session_cache_key] = cache_entry
                elif not needs_chunking and cached_chunks:
                    # Use cached chunks from previous query
                    logger.info(f"Reusing {len(cached_chunks)} cached chunks (skipping chunking & embedding)")
                    chunks = cached_chunks
                    # Ensure cache_entry is available for parent chunk lookup later
                    if session_cache_key in _GLOBAL_CHUNK_CACHE:
                        cache_entry = _GLOBAL_CHUNK_CACHE[session_cache_key]
                    else:
                        cache_entry = None

                # SKIP RETRIEVAL FOR SPECIALIZED FLOWS (but keep the chunks in cache)
                # General Summary flow does per-component retrieval
                if state.is_general_summary_flow:
                    logger.info(f"Skipping global retrieval - General Summary flow detected")
                    logger.info(f"✅ Chunks cached ({len(chunks) if chunks else len(cached_chunks)} chunks) - components will perform independent retrieval")
                    return state
            
                if state.stream_callback:
                
                    language = getattr(state, 'user_language', 'en')

                    description = get_message(
                        "intelligent_retrieve_chunks",
                        "retrieval",
                        language
                    )

                    await state.stream_callback({
                                        "type": "status",
                                        "step": "intelligent_retrieve_chunks",
                                        "description": description,
                                        "status": "processing",
                                        "timestamp": datetime.now().isoformat()
                                    })
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

                # 8-9) Agentic evaluation and refinement
                logger.info(f"Selected {len(selected_indices)} chunks after MMR")

                # Build chunk list for evaluation
                selected_chunks_for_eval = [
                    {
                        "chunk_id": chunks[i].get("chunk_id", i),
                        "content": chunks[i].get("content", ""),
                        "metadata": chunks[i].get("metadata", {}),
                        "data_type": chunks[i].get("data_type", "unknown")
                    }
                    for i in selected_indices
                ]

                # Agentic evaluation (LLM decides if chunks are sufficient)
                try:
                    is_sufficient, reasoning = await self._evaluate_chunk_sufficiency(
                        query=state.user_prompt,
                        chunks=selected_chunks_for_eval,
                        scores=gate_scores,
                        classification=state.query_classification or "general",
                        attempt=state.retrieval_retry_attempts
                    )

                    logger.info(f"Agentic evaluation: sufficient={is_sufficient}")
                    logger.info(f"Reasoning: {reasoning}")

                    # If insufficient and haven't exceeded max retries, refine and retry
                    if not is_sufficient and state.retrieval_retry_attempts < RETRY_MAX:
                        logger.info(f"Insufficient chunks (attempt {state.retrieval_retry_attempts}/{RETRY_MAX})")
                        logger.info(f"Generating refined queries...")

                        # Generate refined queries with reasoning context
                        try:
                            refinements = await self._refine_queries(
                                query=state.user_prompt,
                                seen_passages=[c.get("content", "") for c in selected_chunks_for_eval],
                                insufficiency_reasoning=reasoning
                            )
                            logger.info(f"Generated {len(refinements)} refined queries: {refinements}")
                            state.refined_queries = [r for r in refinements if r][:2]
                        except Exception as e:
                            logger.warning(f"Refinement failed: {e}")
                            state.refined_queries = []

                        # Set flag for retry loop
                        state.needs_refinement = bool(state.refined_queries)
                        state.retrieval_retry_attempts += 1

                        if state.needs_refinement:
                            # Set partial state for streaming decorator to show progress
                            # Swap child chunks for parent chunks (same logic as main flow)
                            if session_cache_key in _GLOBAL_CHUNK_CACHE:
                                cache_entry = _GLOBAL_CHUNK_CACHE[session_cache_key]
                            parent_lookup = cache_entry.get("parent_chunks", {}) if cache_entry else {}
                            
                            state.retrieved_chunks = []
                            for i in selected_indices:
                                child_chunk = chunks[i]
                                child_metadata = child_chunk.get("metadata", {}) or {}
                                parent_chunk_id = child_metadata.get("parent_chunk_id")
                                
                                if parent_chunk_id and parent_lookup and parent_chunk_id in parent_lookup:
                                    parent_chunk = parent_lookup[parent_chunk_id]
                                    parent_metadata = parent_chunk.get("metadata", {}).copy() if parent_chunk.get("metadata") else {}
                                    parent_metadata["child_chunk_id"] = child_chunk.get("chunk_id") or child_chunk.get("id")
                                    parent_metadata["child_metadata"] = child_metadata
                                    state.retrieved_chunks.append({
                                        "chunk_id": parent_chunk.get("chunk_id") or parent_chunk.get("id"),
                                        "content": parent_chunk.get("content", ""),
                                        "metadata": parent_metadata
                                    })
                                else:
                                    state.retrieved_chunks.append({
                                        "chunk_id": child_chunk["chunk_id"],
                                        "content": child_chunk["content"],
                                        "metadata": child_chunk["metadata"]
                                    })

                            # Build citations from chunk metadata
                            if state.retrieved_chunks:
                                state.citations, state.chunk_id_to_number = self._build_citations_from_chunks(state.retrieved_chunks)

                            state.chunk_analysis = {
                                "method": "bi_cross_mmr_agentic_refining",
                                "dynamic_n": len(selected_indices),
                                "selected_chunks": [f"chunk_{i}" for i in selected_indices],
                                "total_chunks_processed": len(chunks),
                                "chunks_after_bi_encoder": len(initial_indices),
                                "chunks_after_cross_encoder": len(reranked),
                                "chunks_after_mmr": len(selected_indices),
                                "chunks_after_agentic_eval": len(selected_indices),
                                "refinement_attempt": state.retrieval_retry_attempts,
                                "refined_queries": state.refined_queries,
                                "insufficiency_reasoning": reasoning
                            }
                            state.retrieval_reasoning = f"Refining search (attempt {state.retrieval_retry_attempts}): {reasoning}"

                            logger.info(f"Setting up for retry with {len(state.refined_queries)} refined queries")
                            # Do not finalize retrieved_chunks yet; upstream conditional edge will loop
                            return state

                    # If sufficient or max retries reached, use current chunks
                    if state.retrieval_retry_attempts >= RETRY_MAX:
                        logger.info(f"Max refinement attempts reached ({RETRY_MAX}), using current chunks")

                except Exception as e:
                    logger.warning(f"Agentic evaluation failed: {e}, using current chunks")

                # Use all selected indices as final result
                final_selected = selected_indices

                if not final_selected:
                    logger.info("No chunks selected, using fallback selection")
                    fallback_n = min(max(N_MIN, 1), len(reranked))
                    final_selected = [idx for idx, _ in reranked[:fallback_n]]
                    logger.info(f"Fallback selected {len(final_selected)} chunks: {final_selected}")

                # Log final selected chunks (GDPR-safe)
                logger.info(f"Final selected chunks ({len(final_selected)}):")
                for i, idx in enumerate(final_selected):
                    chunk_type = chunks[idx]["data_type"]
                    chunk_length = len(cast(str, chunks[idx]["content"]))
                    logger.info(f"  {i+1}. Chunk {idx} ({chunk_type}): {chunk_length} chars")

                # Log data lineage: Embeddings → Retrieval (bi-encoder + cross-encoder + MMR + agentic evaluation)
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
                            "agentic_evaluation",
                            f"dynamic_n_selection_{len(final_selected)}"
                        ],
                        data_quality_score=min(1.0, max(0.0, quality_score))
                    )

                # Set state variables early so streaming decorator can access them
                # Ensure we have access to parent chunks from cache
                if session_cache_key in _GLOBAL_CHUNK_CACHE:
                    cache_entry = _GLOBAL_CHUNK_CACHE[session_cache_key]
                parent_lookup = cache_entry.get("parent_chunks", {}) if cache_entry else {}
                
                logger.info(f"🔑 Parent chunk lookup: {len(parent_lookup)} parent chunks available")
                
                state.retrieved_chunks = []
                swapped_count = 0
                for idx in final_selected:
                    child_chunk = chunks[idx]
                    child_metadata = child_chunk.get("metadata", {}) or {}
                    parent_chunk_id = child_metadata.get("parent_chunk_id")

                    if parent_chunk_id and parent_lookup and parent_chunk_id in parent_lookup:
                        parent_chunk = parent_lookup[parent_chunk_id]
                        parent_metadata = parent_chunk.get("metadata", {}).copy() if parent_chunk.get("metadata") else {}
                        parent_metadata["child_chunk_id"] = child_chunk.get("chunk_id") or child_chunk.get("id")
                        parent_metadata["child_metadata"] = child_metadata

                        state.retrieved_chunks.append({
                            "chunk_id": parent_chunk.get("chunk_id") or parent_chunk.get("id"),
                            "content": parent_chunk.get("content", ""),
                            "metadata": parent_metadata
                        })
                        swapped_count += 1
                    else:
                        if parent_chunk_id:
                            logger.warning(f"Parent chunk {parent_chunk_id} not found in lookup - using child chunk")
                        state.retrieved_chunks.append({
                            "chunk_id": child_chunk.get("chunk_id") or child_chunk.get("id"),
                            "content": child_chunk.get("content", ""),
                            "metadata": child_metadata
                        })
                
                logger.info(f"🔄 Parent-child swap: {swapped_count}/{len(final_selected)} chunks swapped to parents")

                # Build citations from chunk metadata with sequential numbers
                state.citations, state.chunk_id_to_number = self._build_citations_from_chunks(state.retrieved_chunks)
                logger.info(f"🔖 Built citations: {len(state.citations)} total")
                logger.info(f"🔖 Citation IDs: {list(state.citations.keys())}")
                if state.citations:
                    first_citation = list(state.citations.values())[0]
                    logger.info(f"🔖 First citation sample: {first_citation}")

                state.chunk_analysis = {
                    "method": "bi_cross_mmr_agentic",
                    "dynamic_n": len(final_selected),
                    "selected_chunks": [f"chunk_{i}" for i in final_selected],
                    "total_chunks_processed": len(chunks),
                    "chunks_after_bi_encoder": len(initial_indices),
                    "chunks_after_cross_encoder": len(reranked),
                    "chunks_after_mmr": len(selected_indices),
                    "chunks_after_agentic_eval": len(final_selected)
                }
                state.retrieval_reasoning = "Paraphrases + bi-encoder, cross-encoder rerank, MMR diversity, agentic evaluation"

                logger.info(f"Retrieval complete: {len(state.retrieved_chunks)} chunks selected")
                logger.info(f"Chunk analysis: {state.chunk_analysis}")

                # Log successful retrieval completion
                retrieval_duration_ms = int((time.time() - retrieval_start_time) * 1000)
                if self._audit_repo and state.session_id:
                    # Log audit event: COMPLETE retrieval
                    create_background_task(
                        self._audit_repo.log_audit_event(
                            session_id=state.session_id,
                            action="FETCH_CHUNKS_COMPLETE",
                            resource_type="chunk",
                            outcome="success",
                            latency_ms=retrieval_duration_ms,
                            user_id=state.user_id,
                            metadata={"chunks_retrieved": len(final_selected), "total_chunks": len(chunks)}
                        ),
                        "log_audit_event_fetch_complete",
                        session_id=state.session_id,
                        user_id=state.user_id
                    )

                    # Log performance metric: total retrieval time
                    create_background_task(
                        self._audit_repo.log_performance_metric(
                            metric_category="retrieval",
                            metric_name="total_retrieval_time",
                            value=float(retrieval_duration_ms),
                            unit="milliseconds",
                            session_id=state.session_id,
                            user_id=state.user_id,
                            processing_stage="intelligent_retrieve_chunks",
                            patient_context_size=len(final_selected)
                        ),
                        "log_performance_total_retrieval",
                        session_id=state.session_id,
                        user_id=state.user_id
                    )

                    # Log performance metric: chunks retrieved count
                    create_background_task(
                        self._audit_repo.log_performance_metric(
                            metric_category="retrieval",
                            metric_name="chunks_retrieved_count",
                            value=float(len(final_selected)),
                            unit="count",
                            session_id=state.session_id,
                            user_id=state.user_id,
                            processing_stage="intelligent_retrieve_chunks"
                        ),
                        "log_performance_chunk_count",
                        session_id=state.session_id,
                        user_id=state.user_id
                    )

                    # Log evidence sets for each selected chunk
                    question_id = str(uuid.uuid4())  # Unique ID for this query
                    for rank, idx in enumerate(final_selected, start=1):
                        chunk_dict: dict[str, Any] = chunks[idx]
                        chunk_preview = chunk_dict.get("content", "")[:200] if isinstance(chunk_dict.get("content"), str) else ""
                        rerank_score = next((score for r_idx, score in reranked if r_idx == idx), None)

                        create_background_task(
                            self._audit_repo.log_evidence_set(
                                session_id=state.session_id,
                                question_id=question_id,
                                rank=rank,
                                resource_type=chunk_dict.get("data_type", "chunk"),
                                resource_id=chunk_dict.get("chunk_id"),
                                rerank_score=rerank_score,
                                reason="cross_encoder_reranked_mmr_diversified",
                                chunk_text_preview=chunk_preview
                            ),
                            f"log_evidence_set_rank_{rank}",
                            session_id=state.session_id,
                            user_id=state.user_id
                        )

            except Exception as e:
                logger.info(f"Error: {e}")
                state.retrieved_chunks = []
                state.chunk_analysis = {"method": "error", "reason": str(e)}
                return state

            return state

        async def _retrieve_with_full_pipeline(
            self,
            state: FlowState,
            queries: List[str],
            context_label: str,
            topk_initial: int = 100,
            topk_rerank: int = 30,
            use_mmr: bool = True,
            use_agentic_refinement: bool = True,
            refinement_attempt: int = 0
        ) -> List[Dict[str, Any]]:
            """
            Core retrieval pipeline with full agentic algorithm.

            Stages:
            1. Get chunks from global cache (already chunked & embedded)
            2. Query paraphrasing
            3. Query embedding
            4. Bi-encoder scoring (cosine similarity)
            5. Cross-encoder reranking
            6. Dynamic-N selection
            7. MMR diversification
            8. Agentic evaluation (LLM decides sufficiency)
            9. Query refinement & retry (if insufficient)

            Args:
                state: Current flow state with cached chunks
                queries: Component-specific queries (e.g., ["current vital signs", "recent symptoms"])
                context_label: Label for logging (e.g., "sbar_situation")
                topk_initial: Number of chunks to select after bi-encoder (default: 100)
                topk_rerank: Number of chunks to rerank with cross-encoder (default: 30)
                use_mmr: Whether to apply MMR diversification (default: True)
                use_agentic_refinement: Whether to enable LLM evaluation and refinement (default: True)
                refinement_attempt: Current refinement iteration (internal, starts at 0)

            Returns:
                List of chunk dicts with content, metadata, embeddings
            """
            logger.info(f"[{context_label}] Starting full retrieval pipeline")
            logger.info(f"[{context_label}] Queries: {len(queries)} variants")

            if state.stream_callback:
                
                language = getattr(state, 'user_language', 'en')

                description = get_message(
                    "intelligent_retrieve_chunks",
                    "retrieval",
                    language
                )

                await state.stream_callback({
                                    "type": "status",
                                    "step": "intelligent_retrieve_chunks",
                                    "description": description,
                                    "status": "processing",
                                    "timestamp": datetime.now().isoformat()
                                })

            # 1) Get chunks from global cache
            session_cache_key = state.session_id or "default_session"
            global _GLOBAL_CHUNK_CACHE

            if session_cache_key not in _GLOBAL_CHUNK_CACHE:
                logger.warning(f"[{context_label}] No cached chunks found - cannot retrieve")
                return []

            cache_entry = _GLOBAL_CHUNK_CACHE[session_cache_key]
            chunks = cache_entry.get("chunks", [])

            if not chunks:
                logger.warning(f"[{context_label}] Empty chunk cache")
                return []

            logger.info(f"[{context_label}] Retrieved {len(chunks)} chunks from cache")

            # 2-3) Query paraphrasing + embedding
            logger.info(f"[{context_label}] Generating query variants...")
            try:
                # Generate paraphrases for the first query
                paraphrases = await self._paraphrase_query_variants(queries[0] if queries else "")
                logger.info(f"[{context_label}] Generated {len(paraphrases)} paraphrases")
            except Exception as e:
                logger.warning(f"[{context_label}] Failed to generate paraphrases: {e}")
                paraphrases = []

            # Combine original queries + paraphrases
            query_variants = queries + paraphrases[:2]  # Limit paraphrases
            logger.info(f"[{context_label}] Using {len(query_variants)} query variants total")

            # Embed all query variants
            query_vecs = await self._embed_many(query_variants, mode="query")
            logger.info(f"[{context_label}] Embedded {len(query_vecs)} query vectors")

            # 4) Bi-encoder scoring (max cosine similarity across all query variants)
            logger.info(f"[{context_label}] Computing bi-encoder scores for {len(chunks)} chunks...")

            def bi_score(vec: list[float]) -> float:
                return max(self._cosine(vec, qv) for qv in query_vecs)

            from typing import cast
            bi_scored = [(i, bi_score(cast(list[float], chunks[i]["embedding"]))) for i in range(len(chunks))]
            bi_scored.sort(key=lambda x: x[1], reverse=True)

            # Log top bi-encoder scores
            logger.info(f"[{context_label}] Top 5 bi-encoder scores:")
            for i, (idx, score) in enumerate(bi_scored[:5]):
                chunk_type = chunks[idx].get("data_type", "unknown")
                logger.info(f"  {i+1}. Chunk {idx} ({chunk_type}): {score:.4f}")

            if bi_scored:
                bi_scores = [score for _, score in bi_scored]
                logger.info(f"[{context_label}] Bi-encoder score range: [{min(bi_scores):.4f}, {max(bi_scores):.4f}]")

            # Select top-K for cross-encoder reranking
            initial_indices = [idx for idx, _ in bi_scored[:topk_initial]]
            logger.info(f"[{context_label}] Selected top {len(initial_indices)} chunks for cross-encoder")

            # 5-8) Cross-encoder operations (reranking, MMR, gating) - PARALLEL EXECUTION
            lang = detect_language_code(queries[0] if queries else "")
            logger.info(f"[{context_label}] Detected language: {lang}")
            logger.info(f"[{context_label}] Running parallel cross-encoder operations...")

            # Use the optimized parallel cross-encoder method
            reranked, selected_indices, gate_scores = await self._run_parallel_cross_encoder_operations(
                state, chunks, initial_indices, query_vecs
            )

            # 8-9) Agentic evaluation and refinement
            logger.info(f"[{context_label}] Selected {len(selected_indices)} chunks after MMR")

            # Build chunk list for evaluation
            selected_chunks = [
                {
                    "chunk_id": chunks[i].get("chunk_id", i),
                    "content": chunks[i].get("content", ""),
                    "metadata": chunks[i].get("metadata", {}),
                    "data_type": chunks[i].get("data_type", "unknown")
                }
                for i in selected_indices
            ]

            # 🔑 PARENT-CHILD SWAP: Replace child chunks with parent chunks for LLM evaluation
            # This provides richer context while maintaining precise retrieval
            parent_lookup = cache_entry.get("parent_chunks", {}) if cache_entry else {}
            if parent_lookup:
                selected_chunks_with_parents = []
                seen_parent_ids = set()  # Deduplicate parents (multiple children may share same parent)

                for child_chunk in selected_chunks:
                    parent_chunk_id = child_chunk.get("metadata", {}).get("parent_chunk_id")

                    if parent_chunk_id and parent_chunk_id in parent_lookup and parent_chunk_id not in seen_parent_ids:
                        # Swap child for parent
                        parent_chunk = parent_lookup[parent_chunk_id]
                        parent_dict = {
                            "chunk_id": parent_chunk.get("chunk_id") or parent_chunk.get("id"),
                            "content": parent_chunk.get("content", ""),
                            "metadata": parent_chunk.get("metadata", {}),
                            "data_type": parent_chunk.get("data_type", "unknown")
                        }
                        selected_chunks_with_parents.append(parent_dict)
                        seen_parent_ids.add(parent_chunk_id)
                    elif parent_chunk_id is None:
                        # No parent-child structure (backward compatibility), use child as-is
                        selected_chunks_with_parents.append(child_chunk)
                    # Skip if parent already added (deduplication)

                if selected_chunks_with_parents:
                    logger.info(f"[{context_label}] Swapped {len(selected_chunks)} child chunks → {len(selected_chunks_with_parents)} parent chunks for LLM evaluation")
                    selected_chunks = selected_chunks_with_parents
                else:
                    logger.info(f"[{context_label}] No parent chunks found, using {len(selected_chunks)} child chunks")
            else:
                logger.info(f"[{context_label}] No parent-child structure, using {len(selected_chunks)} chunks as-is")

            # Agentic evaluation (LLM decides if chunks are sufficient)
            if use_agentic_refinement:
                try:
                    is_sufficient, reasoning = await self._evaluate_chunk_sufficiency(
                        query=queries[0] if queries else "",
                        chunks=selected_chunks,
                        scores=gate_scores,
                        classification=context_label,
                        attempt=refinement_attempt
                    )

                    logger.info(f"[{context_label}] Agentic evaluation: sufficient={is_sufficient}")
                    logger.info(f"[{context_label}] Reasoning: {reasoning}")

                    # If insufficient and haven't exceeded max retries, refine and retry
                    if not is_sufficient and refinement_attempt < RETRY_MAX:
                        logger.info(f"[{context_label}] Insufficient chunks (attempt {refinement_attempt}/{RETRY_MAX})")
                        logger.info(f"[{context_label}] Generating refined queries...")

                        # Generate refined queries with reasoning context
                        refined_queries = await self._refine_queries(
                            query=queries[0] if queries else "",
                            seen_passages=[c.get("content", "") for c in selected_chunks],
                            insufficiency_reasoning=reasoning
                        )

                        if refined_queries:
                            logger.info(f"[{context_label}] Generated {len(refined_queries)} refined queries: {refined_queries}")
                            logger.info(f"[{context_label}] Retrying retrieval with refined queries...")

                            # Emit refinement status with reasoning (localized)
                            if state.stream_callback:
                                # Get language from state
                                language = getattr(state, 'user_language', 'en')

                                # Format localized message
                                description = get_message(
                                    "intelligent_retrieve_chunks",
                                    "refining_with_reason",
                                    language,
                                    reason=reasoning[:10],
                                    attempt=refinement_attempt + 1,
                                    max_attempts=RETRY_MAX
                                )

                                await state.stream_callback({
                                    "type": "status",
                                    "step": "intelligent_retrieve_chunks",
                                    "description": description,
                                    "status": "refining_with_reason",
                                    "timestamp": datetime.now().isoformat()
                                })

                            # Recursive retry with refined queries
                            return await _retrieve_with_full_pipeline(
                                self,
                                state=state,
                                queries=refined_queries,
                                context_label=context_label,
                                topk_initial=topk_initial,
                                topk_rerank=topk_rerank,
                                use_mmr=use_mmr,
                                use_agentic_refinement=use_agentic_refinement,
                                refinement_attempt=refinement_attempt + 1
                            )
                        else:
                            logger.warning(f"[{context_label}] Failed to generate refined queries, using current chunks")

                    # If sufficient or max retries reached
                    if refinement_attempt >= RETRY_MAX:
                        logger.info(f"[{context_label}] Max refinement attempts reached ({RETRY_MAX}), using current chunks")

                except Exception as e:
                    logger.warning(f"[{context_label}] Agentic evaluation failed: {e}, using current chunks")

            # Use all selected indices as final result
            final_selected = selected_indices

            # Prepare final chunk results
            result_chunks: list[dict[str, Any]] = []
            for i in final_selected:
                child_chunk = chunks[i]
                child_metadata = child_chunk.get("metadata", {}) or {}
                parent_chunk_id = child_metadata.get("parent_chunk_id")

                if parent_chunk_id and parent_lookup and parent_chunk_id in parent_lookup:
                    parent_chunk = parent_lookup[parent_chunk_id]
                    parent_metadata = parent_chunk.get("metadata", {}).copy() if parent_chunk.get("metadata") else {}
                    # Preserve linkage to the originating child chunk for auditing/citations
                    parent_metadata["child_chunk_id"] = child_chunk.get("chunk_id") or child_chunk.get("id")
                    parent_metadata["child_metadata"] = child_metadata

                    result_chunks.append({
                        "chunk_id": parent_chunk.get("chunk_id") or parent_chunk.get("id"),
                        "content": parent_chunk.get("content", ""),
                        "metadata": parent_metadata,
                        "embedding": child_chunk.get("embedding")
                    })
                else:
                    result_chunks.append({
                        "chunk_id": child_chunk.get("chunk_id") or child_chunk.get("id"),
                        "content": child_chunk.get("content", ""),
                        "metadata": child_metadata,
                        "embedding": child_chunk.get("embedding")
                    })

            logger.info(f"[{context_label}] Retrieval complete: {len(result_chunks)} chunks selected")
            logger.info(f"[{context_label}] Pipeline stats: {len(chunks)} total → {len(initial_indices)} bi-encoder → {len(reranked)} cross-encoder → {len(selected_indices)} MMR → {len(final_selected)} agentic-eval (attempt {refinement_attempt})")

            return result_chunks

        async def _generate_general_summary_queries(state: FlowState, component: str, focus_instruction: str) -> List[str]:
            """Generate focused queries for each general summary component based on the user's original query and chat history."""
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

                # Include chat history context for better query generation
                history_context = ""
                if state.chat_history:
                    recent = state.chat_history[-4:]  # Last 2 turns (2 user + 2 assistant)
                    if recent:
                        history_context = "\n\nRecent conversation context:\n"
                        for msg in recent:
                            # Truncate long messages
                            content_preview = msg.content[:150] if len(msg.content) > 150 else msg.content
                            history_context += f"{msg.role.value}: {content_preview}\n"

                prompt = f"""
Based on this user query: "{state.user_prompt}"{history_context}

Generate 3 specific search queries focused on the {component.upper()} component of a comprehensive patient summary.

{component.upper()} should focus on: {component_prompts.get(component, focus_instruction)}

Return only the 3 queries, one per line, without numbers or bullets.
Keep queries concise and medical terminology appropriate.
Consider what has already been discussed in the conversation to avoid redundancy.
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

            # Localized fallback text
            if is_swedish:
                unknown_type = "Okänd"
                unknown_date = "Datum okänt"
                no_summary = "Ingen sammanfattning"
            else:
                unknown_type = "Unknown"
                unknown_date = "Date unknown"
                no_summary = "No summary"

            lines = []

            if major:
                major_header = "**Större vårdtillfällen**\n" if is_swedish else "**Major Encounters**\n"
                lines.append(major_header)
                for enc in major:
                    # Format: • **Type** (date) - brief
                    lines.append(f"• **{enc.get('encounter_type', unknown_type)}** ({enc.get('date', unknown_date)}) - {enc.get('brief', no_summary)}\n")
                lines.append("")  # Blank line between sections

            if minor:
                minor_header = "**Mindre vårdtillfällen**\n" if is_swedish else "**Minor Encounters**\n"
                lines.append(minor_header)
                for enc in minor:
                    lines.append(f"• **{enc.get('encounter_type', unknown_type)}** ({enc.get('date', unknown_date)}) - {enc.get('brief', no_summary)}\n")

            return "\n".join(lines)

        # Note: SBAR, focused summary, and timeline helper functions removed
        # (These flows removed in favor of system-prompt-driven approach)

        @streaming_step("retrieve_snapshot_chunks")
        async def retrieve_snapshot_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on patient snapshot using full retrieval pipeline."""
            try:
                logger.info("Generating snapshot-focused queries from user prompt")

                snapshot_queries = await _generate_general_summary_queries(state, "snapshot",
                    "Generate queries focused on patient demographics, living situation, and chronic conditions")

                chunks = await _retrieve_with_full_pipeline(
                    self, state=state,
                    queries=snapshot_queries,
                    context_label="general_snapshot",
                    topk_initial=100,
                    topk_rerank=15,
                    use_mmr=True,
                    
                    use_agentic_refinement=True
                )
                state.general_snapshot_chunks = chunks
                logger.info(f"Retrieved {len(state.general_snapshot_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_snapshot_chunks = []

            return state

        @streaming_step("retrieve_problems_chunks")
        async def retrieve_problems_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on active problems using full retrieval pipeline."""
            try:
                logger.info("Generating problems-focused queries from user prompt")

                problems_queries = await _generate_general_summary_queries(state, "problems",
                    "Generate queries focused on active medical problems and chronic diseases")

                chunks = await _retrieve_with_full_pipeline(
                    self, state=state,
                    queries=problems_queries,
                    context_label="general_problems",
                    topk_initial=100,
                    topk_rerank=15,
                    use_mmr=True,
                    
                    use_agentic_refinement=True
                )
                state.general_problems_chunks = chunks
                logger.info(f"Retrieved {len(state.general_problems_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_problems_chunks = []

            return state

        @streaming_step("retrieve_medications_chunks")
        async def retrieve_medications_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on medications using full retrieval pipeline."""
            try:
                logger.info("Generating medications-focused queries from user prompt")

                medications_queries = await _generate_general_summary_queries(state, "medications",
                    "Generate queries focused on current medications and high-risk drugs")

                chunks = await _retrieve_with_full_pipeline(
                    self, state=state,
                    queries=medications_queries,
                    context_label="general_medications",
                    topk_initial=100,
                    topk_rerank=15,
                    use_mmr=True,
                    
                    use_agentic_refinement=True
                )
                state.general_medications_chunks = chunks
                logger.info(f"Retrieved {len(state.general_medications_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_medications_chunks = []

            return state

        @streaming_step("retrieve_trends_chunks")
        async def retrieve_trends_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on trends using full retrieval pipeline."""
            try:
                logger.info("Generating trends-focused queries from user prompt")

                trends_queries = await _generate_general_summary_queries(state, "trends",
                    "Generate queries focused on lab values and vital signs trends")

                chunks = await _retrieve_with_full_pipeline(
                    self, state=state,
                    queries=trends_queries,
                    context_label="general_trends",
                    topk_initial=100,
                    topk_rerank=15,
                    use_mmr=True,
                    
                    use_agentic_refinement=True
                )
                state.general_trends_chunks = chunks
                logger.info(f"Retrieved {len(state.general_trends_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_trends_chunks = []

            return state

        @streaming_step("retrieve_history_chunks")
        async def retrieve_history_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on medical history using full retrieval pipeline."""
            try:
                logger.info("Generating history-focused queries from user prompt")

                history_queries = await _generate_general_summary_queries(state, "history",
                    "Generate queries focused on major hospitalizations and surgeries")

                chunks = await _retrieve_with_full_pipeline(
                    self, state=state,
                    queries=history_queries,
                    context_label="general_history",
                    topk_initial=100,
                    topk_rerank=15,
                    use_mmr=True,
                    
                    use_agentic_refinement=True
                )
                state.general_history_chunks = chunks
                logger.info(f"Retrieved {len(state.general_history_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_history_chunks = []

            return state

        @streaming_step("retrieve_risks_chunks")
        async def retrieve_risks_chunks(state: FlowState) -> FlowState:
            """Retrieve chunks focused on risks using full retrieval pipeline."""
            try:
                logger.info("Generating risks-focused queries from user prompt")

                risks_queries = await _generate_general_summary_queries(state, "risks",
                    "Generate queries focused on allergies, fall risk, and clinical alerts")

                chunks = await _retrieve_with_full_pipeline(
                    self, state=state,
                    queries=risks_queries,
                    context_label="general_risks",
                    topk_initial=100,
                    topk_rerank=15,
                    use_mmr=True,
                    
                    use_agentic_refinement=True
                )
                state.general_risks_chunks = chunks
                logger.info(f"Retrieved {len(state.general_risks_chunks)} chunks")

            except Exception as e:
                logger.info(f"Error: {e}")
                state.general_risks_chunks = []

            return state


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
                    
                    # Create user action for metrics
                    user_action = UserAction(
                        action_id=str(uuid.uuid4()),
                        user_id=state.user_id,
                        action_type="chat_message",
                        resource_type="prompt",
                        resource_id=str(uuid.uuid4()),
                        description=f"User sent {state.query_classification} prompt",
                        metadata={
                            "prompt_category": state.query_classification,
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
                    logger.info(f"Stored encrypted GDPR-safe metrics: {state.query_classification} prompt from user {sanitize_user_id(state.user_id)}")
                
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

        # Note: SBAR generate functions removed (generate_sbar_situation, generate_sbar_background,
        # generate_sbar_assessment, generate_sbar_recommendation)
        # SBAR flow removed in favor of system-prompt-driven approach

        @streaming_step("generate_snapshot_summary")
        async def generate_snapshot_summary(state: FlowState) -> FlowState:
            """Generate Patient Snapshot component."""
            try:
                logger.info("Starting Snapshot generation")

                chunks = state.general_snapshot_chunks or []

                current_date = datetime.now().strftime('%Y-%m-%d')
                prompt = f"""
                Current date: {current_date}
                
                Create a concise Patient Snapshot with 5 bullet points with headers:

                USER QUERY: {state.user_prompt}

                CRITICAL: Translate ALL bold headers to the SAME language as the user's query.
                - If user asks in English, headers must be in English
                - If user asks in Swedish, headers must be in Swedish

                Format as 5 bullet points with the following categories (headers in target language):
                • **[Demographics]:** Age, sex
                • **[Living Situation]:** Living arrangement, occupation/status
                • **[Functional Status]:** Mobility and independence level
                • **[Social Support]:** Care situation
                • **[Lifestyle Factors]:** Smoking, alcohol, substance use, diet, exercise

                Example format:
                • **[Header in target language]:** **Key info** (recorded YYYY-MM-DD) [citation]

                ⚠️ **ANTI-HALLUCINATION RULES** ⚠️:
                - If NO information exists for a category, write in user's language:
                  * English: "Information not documented"
                  * Swedish: "Information ej dokumenterad"
                - DO NOT make up, infer, or assume ANY clinical data
                - ONLY use information explicitly stated in the provided chunks
                - If uncertain about a detail, omit it or write in user's language:
                  * English: "Not specified"
                  * Swedish: "Ej specificerat"

                MANDATORY:
                - TRANSLATE all bold headers to the target language
                - Each bullet must have a bold header followed by colon
                - Use **bold** markdown for important clinical terms, values, and key phrases
                - CRITICAL: Include date/time stamp in parentheses (YYYY-MM-DD or YYYY-MM-DD HH:MM) showing when the information was recorded
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                - Add blank line between each bullet point for readability
                CRITICAL: 5 bullet points with headers. 6-12 words each. Each bullet point one line. Include dates. Keep very concise and scannable. NO hallucinations.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA, a clinical information assistant. Answer in the same language as the user's query. Format output as markdown. Include citations [1] [2] after statements. ONLY use information from provided chunks - NO hallucinations. Information system only - NOT a medical device.")
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

                current_date = datetime.now().strftime('%Y-%m-%d')
                prompt = f"""
                Current date: {current_date}
                
                List the top 5-7 problems divided into two subsections - EXACTLY 6-12 words per bullet.

                USER QUERY: {state.user_prompt}

                Format with TWO subsections (most relevant and frequently mentioned at the top of each list).

                CRITICAL: The section headers MUST be translated to the SAME language as the user's query.
                - If user asks in English, use English headers ("Current Conditions" and "Previous Conditions")
                - If user asks in Swedish, use Swedish headers ("Aktuella tillstånd" and "Tidigare tillstånd")

                Structure:
                # [Header for current/active conditions in target language]
                • **Disease name** (year) - status with dates

                # [Header for previous/resolved conditions in target language]
                • **Disease name** (year) - status with dates

                Example format (6-12 words each):
                • **Disease** (diagnosed YYYY) **key value** status detail (date) [citation]

                Add blank line between each bullet point for readability.

                ⚠️ **ANTI-HALLUCINATION RULES** ⚠️:
                - If NO problems/conditions exist for a section, write in user's language:
                  * English: "No active problems documented" or "No previous conditions documented"
                  * Swedish: "Inga aktiva problem dokumenterade" or "Inga tidigare tillstånd dokumenterade"
                - DO NOT make up, infer, or assume ANY diagnoses or conditions
                - ONLY list problems explicitly documented in the provided chunks
                - DO NOT add problems based on symptoms or lab values alone - only documented diagnoses

                MANDATORY:
                - TRANSLATE section headers to the target language (current/active conditions vs previous/resolved conditions)
                - Divide into active/ongoing conditions and resolved/historical conditions
                - Sort by relevance and frequency - most mentioned/relevant at the top of each subsection
                - Use **bold** markdown for disease names and key values
                - CRITICAL: Include date/time stamp in parentheses (YYYY-MM-DD or YYYY-MM-DD HH:MM) showing when the information was recorded/updated
                - Each bullet MUST be between 6-12 words (excluding date and citation) - COUNT THEM
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                - DO NOT add hints or extra text after the problems list
                CRITICAL: 5-7 problems total across both subsections. 6-12 words each. Include dates. Blank lines between bullets. Very scannable. NO hallucinations or inferred diagnoses.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA, a clinical information assistant. Answer in the same language as the user's query. Format output as markdown. Include citations [1] [2] after statements. ONLY use information from provided chunks - NO hallucinations. Information system only - NOT a medical device."),
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

                current_date = datetime.now().strftime('%Y-%m-%d')
                prompt = f"""
                Current date: {current_date}
                
                List 5-7 most important/recent medications divided into two subsections - EXACTLY 6-12 words per bullet.

                USER QUERY: {state.user_prompt}

                Format with TWO subsections (most relevant at the top of each list).

                CRITICAL: The section headers MUST be translated to the SAME language as the user's query.
                - If user asks in English, use "Current Medications" and "Prior Medications"
                - If user asks in Swedish, use "Aktuella läkemedel" and "Tidigare läkemedel"

                Structure:
                # [Header for current/active medications in target language]
                • **Drug name dose** (started YYYY-MM-DD) - purpose
                • **Drug old→new** ↑ (increased YYYY-MM-DD) - reason for change
                • 🔺 **Drug dose** (dates) - purpose ALLERGY NOTED  ← Add 🔺 if patient has documented allergy
                • ⚠️ **High-risk drug dose** (dates) - purpose  ← Mark anticoagulants, opioids, insulin with ⚠️

                # [Header for prior/discontinued medications in target language]
                • **Drug dose** (started YYYY-MM-DD, stopped YYYY-MM-DD) - reason

                Example format (6-12 words each):
                • **Drug dose** (started date) - purpose **value** [citation]

                Add blank line between each bullet point for readability.

                ⚠️ **ANTI-HALLUCINATION RULES** ⚠️:
                - If NO medications exist for a section, write in user's language:
                  * English: "No medications documented" or "No prior medications documented"
                  * Swedish: "Inga läkemedel hittades vid denna sökning" or "Inga tidigare läkemedel hittades vid denna sökning"
                - DO NOT make up, infer, or assume ANY medications or doses
                - ONLY list medications explicitly documented in the provided chunks
                - DO NOT add medications based on conditions alone - only documented prescriptions
                - DO NOT assume dose changes unless explicitly stated in the chunks

                MANDATORY:
                - TRANSLATE section headers to the target language (current/active medications vs prior/discontinued medications)
                - Divide into active medications and discontinued medications (only if relevant to user query)
                - Sort by relevance - most relevant at the top of each subsection
                - Use **bold** markdown for drug names, doses, and key values
                - Show dose changes as **OldDose→NewDose** with ↑ (increase) or ↓ (decrease) arrows
                - Add 🔺 if patient has documented allergy to that medication (check allergy mentions in data)
                - CRITICAL: Include start date for all medications; include end date for discontinued medications
                - For dose changes, include the date of change and brief explanation
                - Each bullet MUST be between 6-12 words (excluding dates and citation) - COUNT THEM
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                - DO NOT add hints or extra text after the medications list
                CRITICAL: 5-7 most important meds total. 6-12 words each. Include dates. Blank lines between bullets. Prior medications only if relevant. Very scannable. NO hallucinations.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA, a clinical information assistant. Answer in the same language as the user's query. Format output as markdown. Include citations [1] [2] after statements. ONLY use information from provided chunks - NO hallucinations. Information system only - NOT a medical device."),
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

                current_date = datetime.now().strftime('%Y-%m-%d')
                prompt = f"""
                Current date: {current_date}
                
                Show 5-7 key lab/vital trends - EXACTLY 6-12 words per bullet. Use arrows: ↑ ↓ →

                USER QUERY: {state.user_prompt}

                Format (ONE line per value):
                • **Lab/Vital**: old (date) → **new** (date) (arrow) note [citation]

                Example format:
                • **HbA1c**: 62 (2023-07-10) → **68 mmol/mol** (2024-01-15) (↑) worsening control [1]
                • **eGFR**: 64 (2023-06-15) → **52** (2024-01-15 08:30) (↓) declining kidney function [2]
                • **Weight**: 98 (2023-12-01) → **96 kg** (2024-01-15 09:00) (↓) intentional loss [3]
                • **BP**: 135/80 (2023-11-10) → **145/85** (2024-01-15 09:00) (↑) target 140/90 [4]
                • **INR**: 2.8 (2024-01-08) → **2.5** (2024-01-15 09:00) (↓) now in range [5]

                Add blank line between each bullet point for readability.

                ⚠️ **ANTI-HALLUCINATION RULES** ⚠️:
                - If NO lab/vital trends exist, write in user's language:
                  * English: "No lab/vital trends documented"
                  * Swedish: "Inga lab/vitalparameter-trender dokumenterade"
                - DO NOT make up, infer, or assume ANY lab values or vital signs
                - ONLY list trends explicitly documented in the provided chunks
                - DO NOT fabricate dates, values, or trends
                - If only one value exists (no trend), list it as a single measurement, not a trend

                MANDATORY:
                - Use **bold** markdown for parameter names and current values
                - Include date/time stamps (YYYY-MM-DD or YYYY-MM-DD HH:MM) in parentheses for BOTH old and new values
                - Each bullet MUST be between 6-12 words (excluding dates and citation)
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                - DO NOT add any extra text, hints, or notes after the bullet points
                CRITICAL: 5-7 most important trends. 6-12 words each. Include dates for both values. Blank lines between bullets. Very scannable. NO hallucinations.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA, a clinical information assistant. Answer in the same language as the user's query. Format output as markdown. Include citations [1] [2] after statements. ONLY use information from provided chunks - NO hallucinations. Information system only - NOT a medical device."),
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

                current_date = datetime.now().strftime('%Y-%m-%d')
                prompt = f"""
Current date: {current_date}

Generate a JSON response with recent encounters. Classify each as MAJOR or MINOR, and provide both a brief one-liner and a detailed summary.

USER QUERY: {state.user_prompt}

CRITICAL: The "encounter_type" field MUST be translated to match the user's query language.
- If user asks in English → use "Hospitalization", "ER visit", "GP visit", etc.
- If user asks in Swedish → use "Slutenvård", "Akutbesök", "Vårdcentralbesök", etc.

Output VALID JSON with this exact structure:
{{
  "encounters": [
    {{
      "id": "enc-001",
      "date": "YYYY-MM-DD HH:MM",
      "encounter_type": "[Encounter type in user's language]",
      "category": "major",
      "brief": "One-line summary (10-15 words) with citations [1] [2]",
      "detailed": "Detailed summary (30-80 words) with presenting complaint, key findings, interventions, medications, outcome. Use **bold** for clinical terms. Citations [1] [2]"
    }}
  ]
}}

CATEGORIES:
- MAJOR: Hospitalizations, ER visits, surgeries, ICU stays, specialist procedures, significant imaging
- MINOR: GP visits, phone consults, lab draws, routine follow-ups, medication refills, minor procedures

⚠️ **ANTI-HALLUCINATION RULES** ⚠️:
- If NO encounters exist in the chunks, output: {{"encounters": []}}
- DO NOT make up, infer, or assume ANY encounter information
- ONLY include encounters explicitly documented in the provided chunks
- DO NOT fabricate dates, encounter types, or clinical details
- If encounter details are unclear, DO NOT include that encounter

MANDATORY:
- TRANSLATE the encounter_type field to match the user's query language
- Include 5-7 most recent encounters (newest first)
- Brief: 10-15 words maximum, for display in the card
- Detailed: 30-80 words with full clinical context for popup modal
- Include citations [1] [2] etc in BOTH brief and detailed fields
- Use **bold** markdown in detailed summaries for clinical terms
- Include exact date/time when available (YYYY-MM-DD HH:MM format)
- Each encounter must have a unique id
CRITICAL: Output ONLY valid JSON. Translate encounter_type to user's language. NO hallucinations - only documented encounters.
"""

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA, a clinical information assistant. Answer in the same language as the user's query. Format output as markdown. Include citations [1] [2] after statements. ONLY use information from provided chunks - NO hallucinations. Information system only - NOT a medical device.")
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

                    # Ensure we have valid encounters data
                    if not state.general_encounters_structured:
                        logger.info("LLM returned empty encounters list")
                        state.general_history_result = "Inga senaste vårdtillfällen dokumenterade" if is_swedish else "No recent encounters documented"
                    else:
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
                    state.general_history_result = "Inga senaste vårdtillfällen dokumenterade" if is_swedish else "No recent encounters documented"
                    state.general_encounters_structured = []
                    state.general_history_cited_ids = []

            except Exception as e:
                logger.error(f"Error generating encounters: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                state.general_history_result = "Inga senaste vårdtillfällen dokumenterade" if is_swedish else "No recent encounters documented"
                state.general_encounters_structured = []

            return state

        @streaming_step("generate_risks_summary")
        async def generate_risks_summary(state: FlowState) -> FlowState:
            """Generate Red Flags / Alerts component."""
            try:
                logger.info("Starting Risks/Alerts generation")

                chunks = state.general_risks_chunks or []

                current_date = datetime.now().strftime('%Y-%m-%d')
                prompt = f"""
                Current date: {current_date}
                
                List 5-7 critical RISKS/ALERTS - EXACTLY 8-15 words per bullet. Each risk must be a specific safety concern, NOT a patient description.

                USER QUERY: {state.user_prompt}

                Format (Use colon to separate risk from reason):
                • ⚠️ **Risk name**: Explanation of why this is dangerous (documented date) [citation]

                Example format:
                • ⚠️ **Fall risk**: Three documented falls, uses walker, impaired mobility (assessed 2024-01-10) [3]
                • ⚠️ **Penicillin allergy**: History of rash and angioedema, avoid beta-lactams (documented 2015-03-20) [1]
                • ⚠️ **Lives alone**: No caregiver support, safety concerns for discharge (noted 2024-01-05) [6]
                • ⚠️ **DNR order**: Do not resuscitate, comfort care only (established 2024-01-12) [2]

                Add blank line between each bullet point for readability.

                ⚠️ **ANTI-HALLUCINATION RULES** ⚠️:
                - If NO risks/alerts exist, write in user's language:
                  * English: "No critical risks/alerts documented"
                  * Swedish: "Inga kritiska risker/varningar dokumenterade"
                - DO NOT make up, infer, or assume ANY risks
                - ONLY list risks explicitly documented in chunks
                - DO NOT add risks based on conditions alone - only documented SAFETY CONCERNS
                - DO NOT write patient descriptions like "Patient is 87-year-old female with..." - this is NOT a risk

                MANDATORY:
                - TRANSLATE the risk name (before colon) to match the user's query language
                - Use format: **Risk**: Reason (with colon separating risk from explanation)
                - Use **bold** markdown for the risk name only (before the colon)
                - Each bullet MUST be between 8-15 words (excluding citation)
                - Include date/time stamp in parentheses (YYYY-MM-DD or YYYY-MM-DD HH:MM) showing when documented
                - Include citations after each statement - DO NOT use verbose citations like "According to..." or "from EHR..."
                - DO NOT add hints or extra text after the risks list
                CRITICAL: 5-7 most important alerts. 8-15 words each. Include dates. Blank lines between bullets. TRANSLATE risk names to user's language. NO hallucinations.
                """

                messages = [
                    self._get_language_policy_message(state),
                    ChatMessage(role=ChatRole.SYSTEM, content="You are CLARA, a clinical information assistant. Answer in the same language as the user's query. Format output as markdown. Include citations [1] [2] after statements. ONLY use information from provided chunks - NO hallucinations. Information system only - NOT a medical device."),
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

        # Note: SBAR merge and dispatcher functions removed (merge_sbar_results, sbar_parallel_dispatcher)
        # SBAR flow removed in favor of system-prompt-driven approach

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

                # Language-aware titles and fallback messages
                is_swedish = state.user_language == "sv"
                fallback_failed = "Innehållsgenerering misslyckades" if is_swedish else "Content generation failed"
                fallback_encounters = "Inga vårdtillfällen dokumenterade" if is_swedish else "No encounters documented"

                structured_summary = {
                    "type": "general_summary_cards",
                    "context": conversation_context,
                    "citations": filtered_citations,
                    "components": {
                        "snapshot": {
                            "title": "Patientöversikt" if is_swedish else "Patient Snapshot",
                            "content": (general_results.get("snapshot") or fallback_failed).strip() or fallback_failed,
                            "icon": "user",
                            "color": "blue"
                        },
                        "problems": {
                            "title": "Tidigare och Nuvarande Sjukdomar" if is_swedish else "Active Problems",
                            "content": (general_results.get("problems") or fallback_failed).strip() or fallback_failed,
                            "icon": "alert-circle",
                            "color": "red"
                        },
                        "medications": {
                            "title": "Läkemedel" if is_swedish else "Medications",
                            "content": (general_results.get("medications") or fallback_failed).strip() or fallback_failed,
                            "icon": "pill",
                            "color": "purple"
                        },
                        "trends": {
                            "title": "Lab- & vitaltrender" if is_swedish else "Lab & Vital Trends",
                            "content": (general_results.get("trends") or fallback_failed).strip() or fallback_failed,
                            "icon": "trending-up",
                            "color": "green"
                        },
                        "encounters": {
                            "title": "Senaste vårdtillfällen" if is_swedish else "Recent Encounters",
                            "content": (general_results.get("encounters") or fallback_encounters).strip() or fallback_encounters,
                            "structured_data": state.general_encounters_structured or [],
                            "icon": "file-text",
                            "color": "indigo"
                        },
                        "risks": {
                            "title": "Risker & varningar" if is_swedish else "Risks & Alerts",
                            "content": (general_results.get("risks") or fallback_failed).strip() or fallback_failed,
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
                # Fallback response with language-aware titles
                import json
                is_swedish = state.user_language == "sv"
                fallback_summary = {
                    "type": "general_summary_cards",
                    "error": str(e),
                    "components": {
                        "snapshot": {"title": "Patientöversikt" if is_swedish else "Patient Snapshot", "content": "Error generating content", "icon": "user", "color": "blue"},
                        "problems": {"title": "Aktiva problem" if is_swedish else "Active Problems", "content": "Error generating content", "icon": "alert-circle", "color": "red"},
                        "medications": {"title": "Läkemedel" if is_swedish else "Medications", "content": "Error generating content", "icon": "pill", "color": "purple"},
                        "trends": {"title": "Lab- & vitaltrender" if is_swedish else "Lab & Vital Trends", "content": "Error generating content", "icon": "trending-up", "color": "green"},
                        "encounters": {"title": "Senaste vårdtillfällen" if is_swedish else "Recent Encounters", "content": "Error generating content", "structured_data": [], "icon": "file-text", "color": "indigo"},
                        "risks": {"title": "Risker & varningar" if is_swedish else "Risks & Alerts", "content": "Error generating content", "icon": "alert-triangle", "color": "yellow"}
                    }
                }
                state.llm_response = ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=json.dumps(fallback_summary, indent=2)
                )

            return state

        @streaming_step("general_summary_parallel_dispatcher")
        async def general_summary_parallel_dispatcher(state: FlowState) -> FlowState:
            """Execute parallel general summary component retrieval using asyncio.gather."""
            try:
                logger.info("Initiating parallel general summary retrieval for 6 components using asyncio.gather")

                # Initialize general summary cache if needed
                if not state.general_retrieval_cache:
                    state.general_retrieval_cache = {}

                # Disable refinement for summary flows (they use their own retrieval)
                state.needs_refinement = False

                # Generate queries for all components IN PARALLEL
                logger.info("Generating queries for all 6 components in parallel")
                query_results = await asyncio.gather(
                    _generate_general_summary_queries(state, "snapshot",
                        "Generate queries focused on patient demographics, living situation, and chronic conditions"),
                    _generate_general_summary_queries(state, "problems",
                        "Generate queries focused on active diagnoses and health concerns"),
                    _generate_general_summary_queries(state, "medications",
                        "Generate queries focused on current medications and recent prescriptions"),
                    _generate_general_summary_queries(state, "trends",
                        "Generate queries focused on lab values and vital signs trends"),
                    _generate_general_summary_queries(state, "history",
                        "Generate queries focused on recent care visits and hospitalizations"),
                    _generate_general_summary_queries(state, "risks",
                        "Generate queries focused on allergies, fall risk, and clinical alerts"),
                    return_exceptions=True
                )

                # Unpack query results
                snapshot_queries, problems_queries, medications_queries, trends_queries, history_queries, risks_queries = query_results
                logger.info("All queries generated in parallel, starting retrievals")

                # Execute all retrievals in parallel using asyncio.gather
                results = await asyncio.gather(
                    _retrieve_with_full_pipeline(
                        self, state=state, queries=snapshot_queries, context_label="general_snapshot",
                        topk_initial=100, topk_rerank=15, use_mmr=True,  use_agentic_refinement=True
                    ),
                    _retrieve_with_full_pipeline(
                        self, state=state, queries=problems_queries, context_label="general_problems",
                        topk_initial=100, topk_rerank=15, use_mmr=True,  use_agentic_refinement=True
                    ),
                    _retrieve_with_full_pipeline(
                        self, state=state, queries=medications_queries, context_label="general_medications",
                        topk_initial=100, topk_rerank=15, use_mmr=True,  use_agentic_refinement=True
                    ),
                    _retrieve_with_full_pipeline(
                        self, state=state, queries=trends_queries, context_label="general_trends",
                        topk_initial=100, topk_rerank=15, use_mmr=True,  use_agentic_refinement=True
                    ),
                    _retrieve_with_full_pipeline(
                        self, state=state, queries=history_queries, context_label="general_history",
                        topk_initial=100, topk_rerank=15, use_mmr=True,  use_agentic_refinement=True
                    ),
                    _retrieve_with_full_pipeline(
                        self, state=state, queries=risks_queries, context_label="general_risks",
                        topk_initial=100, topk_rerank=15, use_mmr=True,  use_agentic_refinement=True
                    ),
                    return_exceptions=True
                )

                # Assign results to state fields
                component_names = ["snapshot", "problems", "medications", "trends", "history", "risks"]
                for component_name, chunks in zip(component_names, results):
                    if isinstance(chunks, Exception):
                        logger.error(f"Error retrieving {component_name}: {chunks}")
                        chunks = []

                    if component_name == "snapshot":
                        state.general_snapshot_chunks = chunks
                    elif component_name == "problems":
                        state.general_problems_chunks = chunks
                    elif component_name == "medications":
                        state.general_medications_chunks = chunks
                    elif component_name == "trends":
                        state.general_trends_chunks = chunks
                    elif component_name == "history":
                        state.general_history_chunks = chunks
                    elif component_name == "risks":
                        state.general_risks_chunks = chunks

                    logger.info(f"Retrieved {len(chunks)} chunks for {component_name}")

                logger.info("All 6 parallel retrievals completed successfully")

                # Build citations from all retrieved chunks
                all_chunks = []
                for chunks in [state.general_snapshot_chunks, state.general_problems_chunks,
                               state.general_medications_chunks, state.general_trends_chunks,
                               state.general_history_chunks, state.general_risks_chunks]:
                    if chunks:
                        all_chunks.extend(chunks)

                if all_chunks:
                    state.citations, state.chunk_id_to_number = self._build_citations_from_chunks(all_chunks)
                    logger.info(f"🔖 Built {len(state.citations)} citations from {len(all_chunks)} total chunks")
                else:
                    state.citations = {}
                    state.chunk_id_to_number = {}
                    logger.warning("No chunks retrieved - citations will be empty")

                # Now generate all 6 components in parallel using the retrieved chunks
                logger.info("Starting parallel generation for 6 components")

                generation_results = await asyncio.gather(
                    # Generate snapshot
                    generate_snapshot_summary(state),
                    # Generate problems
                    generate_problems_summary(state),
                    # Generate medications
                    generate_medications_summary(state),
                    # Generate trends
                    generate_trends_summary(state),
                    # Generate history/encounters
                    generate_history_summary(state),
                    # Generate risks
                    generate_risks_summary(state),
                    return_exceptions=True
                )

                # Check for errors in generation
                for i, result in enumerate(generation_results):
                    if isinstance(result, Exception):
                        component_names = ["snapshot", "problems", "medications", "trends", "history", "risks"]
                        logger.error(f"Error generating {component_names[i]}: {result}")

                logger.info("All 6 parallel generations completed successfully")
                return state

            except Exception as e:
                log_error(logger, "general_summary_parallel_dispatcher", e)
                # Set empty chunks on error
                state.general_snapshot_chunks = []
                state.general_problems_chunks = []
                state.general_medications_chunks = []
                state.general_trends_chunks = []
                state.general_history_chunks = []
                state.general_risks_chunks = []
                return state

        # Note: Focused summary flow nodes removed (focused_summary_parallel_dispatcher, identify_aspect_and_retrieve,
        # retrieve_focused_*_chunks, generate_*_section, merge_focused_summary_results)
        # Focused summary flow removed in favor of system-prompt-driven approach

        # ==================== FOCUSED SUMMARY REMOVED ====================
        # Note: All focused summary functions have been removed
        # (focused_summary_parallel_dispatcher, identify_aspect_and_retrieve, 
        # retrieve_focused_*_chunks, generate_*_section, merge_focused_summary_results)
        # All orphaned code removed - continuing to timeline flow
        # Note: Timeline flow nodes removed (now uses default provide_information flow)

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
                current_date = datetime.now().strftime('%Y-%m-%d')
                note_system_prompt = f"""You are a medical documentation assistant generating a clinical note in {lang_name}.

Current Date: {current_date}

Template: {template.name}
Type: {template.template_type.value}

Your task is to fill in the template sections based on the provided clinical information.

CRITICAL LANGUAGE POLICY:
- TRANSLATE ALL content to {lang_name} - section titles, headers, medical terms, and all text
- Use medical terminology appropriate for {lang_name}
- If information is not available for a section, write "Information not available" in {lang_name}
- Do NOT mix languages - everything must be in {lang_name}

CRITICAL GUIDELINES:
- Be CONCISE and FOCUSED - include only essential clinical information
- Use **bold** markdown to highlight important clinical terms, diagnoses, medications, vital signs, and key findings
- Do NOT include source references, citations, or document names (write directly from the information)
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

        # ==================== DOCUMENT GENERATION FLOW NODES (Referrals & Medical Certificates) ====================

        @streaming_step("determine_document_sections")
        async def determine_document_sections(state: FlowState) -> FlowState:
            """
            Use LLM to determine appropriate sections/headers for the document based on:
            - Document type (referral or medical_certificate)
            - User's query/context
            - Document-specific system prompt requirements
            
            IMPORTANT: First extracts the PRIMARY FOCUS (diagnostic question/main topic) to ensure
            all subsequent sections retrieve only information relevant to that specific topic.
            """
            try:
                logger.info(f"📋 Determining sections for document type: {state.document_type}")

                # Get the appropriate system prompt
                if state.document_type == "referral":
                    doc_system_prompt = REFERRAL_SYSTEM_PROMPT
                    doc_type_name = "Referral (Remiss)"
                    doc_type_display = "referral" if state.user_language != "sv" else "remiss"
                elif state.document_type == "medical_certificate":
                    doc_system_prompt = MEDICAL_CERTIFICATE_SYSTEM_PROMPT
                    doc_type_name = "Medical Certificate (Läkarintyg)"
                    doc_type_display = "medical certificate" if state.user_language != "sv" else "läkarintyg"
                else:
                    logger.warning(f"Unknown document type: {state.document_type}, defaulting to referral")
                    doc_system_prompt = REFERRAL_SYSTEM_PROMPT
                    doc_type_name = "Referral (Remiss)"
                    doc_type_display = "referral"

                # Emit starting status
                if hasattr(state, 'stream_callback') and state.stream_callback:
                    language = getattr(state, 'user_language', 'en')
                    description = get_message(
                        "determine_document_sections",
                        "starting",
                        language,
                        document_type=doc_type_display
                    )
                    await state.stream_callback({
                        "type": "status",
                        "step": "determine_document_sections",
                        "description": description,
                        "status": "in_progress",
                        "progress": state.progress_percentage,
                        "timestamp": datetime.now().isoformat()
                    })

                # Detect language
                lang_code = detect_language_code(state.user_prompt)
                lang_name = "Swedish" if lang_code == "sv" else "English"

                # ===== STEP 1: Extract PRIMARY FOCUS (diagnostic question/main topic) =====
                # This is CRITICAL - all sections must be focused on this specific topic
                focus_prompt = f"""Analyze this request for a medical {doc_type_name}:

User's Request: "{state.user_prompt}"

Extract the PRIMARY DIAGNOSTIC FOCUS - the single main condition, diagnosis, or health issue this document is about.

Examples:
- "Write a referral for depression evaluation" -> "depression"
- "I need a certificate for the patient's back pain and inability to work" -> "back pain / lumbar issues"
- "Referral to dermatologist for psoriasis" -> "psoriasis"
- "Medical certificate for patient's anxiety disorder" -> "anxiety disorder"

Return ONLY the primary focus as a short phrase (1-5 words). No explanation."""

                from optimed.core.domain import ChatMessage, ChatRole
                focus_messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content="Extract the primary medical focus from the request. Return only a short phrase."),
                    ChatMessage(role=ChatRole.USER, content=focus_prompt)
                ]

                focus_response = await self._llm.chat(focus_messages)
                state.document_primary_focus = focus_response.content.strip().strip('"').strip("'")
                logger.info(f"🎯 Primary document focus: '{state.document_primary_focus}'")

                # ===== STEP 2: Determine sections =====
                # Build prompt to determine sections
                section_prompt = f"""Based on the user's request and the document requirements, determine the appropriate sections for this {doc_type_name}.

PRIMARY FOCUS: {state.document_primary_focus}
(ALL sections must be focused ONLY on information relevant to: {state.document_primary_focus})

User's Request: "{state.user_prompt}"

Document Requirements:
{doc_system_prompt}

Your task is to analyze the user's request and determine which sections are most appropriate for this specific document. 
Consider what information would be relevant based on the request context.

Return a JSON array of section objects with the following structure:
[
    {{"name": "section_key", "label": "Section Title in {lang_name}", "description": "Brief description of what this section should contain"}}
]

IMPORTANT:
- Use {lang_name} for the section labels
- Include 5-10 sections that are most relevant for this specific request
- Section names should be snake_case (e.g., "patient_info", "current_symptoms")
- Order sections logically for the document type

Return ONLY the JSON array, no additional text."""

                # Call LLM to determine sections
                from optimed.core.domain import ChatMessage, ChatRole
                messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content="You are a medical documentation specialist. Analyze the request and return a JSON array of appropriate document sections."),
                    ChatMessage(role=ChatRole.USER, content=section_prompt)
                ]

                response = await self._llm.chat(messages)
                response_text = response.content.strip()

                # Parse JSON response
                # Try to extract JSON from the response
                try:
                    # Handle markdown code blocks
                    if "```json" in response_text:
                        response_text = response_text.split("```json")[1].split("```")[0].strip()
                    elif "```" in response_text:
                        response_text = response_text.split("```")[1].split("```")[0].strip()
                    
                    sections = json.loads(response_text)
                    
                    if not isinstance(sections, list):
                        raise ValueError("Response is not a list")
                    
                    state.document_sections = sections
                    logger.info(f"✓ Determined {len(sections)} sections for {state.document_type}")
                    
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse sections JSON: {e}, using default sections")
                    # Fallback to default sections based on document type
                    if state.document_type == "referral":
                        state.document_sections = [
                            {"name": "fragestallning", "label": "Frågeställning" if lang_code == "sv" else "Diagnostic Question", "description": "ONE word or short phrase - suspected diagnosis or question"},
                            {"name": "bakgrund", "label": "Bakgrund" if lang_code == "sv" else "Background", "description": "Age, relevant medical history, heredity if applicable"},
                            {"name": "aktuellt", "label": "Aktuellt" if lang_code == "sv" else "Current Status", "description": "Current symptoms, findings, observations as brief facts"},
                            {"name": "funktionsniva", "label": "Funktionsnivå" if lang_code == "sv" else "Functional Level", "description": "ONE sentence on how condition affects daily function"},
                            {"name": "tidigare_insatser", "label": "Tidigare behandlingsinsatser" if lang_code == "sv" else "Previous Interventions", "description": "What investigations/treatments done and results"},
                            {"name": "bedomning", "label": "Bedömning" if lang_code == "sv" else "Assessment", "description": "ONE sentence recommendation"},
                        ]
                    else:  # medical_certificate
                        state.document_sections = [
                            {"name": "syfte", "label": "Intygets syfte" if lang_code == "sv" else "Certificate Purpose", "description": "Purpose of the certificate"},
                            {"name": "diagnosis", "label": "Diagnos" if lang_code == "sv" else "Diagnosis", "description": "Diagnosis with ICD code"},
                            {"name": "functional_impairment", "label": "Funktionsnedsättning" if lang_code == "sv" else "Functional Impairment", "description": "Objective findings on impaired function"},
                            {"name": "activity_limitation", "label": "Aktivitetsbegränsning" if lang_code == "sv" else "Activity Limitation", "description": "Concrete limitations in work tasks"},
                            {"name": "work_capacity", "label": "Arbetsförmåga" if lang_code == "sv" else "Work Capacity", "description": "Assessment of work capacity percentage"},
                            {"name": "time_period", "label": "Tidsperiod" if lang_code == "sv" else "Time Period", "description": "Certificate start and end dates"},
                            {"name": "prognosis", "label": "Prognos och plan" if lang_code == "sv" else "Prognosis and Plan", "description": "Expected recovery and planned treatments"},
                            {"name": "ovriga_upplysningar", "label": "Övriga upplysningar" if lang_code == "sv" else "Additional Information", "description": "Other relevant information"},
                        ]
                    logger.info(f"✓ Using {len(state.document_sections)} default sections for {state.document_type}")

                # Generate a note_generation_id for tracking
                import uuid
                state.note_generation_id = str(uuid.uuid4())

                # Emit completion status
                if hasattr(state, 'stream_callback') and state.stream_callback:
                    language = getattr(state, 'user_language', 'en')
                    description = get_message(
                        "determine_document_sections",
                        "completed",
                        language,
                        section_count=len(state.document_sections)
                    )
                    await state.stream_callback({
                        "type": "status",
                        "step": "determine_document_sections",
                        "description": description,
                        "status": "completed",
                        "progress": state.progress_percentage,
                        "timestamp": datetime.now().isoformat()
                    })

                return state

            except Exception as e:
                logger.error(f"❌ Error determining document sections: {e}")
                import traceback
                traceback.print_exc()
                # Set minimal fallback sections
                state.document_sections = [
                    {"name": "content", "label": "Content", "description": "Document content"}
                ]
                return state

        async def _generate_document_section_queries(state: FlowState, section: dict, doc_type: str) -> List[str]:
            """
            Generate focused queries for a specific document section.
            
            CRITICAL: All queries MUST be focused on the PRIMARY FOCUS (diagnostic question/condition).
            This ensures the document is coherent and only contains relevant information.
            """
            try:
                section_name = section.get("name", "")
                section_label = section.get("label", section_name)
                section_desc = section.get("description", "")
                
                # Get the primary focus - this is the key to consistency
                primary_focus = state.document_primary_focus or ""

                logger.info(f"Generating queries for section: {section_label} (focus: {primary_focus})")

                # Include chat history context for better query generation
                history_context = ""
                if state.chat_history:
                    recent = state.chat_history[-4:]  # Last 2 turns
                    if recent:
                        history_context = "\n\nRecent conversation context:\n"
                        for msg in recent:
                            content_preview = msg.content[:150] if len(msg.content) > 150 else msg.content
                            history_context += f"{msg.role.value}: {content_preview}\n"

                # Build prompt with PRIMARY FOCUS as the central constraint
                prompt = f"""Generate search queries for a {doc_type} document.

PRIMARY CONDITION/FOCUS: {primary_focus}
⚠️ ALL queries MUST retrieve information ONLY relevant to: {primary_focus}
Do NOT retrieve information about other conditions or unrelated medical history.

Section: "{section_label}"
Section description: {section_desc}

User's original request: "{state.user_prompt}"{history_context}

Generate 3 specific search queries that will find information about {primary_focus} as it relates to "{section_label}".

IMPORTANT CONSTRAINTS:
- Every query MUST include or be focused on: {primary_focus}
- Do NOT generate generic queries - make them specific to {primary_focus}
- Retrieve ONLY information that would be relevant when discussing {primary_focus}

Example for depression referral:
- Section "Background" -> "patient history depression onset family mental health"
- Section "Current Status" -> "current depression symptoms mood sleep appetite concentration"
- Section "Functional Level" -> "depression impact work daily activities social function"

Your 3 queries (one per line):"""

                from optimed.core.domain import ChatMessage, ChatRole
                messages = [
                    ChatMessage(role=ChatRole.SYSTEM, content=f"You generate search queries focused ONLY on information relevant to: {primary_focus}. Every query must retrieve content specific to this condition/topic. Return exactly 3 queries, one per line."),
                    ChatMessage(role=ChatRole.USER, content=prompt)
                ]

                response = await self._llm.chat(messages)
                queries_text = response.content.strip()

                # Parse queries (one per line)
                queries = [q.strip() for q in queries_text.split('\n') if q.strip() and not q.strip().startswith('#')]
                queries = queries[:3]  # Limit to 3

                if not queries:
                    # Fallback queries - still focused on primary condition
                    queries = [
                        f"{primary_focus} {section_label}",
                        f"{primary_focus} {section_desc}",
                        f"patient {primary_focus} {section_name}"
                    ]

                logger.info(f"Generated {len(queries)} queries for section '{section_label}' (focus: {primary_focus})")
                return queries

            except Exception as e:
                logger.error(f"Error generating queries for section: {e}")
                # Even in error fallback, include primary focus
                primary_focus = state.document_primary_focus or ""
                return [f"{primary_focus} {section.get('label', 'medical information')}"]

        @streaming_step("parallel_retrieve_for_document_sections")
        async def parallel_retrieve_for_document_sections(state: FlowState) -> FlowState:
            """
            Execute parallel retrieval for all document sections using asyncio.gather.
            Similar to general_summary_parallel_dispatcher but for document sections.
            """
            try:
                logger.info(f"🔄 Starting parallel retrieval for {len(state.document_sections)} document sections")

                if not state.document_sections:
                    logger.warning("No document sections defined, skipping retrieval")
                    return state

                # Emit starting status
                if hasattr(state, 'stream_callback') and state.stream_callback:
                    language = getattr(state, 'user_language', 'en')
                    description = get_message(
                        "parallel_retrieve_for_document_sections",
                        "starting",
                        language,
                        section_count=len(state.document_sections)
                    )
                    await state.stream_callback({
                        "type": "status",
                        "step": "parallel_retrieve_for_document_sections",
                        "description": description,
                        "status": "in_progress",
                        "progress": state.progress_percentage,
                        "timestamp": datetime.now().isoformat()
                    })

                # Disable refinement for document flows (they use their own retrieval)
                state.needs_refinement = False

                # Get document type name for queries
                doc_type = "referral" if state.document_type == "referral" else "medical certificate"

                # Generate queries for all sections IN PARALLEL
                logger.info("Generating queries for all sections in parallel")
                query_tasks = [
                    _generate_document_section_queries(state, section, doc_type)
                    for section in state.document_sections
                ]
                query_results = await asyncio.gather(*query_tasks, return_exceptions=True)

                # Handle any exceptions in query generation
                section_queries = {}
                for i, (section, queries) in enumerate(zip(state.document_sections, query_results)):
                    section_name = section.get("name", f"section_{i}")
                    if isinstance(queries, Exception):
                        logger.error(f"Error generating queries for {section_name}: {queries}")
                        section_queries[section_name] = [section.get("label", "medical information")]
                    else:
                        section_queries[section_name] = queries

                logger.info("All queries generated, starting parallel retrievals")

                # Execute all retrievals in parallel using asyncio.gather
                retrieval_tasks = []
                section_names = []
                for section in state.document_sections:
                    section_name = section.get("name", "")
                    queries = section_queries.get(section_name, [])
                    section_names.append(section_name)
                    retrieval_tasks.append(
                        _retrieve_with_full_pipeline(
                            self, state=state,
                            queries=queries,
                            context_label=f"document_{section_name}",
                            topk_initial=100,
                            topk_rerank=15,
                            use_mmr=True,
                            use_agentic_refinement=True
                        )
                    )

                results = await asyncio.gather(*retrieval_tasks, return_exceptions=True)

                # Store results in document_section_chunks
                state.document_section_chunks = {}
                all_chunks = []
                for section_name, chunks in zip(section_names, results):
                    if isinstance(chunks, Exception):
                        logger.error(f"Error retrieving chunks for {section_name}: {chunks}")
                        state.document_section_chunks[section_name] = []
                    else:
                        state.document_section_chunks[section_name] = chunks
                        all_chunks.extend(chunks)
                        logger.info(f"Retrieved {len(chunks)} chunks for section '{section_name}'")

                logger.info(f"✓ Parallel retrieval completed for {len(state.document_sections)} sections, {len(all_chunks)} total chunks")

                # Build citations from all retrieved chunks
                if all_chunks:
                    state.citations, state.chunk_id_to_number = self._build_citations_from_chunks(all_chunks)
                    logger.info(f"🔖 Built {len(state.citations)} citations from {len(all_chunks)} total chunks")
                else:
                    state.citations = {}
                    state.chunk_id_to_number = {}
                    logger.warning("No chunks retrieved - citations will be empty")

                # Emit completion status
                if hasattr(state, 'stream_callback') and state.stream_callback:
                    language = getattr(state, 'user_language', 'en')
                    description = get_message(
                        "parallel_retrieve_for_document_sections",
                        "completed",
                        language,
                        section_count=len(state.document_sections),
                        chunk_count=len(all_chunks)
                    )
                    await state.stream_callback({
                        "type": "status",
                        "step": "parallel_retrieve_for_document_sections",
                        "description": description,
                        "status": "completed",
                        "progress": state.progress_percentage,
                        "timestamp": datetime.now().isoformat()
                    })

                return state

            except Exception as e:
                logger.error(f"❌ Error in parallel retrieval: {e}")
                import traceback
                traceback.print_exc()
                state.document_section_chunks = {}
                return state

        @streaming_step("generate_document_content")
        async def generate_document_content(state: FlowState) -> FlowState:
            """
            Generate content for all document sections using the section-specific chunks.
            Uses the document-specific system prompt for guidance.
            """
            try:
                logger.info(f"📝 Generating content for {len(state.document_sections)} document sections")

                if not state.document_sections:
                    logger.warning("No document sections defined")
                    return state

                # Get the appropriate system prompt
                if state.document_type == "referral":
                    doc_system_prompt = REFERRAL_SYSTEM_PROMPT
                    doc_type_name = "Referral (Remiss)"
                    doc_type_display = "referral" if state.user_language != "sv" else "remiss"
                else:
                    doc_system_prompt = MEDICAL_CERTIFICATE_SYSTEM_PROMPT
                    doc_type_name = "Medical Certificate (Läkarintyg)"
                    doc_type_display = "medical certificate" if state.user_language != "sv" else "läkarintyg"

                # Emit starting status
                if hasattr(state, 'stream_callback') and state.stream_callback:
                    language = getattr(state, 'user_language', 'en')
                    description = get_message(
                        "generate_document_content",
                        "starting",
                        language,
                        document_type=doc_type_display,
                        section_count=len(state.document_sections)
                    )
                    await state.stream_callback({
                        "type": "status",
                        "step": "generate_document_content",
                        "description": description,
                        "status": "in_progress",
                        "progress": state.progress_percentage,
                        "timestamp": datetime.now().isoformat()
                    })

                # Detect language
                lang_code = detect_language_code(state.user_prompt)
                lang_name = "Swedish" if lang_code == "sv" else "English"

                current_date = datetime.now().strftime('%Y-%m-%d')

                # Get the primary focus for consistency
                primary_focus = state.document_primary_focus or "the patient's condition"

                # Build the full system prompt for generation
                generation_system_prompt = f"""You are generating a {doc_type_name} in {lang_name}.

Date: {current_date}
PRIMARY FOCUS: {primary_focus}

{doc_system_prompt}

CRITICAL:
- Write in {lang_name}
- PLAIN TEXT only
- NEVER include citations or references
- Write like clinical notes - short facts, not prose
- Omit sections where no data available
- EVERY section must be focused on: {primary_focus}
- Do NOT include information about other conditions unless directly relevant to {primary_focus}
"""

                # Generate content for each section
                sections_content = {}
                
                async def generate_section_content(section: dict) -> Tuple[str, str]:
                    """Generate content for a single section, focused on the primary condition."""
                    section_name = section.get("name", "")
                    section_label = section.get("label", section_name)
                    section_desc = section.get("description", "")

                    # Get section-specific chunks
                    section_chunks = state.document_section_chunks.get(section_name, [])
                    
                    if section_chunks:
                        # Format chunks WITHOUT citations for document generation
                        limited_chunks = self._limit_chunks_for_context(section_chunks[:10], max_tokens=30000, max_chunk_chars=10000)
                        chunks_text = "\n\n".join([
                            chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
                            for chunk in limited_chunks
                        ])
                    else:
                        chunks_text = "No specific information available."

                    # Build section-specific prompt - emphasize focus on primary condition
                    if state.document_type == "referral":
                        section_prompt = f"""Generate "{section_label}" section for {primary_focus}.

⚠️ IMPORTANT: Include ONLY information relevant to {primary_focus}. Ignore unrelated conditions.

Purpose: {section_desc}

Data:
{chunks_text}

Write telegram-style clinical notes about {primary_focus}. Short facts separated by periods. No prose. No citations.
Only include facts that are relevant to {primary_focus}."""
                    else:
                        section_prompt = f"""Generate "{section_label}" section for {primary_focus}.

⚠️ IMPORTANT: Include ONLY information relevant to {primary_focus}. Ignore unrelated conditions.

Purpose: {section_desc}

Data:
{chunks_text}

Write 2-4 sentences about {primary_focus}. Plain text, no citations.
Only include facts that are directly relevant to {primary_focus}."""

                    from optimed.core.domain import ChatMessage, ChatRole
                    messages = [
                        ChatMessage(role=ChatRole.SYSTEM, content=generation_system_prompt),
                        ChatMessage(role=ChatRole.USER, content=section_prompt)
                    ]

                    # Disable citations for document generation
                    response = await self._llm.chat(messages, enable_chunk_citations=False)
                    content = response.content.strip()

                    logger.info(f"✓ Generated {len(content)} chars for section '{section_label}'")
                    return section_name, content

                # Generate all sections in parallel
                generation_tasks = [generate_section_content(section) for section in state.document_sections]
                generation_results = await asyncio.gather(*generation_tasks, return_exceptions=True)

                # Process results
                for result in generation_results:
                    if isinstance(result, Exception):
                        logger.error(f"Error generating section content: {result}")
                    else:
                        section_name, content = result
                        sections_content[section_name] = content

                # Store in note_sections for compatibility with format_note_response
                state.note_sections = sections_content

                # Format the final document content
                final_content = f"# {doc_type_name}\n\n"
                for section in state.document_sections:
                    section_name = section.get("name", "")
                    section_label = section.get("label", section_name)
                    section_content = sections_content.get(section_name, "")
                    final_content += f"## {section_label}\n{section_content}\n\n"

                state.note_final_content = final_content
                state.note_sources = []  # No sources needed in final output

                logger.info(f"✓ Complete document generated: {len(final_content)} chars, {len(state.document_sections)} sections")

                # Emit completion status
                if hasattr(state, 'stream_callback') and state.stream_callback:
                    language = getattr(state, 'user_language', 'en')
                    description = get_message(
                        "generate_document_content",
                        "completed",
                        language,
                        section_count=len(state.document_sections),
                        char_count=len(final_content)
                    )
                    await state.stream_callback({
                        "type": "status",
                        "step": "generate_document_content",
                        "description": description,
                        "status": "completed",
                        "progress": state.progress_percentage,
                        "timestamp": datetime.now().isoformat()
                    })

                return state

            except Exception as e:
                logger.error(f"❌ Error generating document content: {e}")
                import traceback
                traceback.print_exc()
                return state

        @streaming_step("format_document_response")
        async def format_document_response(state: FlowState) -> FlowState:
            """
            Format the final document response for streaming to frontend.
            Returns as JSON structure compatible with NoteGenerationDialog.
            """
            try:
                logger.info("Formatting document for response")

                # Emit starting status
                if hasattr(state, 'stream_callback') and state.stream_callback:
                    language = getattr(state, 'user_language', 'en')
                    doc_type_display = "referral" if state.document_type == "referral" else "medical certificate"
                    if language == "sv":
                        doc_type_display = "remiss" if state.document_type == "referral" else "läkarintyg"
                    description = get_message(
                        "format_document_response",
                        "starting",
                        language,
                        document_type=doc_type_display
                    )
                    await state.stream_callback({
                        "type": "status",
                        "step": "format_document_response",
                        "description": description,
                        "status": "in_progress",
                        "progress": state.progress_percentage,
                        "timestamp": datetime.now().isoformat()
                    })

                if not state.note_final_content:
                    logger.warning("⚠️ No document content to format")
                    from optimed.core.domain import ChatMessage, ChatRole
                    error_response = {
                        "type": "error",
                        "message": "Document generation failed to produce content. Please try again."
                    }
                    state.llm_response = ChatMessage(
                        role=ChatRole.ASSISTANT,
                        content=json.dumps(error_response, ensure_ascii=False)
                    )
                    return state

                # Create structured response compatible with generated_note format
                doc_response = {
                    "type": "generated_note",  # Reuse existing frontend component
                    "generation_id": state.note_generation_id,
                    "template_name": "Referral" if state.document_type == "referral" else "Medical Certificate",
                    "template_type": state.document_type,
                    "language": detect_language_code(state.user_prompt),
                    "content": state.note_final_content,
                    "sections": state.note_sections,
                    "sources": state.note_sources,
                    "metadata": {
                        "document_type": state.document_type,
                        "sections_count": len(state.document_sections),
                        "chunks_used": sum(len(chunks) for chunks in state.document_section_chunks.values()),
                        "word_count": len(state.note_final_content.split())
                    }
                }

                from optimed.core.domain import ChatMessage, ChatRole
                state.llm_response = ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=json.dumps(doc_response, ensure_ascii=False)
                )

                logger.info("✓ Document response formatted and ready")

                # Emit completion status
                if hasattr(state, 'stream_callback') and state.stream_callback:
                    language = getattr(state, 'user_language', 'en')
                    description = get_message(
                        "format_document_response",
                        "completed",
                        language
                    )
                    await state.stream_callback({
                        "type": "status",
                        "step": "format_document_response",
                        "description": description,
                        "status": "completed",
                        "progress": state.progress_percentage,
                        "timestamp": datetime.now().isoformat()
                    })

                return state

            except Exception as e:
                logger.error(f"❌ Error formatting document response: {e}")
                import traceback
                traceback.print_exc()
                return state

        # ==================== END DOCUMENT GENERATION FLOW NODES ====================

        @streaming_step("provide_information")
        async def provide_information(state: FlowState) -> FlowState:
            logger.info("🎯 Starting information provision")
            logger.info(f"🔍 Query length: {len(state.user_prompt)} chars")
            logger.info(f"🆔 Session ID: {sanitize_session_id(state.session_id)}")
            logger.info(f"👤 User ID: {sanitize_user_id(state.user_id)}")

            # Update status: Preparing context
            state.current_step = "Preparing Context"
            state.step_details = "Setting up language and system instructions..."

            # Emit status update
            if hasattr(state, 'stream_callback') and state.stream_callback:

                language = getattr(state, 'user_language', 'en')

                description = get_message(
                    "prepare_context",
                    "in_progress",
                    language
                )

                await state.stream_callback({
                    "type": "status",
                    "step": "prepare_context",
                    "description": description,
                    "status": "in_progress",
                    "progress": 0,
                    "timestamp": datetime.now().isoformat()
                })

            # Use the single system message for information relay (with current date)
            messages = [get_system_msg_info_relay()]

            # Language policy system message (answer in user's prompt language)
            language_system_msg = self._get_language_policy_message(state)
            messages.insert(0, language_system_msg)

            if state.user_context:
                user_info = ChatMessage(
                    role=ChatRole.USER,
                    content=f"Current user: {state.user_context.display_name} ({state.user_context.role.value})"
                )
                messages.append(user_info)

            # Update status: Loading conversation history
            state.current_step = "Loading History"
            state.step_details = f"Loading {len(state.chat_history)} previous messages from session..."

            # Emit status update
            if hasattr(state, 'stream_callback') and state.stream_callback:
                language = getattr(state, 'user_language', 'en')

                description = get_message(
                    "load_history",
                    "in_progress",
                    language
                )
                await state.stream_callback({
                    "type": "status",
                    "step": "load_history",
                    "description": description,
                    "status": "in_progress",
                    "progress": 0,
                    "timestamp": datetime.now().isoformat()
                })

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
                    # Use LLM to create an intelligent summary of conversation history
                    logger.info("📝 Creating LLM-based conversation summary")
                    
                    try:
                        # Build full conversation text for LLM summarization
                        conversation_lines = []
                        for msg in current_history:
                            if not msg.content or not msg.content.strip():
                                continue
                            role_name = "User" if msg.role == ChatRole.USER else "CLARA"
                            conversation_lines.append(f"{role_name}: {msg.content}")
                        
                        if conversation_lines:
                            full_conversation = "\n".join(conversation_lines)
                            
                            # Use LLM to create a concise summary
                            summary_prompt = f"""Summarize this clinical conversation in 2-3 sentences, focusing on:
1. The main clinical topic or patient concern being discussed
2. Key information already provided (diagnoses, medications, symptoms mentioned)
3. What the user was asking about

Conversation:
{full_conversation}

Provide ONLY the summary, no preamble or explanation."""

                            summary_response = await self._llm.chat([
                                ChatMessage(
                                    role=ChatRole.SYSTEM,
                                    content="You are a clinical conversation summarizer. Create brief, focused summaries that capture the essential clinical context."
                                ),
                                ChatMessage(role=ChatRole.USER, content=summary_prompt)
                            ])
                            
                            conversation_summary = summary_response.content.strip()
                            
                            conversation_context = ChatMessage(
                                role=ChatRole.USER,
                                content=f"Previous conversation context:\n{conversation_summary}\n\nCurrent question:",
                                user_id=None,
                                user_role=None,
                                metadata={}
                            )
                            messages.append(conversation_context)
                            logger.info(f"✅ Added LLM conversation summary ({len(conversation_summary)} chars)")
                        else:
                            logger.info("⚠️ No valid conversation content to summarize")
                    except Exception as e:
                        logger.warning(f"LLM summarization failed, falling back to truncation: {e}")
                        # Fallback to simple truncation if LLM fails
                        conversation_lines = []
                        for msg in current_history[-5:]:  # Last 5 messages only
                            if msg.content and msg.content.strip():
                                role_name = "User" if msg.role == ChatRole.USER else "CLARA"
                                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                                conversation_lines.append(f"{role_name}: {content}")
                        if conversation_lines:
                            conversation_context = ChatMessage(
                                role=ChatRole.USER,
                                content=f"Previous conversation context:\n{chr(10).join(conversation_lines)}\n\nCurrent question:",
                                user_id=None,
                                user_role=None,
                                metadata={}
                            )
                            messages.append(conversation_context)
                elif not ENABLE_CONVERSATION_HISTORY:
                    logger.info("⚠️ Conversation history disabled temporarily to prevent API errors")
                else:
                    logger.info("⚠️ No conversation history to include in model prompt")
            
            # Add retrieved chunks (parent chunks are swapped in intelligent_retrieve_chunks)
            logger.info(f"📄 Retrieved chunks count: {len(state.retrieved_chunks) if state.retrieved_chunks else 0}")
            
            if state.retrieved_chunks:
                # Update status: Processing clinical data
                state.current_step = "Processing Clinical Data"
                state.step_details = f"Analyzing {len(state.retrieved_chunks)} relevant clinical records..."

                # Emit status update
                if hasattr(state, 'stream_callback') and state.stream_callback:

                    language = getattr(state, 'user_language', 'en')

                    description = get_message(
                        "process_clinical_data",
                        "in_progress",
                        language
                    )

                    await state.stream_callback({
                        "type": "status",
                        "step": "process_clinical_data",
                        "description": description,
                        "status": "in_progress",
                        "progress": 0,
                        "timestamp": datetime.now().isoformat()
                    })

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

                # Emit status update
                if hasattr(state, 'stream_callback') and state.stream_callback:
                    language = getattr(state, 'user_language', 'en')

                    description = get_message(
                        "integrate_web_sources",
                        "in_progress",
                        language
                    )
                    await state.stream_callback({
                        "type": "status",
                        "step": "integrate_web_sources",
                        "description": description,
                        "status": "in_progress",
                        "progress": 0,
                        "timestamp": datetime.now().isoformat(),
                        "count": len(state.web_search_response.results)
                    })

                # Create a more detailed and instructional web search message
                sources_list = []
                for i, result in enumerate(state.web_search_response.results[:5], 1):
                    sources_list.append(f"{i}. [{result.title}]({result.url})\n   - {result.snippet[:200]}...")
                
                web_info = ChatMessage(
                    role=ChatRole.USER,
                    content=f"""=== WEB SEARCH RESULTS FOR: '{state.user_prompt}' ===

SEARCH SUMMARY: {state.web_search_response.summary}

SOURCES TO CITE IN YOUR RESPONSE IF YOU USE INFORMATION FROM THEM:
{chr(10).join(sources_list)}

INSTRUCTION: You MUST cite these sources in your response ONLY IF you use information from them. Use the format [Source Title](URL) in your response.
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

            # Create reasoning prompt for structured thinking
            reasoning_prompt = self._create_reasoning_prompt(state)

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

            # Emit status update
            if hasattr(state, 'stream_callback') and state.stream_callback:
                language = getattr(state, 'user_language', 'en')

                description = get_message(
                    "generate_response",
                    "in_progress",
                    language
                )
                await state.stream_callback({
                    "type": "status",
                    "step": "generate_response",
                    "description": description,
                    "status": "in_progress",
                    "progress": 0,
                    "timestamp": datetime.now().isoformat()
                })

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
                        "prompt": state.query_classification,
                        "chat_mode": state.chat_mode,
                        "session_id": state.session_id
                    }
                )
                await self._user_repo.log_action(action)

            # Check if LLM refused to answer (common when no patient data is available)
            if state.llm_response and state.llm_response.content:
                response_lower = state.llm_response.content.lower()
                if "i'm sorry" in response_lower and "cannot assist" in response_lower:
                    logger.info("⚠️ LLM refused to answer - likely due to insufficient patient context")
                    # Provide a more helpful error message
                    state.llm_response = ChatMessage(
                        role=ChatRole.ASSISTANT,
                        content="I need more specific patient information to answer this question. Please ensure:\n\n• The patient has relevant clinical data recorded\n• You're asking about documented information\n• The question is specific enough to search for\n\nTry rephrasing your question or ask about a different aspect of the patient's care."
                    )

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

Task: If the current query references previous context (e.g., "yes", "tell me more", "that one"), reformulate it to be self-contained. If it's already clear, return it unchanged.

Examples:
- "yes" after "Would you like more details about the medications?" → "Give me more details about the patient's medications"
- "tell me more" after discussing lab results → "Tell me more about the patient's lab results"
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
            classify_start_time = time.time()

            # Log audit event: START classification
            if self._audit_repo and state.session_id:
                create_background_task(
                    self._audit_repo.log_audit_event(
                        session_id=state.session_id,
                        action="CLASSIFY_QUERY",
                        resource_type="query",
                        outcome="in_progress",
                        user_id=state.user_id
                    ),
                    "log_audit_event_classify_start",
                    session_id=state.session_id,
                    user_id=state.user_id
                )

            try:
                logger.info(f"Classifying query (length={len(state.user_prompt)} chars)")

                # Skip classification if already in note generation flow
                if hasattr(state, 'is_note_generation_flow') and state.is_note_generation_flow:
                    logger.info("Already in note generation flow, skipping classification")
                    return state

                # Use contextualized query if available (from contextualize_query_for_classification node)
                query_to_classify = getattr(state, 'classification_query', state.user_prompt)

                logger.info(f"Classifying query (length={len(query_to_classify)} chars)")

                # Use the LLM-based classifier (async) with simplified labels
                # Only 2 specialized flows + default
                classifier = self._zero_shot_classifier
                label = await classifier.classify(query_to_classify, [
                    "general_summary", "note_generation", "default"
                ], llm_client=self._llm)

                logger.info(f"Query classified as: {label}")

                # Store classification in state
                state.query_classification = label

                # Check for note generation intent (high precision)
                if label == "note_generation":
                    logger.info("Note generation detected!")
                    state.is_note_generation_flow = True

                    # Determine template type from query content
                    query_lower = state.user_prompt.lower()

                    # Template detection with keywords (includes SBAR, discharge, etc. as note types)
                    # Check for document generation types FIRST (referral, medical certificate)
                    if any(word in query_lower for word in ["remiss", "referral", "refer", "hänvisa", "remittera"]):
                        template_type = "referral"
                        # Route to document generation flow for referrals
                        state.is_document_generation_flow = True
                        state.document_type = "referral"
                        state.is_note_generation_flow = False  # Use document flow instead
                        logger.info(f"Document generation flow activated: referral")
                    elif any(word in query_lower for word in ["läkarintyg", "intyg", "sjukintyg", "medical certificate", "sick certificate", "certificate"]):
                        template_type = "medical_certificate"
                        # Route to document generation flow for medical certificates
                        state.is_document_generation_flow = True
                        state.document_type = "medical_certificate"
                        state.is_note_generation_flow = False  # Use document flow instead
                        logger.info(f"Document generation flow activated: medical_certificate")
                    elif any(word in query_lower for word in ["sbar", "situation", "bakgrund", "background", "handoff", "överlämning"]):
                        template_type = "sbar"
                    elif any(word in query_lower for word in ["soap", "subjective", "objective", "assessment", "plan"]):
                        template_type = "soap"
                    elif any(word in query_lower for word in ["journal", "progress", "anteckning"]):
                        template_type = "journal_entry"
                    elif any(word in query_lower for word in ["consultation", "konsultation"]):
                        template_type = "consultation"
                    elif any(word in query_lower for word in ["discharge", "utskrivning", "slutanteckning"]):
                        template_type = "discharge"
                    else:
                        # Default to SBAR for general note requests
                        template_type = "sbar"

                    logger.info(f"Auto-selected template type: {template_type}")

                    # Store template type preference for later retrieval
                    state.note_template_type_preference = template_type
                    state.is_general_summary_flow = False
                    return state

                # General summary flow is triggered by "general_summary" classification
                state.is_general_summary_flow = (label == "general_summary")
                logger.info(f"General summary flow (classifier): {state.is_general_summary_flow}")

                # Initialize general summary cache if using general summary flow
                if state.is_general_summary_flow:
                    state.general_retrieval_cache = {}

            except Exception as e:
                logger.info(f"Classification failed: {e}, defaulting to regular flow")
                state.query_classification = "default"  # Default fallback
                state.is_note_generation_flow = False
                state.is_general_summary_flow = False

            # Log classification completion
            classify_duration_ms = int((time.time() - classify_start_time) * 1000)
            if self._audit_repo and state.session_id:
                classification_result = getattr(state, 'query_classification', 'unknown')
                create_background_task(
                    self._audit_repo.log_audit_event(
                        session_id=state.session_id,
                        action="CLASSIFY_QUERY_COMPLETE",
                        resource_type="query",
                        outcome="success",
                        latency_ms=classify_duration_ms,
                        user_id=state.user_id,
                        metadata={"classification": classification_result}
                    ),
                    "log_audit_event_classify_complete",
                    session_id=state.session_id,
                    user_id=state.user_id
                )

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
        _builder.add_node("contextualize_query_for_classification", contextualize_query_for_classification)
        _builder.add_node("classify_query_intent", classify_query_intent)
        _builder.add_node("store_user_message", store_user_message)
        _builder.add_node("load_current_session_history", load_current_session_history)
        _builder.add_node("fetch_patient", fetch_patient)
        _builder.add_node("fetch_pdfs", fetch_pdfs)
        _builder.add_node("fetch_xmls", fetch_xmls)
        _builder.add_node("intelligent_retrieve_chunks", intelligent_retrieve_chunks)
        # Note: SBAR nodes removed (flow replaced by system-prompt-driven approach)
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
        # Note: Focused summary and Timeline nodes removed (flows replaced by system-prompt-driven approach)
        # Note generation flow nodes
        _builder.add_node("load_note_template", load_note_template)
        _builder.add_node("generate_note_section", generate_note_section)
        _builder.add_node("format_note_response", format_note_response)
        _builder.add_node("store_note_metadata", store_note_metadata)
        # Document generation flow nodes (referrals, medical certificates)
        _builder.add_node("determine_document_sections", determine_document_sections)
        _builder.add_node("parallel_retrieve_for_document_sections", parallel_retrieve_for_document_sections)
        _builder.add_node("generate_document_content", generate_document_content)
        _builder.add_node("format_document_response", format_document_response)
        # Note: Guideline and general knowledge nodes removed (flows replaced by system-prompt-driven approach)
        _builder.add_node("evaluate_web_search_need", evaluate_web_search_need)
        _builder.add_node("perform_web_search", perform_web_search)
        _builder.add_node("provide_information", provide_information)
        _builder.add_node("store_assistant_response", store_assistant_response)

        _builder.set_entry_point("load_user_context")  # Start with loading user context

        # Add edges for user context loading and classification
        _builder.add_edge("load_user_context", "contextualize_query_for_classification")
        _builder.add_edge("contextualize_query_for_classification", "classify_query_intent")
        _builder.add_edge("classify_query_intent", "store_user_message")
        _builder.add_edge("store_user_message", "load_current_session_history")

        # After loading session history, always proceed to check_patient
        _builder.add_edge("load_current_session_history", "check_patient")

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

        # Route after fetching XMLs - always proceed to chunk retrieval
        _builder.add_edge("fetch_xmls", "intelligent_retrieve_chunks")

        # Note: SBAR edges removed (flow replaced by system-prompt-driven approach)

        # General summary execution - dispatcher uses asyncio.gather for parallel retrieval + generation
        # Dispatcher does all 6 retrievals and generations in parallel, then routes to merge
        _builder.add_edge("general_summary_parallel_dispatcher", "merge_general_summary_results")

        # General summary merge to store response
        _builder.add_edge("merge_general_summary_results", "store_assistant_response")

        # Note: Focused summary edges removed (flow replaced by system-prompt-driven approach)
        # Note: Timeline flow edges removed (now uses default provide_information flow)

        # Note generation flow edges - sequential processing
        _builder.add_edge("load_note_template", "generate_note_section")
        _builder.add_edge("generate_note_section", "format_note_response")
        _builder.add_edge("format_note_response", "store_note_metadata")
        _builder.add_edge("store_note_metadata", "store_assistant_response")

        # Document generation flow edges - referrals and medical certificates
        _builder.add_edge("determine_document_sections", "parallel_retrieve_for_document_sections")
        _builder.add_edge("parallel_retrieve_for_document_sections", "generate_document_content")
        _builder.add_edge("generate_document_content", "format_document_response")
        _builder.add_edge("format_document_response", "store_note_metadata")  # Reuse note metadata storage

        # Route after chunk retrieval: check flow type (3 specialized flows + default)
        def route_after_chunks(state):
            logger.info(f"🔀 route_after_chunks called - is_general_summary_flow: {getattr(state, 'is_general_summary_flow', False)}, is_note_generation_flow: {getattr(state, 'is_note_generation_flow', False)}, is_document_generation_flow: {getattr(state, 'is_document_generation_flow', False)}, needs_refinement: {getattr(state, 'needs_refinement', False)}")

            # Check specialized flows FIRST (they have priority and don't need refinement)
            # Document generation flow (referrals, medical certificates) - highest priority
            if hasattr(state, 'is_document_generation_flow') and state.is_document_generation_flow:
                logger.info(f"📄 Routing to document generation flow (type: {getattr(state, 'document_type', 'unknown')})")
                return "determine_document_sections"
            elif hasattr(state, 'is_note_generation_flow') and state.is_note_generation_flow:
                logger.info("📝 Routing to note generation flow")
                return "load_note_template"
            elif hasattr(state, 'is_general_summary_flow') and state.is_general_summary_flow:
                logger.info("📊 Routing to general summary flow")
                return "general_summary_parallel_dispatcher"
            # Only check refinement if NOT in a specialized flow
            elif hasattr(state, 'needs_refinement') and state.needs_refinement and state.retrieval_retry_attempts < RETRY_MAX:
                # Increment retry attempts to prevent infinite loop
                state.retrieval_retry_attempts += 1
                logger.info(f"🔄 Retrieval refinement needed, attempt {state.retrieval_retry_attempts}/{RETRY_MAX}")
                return "intelligent_retrieve_chunks"
            else:
                # Clear refinement flag for next query
                state.needs_refinement = False
                logger.info("➡️ Routing to web search evaluation (then provide_information)")
                return "evaluate_web_search_need"

        _builder.add_conditional_edges(
            "intelligent_retrieve_chunks",
            route_after_chunks,
            {
                "determine_document_sections": "determine_document_sections",
                "load_note_template": "load_note_template",
                "general_summary_parallel_dispatcher": "general_summary_parallel_dispatcher",
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
        # Note: Guideline and general knowledge edges removed (flows replaced by system-prompt-driven approach)
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

    def _parse_journal_entries(self, text: str) -> List[Tuple[datetime, str]]:
        """
        Parse Swedish journal entries using line-start dates as boundaries.

        RULE: A date at the START of a line (with optional whitespace) marks a new entry.
        This avoids false positives from dates mentioned in entry content.

        Supports:
        - YYYY-MM-DD HH:MM (e.g., 2024-09-25 09:45)
        - YYYY-MM-DD (e.g., 2024-09-25)

        Returns: List of (entry_date, entry_text) tuples
        """
        lines = text.split('\n')

        # Pattern: Optional whitespace, then date at start of line
        date_at_line_start = r'^\s*(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?'

        entries = []
        current_entry_date = None
        current_entry_lines = []

        for line in lines:
            # Check if this line starts with a date
            match = re.match(date_at_line_start, line)

            if match:
                # NEW ENTRY FOUND

                # Save previous entry if exists
                if current_entry_date is not None and current_entry_lines:
                    entry_text = '\n'.join(current_entry_lines).strip()
                    if entry_text:
                        entries.append((current_entry_date, entry_text))

                # Parse the new entry's date
                date_part = match.group(1)  # YYYY-MM-DD
                time_part = match.group(2)  # HH:MM or None

                if time_part:
                    date_str = f"{date_part} {time_part}"
                    date_format = '%Y-%m-%d %H:%M'
                else:
                    date_str = date_part
                    date_format = '%Y-%m-%d'

                try:
                    current_entry_date = datetime.strptime(date_str, date_format)
                    current_entry_lines = [line]  # Start with header line
                    logger.debug(f"New journal entry: {date_str}")
                except ValueError:
                    logger.warning(f"Could not parse date: {date_str}")
                    current_entry_date = None
                    current_entry_lines = []
            else:
                # This line is part of the current entry
                if current_entry_date is not None:
                    current_entry_lines.append(line)

        # Save the last entry
        if current_entry_date is not None and current_entry_lines:
            entry_text = '\n'.join(current_entry_lines).strip()
            if entry_text:
                entries.append((current_entry_date, entry_text))

        logger.info(f"Parsed {len(entries)} journal entries using line-start date markers")
        return entries

    async def _chunk_pdf_documents(self, pdf_documents: List[PDFDocument], orchestrator: ChunkingOrchestrator, patient_id_str: Optional[str]) -> List[Chunk]:
        """
        Chunk PDF documents using SemanticPDFChunker.

        NOTE: We skip NarrativeV1 double-chunking to preserve semantic coherence.
        SemanticPDFChunker already creates optimal chunks with medical context awareness.
        """
        from optimed.core.domain import Chunk
        from optimed.core.services.hash_utils import stable_hash
        import uuid

        if not pdf_documents:
            return []

        # Final chunks to return (both parent and child chunks)
        final_chunks = []
        table_parser = PDFTableParser()

        # Use semantic chunking for better PDF processing
        from optimed.adapters.pdf.semantic_chunker import SemanticPDFChunker

        # Create parent chunker for large context chunks
        # Note: target_chunk_size is in CHARACTERS, ~4 chars per token
        parent_chunker = SemanticPDFChunker(
            target_chunk_size=6000,  # 1500 tokens * 4 = 6000 chars (large chunks for LLM context)
            overlap_ratio=0.25,      # ~375 tokens overlap for context preservation
            preserve_medical_context=True,
            disable_section_detection=True  # Don't split on headers/lists - we want large coherent chunks
        )

        # Create child chunker for precise retrieval chunks
        child_chunker = SemanticPDFChunker(
            target_chunk_size=1000,  # 250 tokens * 4 = 1000 chars (200-300 token range for precise retrieval)
            overlap_ratio=0.15,      # ~60 tokens overlap
            preserve_medical_context=True,
            disable_section_detection=True  # Don't split on headers/lists - paragraph-based chunking only
        )

        for pdf in pdf_documents:
            if not pdf.extracted_text:
                continue

            # Use appropriate patient reference
            if pdf.patient_id:
                pseudo_patient = stable_hash({"pid": pdf.patient_id}, namespace="patient")
            else:
                pseudo_patient = stable_hash({"uid": pdf.user_id}, namespace="user")

            # Try to parse as journal format first
            journal_entries = self._parse_journal_entries(pdf.extracted_text)

            if journal_entries:
                # JOURNAL FORMAT DETECTED
                logger.info(f"PDF '{pdf.filename}' detected as journal with {len(journal_entries)} entries")

                # Chunk each journal entry separately
                for entry_date, entry_text in journal_entries:
                    # STEP 1: Create PARENT chunks from THIS ENTRY
                    parent_semantic_chunks = parent_chunker.chunk_pdf_text(
                        entry_text,
                        pdf.document_id,
                        {
                            "title": pdf.metadata.title,
                            "filename": pdf.filename,
                            "entry_date": entry_date.strftime('%Y-%m-%d %H:%M')
                        }
                    )

                    logger.info(f"  Entry {entry_date.strftime('%Y-%m-%d %H:%M')}: {len(parent_semantic_chunks)} parent chunks")

                    # Create document header for journal entry
                    base_doc_header = f"Journal Entry: {entry_date.strftime('%Y-%m-%d %H:%M')}\n"
                    base_doc_header += f"PDF Document: {pdf.get_display_name()}\n"
                    base_doc_header += f"Filename: {pdf.filename}\n"
                    if pdf.metadata.title:
                        base_doc_header += f"Title: {pdf.metadata.title}\n"
                    base_doc_header += "---\n"

                    # STEP 2: For EACH parent chunk, create child chunks from parent's text
                    for parent_idx, parent_semantic_chunk in enumerate(parent_semantic_chunks):
                        # Create PARENT Chunk object
                        parent_chunk_uuid = str(uuid.uuid4())
                        parent_full_text = base_doc_header + parent_semantic_chunk.text

                        parent_chunk = Chunk(
                            id=parent_chunk_uuid,
                            patient_ref=pseudo_patient,
                            encounter_ref=None,
                            resource_type="journal_entry",
                            key=parent_semantic_chunk.metadata.chunk_id,
                            text=parent_full_text,
                            strategy_id="SemanticPDFChunker",
                            strategy_version="1.0",
                            timestamp=entry_date,
                            meta={
                                "entry_date": entry_date.isoformat(),
                                "document_name": pdf.get_display_name(),
                                "filename": pdf.filename,
                                "title": pdf.metadata.title,
                                "chunk_index": parent_idx,
                                "total_chunks": len(parent_semantic_chunks),
                                "chunk_level": "parent",
                                "child_chunk_ids": []  # Will populate below
                            },
                            has_phi=False
                        )
                        final_chunks.append(parent_chunk)

                        # STEP 3: Split THIS parent chunk into child chunks
                        child_semantic_chunks = child_chunker.chunk_pdf_text(
                            parent_semantic_chunk.text,  # 🔑 Chunk from PARENT text, not full entry
                            f"{pdf.document_id}_parent_{parent_idx}",
                            {
                                "title": pdf.metadata.title,
                                "filename": pdf.filename,
                                "entry_date": entry_date.strftime('%Y-%m-%d %H:%M'),
                                "parent_chunk_id": parent_chunk_uuid
                            }
                        )

                        # Create CHILD Chunk objects from this parent
                        child_chunk_ids = []
                        for child_idx, child_semantic_chunk in enumerate(child_semantic_chunks):
                            child_chunk_uuid = str(uuid.uuid4())
                            child_full_text = base_doc_header + child_semantic_chunk.text

                            child_chunk = Chunk(
                                id=child_chunk_uuid,
                                patient_ref=pseudo_patient,
                                encounter_ref=None,
                                resource_type="journal_entry",
                                key=child_semantic_chunk.metadata.chunk_id,
                                text=child_full_text,
                                strategy_id="SemanticPDFChunker",
                                strategy_version="1.0",
                                timestamp=entry_date,
                                meta={
                                    "entry_date": entry_date.isoformat(),
                                    "document_name": pdf.get_display_name(),
                                    "filename": pdf.filename,
                                    "title": pdf.metadata.title,
                                    "chunk_index": child_idx,
                                    "total_chunks": len(child_semantic_chunks),
                                    "chunk_level": "child",
                                    "parent_chunk_id": parent_chunk_uuid  # 🔑 Natural parent-child link
                                },
                                has_phi=False
                            )
                            final_chunks.append(child_chunk)
                            child_chunk_ids.append(child_chunk_uuid)

                        # Update parent's child_chunk_ids
                        parent_chunk.meta["child_chunk_ids"] = child_chunk_ids
                        logger.info(f"    Parent chunk {parent_idx}: {len(child_chunk_ids)} child chunks")
            else:
                # NOT A JOURNAL - use standard hierarchical chunking
                logger.info(f"PDF '{pdf.filename}' is not journal format - using standard chunking")
                
                # Try coordinate-based table parsing first (more accurate column alignment)
                table_output = None
                try:
                    raw_content = await self._pdf_service.get_document_raw_content(pdf.document_id, pdf.user_id)
                    if raw_content:
                        from optimed.adapters.pdf.pdf_processor import PyMuPDFProcessor
                        pdf_processor = PyMuPDFProcessor()
                        pages_with_coords = await pdf_processor.extract_text_with_coords(raw_content)
                        table_output = table_parser.extract_tables_with_coords(pages_with_coords, pdf.document_id)
                        logger.info(f"Used coordinate-based table parsing for '{pdf.filename}'")
                except Exception as e:
                    logger.warning(f"Coordinate-based parsing failed for '{pdf.filename}': {e}, falling back to text-based")
                    table_output = None
                
                # Fall back to text-based parsing if coordinate-based failed
                if table_output is None:
                    table_output = table_parser.extract_tables(pdf.extracted_text, pdf.document_id)
                    logger.info(f"Used text-based table parsing for '{pdf.filename}'")
                
                if table_output.tables:
                    logger.info(f"Found {len(table_output.tables)} tables in '{pdf.filename}' - creating structured JSON chunks")
                    table_chunks = self._build_pdf_table_chunks(
                        tables=table_output.tables,
                        pdf=pdf,
                        pseudo_patient=pseudo_patient,
                    )
                    logger.info(f"Created {len(table_chunks)} table chunks ({len([c for c in table_chunks if c.meta.get('chunk_level') == 'parent'])} parent + {len([c for c in table_chunks if c.meta.get('chunk_level') == 'child'])} child)")
                    final_chunks.extend(table_chunks)
                else:
                    logger.info(f"No tables detected in '{pdf.filename}' - using standard chunking")
                text_for_chunking = table_output.cleaned_text or pdf.extracted_text
                if not text_for_chunking:
                    logger.info(f"PDF '{pdf.filename}' contains tables only - skipping semantic chunker")
                    continue

                # STEP 1: Create PARENT chunks from the full PDF
                parent_semantic_chunks = parent_chunker.chunk_pdf_text(
                    text_for_chunking,
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

                logger.info(f"PDF {pdf.filename} -> {len(parent_semantic_chunks)} parent chunks")

                # Create base document header
                base_doc_header = f"PDF Document: {pdf.get_display_name()}\n"
                base_doc_header += f"Filename: {pdf.filename}\n"
                if pdf.metadata.title:
                    base_doc_header += f"Title: {pdf.metadata.title}\n"
                if pdf.metadata.author:
                    base_doc_header += f"Author: {pdf.metadata.author}\n"
                base_doc_header += f"Upload Date: {pdf.uploaded_at.strftime('%Y-%m-%d %H:%M')}\n"
                base_doc_header += f"{'Patient ID: ' + pdf.patient_id if pdf.patient_id else 'General Document'}\n"

                # STEP 2: For EACH parent chunk, create child chunks from parent's text
                for parent_idx, parent_semantic_chunk in enumerate(parent_semantic_chunks):
                    # Build parent document header
                    parent_doc_header = base_doc_header

                    if parent_semantic_chunk.metadata.section_title:
                        parent_doc_header += f"Section: {parent_semantic_chunk.metadata.section_title}\n"

                    # Include page numbers for citation
                    if parent_semantic_chunk.metadata.start_page == parent_semantic_chunk.metadata.end_page:
                        parent_doc_header += f"Page: {parent_semantic_chunk.metadata.start_page}\n"
                    else:
                        parent_doc_header += f"Pages: {parent_semantic_chunk.metadata.start_page}-{parent_semantic_chunk.metadata.end_page}\n"

                    parent_doc_header += f"Chunk {parent_idx+1}/{len(parent_semantic_chunks)}\n---\n"

                    # Create PARENT Chunk object
                    parent_chunk_uuid = str(uuid.uuid4())
                    parent_full_text = parent_doc_header + parent_semantic_chunk.text

                    parent_chunk = Chunk(
                        id=parent_chunk_uuid,
                        patient_ref=pseudo_patient,
                        encounter_ref=None,
                        resource_type="pdf_document",
                        key=parent_semantic_chunk.metadata.chunk_id,
                        text=parent_full_text,
                        strategy_id="SemanticPDFChunker",
                        strategy_version="1.0",
                        timestamp=pdf.uploaded_at,
                        meta={
                            "filename": pdf.filename,
                            "title": pdf.metadata.title,
                            "author": pdf.metadata.author,
                            "start_page": parent_semantic_chunk.metadata.start_page,
                            "end_page": parent_semantic_chunk.metadata.end_page,
                            "section_title": parent_semantic_chunk.metadata.section_title,
                            "chunk_index": parent_idx,
                            "total_chunks": len(parent_semantic_chunks),
                            "chunk_level": "parent",
                            "child_chunk_ids": []  # Will populate below
                        },
                        has_phi=False
                    )
                    final_chunks.append(parent_chunk)

                    # STEP 3: Split THIS parent chunk into child chunks
                    child_semantic_chunks = child_chunker.chunk_pdf_text(
                        parent_semantic_chunk.text,  # 🔑 Chunk from PARENT text, not full PDF
                        f"{pdf.document_id}_parent_{parent_idx}",
                        {
                            "title": pdf.metadata.title,
                            "author": pdf.metadata.author,
                            "filename": pdf.filename,
                            "uploaded_at": pdf.uploaded_at.strftime('%Y-%m-%d %H:%M'),
                            "parent_chunk_id": parent_chunk_uuid
                        }
                    )

                    # Create CHILD Chunk objects from this parent
                    child_chunk_ids = []
                    for child_idx, child_semantic_chunk in enumerate(child_semantic_chunks):
                        # Build child document header
                        child_doc_header = base_doc_header

                        if child_semantic_chunk.metadata.section_title:
                            child_doc_header += f"Section: {child_semantic_chunk.metadata.section_title}\n"

                        # Include page numbers for citation
                        if child_semantic_chunk.metadata.start_page == child_semantic_chunk.metadata.end_page:
                            child_doc_header += f"Page: {child_semantic_chunk.metadata.start_page}\n"
                        else:
                            child_doc_header += f"Pages: {child_semantic_chunk.metadata.start_page}-{child_semantic_chunk.metadata.end_page}\n"

                        child_doc_header += f"Child {child_idx+1}/{len(child_semantic_chunks)}\n---\n"

                        child_chunk_uuid = str(uuid.uuid4())
                        child_full_text = child_doc_header + child_semantic_chunk.text

                        child_chunk = Chunk(
                            id=child_chunk_uuid,
                            patient_ref=pseudo_patient,
                            encounter_ref=None,
                            resource_type="pdf_document",
                            key=child_semantic_chunk.metadata.chunk_id,
                            text=child_full_text,
                            strategy_id="SemanticPDFChunker",
                            strategy_version="1.0",
                            timestamp=pdf.uploaded_at,
                            meta={
                                "filename": pdf.filename,
                                "title": pdf.metadata.title,
                                "author": pdf.metadata.author,
                                "start_page": child_semantic_chunk.metadata.start_page,
                                "end_page": child_semantic_chunk.metadata.end_page,
                                "section_title": child_semantic_chunk.metadata.section_title,
                                "chunk_index": child_idx,
                                "total_chunks": len(child_semantic_chunks),
                                "chunk_level": "child",
                                "parent_chunk_id": parent_chunk_uuid  # 🔑 Natural parent-child link
                            },
                            has_phi=False
                        )
                        final_chunks.append(child_chunk)
                        child_chunk_ids.append(child_chunk_uuid)

                    # Update parent's child_chunk_ids
                    parent_chunk.meta["child_chunk_ids"] = child_chunk_ids
                    logger.info(f"  Parent chunk {parent_idx}: {len(child_chunk_ids)} child chunks")

        if not final_chunks:
            return []

        # Count parent and child chunks
        parent_count = len([c for c in final_chunks if c.meta.get("chunk_level") == "parent"])
        child_count = len([c for c in final_chunks if c.meta.get("chunk_level") == "child"])

        logger.info(f"Created {len(final_chunks)} total chunks from {len(pdf_documents)} PDF documents ({parent_count} parent + {child_count} child, parent-child hierarchical chunking)")

        return final_chunks

    def _build_pdf_table_chunks(self, tables: list[ParsedTable], pdf: PDFDocument, pseudo_patient: str) -> list[Chunk]:
        """Create parent/child chunks from parsed tables."""
        from optimed.core.domain import Chunk

        if not tables:
            return []

        table_chunks: list[Chunk] = []
        for table in tables:
            parent_uuid = str(uuid.uuid4())
            parent_chunk = Chunk(
                id=parent_uuid,
                patient_ref=pseudo_patient,
                encounter_ref=None,
                resource_type="pdf_table",
                key=f"{pdf.document_id}_table_{table.table_id}",
                text=table.to_json(pdf.document_id),
                strategy_id="PDFTableParser",
                strategy_version="1.0",
                timestamp=pdf.uploaded_at,
                meta={
                    "filename": pdf.filename,
                    "title": pdf.metadata.title,
                    "page_number": table.page_number,
                    "chunk_level": "parent",
                    "chunk_type": "pdf_table",
                    "table_id": table.table_id,
                    "child_chunk_ids": [],
                },
                has_phi=False,
            )
            table_chunks.append(parent_chunk)

            for row in table.rows:
                child_uuid = str(uuid.uuid4())
                child_chunk = Chunk(
                    id=child_uuid,
                    patient_ref=pseudo_patient,
                    encounter_ref=None,
                    resource_type="pdf_table",
                    key=f"{row.row_id}",
                    text=row.to_json(table.table_id, table.page_number, pdf.document_id),
                    strategy_id="PDFTableParser",
                    strategy_version="1.0",
                    timestamp=pdf.uploaded_at,
                    meta={
                        "filename": pdf.filename,
                        "title": pdf.metadata.title,
                        "page_number": table.page_number,
                        "chunk_level": "child",
                        "chunk_type": "pdf_table",
                        "table_id": table.table_id,
                        "row_id": row.row_id,
                        "parent_chunk_id": parent_uuid,
                    },
                    has_phi=False,
                )
                parent_chunk.meta["child_chunk_ids"].append(child_uuid)
                table_chunks.append(child_chunk)

        return table_chunks

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
            n_class = N_MAX

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

    async def _evaluate_chunk_sufficiency(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        scores: list[float],
        classification: Optional[str] = None,
        attempt: int = 0
    ) -> tuple[bool, str]:
        """
        Agentic evaluation of retrieved chunks using LLM.

        Args:
            query: The original clinical query
            chunks: Retrieved chunks with content and metadata
            scores: Cross-encoder relevance scores for each chunk
            classification: Query type classification (lookup/summary/temporal/etc)
            attempt: Current refinement attempt number

        Returns:
            tuple[bool, str]: (is_sufficient, reasoning)
                - is_sufficient: True if chunks are adequate, False if need refinement
                - reasoning: Ultra minimal (2-3 sentences) explaining what's missing
        """
        # Prepare chunk summaries with scores
        chunk_summaries = []
        for i, (chunk, score) in enumerate(zip(chunks, scores)):
            # Use full content for sufficiency evaluation as requested
            content_full = chunk.get('content', '') or ''
            chunk_summaries.append(
                f"[Chunk {i+1}, Score: {score:.3f}] {content_full}"
            )

        prompt = (
            f"You are evaluating if retrieved clinical chunks are sufficient to answer the query.\n\n"
            f"Query: {query}\n"
            f"Query Type: {classification or 'general'}\n"
            f"Refinement Attempt: {attempt}/{RETRY_MAX}\n"
            f"Retrieved Chunks ({len(chunks)} total):\n" + "\n".join(chunk_summaries) + "\n\n"
            f"Evaluate if these chunks are sufficient to answer the query. Consider:\n"
            f"- Do chunks contain relevant clinical information?\n"
            f"- Are there gaps in temporal coverage, medication details, lab results, or clinical context?\n"
            f"- Given the query type, is the chunk count and diversity adequate?\n\n"
            f"Return JSON with:\n"
            f'{{"is_sufficient": true/false, "reasoning": "2-3 sentence explanation of what\'s missing if insufficient"}}'
        )

        try:
            resp = await self._llm.chat([
                ChatMessage(role=ChatRole.SYSTEM, content="You are a clinical information retrieval expert. Evaluate chunk sufficiency concisely."),
                ChatMessage(role=ChatRole.USER, content=prompt),
            ], json_mode=True)

            if resp and resp.content:
                content = resp.content.strip()
                # Handle markdown code blocks
                if content.startswith("```"):
                    start = content.find('\n') + 1
                    end = content.rfind("```")
                    if start > 0 and end > start:
                        content = content[start:end].strip()

                result = json.loads(content)
                is_sufficient = result.get('is_sufficient', False)
                reasoning = result.get('reasoning', 'No reasoning provided')

                logger.info(f"Agentic evaluation: sufficient={is_sufficient}, reasoning={reasoning}")
                return (is_sufficient, reasoning)

        except Exception as e:
            logger.warning(f"Agentic evaluation failed: {e}, defaulting to insufficient")
            return (False, "Evaluation failed, retrying with refined queries")

        # Default fallback: consider insufficient if we got here
        return (False, "Unable to evaluate chunks, attempting refinement")

    async def _refine_queries(
        self,
        query: str,
        seen_passages: list[str],
        insufficiency_reasoning: str = ""
    ) -> list[str]:
        """
        Generate refined queries based on what's missing from retrieved chunks.

        Args:
            query: Original clinical query
            seen_passages: Already-retrieved chunk contents
            insufficiency_reasoning: LLM-generated reasoning about what's missing

        Returns:
            list[str]: Up to 2 refined queries targeting missing aspects
        """
        # Include reasoning in prompt to guide query refinement
        reasoning_context = (
            f"\n\nWHAT'S MISSING: {insufficiency_reasoning}\n"
            if insufficiency_reasoning else ""
        )

        prompt = (
            "Given the clinical query, partial relevant passages, and analysis of what's missing, "
            "propose up to 2 refined queries that target the missing information. "
            "Return a JSON array of strings only.\n\n"
            f"Query: {query}\n"
            f"Passages:\n- " + "\n- ".join([(p or "")[:300] for p in seen_passages]) +
            reasoning_context
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
                        "description": "Analysis complete",
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
                        # Log the task exception with full traceback for debugging
                        import logging
                        import traceback
                        logging.error(f"Graph task failed with exception: {task_exception}")
                        logging.error(f"Full traceback:\n{traceback.format_exc()}")

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

    
