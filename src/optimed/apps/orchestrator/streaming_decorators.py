from functools import wraps
from typing import Callable

class StreamingStatus:
    """Context manager for streaming status updates."""
    
    def __init__(self, state, step_name: str, description: str, is_long_running: bool = False, estimated_time: str = ""):
        self.state = state
        self.step_name = step_name
        self.description = description
        self.is_long_running = is_long_running
        self.estimated_time = estimated_time
    
    async def __aenter__(self):
        self.state.current_step = self.step_name
        self.state.step_status = "starting"
        # Use the dynamic description generator
        self.state.step_details = self._generate_detailed_description("starting")
        self.state.completed_steps += 1
        self.state.progress_percentage = (self.state.completed_steps / self.state.total_steps) * 100
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.state.step_status = "completed"
            self.state.step_details = self._generate_detailed_description("completed")
        else:
            self.state.step_status = "error"
            self.state.step_details = f"Error in {self.step_name}: {str(exc_val)}"
    
    def update(self, details: str, status: str = "in_progress"):
        """Update status mid-operation."""
        self.state.step_status = status
        self.state.step_details = details
    
    def _generate_detailed_description(self, status: str) -> str:
        """Generate detailed descriptions based on step name and current state."""
        step_lower = self.step_name.lower()
        
        if status == "starting":
            return self._get_starting_description(step_lower)
        elif status == "completed":
            return self._get_completed_description(step_lower)
        else:
            return f"{self.step_name}: {status}"
    
    def _get_starting_description(self, step_lower: str) -> str:
        """Get detailed starting descriptions."""
        descriptions = {
            "load_user_context": f"Loading user profile and permissions for user ID: {getattr(self.state, 'user_id', 'unknown')}",
            "fetch_patient": f"Retrieving patient data from medical records for patient ID: {getattr(self.state, 'patient_id', 'unknown')}",
            "store_patient_chunks": f"Breaking down patient context into searchable chunks for patient {getattr(self.state, 'patient_id', 'unknown')}",
            "intelligent_retrieve_chunks": f"Analyzing clinical records using AI to find information relevant to: '{getattr(self.state, 'user_prompt', '')[:50]}...'",
            "evaluate_web_search_need": f"Evaluating if current medical literature search is needed for query: '{getattr(self.state, 'user_prompt', '')[:50]}...'",
            "perform_web_search": f"Searching latest medical literature and clinical guidelines for: '{getattr(self.state, 'user_prompt', '')[:50]}...'",
            "evaluate_image_generation_need": f"Analyzing if visual medical illustrations would help explain concepts for: '{getattr(self.state, 'user_prompt', '')[:50]}...'",
            "generate_image": f"Creating educational medical illustration: '{getattr(self.state, 'image_generation_prompt', '')[:100]}...'",
            "load_current_session_history": f"Loading conversation history for session {getattr(self.state, 'session_id', 'unknown')}",
            "evaluate_cross_session_history_need": "Evaluating if previous conversations from other sessions are relevant",
            "search_cross_session_history": "Searching previous conversations across all sessions for relevant context",
            "diagnose": "AI model analyzing all available information to provide comprehensive response...",
            "store_user_message": f"Storing user message in chat history for session {getattr(self.state, 'session_id', 'unknown')}",
            "store_assistant_response": "Saving AI response and reasoning to chat history"
        }
        
        return descriptions.get(step_lower, f"Starting {self.step_name}...")
    
    def _get_completed_description(self, step_lower: str) -> str:
        """Get detailed completion descriptions with actual results."""
        if step_lower == "load_user_context":
            user_context = getattr(self.state, 'user_context', None)
            if user_context:
                return f"Loaded user context: {user_context.display_name} ({user_context.role.value})"
            else:
                return "No user context found - continuing as anonymous user"
        
        elif step_lower == "fetch_patient":
            patient_ctx = getattr(self.state, 'patient_ctx', None)
            if patient_ctx:
                return f"Successfully loaded patient: {patient_ctx.name}, Age: {patient_ctx.age}, Sex: {patient_ctx.sex}"
            else:
                return "Patient data retrieval failed"
        
        elif step_lower == "store_patient_chunks":
            return "Successfully stored patient data chunks (demographics, vitals, labs, journal entries)"
        
        elif step_lower == "intelligent_retrieve_chunks":
            chunks = getattr(self.state, 'retrieved_chunks', [])
            reasoning = getattr(self.state, 'retrieval_reasoning', "")
            return f"Selected {len(chunks)} relevant clinical data chunks. {reasoning[:100]}..." if reasoning else f"Selected {len(chunks)} relevant clinical data chunks"
        
        elif step_lower == "evaluate_web_search_need":
            needs_search = getattr(self.state, 'web_search_performed', False)
            return f"Web search {'required' if needs_search else 'not needed'} - {'will search latest medical literature' if needs_search else 'sufficient information available locally'}"
        
        elif step_lower == "perform_web_search":
            web_response = getattr(self.state, 'web_search_response', None)
            if web_response and web_response.results:
                return f"Found {len(web_response.results)} relevant medical sources: {web_response.summary[:100]}..."
            else:
                return "Web search completed but no relevant sources found"
        
        elif step_lower == "evaluate_image_generation_need":
            needs_image = getattr(self.state, 'image_generation_needed', False)
            prompt = getattr(self.state, 'image_generation_prompt', "")
            return f"Image generation {'recommended' if needs_image else 'not needed'}{f': {prompt[:100]}...' if prompt else ''}"
        
        elif step_lower == "generate_image":
            generated_image = getattr(self.state, 'generated_image', None)
            if generated_image:
                return f"Successfully generated medical illustration (ID: {generated_image.generation_id})"
            else:
                return "Image generation failed - continuing without illustration"
        
        elif step_lower == "load_current_session_history":
            history = getattr(self.state, 'chat_history', [])
            return f"Loaded {len(history)} previous messages from current session"
        
        elif step_lower == "evaluate_cross_session_history_need":
            needs_search = getattr(self.state, 'needs_cross_session_search', False)
            return f"Cross-session history {'needed' if needs_search else 'not required'} - {'will search previous conversations' if needs_search else 'current context sufficient'}"
        
        elif step_lower == "search_cross_session_history":
            history = getattr(self.state, 'relevant_cross_session_history', [])
            return f"Found {len(history)} relevant messages from previous sessions"
        
        elif step_lower == "diagnose":
            response = getattr(self.state, 'llm_response', None)
            if response:
                return f"AI analysis complete - generated {len(response.content)} character response"
            else:
                return "AI analysis completed"
        
        elif step_lower == "store_user_message":
            return "User message stored in chat history"
        
        elif step_lower == "store_assistant_response":
            reasoning_stored = hasattr(self.state, 'llm_reasoning') and getattr(self.state, 'llm_reasoning', '') # type: ignore 
            image_stored = hasattr(self.state, 'generated_image') and getattr(self.state, 'generated_image', None)
            return f"AI response saved to chat history{' with reasoning' if reasoning_stored else ''}{' and image' if image_stored else ''}"
        
        # Fallback
        return f"Completed {self.step_name}"

def streaming_step(step_name: str, description: str = "", is_long_running: bool = False, estimated_time: str = ""):
    """
    Decorator to automatically handle streaming status for graph nodes.
    Now generates detailed descriptions automatically based on step name and state.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(state, *args, **kwargs):
            async with StreamingStatus(state, step_name, description, is_long_running, estimated_time) as status:
                # For long-running operations, update status periodically
                if is_long_running:
                    status.update(f"Processing {step_name} (this may take {estimated_time})", "in_progress")
                
                result = await func(state, *args, **kwargs)
                return result
        return wrapper
    return decorator