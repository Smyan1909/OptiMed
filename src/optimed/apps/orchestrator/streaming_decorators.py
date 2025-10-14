from functools import wraps
from typing import Callable, Any
from optimed.core.logging_utils import get_logger, log_error
from optimed.core.streaming_messages import get_message

logger = get_logger(__name__)

class StreamingStatus:
    """
    Context manager for streaming status updates with language-aware messages.

    Uses the streaming_messages module to provide localized status updates
    in English or Swedish based on the user's language preference.
    """

    def __init__(self, state, step_name: str, description: str = "", is_long_running: bool = False, estimated_time: str = ""):
        self.state = state
        self.step_name = step_name
        self.description = description  # Legacy parameter, kept for compatibility
        self.is_long_running = is_long_running
        self.estimated_time = estimated_time

    async def __aenter__(self):
        # Get language from state, default to English
        language = getattr(self.state, 'user_language', 'en')

        self.state.current_step = self.step_name
        self.state.step_status = "starting"

        # Use the new localized message system
        self.state.step_details = self._get_localized_message("starting", language)

        # Increment step counter (no percentage-based progress bar)
        self.state.completed_steps += 1

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Get language from state, default to English
        language = getattr(self.state, 'user_language', 'en')

        if exc_type is None:
            self.state.step_status = "completed"
            self.state.step_details = self._get_localized_message("completed", language)
        else:
            self.state.step_status = "error"
            # Error messages in the appropriate language
            error_prefix = "Fel i" if language == "sv" else "Error in"
            self.state.step_details = f"{error_prefix} {self.step_name}: {str(exc_val)}"

    def update(self, details: str, status: str = "in_progress"):
        """Update status mid-operation with custom details."""
        self.state.step_status = status
        self.state.step_details = details
    
    def update_diagnosis_progress(self, diagnosis_name: str, step: str, progress_detail: str = ""):
        """Special update method for differential diagnosis computation."""
        language = getattr(self.state, 'user_language', 'en')

        self.state.step_status = "computing_differential"
        self.state.prelim_diagnosis_name = diagnosis_name
        self.state.diff_diag_compute_step = step

        # Create localized status message
        analyzing_text = "Analyserar" if language == "sv" else "Analyzing"
        if progress_detail:
            status_message = f"{analyzing_text} {diagnosis_name}: {step} - {progress_detail}"
        else:
            status_message = f"{analyzing_text} {diagnosis_name}: {step}"

        self.state.step_details = status_message

        # Emit streaming update if callback exists
        if hasattr(self.state, 'stream_callback') and self.state.stream_callback:
            import asyncio
            update = {
                "type": "differential_diagnosis_progress",
                "diagnosis_name": diagnosis_name,
                "step": step,
                "details": progress_detail,
                "message": status_message,
                "timestamp": None  # Will be set by the receiver
            }
            # Schedule the callback to run asynchronously
            try:
                asyncio.create_task(self.state.stream_callback(update))
            except Exception as e:
                log_error(logger, "emit_differential_diagnosis_update", e)
    
    def _get_localized_message(self, status: str, language: str) -> str:
        """
        Get a localized message for the current step and status.

        Args:
            status: The status ("starting", "completed", etc.)
            language: Language code ("en" or "sv")

        Returns:
            Localized message with context from state
        """
        step_lower = self.step_name.lower()

        # Gather context data from state for message formatting
        kwargs: dict[str, Any] = {}

        # Common context
        if hasattr(self.state, 'user_prompt') and self.state.user_prompt:
            kwargs['query'] = self.state.user_prompt[:50]

        # User context
        if step_lower == "load_user_context" and status == "completed":
            user_context = getattr(self.state, 'user_context', None)
            if user_context:
                kwargs['user_name'] = user_context.display_name
                kwargs['user_role'] = user_context.role.value
                return get_message(step_lower, "completed", language, **kwargs)
            else:
                return get_message(step_lower, "completed_anonymous", language)

        # Patient context
        elif step_lower == "fetch_patient" and status == "completed":
            patient_ctx = getattr(self.state, 'patient_ctx', None)
            if patient_ctx:
                kwargs['patient_name'] = patient_ctx.name
                kwargs['patient_age'] = patient_ctx.age
                kwargs['patient_sex'] = patient_ctx.sex
                return get_message(step_lower, "completed", language, **kwargs)
            else:
                return get_message(step_lower, "failed", language)

        # Retrieval context
        elif step_lower == "intelligent_retrieve_chunks":
            if status == "completed":
                chunks = getattr(self.state, 'retrieved_chunks', [])
                chunk_analysis = getattr(self.state, 'chunk_analysis', {})
                kwargs['chunk_count'] = len(chunks)

                if chunk_analysis:
                    kwargs['total_processed'] = chunk_analysis.get("total_chunks_processed", 0)
                    reasoning = getattr(self.state, 'retrieval_reasoning', "")
                    if reasoning:
                        kwargs['reasoning'] = reasoning[:100]
                        return get_message(step_lower, "completed_with_reasoning", language, **kwargs)

                return get_message(step_lower, "completed", language, **kwargs)

        # Web search
        elif step_lower == "perform_web_search" and status == "completed":
            web_response = getattr(self.state, 'web_search_response', None)
            if web_response and web_response.results:
                kwargs['count'] = len(web_response.results)
                return get_message(step_lower, "completed", language, **kwargs)
            else:
                return get_message(step_lower, "failed", language)

        # Evaluation steps with conditional completions
        elif step_lower in ["evaluate_web_search_need", "evaluate_image_generation_need",
                           "evaluate_query_complexity", "evaluate_icd_parsing_need"]:
            if status == "completed":
                # Determine which completion message to use
                if step_lower == "evaluate_web_search_need":
                    needed = getattr(self.state, 'web_search_performed', False)
                elif step_lower == "evaluate_image_generation_need":
                    needed = getattr(self.state, 'image_generation_needed', False)
                elif step_lower == "evaluate_query_complexity":
                    needed = getattr(self.state, 'requires_full_processing', False)
                else:  # evaluate_icd_parsing_need
                    needed = getattr(self.state, 'should_parse_icd_codes', False)

                completion_status = "completed_needed" if needed else "completed_not_needed"
                if step_lower == "evaluate_query_complexity":
                    completion_status = "completed_full" if needed else "completed_simple"

                return get_message(step_lower, completion_status, language, **kwargs)

        # Differential diagnoses
        elif step_lower == "parse_icd" and status == "completed":
            parsed_response = getattr(self.state, 'parsed_response', None)
            if parsed_response and hasattr(parsed_response, 'differential') and parsed_response.differential:
                diag_count = len(parsed_response.differential)
                diag_names = [d.diagnosis_name for d in parsed_response.differential[:3]]
                names_display = ", ".join(diag_names)
                if diag_count > 3:
                    and_more = "och" if language == "sv" else "and"
                    names_display += f" {and_more} {diag_count - 3} " + ("fler" if language == "sv" else "more")
                kwargs['count'] = diag_count
                kwargs['diagnoses'] = names_display
                return get_message(step_lower, "completed", language, **kwargs)
            else:
                return get_message(step_lower, "completed_none", language)

        # Session history
        elif step_lower in ["load_current_session_history", "search_cross_session_history"]:
            if status == "completed":
                if step_lower == "load_current_session_history":
                    history = getattr(self.state, 'chat_history', [])
                else:
                    history = getattr(self.state, 'relevant_cross_session_history', [])
                kwargs['count'] = len(history)
                return get_message(step_lower, "completed", language, **kwargs)

        # Note generation
        elif step_lower == "load_note_template":
            if status == "starting":
                template_type = getattr(self.state, 'note_template_type_preference', 'journal entry')
                kwargs['template_type'] = template_type
            elif status == "completed":
                note_template = getattr(self.state, 'note_template', None)
                if note_template and hasattr(note_template, 'name'):
                    kwargs['template_name'] = note_template.name
                    return get_message(step_lower, "completed", language, **kwargs)

        elif step_lower == "generate_note_section" and status == "completed":
            note_sections = getattr(self.state, 'note_sections', {})
            note_content = getattr(self.state, 'note_final_content', '')
            kwargs['section_count'] = len(note_sections)
            kwargs['char_count'] = len(note_content)
            return get_message(step_lower, "completed", language, **kwargs)

        elif step_lower == "format_note_response" and status == "completed":
            note_sources = getattr(self.state, 'note_sources', [])
            kwargs['citation_count'] = len(note_sources)
            return get_message(step_lower, "completed", language, **kwargs)

        # Timeline
        elif step_lower == "extract_timeline_events" and status == "completed":
            # Assuming timeline events are stored somewhere
            kwargs['count'] = getattr(self.state, 'timeline_event_count', 0)
            return get_message(step_lower, "completed", language, **kwargs)

        # PDF/XML documents
        elif step_lower in ["fetch_pdfs", "fetch_xmls"] and status == "completed":
            # Get document counts from the correct state fields
            if step_lower == "fetch_pdfs":
                count = len(getattr(self.state, 'uploaded_pdfs', []))
            else:
                count = len(getattr(self.state, 'uploaded_xmls', []))
            kwargs['count'] = count
            if count > 0:
                return get_message(step_lower, "completed", language, **kwargs)
            else:
                return get_message(step_lower, "failed", language)

        # Query classification
        elif step_lower == "classify_query_intent" and status == "completed":
            intent = getattr(self.state, 'query_intent', 'general')
            kwargs['intent'] = intent
            return get_message(step_lower, "completed", language, **kwargs)

        # Default: Use the basic message from the translation system
        return get_message(step_lower, status, language, **kwargs)

def streaming_step(step_name: str, description: str = "", is_long_running: bool = False, estimated_time: str = ""):
    """
    Decorator to automatically handle streaming status for graph nodes.

    Generates localized descriptions automatically based on step name and state.
    The description parameter is kept for backward compatibility but is no longer required.

    Args:
        step_name: Identifier for this step (e.g., "fetch_patient", "diagnose")
        description: Legacy parameter, kept for compatibility (not used)
        is_long_running: Whether this is a long-running operation
        estimated_time: Estimated time for long-running operations

    Example:
        @streaming_step("fetch_patient")
        async def fetch_patient_data(state):
            # ... implementation
            return state
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(state, *args, **kwargs):
            async with StreamingStatus(state, step_name, description, is_long_running, estimated_time) as status:
                # For long-running operations, optionally update status with time estimate
                if is_long_running and estimated_time:
                    language = getattr(state, 'user_language', 'en')
                    processing_text = "Bearbetar" if language == "sv" else "Processing"
                    may_take_text = "detta kan ta" if language == "sv" else "this may take"
                    status.update(f"{processing_text} {step_name} ({may_take_text} {estimated_time})", "in_progress")

                result = await func(state, *args, **kwargs)
                return result
        return wrapper
    return decorator