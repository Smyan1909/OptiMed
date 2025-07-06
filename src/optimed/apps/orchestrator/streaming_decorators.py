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
        self.state.step_details = self.description
        self.state.completed_steps += 1
        self.state.progress_percentage = (self.state.completed_steps / self.state.total_steps) * 100
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.state.step_status = "completed"
            self.state.step_details = f"{self.description} - Complete"
        else:
            self.state.step_status = "error"
            self.state.step_details = f"{self.description} - Error: {str(exc_val)}"
    
    def update(self, details: str, status: str = "in_progress"):
        """Update status mid-operation."""
        self.state.step_status = status
        self.state.step_details = details

def streaming_step(step_name: str, description: str, is_long_running: bool = False, estimated_time: str = ""):
    """Decorator to automatically handle streaming status for graph nodes."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(state, *args, **kwargs):
            async with StreamingStatus(state, step_name, description, is_long_running, estimated_time) as status:
                # For long-running operations, update status periodically
                if is_long_running:
                    status.update(f"{description} (this may take {estimated_time})", "in_progress")
                
                result = await func(state, *args, **kwargs)
                return result
        return wrapper
    return decorator