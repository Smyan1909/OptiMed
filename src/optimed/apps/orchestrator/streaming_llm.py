from typing import List, Optional, Any
from optimed.core.domain import ChatMessage, ChatRole
from optimed.core.ports import LLMClient

class StreamingLLMWrapper:
    """Wrapper that captures LLM reasoning and makes it available for streaming."""
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.current_reasoning = ""
        self.reasoning_steps: List[Any] = []
    
    async def chat_with_reasoning(
        self, 
        messages: List[ChatMessage], 
        state=None,
        reasoning_prompt: Optional[str] = None,
        **kwargs
    ) -> ChatMessage:
        """
        Chat with the LLM while capturing its reasoning process.
        """
        # Step 1: Get the LLM to think through the problem
        if reasoning_prompt:
            thinking_messages = messages + [
                ChatMessage(
                    role=ChatRole.USER, 
                    content=f"""Before providing your final response, please think through this step by step:

{reasoning_prompt}

Structure your thinking process clearly, explaining your reasoning for each step. Then provide your final response.

Format your response as:
THINKING:
[Your step-by-step reasoning here]

RESPONSE:
[Your final response here]"""
                )
            ]
        else:
            thinking_messages = messages + [
                ChatMessage(
                    role=ChatRole.USER, 
                    content="""Before providing your final response, please think through this step by step.

Structure your thinking process clearly, explaining your reasoning for each step. Then provide your final response.

Format your response as:
THINKING:
[Your step-by-step reasoning here]

RESPONSE:
[Your final response here]"""
                )
            ]
        
        # Update state to show we're getting LLM reasoning
        if state:
            state.step_status = "in_progress"
            state.step_details = "AI model analyzing and reasoning through the problem..."
        
        # Get the full response with reasoning
        full_response = await self.llm_client.chat(thinking_messages, **kwargs)
        
        # Parse the thinking and response sections
        content = full_response.content
        thinking_section = ""
        final_response = ""
        
        if "THINKING:" in content and "RESPONSE:" in content:
            # Extract thinking section
            thinking_start = content.find("THINKING:") + len("THINKING:")
            response_start = content.find("RESPONSE:")
            thinking_section = content[thinking_start:response_start].strip()
            
            # Extract final response
            final_response = content[response_start + len("RESPONSE:"):].strip()
        else:
            # Fallback if format isn't followed
            final_response = content
            thinking_section = "The AI model processed this request."
        
        # Store reasoning for streaming
        self.current_reasoning = thinking_section
        self.reasoning_steps = self._parse_reasoning_steps(thinking_section)
        
        # Update state with reasoning
        if state:
            state.llm_reasoning = thinking_section
            state.reasoning_steps = self.reasoning_steps
            state.step_details = "AI model completed reasoning process"
        
        # Return the final response
        return ChatMessage(
            role=ChatRole.ASSISTANT,
            content=final_response,
            metadata={
                **full_response.metadata,
                "reasoning": thinking_section,
                "reasoning_steps": self.reasoning_steps
            }
        )
    
    def _parse_reasoning_steps(self, reasoning: str) -> List[str]:
        """Parse reasoning into discrete steps."""
        steps = []
        
        # Split by numbered steps, bullet points, or paragraphs
        lines = reasoning.split('\n')
        current_step = ""
        
        for line in lines:
            line = line.strip()
            if not line:
                if current_step:
                    steps.append(current_step.strip())
                    current_step = ""
                continue
            
            # Check if this starts a new step (numbered, bulleted, etc.)
            if (line.startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.')) or
                line.startswith(('•', '-', '*')) or
                line.startswith(('First', 'Second', 'Next', 'Then', 'Finally'))):
                
                if current_step:
                    steps.append(current_step.strip())
                current_step = line
            else:
                current_step += " " + line if current_step else line
        
        # Add the last step
        if current_step:
            steps.append(current_step.strip())
        
        return steps if steps else [reasoning]
    
    async def chat(self, messages: List[ChatMessage], **kwargs) -> ChatMessage:
        """Regular chat without reasoning capture."""
        return await self.llm_client.chat(messages, **kwargs)