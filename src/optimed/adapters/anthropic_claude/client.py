from __future__ import annotations

import os 
from typing import Sequence, cast, Optional

import anthropic 
from anthropic.types import Message, MessageParam

from optimed.core.domain import ChatMessage, ChatRole, PatientContext, DICOMMetadata, ImagePixelData
from optimed.core.ports import LLMClient, VisionLLMClient

import numpy as np 
from PIL import Image
import io
import base64

"""
Adapter: Anthropic Claude
Implements the LLMClient Protocol defined in core/ports.py.
"""

class AnthropicClaudeClient(LLMClient, VisionLLMClient):
    """
    Thin async wrapper around the Anthropic Claude API.
    - Converts our domain-level ChatMessage list to Claude format
    - Returns a new ChatMessage(role="ASSISTANT", ...)
    """

    def __init__(
            self,
            *,
            model: str = "claude-opus-4-20250514",
            api_key: str | None = None,
            timeout: float | None = None,
    ) -> None:
        
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
            timeout=timeout,
        )
        self._model = model

    async def chat(
            self,
            messages: Sequence[ChatMessage],
            json_mode: bool = False, 
            temperature: float = 0.7,
            max_tokens: int | None = None,
    ) -> ChatMessage:
        """
        • Pull out the *first* system prompt (optional)
        • Map USER / ASSISTANT turns → Claude’s schema
        • Fire the request asynchronously
        • Wrap the assistant answer back into our ChatMessage VO
        """
        system_prompt: str | None = None
        claude_msgs: list[dict[str, str]] = []

        for msg in messages:
            if msg.role is ChatRole.SYSTEM and system_prompt is None:
                system_prompt = msg.content
            else:
                claude_msgs.append({
                    "role": msg.role.value,
                    "content": msg.content
                })
        
        if json_mode:
            json_instruction = """Please respond with valid JSON only. Do not include any text outside of the JSON structure. 

IMPORTANT: Your response must be properly formatted JSON that can be parsed. If you cannot provide the requested information, return a valid JSON object with appropriate null/empty values rather than no response at all.

Example format:
{
    "field1": "value1",
    "field2": ["item1", "item2"],
    "field3": 0.5
}"""
            if system_prompt is not None:
                system_prompt = f"{system_prompt}\n\n{json_instruction}"
            else:
                system_prompt = json_instruction


        claude_msgs_typed = cast("list[MessageParam]", claude_msgs)

        response: Message | None = None

        if system_prompt is not None:
            response = await self._client.messages.create(
                model=self._model,
                messages=claude_msgs_typed,
                system=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens or 4096,  # Claude's default max tokens
            )
        else:
            response = await self._client.messages.create(
                model=self._model,
                messages=claude_msgs_typed,
                temperature=temperature,
                max_tokens=max_tokens or 4096,  # Claude's default max tokens
            )

        assistant_text = "".join(
            getattr(block, "text", "") for block in response.content
            if getattr(block, "type", None) == "text"
        )

        return ChatMessage(
            role=ChatRole.ASSISTANT,
            content=assistant_text,
            metadata={
                "model": self._model, 
                "response_id": response.id,
                "input_tokens": str(response.usage.input_tokens),
                "output_tokens": str(response.usage.output_tokens)
                },
        )
    
    async def analyze_dicom_image(
        self, 
        pixel_data: ImagePixelData, 
        metadata: DICOMMetadata,
        query: str,
        patient_context: Optional[PatientContext] = None
    ) -> str:
        """Analyze a DICOM image and provide medical insights."""
        try:
            # Convert pixel data to base64 image
            image_b64 = await self._pixel_data_to_base64(pixel_data)
            
            # Create analysis prompt
            metadata_text = self._format_metadata_for_analysis(metadata)
            context_text = self._format_patient_context(patient_context) if patient_context else ""
            
            prompt = f"""You are an expert radiologist analyzing a DICOM medical image.

DICOM Metadata:
{metadata_text}

{f"Patient Context:\n{context_text}\n" if context_text else ""}

Clinical Question: {query}

Please analyze this medical image and provide:
1. Key findings and observations
2. Any abnormalities or areas of concern  
3. Clinical impressions based on the imaging findings
4. Recommendations for further evaluation if needed
{"5. How findings relate to the patient's clinical history" if patient_context else ""}

Focus on being accurate, detailed, and clinically relevant. If you cannot make definitive diagnoses, clearly state limitations and suggest appropriate follow-up."""

            messages: list[MessageParam] = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64
                            }
                        }
                    ]
                }
            ]
            
            response = await self._client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                messages=messages
            )
            
            response_text = ""
            for block in response.content:
                if hasattr(block, 'text') and block.type == "text":
                    response_text += block.text
            
            return response_text
            
        except Exception as e:
            print(f"Error in DICOM image analysis: {e}")
            return "I apologize, but I encountered an error while analyzing the DICOM image. Please try again or consult with a radiologist directly."
    
    async def _pixel_data_to_base64(self, pixel_data: ImagePixelData) -> str:
        """Convert pixel data to base64 encoded PNG image."""
        try:
            # Convert numpy array to PIL Image
            if pixel_data.pixel_array.ndim == 3:
                # Handle multi-slice images by taking the middle slice
                middle_slice = pixel_data.pixel_array.shape[0] // 2
                img_array = pixel_data.pixel_array[middle_slice]
            else:
                img_array = pixel_data.pixel_array
            
            # Normalize to 0-255 range
            img_array = img_array.astype(np.float32)
            img_array = (img_array - img_array.min()) / (img_array.max() - img_array.min()) * 255
            img_array = img_array.astype(np.uint8)
            
            # Create PIL Image
            pil_image = Image.fromarray(img_array)
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
            
            # Convert to PNG bytes
            buffer = io.BytesIO()
            pil_image.save(buffer, format='PNG')
            # Fix: Get bytes from buffer correctly
            png_bytes = buffer.getvalue()
            
            # Encode to base64
            return base64.b64encode(png_bytes).decode('utf-8')
            
        except Exception as e:
            raise ValueError(f"Failed to convert pixel data to base64: {e}")
    
    def _format_metadata_for_analysis(self, metadata: DICOMMetadata) -> str:
        """Format DICOM metadata for analysis prompt."""
        parts = []
        
        if metadata.modality:
            parts.append(f"Modality: {metadata.modality.value}")
        if metadata.body_part_examined:
            parts.append(f"Body Part: {metadata.body_part_examined}")
        if metadata.study_description:
            parts.append(f"Study: {metadata.study_description}")
        if metadata.series_description:
            parts.append(f"Series: {metadata.series_description}")
        if metadata.patient_name:
            parts.append(f"Patient: {metadata.patient_name}")
        if metadata.study_date:
            parts.append(f"Study Date: {metadata.study_date}")
        if metadata.slice_thickness:
            parts.append(f"Slice Thickness: {metadata.slice_thickness}mm")
        if metadata.pixel_spacing:
            parts.append(f"Pixel Spacing: {metadata.pixel_spacing}")
        
        return "\n".join(parts) if parts else "Limited metadata available"
    
    def _format_patient_context(self, context: PatientContext) -> str:
        """Format patient context for analysis."""
        parts = []
        
        # Basic patient info
        parts.append(f"Age: {context.age}")
        parts.append(f"Sex: {context.sex}")
        
        # Vitals
        if context.vitals:
            vital_items = list(context.vitals.items())[:3]  # Show top 3
            vital_strs = [f"{k}: {v}" for k, v in vital_items]
            if vital_strs:
                parts.append(f"Recent Vitals: {', '.join(vital_strs)}")
        
        # Lab results
        if context.labs:
            lab_items = list(context.labs.items())[:3]  # Show top 3
            lab_strs = [f"{k}: {v}" for k, v in lab_items]
            if lab_strs:
                parts.append(f"Recent Labs: {', '.join(lab_strs)}")
        
        # Medications
        if context.medications:
            med_items = list(context.medications.items())[:5]  # Show top 5
            med_strs = [f"{k}: {v}" for k, v in med_items]
            if med_strs:
                parts.append(f"Current Medications: {', '.join(med_strs)}")
        
        # Allergies
        if context.allergies:
            allergy_items = list(context.allergies.items())
            allergy_strs = [f"{k}: {v}" for k, v in allergy_items]
            if allergy_strs:
                parts.append(f"Known Allergies: {', '.join(allergy_strs)}")
        
        # Diagnoses
        if context.diagnoses:
            diagnosis_items = list(context.diagnoses.items())[:5]  # Show top 5
            diagnosis_strs = [f"{k}: {v}" for k, v in diagnosis_items]
            if diagnosis_strs:
                parts.append(f"Active Diagnoses: {', '.join(diagnosis_strs)}")
        
        # Imaging studies
        if context.imaging:
            imaging_items = list(context.imaging.items())[:3]  # Show top 3
            imaging_strs = [f"{k}: {v}" for k, v in imaging_items]
            if imaging_strs:
                parts.append(f"Recent Imaging: {', '.join(imaging_strs)}")
        
        # Social history
        if context.social_history:
            social_items = list(context.social_history.items())[:3]  # Show top 3
            social_strs = [f"{k}: {v}" for k, v in social_items]
            if social_strs:
                parts.append(f"Social History: {', '.join(social_strs)}")
        
        return "\n".join(parts) if parts else ""
    