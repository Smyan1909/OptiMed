from __future__ import annotations

import json
import base64
import httpx
from typing import Optional, Tuple
from optimed.core.domain import ImageGenerationRequest, GeneratedImage, ImageGenerationContext, ChatMessage, ChatRole
from optimed.core.ports import ImageGenerationService, LLMClient
from optimed.core.logging_utils import get_logger, log_error

logger = get_logger(__name__)


class StabilityAIClient(ImageGenerationService):
    """Stability AI client for image generation using their cloud API."""
    
    def __init__(
        self,
        api_key: str,
        llm_client: Optional[LLMClient] = None,
        base_url: str = "https://api.stability.ai",
        model: str = "stable-diffusion-xl-1024-v1-0",
        timeout: int = 120
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.llm_client = llm_client
        self.timeout = timeout
        
        # Medical-safe defaults
        self.medical_negative_prompt = (
            "nsfw, nude, explicit, inappropriate, unprofessional, "
            "low quality, blurry, distorted, malformed, error, "
            "watermark, text, signature, gore, graphic violence"
        )
    
    async def is_available(self) -> bool:
        """Check if the Stability AI service is available."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json"
                }
                response = await client.get(
                    f"{self.base_url}/v1/user/account",
                    headers=headers
                )
                return response.status_code == 200
        except Exception as e:
            log_error(logger, "stability_ai_availability_check", e)
            return False
    
    async def evaluate_generation_need(
        self, 
        context: ImageGenerationContext
    ) -> Tuple[bool, Optional[str]]:
        """Evaluate if image generation would be helpful using LLM."""
        if not self.llm_client:
            return False, None
        
        try:
            # Create evaluation prompt
            evaluation_prompt = f"""
            Analyze this medical/healthcare query to determine if generating an educational image would be helpful:

            Query: "{context.user_query}"
            {"Patient Context: " + context.patient_context.name if context.patient_context else ""}
            {"Medical Context: " + context.medical_context if context.medical_context else ""}
            Purpose: {context.generation_purpose}

            Consider if the query would benefit from:
            - Anatomical illustrations (heart, lungs, brain, organs, etc.)
            - Medical procedure demonstrations
            - Educational diagrams (circulatory system, nervous system, etc.)
            - Visualization of medical concepts (cell structures, disease progression)
            - Comparative anatomical images
            - Medical equipment illustrations

            DO NOT generate images for:
            - Diagnostic purposes (actual medical diagnosis)
            - Patient-specific medical images or scans
            - Inappropriate or sensitive content
            - Simple text-based questions that don't need visual aids
            - Questions about medication dosages or specific treatments

            Respond with JSON:
            {{
                "should_generate": true/false,
                "image_prompt": "detailed prompt for educational image generation if needed",
                "reason": "explanation of why image generation would/wouldn't help"
            }}

            If should_generate is true, create a detailed, professional prompt for a medical illustration that would help explain the concept.
            """
            
            response = await self.llm_client.chat([
                ChatMessage(
                    role=ChatRole.SYSTEM,
                    content="You are a medical education specialist determining when visual aids would enhance learning. Be conservative and only recommend image generation when it would clearly help explain medical concepts."
                ),
                ChatMessage(role=ChatRole.USER, content=evaluation_prompt)
            ], json_mode=True)
            if not response or not response.content:
                        logger.warning("Empty response from LLM during image generation evaluation, using fallback values")
                        raise ValueError("Empty response from LLM")

                    # Strip whitespace and check if content is empty
            response_content = response.content.strip()
            if not response_content:
                logger.warning("Empty content in LLM response during image generation evaluation")
                raise ValueError("Empty content in response")

            # Remove markdown code block markers if present
            if response_content.startswith("```json"):
                # Find the end of the opening marker
                start_idx = response_content.find('\n') + 1
                # Find the closing marker
                end_idx = response_content.rfind("```")
                if start_idx > 0 and end_idx > start_idx:
                    response_content = response_content[start_idx:end_idx].strip()
            elif response_content.startswith("```"):
                # Handle generic code blocks
                start_idx = response_content.find('\n') + 1
                end_idx = response_content.rfind("```")
                if start_idx > 0 and end_idx > start_idx:
                    response_content = response_content[start_idx:end_idx].strip()

            data = json.loads(response_content)
            should_generate = data.get("should_generate", False)
            image_prompt = data.get("image_prompt") if should_generate else None

            logger.info(f"Image generation evaluation - Should generate: {should_generate}")
            if should_generate:
                logger.info("Generated image prompt for medical illustration")
            else:
                logger.info(f"Image generation not needed: {data.get('reason', 'Not specified')}")

            return should_generate, image_prompt

        except Exception as e:
            log_error(logger, "evaluate_image_generation_need", e)
            return False, None
    
    async def generate_image(self, request: ImageGenerationRequest) -> GeneratedImage:
        """Generate an image using Stability AI API."""
        try:
            # Enhance prompt for medical/educational context
            enhanced_prompt = self._enhance_medical_prompt(request.prompt)
            
            # Combine negative prompts
            negative_prompt = request.negative_prompt or ""
            if negative_prompt:
                negative_prompt += ", " + self.medical_negative_prompt
            else:
                negative_prompt = self.medical_negative_prompt
            
            # Prepare request payload for Stability AI
            payload = {
                "text_prompts": [
                    {
                        "text": enhanced_prompt,
                        "weight": 1.0
                    },
                    {
                        "text": negative_prompt,
                        "weight": -1.0
                    }
                ],
                "cfg_scale": request.guidance_scale,
                "height": request.height,
                "width": request.width,
                "steps": request.num_inference_steps,
                "samples": 1,
                "style_preset": "photographic"  # Good for medical illustrations
            }
            
            if request.seed is not None:
                payload["seed"] = request.seed
            
            # Make API request to Stability AI
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
                
                response = await client.post(
                    f"{self.base_url}/v1/generation/{self.model}/text-to-image",
                    json=payload,
                    headers=headers
                )


                if response.status_code != 200:
                    error_detail = response.text
                    logger.error(f"Stability AI API error: {response.status_code} - {error_detail}")
                    raise Exception(f"Stability AI API request failed: {response.status_code} - {error_detail}")
                
                result = response.json()
                
                # Get the first generated image
                if not result.get("artifacts"):
                    raise Exception("No images generated by Stability AI")
                
                image_data = result["artifacts"][0]
                image_b64 = image_data["base64"]
                
                # Convert base64 to bytes
                image_bytes = base64.b64decode(image_b64)
                
                # Create GeneratedImage object
                generated_image = GeneratedImage(
                    image_data=image_bytes,
                    image_format="png",
                    prompt=enhanced_prompt,
                    metadata={
                        "original_prompt": request.prompt,
                        "negative_prompt": negative_prompt,
                        "width": request.width,
                        "height": request.height,
                        "guidance_scale": request.guidance_scale,
                        "num_inference_steps": request.num_inference_steps,
                        "seed": image_data.get("seed"),
                        "user_id": request.user_id,
                        "patient_id": request.patient_id,
                        "session_id": request.session_id,
                        "model": self.model,
                        "style_preset": "photographic"
                    },
                    model_info={
                        "provider": "stability_ai",
                        "model": self.model,
                        "api_version": "v1",
                        "style_preset": "photographic"
                    }
                )

                logger.info(f"Successfully generated medical illustration: {generated_image.generation_id}")
                return generated_image

        except Exception as e:
            log_error(logger, "stability_ai_generate_image", e)
            raise Exception(f"Failed to generate image with Stability AI: {str(e)}")
    
    def _enhance_medical_prompt(self, prompt: str) -> str:
        """Enhance prompt for medical/educational context."""
        # Add medical illustration style keywords
        medical_keywords = [
            "professional medical illustration",
            "educational diagram",
            "anatomically accurate",
            "medical textbook style",
            "clean professional background",
            "detailed scientific accuracy",
            "high quality medical art",
            "educational healthcare visual"
        ]
        
        enhanced = f"{prompt}, {', '.join(medical_keywords)}"
        return enhanced