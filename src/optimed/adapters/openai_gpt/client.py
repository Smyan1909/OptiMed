# type: ignore
from __future__ import annotations

import os 
from typing import Sequence, Optional, AsyncGenerator

import openai
from openai.types.chat import ChatCompletion

from optimed.core.domain import ChatMessage, ChatRole, PatientContext, DICOMMetadata, ImagePixelData
from optimed.core.ports import LLMClient, VisionLLMClient

import numpy as np 
from PIL import Image
import io
import base64

"""
Adapter: OpenAI GPT-4o
Implements the LLMClient and VisionLLMClient Protocols defined in core/ports.py.
"""

class OpenAIGPT4oClient(LLMClient, VisionLLMClient):
    """
    Async wrapper around the OpenAI GPT-4o API.
    - Converts our domain-level ChatMessage list to OpenAI format
    - Returns a new ChatMessage(role="ASSISTANT", ...)
    - Supports vision capabilities for DICOM image analysis
    """

    def __init__(
            self,
            *,
            model: str = "gpt-4o",
            api_key: str | None = None,
            timeout: float | None = None,
    ) -> None:
        
        self._client = openai.AsyncOpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
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
        • Convert ChatMessage sequence to OpenAI format
        • Handle system messages appropriately
        • Fire the request asynchronously
        • Wrap the assistant answer back into our ChatMessage VO
        """
        openai_msgs: list[dict[str, str]] = []

        for msg in messages:
            openai_msgs.append({
                "role": msg.role.value,
                "content": msg.content
            })
        
        # Configure response format for JSON mode
        response_format = {"type": "json_object"} if json_mode else {"type": "text"}
        
        if json_mode:
            json_instruction = """Please respond with valid JSON only. Do not include any text outside of the JSON structure. 

IMPORTANT: Your response must be properly formatted JSON that can be parsed. If you cannot provide the requested information, return a valid JSON object with appropriate null/empty values rather than no response at all.

Example format:
{
    "field1": "value1",
    "field2": ["item1", "item2"],
    "field3": 0.5
}"""
            
            # Add JSON instruction to the last user message or create a new system message
            if openai_msgs and openai_msgs[-1]["role"] == "user":
                openai_msgs[-1]["content"] = f"{openai_msgs[-1]['content']}\n\n{json_instruction}"
            else:
                openai_msgs.append({
                    "role": "system",
                    "content": json_instruction
                })

        response: ChatCompletion = await self._client.chat.completions.create(
            model=self._model,
            messages=openai_msgs,
            temperature=temperature,
            max_tokens=max_tokens or 4096,  # GPT-4o default max tokens
            response_format=response_format
        )

        assistant_text = response.choices[0].message.content or ""

        return ChatMessage(
            role=ChatRole.ASSISTANT,
            content=assistant_text,
            metadata={
                "model": self._model, 
                "response_id": response.id,
                "input_tokens": str(response.usage.prompt_tokens) if response.usage else "0",
                "output_tokens": str(response.usage.completion_tokens) if response.usage else "0",
                "total_tokens": str(response.usage.total_tokens) if response.usage else "0"
                },
        )

    async def chat_stream(
        self,
        messages: Sequence[ChatMessage],
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[str, None]:
        
        openai_msgs: list[dict[str, str]] = []

        for msg in messages:
            openai_msgs.append({
                "role": msg.role.value,
                "content": msg.content
            })
        
        # Configure response format for JSON mode
        response_format = {"type": "json_object"} if json_mode else {"type": "text"}
        
        if json_mode:
            json_instruction = """Please respond with valid JSON only. Do not include any text outside of the JSON structure. 

IMPORTANT: Your response must be properly formatted JSON that can be parsed. If you cannot provide the requested information, return a valid JSON object with appropriate null/empty values rather than no response at all.

Example format:
{
    "field1": "value1",
    "field2": ["item1", "item2"],
    "field3": 0.5
}"""
            
            # Add JSON instruction to the last user message or create a new system message
            if openai_msgs and openai_msgs[-1]["role"] == "user":
                openai_msgs[-1]["content"] = f"{openai_msgs[-1]['content']}\n\n{json_instruction}"
            else:
                openai_msgs.append({
                    "role": "system",
                    "content": json_instruction
                })

        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=openai_msgs,
            temperature=temperature,
            max_tokens=max_tokens or 4096,
            response_format=response_format,
            stream=True
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def analyze_dicom_image(
        self, 
        pixel_data: ImagePixelData, 
        metadata: DICOMMetadata,
        query: str,
        patient_context: Optional[PatientContext] = None
    ) -> str:
        """Analyze a DICOM image and provide medical insights."""
        try:
            # Convert pixel data to base64 for OpenAI Vision API
            base64_image = await self._pixel_data_to_base64(pixel_data)
            
            # Format metadata for analysis
            metadata_text = self._format_metadata_for_analysis(metadata)
            
            # Format patient context if available
            patient_text = ""
            if patient_context:
                patient_text = self._format_patient_context(patient_context)
            
            # Create the analysis prompt
            analysis_prompt = f"""You are an expert radiologist analyzing medical imaging. Please analyze this DICOM image and provide clinical insights.

Query: {query}

DICOM Metadata:
{metadata_text}

{patient_text}

Please provide:
1. Detailed description of visible structures and findings
2. Any abnormalities or areas of concern
3. Clinical interpretation relevant to the query
4. Recommendations for further evaluation if appropriate

Important: Your analysis should be thorough but remember that final diagnostic decisions should always be made by qualified healthcare providers."""

            # Prepare messages with image content
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": analysis_prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}",
                                "detail": "high"  # Use high detail for medical imaging
                            }
                        }
                    ]
                }
            ]

            response = await self._client.chat.completions.create(
                model="gpt-4o",  # Ensure we use vision-capable model
                messages=messages,
                max_tokens=2000,
                temperature=0.3  # Lower temperature for medical analysis
            )

            return response.choices[0].message.content or "Unable to analyze image"

        except Exception as e:
            raise ValueError(f"Failed to analyze DICOM image: {e}")

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
            png_bytes = buffer.getvalue()
            
            # Encode to base64
            return base64.b64encode(png_bytes).decode('utf-8')
            
        except Exception as e:
            raise ValueError(f"Failed to convert pixel data to base64: {e}")

    def _format_metadata_for_analysis(self, metadata: DICOMMetadata) -> str:
        """Format DICOM metadata for analysis prompt."""
        formatted_lines = []
        
        # Key metadata fields for medical analysis
        key_fields = [
            ("Study Description", metadata.study_description),
            ("Series Description", metadata.series_description),
            ("Modality", metadata.modality),
            ("Body Part", metadata.body_part_examined),
            ("Patient Position", metadata.patient_position),
            ("Slice Thickness", f"{metadata.slice_thickness}mm" if metadata.slice_thickness else None),
            ("Pixel Spacing", f"{metadata.pixel_spacing}" if metadata.pixel_spacing else None),
            ("Window Center", metadata.window_center),
            ("Window Width", metadata.window_width),
            ("Study Date", metadata.study_date),
            ("Institution", metadata.institution_name)
        ]
        
        for label, value in key_fields:
            if value:
                formatted_lines.append(f"- {label}: {value}")
        
        return "\n".join(formatted_lines) if formatted_lines else "No metadata available"

    def _format_patient_context(self, context: PatientContext) -> str:
        """Format patient context for analysis."""
        patient_info = []
        
        if context.name:
            patient_info.append(f"Patient: {context.name}")
        if context.age:
            patient_info.append(f"Age: {context.age}")
        if context.sex:
            patient_info.append(f"Sex: {context.sex}")
        
        # Add relevant medical history
        if context.diagnoses:
            diagnoses_list = ", ".join([f"{k}: {v}" for k, v in list(context.diagnoses.items())[:3]])
            patient_info.append(f"Recent Diagnoses: {diagnoses_list}")
        
        if context.medications:
            meds_list = ", ".join([f"{k}: {v}" for k, v in list(context.medications.items())[:3]])
            patient_info.append(f"Current Medications: {meds_list}")
        
        if context.vitals:
            vitals_list = ", ".join([f"{k}: {v}" for k, v in list(context.vitals.items())[:3]])
            patient_info.append(f"Recent Vitals: {vitals_list}")
        
        return "\nPatient Context:\n" + "\n".join([f"- {info}" for info in patient_info]) if patient_info else ""