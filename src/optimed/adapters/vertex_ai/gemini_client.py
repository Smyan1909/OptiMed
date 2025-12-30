from __future__ import annotations

import os
import json
import asyncio
import tempfile
from typing import Sequence, AsyncGenerator, List, Dict, Any, Optional

import vertexai
from vertexai.generative_models import (
    GenerativeModel,
    ChatSession,
    Part,
    Content,
)
from google.oauth2 import service_account

import numpy as np
from PIL import Image
import io
import base64

from optimed.core.domain import ChatMessage, ChatRole, PatientContext, DICOMMetadata, ImagePixelData
from optimed.core.ports import LLMClient, VisionLLMClient


class VertexAIGeminiClient(LLMClient, VisionLLMClient):
    """
    Async wrapper around Vertex AI Gemini 2.5 Flash for fast responses.

    Notes:
    - Uses Vertex AI GenerativeModel API with Gemini 2.5 Flash
    - Defaults to eu-west1 region for European deployment
    - Implements the LLMClient protocol used across the app
    - Supports JSON mode and chunk citations similar to Azure OpenAI adapter
    """

    def __init__(
        self,
        *,
        model: str = "gemini-2.5-flash",
        project_id: str | None = None,
        location: str = "europe-west1",
        timeout: float | None = None,
        default_max_tokens: int | None = None,
        credentials_path: str | None = None,
        service_account_json: str | None = None,
    ) -> None:
        # Initialize Vertex AI with project and location
        self._project_id = project_id or os.getenv("VERTEX_AI_PROJECT_ID")
        if not self._project_id:
            raise ValueError(
                "VERTEX_AI_PROJECT_ID must be set as environment variable or provided as project_id parameter. "
                "Set it via: export VERTEX_AI_PROJECT_ID='your-project-id'"
            )
        
        self._location = location or os.getenv("VERTEX_AI_LOCATION", "europe-west1")
        self._model_name = model or os.getenv("VERTEX_AI_MODEL", "gemini-2.5-flash")
        self._timeout = timeout

        # Handle credentials - support multiple methods:
        # 1. Service account JSON as string (from env var or parameter)
        # 2. Path to service account JSON file
        # 3. Application Default Credentials (fallback)
        
        service_account_json_content = service_account_json or os.getenv("VERTEX_AI_SERVICE_ACCOUNT_JSON")
        credentials_file = credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        
        if service_account_json_content:
            # Parse JSON string and create temporary credentials file
            try:
                # Validate it's valid JSON
                json.loads(service_account_json_content)
                # Create temporary file with credentials
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                    f.write(service_account_json_content)
                    temp_credentials_file = f.name
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_credentials_file
                self._temp_credentials_file = temp_credentials_file  # Store for cleanup if needed
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Invalid JSON in service account credentials: {e}. "
                    "Please provide valid JSON content."
                ) from e
        elif credentials_file:
            if not os.path.exists(credentials_file):
                raise ValueError(
                    f"Credentials file not found: {credentials_file}. "
                    "Please provide a valid path to your service account JSON key file."
                )
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_file
            self._temp_credentials_file = None
        else:
            # Will use Application Default Credentials
            self._temp_credentials_file = None

        # Initialize Vertex AI
        # This will use Application Default Credentials (ADC) if GOOGLE_APPLICATION_CREDENTIALS is set
        # or if gcloud auth application-default login was run
        try:
            vertexai.init(project=self._project_id, location=self._location)
        except Exception as e:
            raise ValueError(
                f"Failed to initialize Vertex AI: {e}. "
                "Please ensure you have set up authentication via one of these methods:\n"
                "1. Set GOOGLE_APPLICATION_CREDENTIALS to path of service account JSON file\n"
                "2. Run: gcloud auth application-default login\n"
                "3. Provide credentials_path parameter"
            ) from e

        # Create the GenerativeModel instance
        try:
            self._model = GenerativeModel(self._model_name)
        except Exception as e:
            raise ValueError(
                f"Failed to create GenerativeModel '{self._model_name}': {e}. "
                "Please verify the model name is correct and you have access to Vertex AI in the {self._location} region."
            ) from e

        # Allow configuration via environment variable
        if default_max_tokens is None:
            env_max = os.getenv("GEMINI_DEFAULT_MAX_TOKENS")
            self._default_max_tokens = int(env_max) if env_max else 8192
        else:
            self._default_max_tokens = default_max_tokens

    @staticmethod
    def _to_vertex_messages(messages: Sequence[ChatMessage]) -> List[Content]:
        """
        Convert ChatMessage sequence to Vertex AI Content format.
        Vertex AI uses a chat history format with role and parts.
        """
        vertex_messages: List[Content] = []
        
        for msg in messages:
            role = "user" if msg.role == ChatRole.USER else "model" if msg.role == ChatRole.ASSISTANT else "user"
            # For system messages, we'll prepend them to the first user message
            if msg.role == ChatRole.SYSTEM:
                # System messages are handled by prepending to the first user message
                continue
            
            vertex_messages.append(
                Content(
                    role=role,
                    parts=[Part.from_text(msg.content)]
                )
            )
        
        return vertex_messages

    def _add_system_message(self, messages: Sequence[ChatMessage], system_text: str) -> List[Content]:
        """Add system message to the beginning of the conversation."""
        vertex_messages = self._to_vertex_messages(messages)
        # Prepend system message as first user message
        if vertex_messages:
            # Add system instruction to the first message
            first_msg = vertex_messages[0]
            if first_msg.role == "user":
                # Prepend system instruction to first user message
                system_part = Part.from_text(system_text)
                first_msg.parts.insert(0, system_part)
        return vertex_messages

    async def chat(  # type: ignore
        self,
        messages: Sequence[ChatMessage],
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        enable_chunk_citations: bool = False,
    ) -> ChatMessage:
        """
        Send chat messages to Gemini and get a response.
        """
        # Chunk citations require JSON mode
        if enable_chunk_citations:
            json_mode = True

        # Convert messages to Vertex AI format
        vertex_messages = self._to_vertex_messages(messages)
        
        # Handle system messages - find and prepend to first user message
        system_instruction = None
        for msg in messages:
            if msg.role == ChatRole.SYSTEM:
                if system_instruction:
                    system_instruction += "\n\n" + msg.content
                else:
                    system_instruction = msg.content

        # Add JSON mode instructions if needed
        json_instruction = None
        if json_mode:
            if enable_chunk_citations:
                json_instruction = """RESPONSE FORMAT (REQUIRED):
You must respond with valid JSON in this exact structure:
{
  "response": "Your clinical response here. When using information from a source, include [X] immediately after the statement, where X is the citation number.",
  "cited_chunks": ["1", "2", "3"]
}

CITATION RULES:
1. The clinical information is labeled with "[Citation: 1]", "[Citation: 2]", etc.
2. Cite the source IMMEDIATELY after the sentence that uses its information
3. Use the EXACT number shown in the "[Citation: X]" markers - just put [X] after your statement
4. Example: If you see "[Citation: 3]\\nPatient is 87 years old", write "Patient is 87 years old [3]"
5. In cited_chunks, list the citation numbers you actually used (as strings)

IMPORTANT: Response must be valid JSON only. No text outside the JSON structure."""
            else:
                json_instruction = """STRICT JSON-ONLY RESPONSE REQUIRED:
- Return exactly ONE valid JSON object.
- Do NOT include any prose, markdown, code fences, or explanations.
- Do NOT include prefix/suffix text.
- If you cannot comply, return: {"response": "", "cited_chunks": []}"""

        # Start a chat session
        # Disable strict response validation to avoid blocking on safety/no-content finishes
        chat = self._model.start_chat(
            history=vertex_messages[:-1] if len(vertex_messages) > 1 else [],
            response_validation=False,
        )
        
        # Get the last message (user's current message)
        last_message = vertex_messages[-1].parts[0].text if vertex_messages else ""
        
        # Add system instruction to the prompt if present
        if system_instruction:
            prompt = f"{system_instruction}\n\n{last_message}"
        else:
            prompt = last_message

        # If JSON mode, append JSON instruction to the last user part to mirror Azure behavior
        if json_mode:
            prompt = f"{prompt}\n\n{json_instruction}"

        # Configure generation config
        generation_config: Dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens if max_tokens is not None else self._default_max_tokens,
        }
        if json_mode:
            generation_config["response_mime_type"] = "application/json"
            if max_tokens is None:
                generation_config["max_output_tokens"] = min(self._default_max_tokens, 2048)
            generation_config["temperature"] = min(temperature, 0.4)

        # Make the request (run in executor since vertexai may be sync)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: chat.send_message(
                prompt,
                generation_config=generation_config,
            )
        )

        assistant_text = self._extract_text_safe(response)

        # Parse cited chunks if chunk citations are enabled
        cited_chunk_ids = None
        if enable_chunk_citations and assistant_text:
            try:
                response_json = json.loads(assistant_text)
                cited_chunk_ids = response_json.get("cited_chunks", [])
                # Extract the actual response content
                assistant_text = response_json.get("response", assistant_text)
            except json.JSONDecodeError:
                # If parsing fails, return the raw text
                pass

        # Extract usage information if available
        usage_metadata = getattr(response, "usage_metadata", None)
        input_tokens = str(getattr(usage_metadata, "prompt_token_count", 0)) if usage_metadata else "0"
        output_tokens = str(getattr(usage_metadata, "candidates_token_count", 0)) if usage_metadata else "0"
        total_tokens = str(getattr(usage_metadata, "total_token_count", 0)) if usage_metadata else "0"
        response_id = getattr(response, "id", None) or getattr(response, "name", None) or ""

        return ChatMessage(
            role=ChatRole.ASSISTANT,
            content=assistant_text,
            cited_chunk_ids=cited_chunk_ids,
            metadata={
                "model": self._model_name,
                "project_id": self._project_id,
                "location": self._location,
                "response_id": response_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "reasoning_effort": "default",
            },
        )

    async def chat_stream(  # type: ignore
        self,
        messages: Sequence[ChatMessage],
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        enable_chunk_citations: bool = False,
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat responses from Gemini.
        """
        # Chunk citations require JSON mode
        if enable_chunk_citations:
            json_mode = True

        # Convert messages to Vertex AI format
        vertex_messages = self._to_vertex_messages(messages)
        
        # Handle system messages
        system_instruction = None
        for msg in messages:
            if msg.role == ChatRole.SYSTEM:
                if system_instruction:
                    system_instruction += "\n\n" + msg.content
                else:
                    system_instruction = msg.content

        # Add JSON mode instructions if needed
        if json_mode:
            if enable_chunk_citations:
                json_instruction = """RESPONSE FORMAT (REQUIRED):
You must respond with valid JSON in this exact structure:
{
  "response": "Your clinical response here. When using information from a source, include [X] immediately after the statement, where X is the citation number.",
  "cited_chunks": ["1", "2", "3"]
}

CITATION RULES:
1. The clinical information is labeled with "[Citation: 1]", "[Citation: 2]", etc.
2. Cite the source IMMEDIATELY after the sentence that uses its information
3. Use the EXACT number shown in the "[Citation: X]" markers - just put [X] after your statement
4. Example: If you see "[Citation: 3]\\nPatient is 87 years old", write "Patient is 87 years old [3]"
5. In cited_chunks, list the citation numbers you actually used (as strings)

IMPORTANT: Response must be valid JSON only. No text outside the JSON structure."""
            else:
                json_instruction = "Please return ONLY strict, valid JSON with no extra text."
            
            if system_instruction:
                system_instruction = f"{system_instruction}\n\n{json_instruction}"
            else:
                system_instruction = json_instruction

        # Start a chat session
        # Disable strict response validation to avoid blocking on safety/no-content finishes
        chat = self._model.start_chat(
            history=vertex_messages[:-1] if len(vertex_messages) > 1 else [],
            response_validation=False,
        )
        
        # Get the last message
        last_message = vertex_messages[-1].parts[0].text if vertex_messages else ""
        
        # Add system instruction to the prompt if present
        if system_instruction:
            prompt = f"{system_instruction}\n\n{last_message}"
        else:
            prompt = last_message

        # If JSON mode, append JSON instruction to the last user part to mirror Azure behavior
        if json_mode:
            prompt = f"{prompt}\n\n{json_instruction}"

        # Configure generation config
        generation_config: Dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens if max_tokens is not None else self._default_max_tokens,
        }
        if json_mode:
            generation_config["response_mime_type"] = "application/json"
            if max_tokens is None:
                generation_config["max_output_tokens"] = min(self._default_max_tokens, 2048)
            generation_config["temperature"] = min(temperature, 0.4)

        try:
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

            def produce_sync() -> None:
                try:
                    stream = chat.send_message(
                        prompt,
                        generation_config=generation_config,
                        stream=True
                    )
                    for chunk in stream:
                        text = getattr(chunk, "text", None)
                        if text:
                            loop.call_soon_threadsafe(queue.put_nowait, text)
                        elif hasattr(chunk, "parts") and getattr(chunk, "parts", None):
                            for part in chunk.parts:
                                part_text = getattr(part, "text", None)
                                if part_text:
                                    loop.call_soon_threadsafe(queue.put_nowait, part_text)
                except Exception as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, f"[stream_error]{exc}")
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            loop.run_in_executor(None, produce_sync)

            while True:
                item = await queue.get()
                if item is None:
                    break
                if item.startswith("[stream_error]"):
                    raise Exception(f"Failed to stream from Vertex AI Gemini: {item[len('[stream_error]'):] }")
                yield item

        except Exception as e:
            import logging
            logging.error(f"Vertex AI Gemini streaming error: {e}")
            raise Exception(f"Failed to stream from Vertex AI Gemini: {e}") from e

    async def analyze_dicom_image(
        self, 
        pixel_data: ImagePixelData, 
        metadata: DICOMMetadata,
        query: str,
        patient_context: Optional[PatientContext] = None
    ) -> str:
        """Analyze a DICOM image and provide medical insights."""
        try:
            # Convert pixel data to base64 for Gemini Vision API
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

            # Decode base64 image to bytes
            image_bytes = base64.b64decode(base64_image)
            
            # Create parts with text and image
            parts = [
                Part.from_text(analysis_prompt),
                Part.from_data(
                    data=image_bytes,
                    mime_type="image/png"
                )
            ]

            # Configure generation config for medical analysis
            generation_config = {
                "temperature": 0.3,  # Lower temperature for medical analysis
                "max_output_tokens": 2000,
            }

            # Make the request
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._model.generate_content(
                    parts,
                    generation_config=generation_config
                )
            )

            return response.text if hasattr(response, 'text') and response.text else "Unable to analyze image"

        except Exception as e:
            raise ValueError(f"Failed to analyze DICOM image: {e}") from e

    # --- Helpers ---
    def _extract_text_safe(self, response: Any) -> str:
        """
        Safely extract text from Vertex response.
        Handles cases where candidates are blocked or have no parts.
        """
        # Try response.text directly
        try:
            if hasattr(response, "text"):
                return response.text or ""
        except Exception:
            pass

        # Try candidates -> content.parts
        try:
            candidates = getattr(response, "candidates", []) or []
            if candidates:
                content = getattr(candidates[0], "content", None)
                if content:
                    parts = getattr(content, "parts", []) or []
                    texts = []
                    for p in parts:
                        txt = getattr(p, "text", None)
                        if txt:
                            texts.append(txt)
                    if texts:
                        return "".join(texts)
        except Exception:
            pass

        # Fallback: stringified response
        try:
            return str(response)
        except Exception:
            return ""

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
            raise ValueError(f"Failed to convert pixel data to base64: {e}") from e

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

