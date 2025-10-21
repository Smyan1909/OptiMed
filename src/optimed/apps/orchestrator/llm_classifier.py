"""LLM-based intent classifier using Azure OpenAI for medical query classification.

This module replaces the complex embedding-based classification with a simple,
more accurate LLM-based approach that provides better semantic understanding
and true multilingual support.
"""

from __future__ import annotations

import asyncio
from typing import List, Optional
from optimed.core.logging_utils import get_logger
from optimed.core.domain import ChatMessage, ChatRole
from optimed.core.ports import LLMClient

logger = get_logger(__name__)


class LLMZeroShotClassifier:
    """LLM-based query intent classifier.

    Uses the LLM to classify user queries into specific intent categories.
    This approach provides:
    - Superior semantic understanding compared to embeddings
    - True multilingual support (LLM handles any language)
    - Consistent predictions across languages
    - No model loading or embedding computation overhead
    - More explainable results

    The classifier is specifically designed for medical/clinical queries.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        """Initialize the LLM-based classifier.

        Args:
            llm_client: LLM client for classification. If None, will need to be
                       provided in classify() method.
        """
        self._llm_client = llm_client

        # Intent descriptions for the LLM prompt
        self._intent_descriptions = {
            "lookup": "Looking up specific patient data values or measurements from the current patient's record (e.g., 'what is the patient's blood pressure?', 'latest creatinine for this patient', 'current heart rate', 'what medications are the patient on?')",
            "general": "General medical knowledge questions not specific to the current patient - asking about medications, diseases, or medical concepts in general (e.g., 'what is metformin used for?', 'tell me about oxybutynin', 'what are the side effects of this drug?', 'what is diabetes?')",
            "focused_summary": "Summary of a specific aspect of the current patient's condition - focusing on one organ system, disease, or clinical area from their medical record (e.g., 'summarize this patient's heart condition', 'kidney disease status for this patient', 'respiratory history')",
            "general_summary": "Complete overview of the entire current patient's status across all conditions and systems (e.g., 'summarize this patient', 'overall patient summary', 'give me the full picture of this patient')",
            "temporal-trend": "How the current patient's values or conditions have changed over time in their medical record (e.g., 'how has this patient's creatinine changed?', 'show glucose trend', 'progression over time for this patient')",
            "comparative": "Comparing or contrasting multiple medical options, treatments, or medications in general (not patient-specific comparison) (e.g., 'compare lisinopril vs losartan', 'difference between ACE inhibitors and ARBs', 'which medication is better for hypertension')",
            "guideline": "Treatment protocols, clinical guidelines, or how to manage medical conditions in general (e.g., 'how to treat hypertension?', 'guideline recommendations for diabetes', 'management protocol for sepsis')",
            "timeline": "Chronological sequence of clinical events over time from the current patient's medical record (e.g., 'when did events happen for this patient?', 'show timeline of hospitalizations', 'chronology of this patient's treatment')",
            "sbar_handoff": "SBAR structured handoff communication for shift changes for the current patient (e.g., 'SBAR report', 'handoff summary', 'sign-out for this patient')",
            "note_generation": "Creating new clinical documentation like progress notes or SOAP notes for the current patient (e.g., 'write a progress note', 'create SOAP note', 'draft consultation note for this patient')",
            "discharge_summary": "Hospital discharge documentation and planning for the current patient (e.g., 'generate discharge summary', 'discharge note', 'discharge plan for this patient')",
        }

        logger.info("Initialized LLM-based ZeroShot Classifier")
        logger.info(f"Available intents: {list(self._intent_descriptions.keys())}")

    def _create_classification_prompt(self, query: str, candidate_labels: List[str]) -> str:
        """Create the classification prompt for the LLM.

        Args:
            query: User query to classify
            candidate_labels: List of possible intent labels

        Returns:
            Formatted prompt for the LLM
        """
        # Filter descriptions to only candidate labels
        available_intents = {
            label: desc for label, desc in self._intent_descriptions.items()
            if label in candidate_labels
        }

        # Build prompt
        intents_text = "\n".join(
            f"- {label}: {desc}"
            for label, desc in available_intents.items()
        )

        prompt = f"""You are a medical query intent classifier. Your task is to classify the user's query into ONE of the following intent categories:

{intents_text}

User Query: "{query}"

Analyze the query carefully and determine which single intent category best matches it. Consider:
- The primary goal of the query
- Whether it asks for a summary (general vs focused), a specific value (lookup), a trend, a comparison, a general question etc.
- Medical context and terminology

Respond with ONLY the intent label (e.g., "focused_summary"), nothing else. Do not provide explanations."""

        return prompt

    async def classify(
        self,
        text: str,
        candidate_labels: List[str],
        llm_client: Optional[LLMClient] = None
    ) -> str:
        """Classify a query into one of the candidate intent labels.

        Args:
            text: Query text to classify
            candidate_labels: List of possible intent labels
            llm_client: LLM client to use (overrides init client)

        Returns:
            The predicted intent label, or "general_summary" as safe default if classification fails
        """
        if not candidate_labels:
            logger.warning("No candidate labels provided, returning 'unknown'")
            return "unknown"

        # Use provided client or fall back to instance client
        client = llm_client or self._llm_client
        if not client:
            logger.error("No LLM client available for classification")
            # Return safe default
            return "general_summary" if "general_summary" in candidate_labels else candidate_labels[0]

        try:
            logger.info(f"Classifying query: {text[:80]}...")

            # Create classification prompt
            prompt = self._create_classification_prompt(text, candidate_labels)

            # Call LLM
            messages = [ChatMessage(role=ChatRole.USER, content=prompt)]
            response = await client.chat(
                messages=messages,
                max_tokens=50  # Only need one label
            )

            # Extract predicted label
            predicted_label = response.content.strip().lower()

            # Validate prediction is in candidate labels
            if predicted_label in candidate_labels:
                logger.info(f"[OK] Classified as: {predicted_label}")
                return predicted_label
            else:
                # LLM returned invalid label, try to find closest match
                logger.warning(f"LLM returned invalid label '{predicted_label}', not in {candidate_labels}")

                # Check if it's a substring match
                for label in candidate_labels:
                    if predicted_label in label or label in predicted_label:
                        logger.info(f"Using closest match: {label}")
                        return label

                # No match found, return safe default
                logger.warning("No match found, using safe default")
                return "general_summary" if "general_summary" in candidate_labels else candidate_labels[0]

        except Exception as e:
            logger.error(f"Classification failed: {e}")
            import traceback
            logger.error(traceback.format_exc())

            # Return safe default on error
            return "general_summary" if "general_summary" in candidate_labels else candidate_labels[0]

    def classify_query(self, text: str, candidate_labels: List[str], llm_client: Optional[LLMClient] = None) -> str:
        """Synchronous wrapper for classify (for backward compatibility).

        Note: This runs the async classify method in a new event loop.
        Prefer using the async classify() method directly when possible.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in async context, cannot use run_until_complete
                logger.warning("classify_query called from async context, returning safe default")
                return "general_summary" if "general_summary" in candidate_labels else candidate_labels[0]
            return loop.run_until_complete(self.classify(text, candidate_labels, llm_client))
        except Exception as e:
            logger.error(f"Synchronous classification failed: {e}")
            return "general_summary" if "general_summary" in candidate_labels else candidate_labels[0]


# For backward compatibility, alias the class
MultilingualZeroShotClassifier = LLMZeroShotClassifier
