from typing import List, Optional, Any, AsyncGenerator
from datetime import datetime
from optimed.core.domain import ChatMessage, ChatRole
from optimed.core.ports import LLMClient

class StreamingLLMWrapper:
    """Wrapper that captures LLM reasoning and makes it available for streaming."""
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.current_reasoning = ""
        self.reasoning_steps: List[Any] = []
    
    async def chat_with_reasoning_stream(
        self, 
        messages: List[ChatMessage], 
        state=None,
        reasoning_prompt: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Chat with the LLM while streaming both reasoning and response.
        Yields updates about reasoning and text generation.
        """
        # Step 1: Get the LLM's reasoning process first
        if reasoning_prompt:
            reasoning_messages = messages + [
                ChatMessage(
                    role=ChatRole.USER,
                    content=f"""Before responding to the user, please think through your reasoning process step by step. Consider this guidance:

{reasoning_prompt}

Explain your reasoning process clearly, including:
- How you're interpreting the question
- What key factors you're considering
- What sources or knowledge you're drawing from
- How you're arriving at your conclusions

Provide only your reasoning process here - not the final answer yet."""
                )
            ]
        else:
            reasoning_messages = messages + [
                ChatMessage(
                    role=ChatRole.USER,
                    content="""Before responding to the user, please think through your reasoning process step by step.

Explain your reasoning process clearly, including:
- How you're interpreting the question
- What key factors you're considering
- What sources or knowledge you're drawing from
- How you're arriving at your conclusions

Provide only your reasoning process here - not the final answer yet."""
                )
            ]

        # Step 2: Prepare messages for the actual response
        if reasoning_prompt:
            response_messages = messages + [
                ChatMessage(
                    role=ChatRole.USER,
                    content=f"""Please consider this guidance when responding:

{reasoning_prompt}

Provide a clear, well-reasoned response addressing the user's question directly."""
                )
            ]
        else:
            response_messages = messages + [
                ChatMessage(
                    role=ChatRole.USER,
                    content="""Please provide a clear, well-reasoned response to the user's question."""
                )
            ]
        
        # Update state to show we're getting LLM reasoning
        if state:
            state.step_status = "in_progress"
            state.step_details = "AI model analyzing and reasoning through the problem..."

        # Step 1: Get reasoning process (non-streaming for clarity)
        reasoning_content = ""

        yield {
            "type": "reasoning_start",
            "timestamp": datetime.now().isoformat(),
            "message": "AI is thinking through the problem..."
        }

        try:
            # Get reasoning first (non-streaming to capture complete reasoning)
            reasoning_response = await self.llm_client.chat(reasoning_messages, **kwargs)
            reasoning_content = reasoning_response.content

            # Parse reasoning steps
            reasoning_steps = self._parse_reasoning_steps(reasoning_content)
            self.current_reasoning = reasoning_content
            self.reasoning_steps = reasoning_steps

            # Update state with reasoning
            if state:
                state.llm_reasoning = reasoning_content
                state.reasoning_steps = reasoning_steps
                state.reasoning_complete = True

            yield {
                "type": "reasoning_complete",
                "reasoning": reasoning_content,
                "reasoning_steps": reasoning_steps
            }

            # Step 2: Now stream the actual response
            yield {
                "type": "response_start",
                "message": "Generating response..."
            }

            response_content = ""
            async for chunk in self.llm_client.chat_stream(response_messages, **kwargs): # type: ignore
                response_content += chunk

                # Stream content directly as it comes
                yield {
                    "type": "content",
                    "content": chunk,
                    "accumulated_content": response_content
                }
                        
        except Exception as e:
            # Handle network errors gracefully
            import logging
            logging.error(f"Streaming LLM error: {e}")
            # If we have partial content, yield it
            if 'response_content' in locals() and response_content:
                yield {
                    "type": "content",
                    "content": response_content,
                    "accumulated_content": response_content,
                    "timestamp": datetime.now().isoformat()
                }

                yield {
                    "type": "completion",
                    "full_content": response_content,
                    "reasoning": reasoning_content,
                    "reasoning_steps": getattr(self, 'reasoning_steps', []),
                    "timestamp": datetime.now().isoformat()
                }
                return
            # Re-raise the original exception if we couldn't handle it
            raise

        # Final completion
        yield {
            "type": "completion",
            "full_content": response_content,
            "reasoning": reasoning_content,
            "reasoning_steps": self.reasoning_steps
        }

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
        # Step 1: Get the LLM's reasoning process first
        if reasoning_prompt:
            reasoning_messages = messages + [
                ChatMessage(
                    role=ChatRole.USER,
                    content=f"""Before responding to the user, please think through your reasoning process step by step. Consider this guidance:

{reasoning_prompt}

Explain your reasoning process clearly, including:
- How you're interpreting the question
- What key factors you're considering
- What sources or knowledge you're drawing from
- How you're arriving at your conclusions

Provide only your reasoning process here - not the final answer yet."""
                )
            ]
        else:
            reasoning_messages = messages + [
                ChatMessage(
                    role=ChatRole.USER,
                    content="""Before responding to the user, please think through your reasoning process step by step.

Explain your reasoning process clearly, including:
- How you're interpreting the question
- What key factors you're considering
- What sources or knowledge you're drawing from
- How you're arriving at your conclusions

Provide only your reasoning process here - not the final answer yet."""
                )
            ]

        # Step 2: Prepare messages for the actual response
        if reasoning_prompt:
            response_messages = messages + [
                ChatMessage(
                    role=ChatRole.USER,
                    content=f"""Please consider this guidance when responding:

{reasoning_prompt}

Provide a clear, well-reasoned response addressing the user's question directly."""
                )
            ]
        else:
            response_messages = messages + [
                ChatMessage(
                    role=ChatRole.USER,
                    content="""Please provide a clear, well-reasoned response to the user's question."""
                )
            ]

        # Update state to show we're getting LLM reasoning
        if state:
            state.step_status = "in_progress"
            state.step_details = "AI model analyzing and reasoning through the problem..."

        # Get reasoning first
        reasoning_response = await self.llm_client.chat(reasoning_messages, **kwargs)
        reasoning_content = reasoning_response.content

        # Parse reasoning steps
        reasoning_steps = self._parse_reasoning_steps(reasoning_content)
        self.current_reasoning = reasoning_content
        self.reasoning_steps = reasoning_steps

        # Get the actual response
        response = await self.llm_client.chat(response_messages, **kwargs)
        content = response.content

        # Update state
        if state:
            state.llm_reasoning = reasoning_content
            state.reasoning_steps = reasoning_steps
            state.step_details = "AI model completed processing"

        # Return the response with reasoning metadata
        return ChatMessage(
            role=ChatRole.ASSISTANT,
            content=content,
            metadata={
                **response.metadata,
                "reasoning": reasoning_content,
                "reasoning_steps": reasoning_steps
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
    
    async def chat_stream(self, messages: List[ChatMessage], **kwargs) -> AsyncGenerator[str, None]:
        """Stream chat response directly."""
        async for chunk in self.llm_client.chat_stream(messages, **kwargs): # type: ignore
            yield chunk

    async def chat(self, messages: List[ChatMessage], **kwargs) -> ChatMessage:
        """Regular chat without reasoning capture."""
        return await self.llm_client.chat(messages, **kwargs)