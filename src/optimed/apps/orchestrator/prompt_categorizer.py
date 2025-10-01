"""
Prompt Categorizer for OptiMed

Categorizes user prompts for usage analytics without storing actual content.
Uses keyword matching and optional LLM-based classification.
"""

import re
import hashlib
from typing import Optional, Dict, List
from dataclasses import dataclass


@dataclass
class PromptCategory:
    """Result of prompt categorization."""
    category: str
    confidence: float
    subcategory: Optional[str] = None
    prompt_hash: str = ""


# Category keywords (case-insensitive)
CATEGORY_KEYWORDS = {
    "symptom_checker": [
        "symptom", "feel", "pain", "hurt", "ache", "fever", "cough",
        "nausea", "dizzy", "tired", "fatigue", "weakness", "sick"
    ],
    "diagnosis_support": [
        "diagnose", "diagnosis", "what is", "could it be", "possibilities",
        "differential", "likely condition", "medical condition"
    ],
    "treatment_planning": [
        "treat", "treatment", "therapy", "medication", "medicine", "drug",
        "prescribe", "prescription", "dosage", "how to treat", "cure"
    ],
    "note_generation": [
        "note", "document", "journal", "record", "write", "generate",
        "soap", "sbar", "summary", "report", "referral"
    ],
    "medical_research": [
        "research", "study", "studies", "evidence", "literature", "paper",
        "guideline", "protocol", "best practice", "latest"
    ],
    "general_inquiry": [
        "what", "how", "why", "when", "explain", "tell me", "information",
        "about", "question", "help", "understand"
    ],
    "lab_interpretation": [
        "lab", "test result", "blood test", "result", "interpretation",
        "normal range", "abnormal", "value", "level"
    ],
    "medication_inquiry": [
        "side effect", "interaction", "contraindication", "allergy",
        "adverse", "warning", "precaution", "drug interaction"
    ]
}


class PromptCategorizer:
    """
    Categorizes prompts for GDPR-compliant usage analytics.

    Uses keyword matching with optional LLM enhancement.
    Stores only category + hash, never actual prompt content.
    """

    def __init__(self, use_llm: bool = False):
        """
        Initialize prompt categorizer.

        Args:
            use_llm: Whether to use LLM for sophisticated categorization
        """
        self.use_llm = use_llm
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for efficient matching."""
        self.patterns: Dict[str, List[re.Pattern]] = {}
        for category, keywords in CATEGORY_KEYWORDS.items():
            self.patterns[category] = [
                re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE)
                for kw in keywords
            ]

    def _hash_prompt(self, prompt: str) -> str:
        """Create SHA256 hash of prompt for logging."""
        return hashlib.sha256(prompt.encode()).hexdigest()

    def _keyword_categorize(self, prompt: str) -> PromptCategory:
        """
        Categorize prompt using keyword matching.

        Args:
            prompt: User prompt text

        Returns:
            PromptCategory with best match
        """
        # Count matches for each category
        scores: Dict[str, int] = {cat: 0 for cat in CATEGORY_KEYWORDS.keys()}

        for category, patterns in self.patterns.items():
            for pattern in patterns:
                if pattern.search(prompt):
                    scores[category] += 1

        # Find category with highest score
        if max(scores.values()) > 0:
            best_category = max(scores, key=scores.get)  # type: ignore
            confidence = scores[best_category] / (len(self.patterns[best_category]) + 1)
            return PromptCategory(
                category=best_category,
                confidence=min(confidence, 0.9),  # Cap at 0.9 for keyword matching
                prompt_hash=self._hash_prompt(prompt)
            )
        else:
            # Default to general_inquiry
            return PromptCategory(
                category="general_inquiry",
                confidence=0.5,
                prompt_hash=self._hash_prompt(prompt)
            )

    async def _llm_categorize(self, prompt: str) -> PromptCategory:
        """
        Categorize prompt using LLM (more sophisticated).

        This is optional and can be enabled for better accuracy.

        Args:
            prompt: User prompt text

        Returns:
            PromptCategory with LLM classification
        """
        # TODO: Implement LLM-based categorization if needed
        # For now, fallback to keyword matching
        return self._keyword_categorize(prompt)

    async def categorize(self, prompt: str) -> PromptCategory:
        """
        Categorize a user prompt.

        Args:
            prompt: User prompt text

        Returns:
            PromptCategory with classification and hash
        """
        if not prompt or not prompt.strip():
            return PromptCategory(
                category="empty_prompt",
                confidence=1.0,
                prompt_hash=self._hash_prompt("")
            )

        # Use keyword matching by default (fast and privacy-preserving)
        if not self.use_llm:
            return self._keyword_categorize(prompt)
        else:
            return await self._llm_categorize(prompt)

    def get_categories(self) -> List[str]:
        """Get list of all available categories."""
        return list(CATEGORY_KEYWORDS.keys())


# Global categorizer instance
_categorizer: Optional[PromptCategorizer] = None


def get_prompt_categorizer(use_llm: bool = False) -> PromptCategorizer:
    """Get global prompt categorizer instance."""
    global _categorizer
    if _categorizer is None:
        _categorizer = PromptCategorizer(use_llm=use_llm)
    return _categorizer


async def categorize_and_log_prompt(
    prompt: str,
    user_id: str,
    session_id: Optional[str],
    audit_repo,
    model_used: Optional[str] = None,
    response_tokens: Optional[int] = None,
    latency_ms: Optional[int] = None
) -> PromptCategory:
    """
    Categorize prompt and log to audit repository.

    Convenience function that combines categorization and logging.

    Args:
        prompt: User prompt
        user_id: User ID
        session_id: Session ID
        audit_repo: Audit repository instance
        model_used: AI model used
        response_tokens: Token count in response
        latency_ms: Response latency

    Returns:
        PromptCategory
    """
    # Categorize
    categorizer = get_prompt_categorizer()
    category_result = await categorizer.categorize(prompt)

    # Log to audit repository (only hash + category, not content)
    try:
        await audit_repo.log_prompt_category(
            user_id=user_id,
            session_id=session_id,
            prompt_hash=category_result.prompt_hash,
            category=category_result.category,
            model_used=model_used,
            response_tokens=response_tokens,
            latency_ms=latency_ms
        )
    except Exception as e:
        print(f"[PROMPT_CATEGORIZER] Error logging prompt category: {e}")

    return category_result
