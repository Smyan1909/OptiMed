from __future__ import annotations


import json

from typing import Sequence
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

from optimed.core.domain import ChatMessage, ChatRole
from optimed.core.ports import LLMClient

"""
Adapter: Intelligent Internet II-Medical-8B-1706
Implements the LLMClient Protocol defined in core/ports.py.
This adapter uses the II-Medical-8B-1706 model for medical text generation.
"""

class IIMedicalClient(LLMClient):
    """
    Adapter for the Intelligent-Internet/II-Medical-8B-1706 model.
    Provides medical-focused text generation capabilities compatible with the patient_flow.py architecture.
    """

    def __init__(
        self,
        *,
        model_name: str = "Intelligent-Internet/II-Medical-8B-1706",
        device: str | None = None,
        max_length: int = 8192,
        temperature: float = 0.7,
        do_sample: bool = True,
        load_in_8bit: bool = False,
        load_in_4bit: bool = False,
    ) -> None:
        """
        Initialize the II-Medical client.
        
        Args:
            model_name: HuggingFace model identifier
            device: Device to run model on (auto-detected if None)
            max_length: Maximum context length
            temperature: Sampling temperature
            do_sample: Whether to use sampling
            load_in_8bit: Whether to load model in 8-bit precision
            load_in_4bit: Whether to load model in 4-bit precision
        """
        self.model_name = model_name
        self.max_length = max_length
        self.temperature = temperature
        self.do_sample = do_sample
        
        # Auto-detect device if not specified
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            
        # Load tokenizer and model
        try:
            print(f"[II-Medical] Loading tokenizer from {model_name}...")
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                trust_remote_code=True,
                padding_side="left"  # Better for generation
            )
            
            # Set pad token if not present
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
                self.tokenizer.pad_token_id = self.tokenizer.eos_token_id
            
            print(f"[II-Medical] Loading model from {model_name}...")
            
            # Configure model loading based on precision requirements
            model_kwargs = {
                "trust_remote_code": True,
                "torch_dtype": torch.float16 if self.device == "cuda" else torch.float32,
            }
            
            if load_in_4bit:
                from transformers import BitsAndBytesConfig
                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4"
                )
                model_kwargs["device_map"] = "auto"
            elif load_in_8bit:
                model_kwargs["load_in_8bit"] = True
                model_kwargs["device_map"] = "auto"
            elif self.device == "cuda":
                model_kwargs["device_map"] = "auto"
            
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name,
                **model_kwargs
            )
            
            # Move to device if not using device_map
            if not (load_in_8bit or load_in_4bit or model_kwargs.get("device_map")):
                self.model = self.model.to(self.device)
            
            # Set model to eval mode
            self.model.eval()
            
            print(f"[II-Medical] Model loaded successfully on {self.device}")
                
        except Exception as e:
            raise RuntimeError(f"Failed to load II-Medical model: {e}")

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatMessage:
        """
        Generate a response using the II-Medical model.
        Compatible with the patient_flow.py diagnostic engine.
        
        Args:
            messages: Conversation history
            json_mode: Whether to request JSON output
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Returns:
            ChatMessage with the model's response
        """
        try:
            # Format conversation for the model
            prompt = self._format_messages(messages, json_mode)
            
            # Truncate prompt if too long to leave room for generation
            max_prompt_length = self.max_length - (max_tokens or 1024)
            
            # Tokenize input
            inputs = self.tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=max_prompt_length,
                padding=False
            ).to(self.device)
            
            # Prepare generation parameters
            generation_kwargs = {
                "max_new_tokens": max_tokens or 1024,
                "temperature": temperature,
                "do_sample": self.do_sample and temperature > 0,
                "pad_token_id": self.tokenizer.pad_token_id,
                "eos_token_id": self.tokenizer.eos_token_id,
                "repetition_penalty": 1.1,
            }
            
            # Add sampling parameters only if do_sample is True
            if generation_kwargs["do_sample"]:
                generation_kwargs.update({
                    "top_p": 0.9,
                    "top_k": 50,
                })
            
            # Generate response
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    **generation_kwargs
                )
            
            # Decode response (skip input tokens)
            generated_text = self.tokenizer.decode(
                outputs[0][inputs['input_ids'].shape[1]:],
                skip_special_tokens=True
            ).strip()
            
            # Clean up the response
            generated_text = self._clean_response(generated_text, json_mode)
            
            # Calculate token usage for metadata
            input_tokens = inputs['input_ids'].shape[1]
            output_tokens = outputs[0].shape[0] - input_tokens
            
            return ChatMessage(
                role=ChatRole.ASSISTANT,
                content=generated_text,
                metadata={
                    "model": self.model_name,
                    "temperature": str(temperature),
                    "max_tokens": str(max_tokens or 1024),
                    "device": self.device,
                    "input_tokens": str(input_tokens),
                    "output_tokens": str(output_tokens),
                    "json_mode": str(json_mode)
                }
            )
            
        except Exception as e:
            error_msg = f"Error generating response with II-Medical model: {e}"
            print(f"[II-Medical] {error_msg}")
            return ChatMessage(
                role=ChatRole.ASSISTANT,
                content="I apologize, but I encountered an error while processing your request. Please try again.",
                metadata={"error": error_msg, "model": self.model_name}
            )

    def _format_messages(self, messages: Sequence[ChatMessage], json_mode: bool = False) -> str:
        """
        Format messages into a prompt suitable for the II-Medical model.
        Uses chat template if available, otherwise falls back to custom formatting.
        """
        try:
            # Try to use the model's chat template if available
            if hasattr(self.tokenizer, 'apply_chat_template') and hasattr(self.tokenizer, 'chat_template') and self.tokenizer.chat_template:
                # Convert ChatMessage objects to the format expected by apply_chat_template
                formatted_messages = []
                for msg in messages:
                    formatted_messages.append({
                        "role": msg.role.value,
                        "content": msg.content
                    })
                
                # Add JSON mode instruction to the last user message if needed
                if json_mode and formatted_messages:
                    last_user_idx = None
                    for i in range(len(formatted_messages) - 1, -1, -1):
                        if formatted_messages[i]["role"] == "user":
                            last_user_idx = i
                            break
                    
                    if last_user_idx is not None:
                        json_instruction = "\n\nIMPORTANT: Respond with valid JSON only. Do not include any text outside of the JSON structure."
                        formatted_messages[last_user_idx]["content"] += json_instruction
                
                return self.tokenizer.apply_chat_template(
                    formatted_messages,
                    tokenize=False,
                    add_generation_prompt=True
                )
            
        except Exception as e:
            print(f"[II-Medical] Failed to use chat template: {e}, falling back to custom formatting")
        
        # Fallback to custom formatting compatible with medical instruction models
        return self._custom_format_messages(messages, json_mode)

    def _custom_format_messages(self, messages: Sequence[ChatMessage], json_mode: bool = False) -> str:
        """
        Custom message formatting for medical instruction following.
        """
        prompt_parts = []
        
        # Add system instruction for medical context
        system_instruction = (
            "You are II-Medical, an AI assistant specialized in medical analysis and healthcare. "
            "Provide accurate, evidence-based medical information while being clear about limitations. "
            "Always recommend consulting healthcare professionals for medical decisions. "
            "Be precise, clinical, and helpful in your responses."
        )
        
        if json_mode:
            json_instruction = (
                "\n\nIMPORTANT: Respond with valid JSON only. Do not include any text outside of the JSON structure. "
                "If you cannot provide the requested information, return a valid JSON object with appropriate null/empty values."
            )
            system_instruction += json_instruction
        
        # Use a medical instruction format
        prompt_parts.append(f"### System:\n{system_instruction}\n")
        
        # Process conversation messages
        for msg in messages:
            if msg.role == ChatRole.SYSTEM:
                # Additional system messages
                prompt_parts.append(f"### System:\n{msg.content}\n")
            elif msg.role == ChatRole.USER:
                prompt_parts.append(f"### Human:\n{msg.content}\n")
            elif msg.role == ChatRole.ASSISTANT:
                prompt_parts.append(f"### Assistant:\n{msg.content}\n")
        
        # Add assistant prompt for generation
        prompt_parts.append("### Assistant:\n")
        
        return "\n".join(prompt_parts)

    def _clean_response(self, response: str, json_mode: bool = False) -> str:
        """Clean up the generated response."""
        # Remove common artifacts
        response = response.strip()
        
        # Remove repetitive patterns
        lines = response.split('\n')
        cleaned_lines = []
        prev_line = ""
        
        for line in lines:
            line = line.strip()
            # Skip empty lines and repetitive content
            if line and line != prev_line:
                cleaned_lines.append(line)
                prev_line = line
        
        response = '\n'.join(cleaned_lines)
        
        # For JSON mode, try to extract valid JSON
        if json_mode:
            response = self._extract_json(response)
        
        return response

    def _extract_json(self, text: str) -> str:
        """Extract JSON from potentially mixed content."""
        try:
            # First, try to parse the entire text as JSON
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON blocks
        import re
        
        # Look for JSON-like structures
        json_patterns = [
            r'\{.*\}',  # Single-line JSON
            r'\{[\s\S]*\}',  # Multi-line JSON
        ]
        
        for pattern in json_patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    json.loads(match)
                    return match
                except json.JSONDecodeError:
                    continue
        
        # If no valid JSON found, return a default error JSON
        return '{"error": "Could not generate valid JSON", "content": "' + text.replace('"', '\\"')[:200] + '"}'

    def cleanup(self) -> None:
        """Clean up model resources."""
        try:
            if hasattr(self, 'model'):
                del self.model
            if hasattr(self, 'tokenizer'):
                del self.tokenizer
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print("[II-Medical] Resources cleaned up")
        except Exception as e:
            print(f"[II-Medical] Error during cleanup: {e}")

    def __del__(self):
        """Ensure cleanup on deletion."""
        try:
            self.cleanup()
        except:
            pass