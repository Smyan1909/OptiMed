from __future__ import annotations

import os
import math
from typing import List, Optional, Tuple


class MultilingualCrossEncoder:
    """Simplified, high-performance cross-encoder that prioritizes speed over features."""

    def __init__(self, model_name: str | None = None) -> None:
        self._model = None
        self._loaded = False
        self._model_name = model_name or "BAAI/bge-reranker-v2-m3"

        print(f"[MultilingualCrossEncoder] Initialized with model: {self._model_name}")

    def _ensure_loaded(self) -> bool:
        """Ensure the model is loaded and ready."""
        if self._loaded and self._model is not None:
            return True

        try:
            print(f"[MultilingualCrossEncoder] Loading model: {self._model_name}")
            from sentence_transformers import CrossEncoder

            # Load model with GPU support if available
            device = "cuda" if os.getenv("CUDA_VISIBLE_DEVICES") else "cpu"
            self._model = CrossEncoder(self._model_name, device=device, trust_remote_code=True)
            self._loaded = True

            print(f"[MultilingualCrossEncoder] Model loaded successfully on {device}")
            return True

        except ImportError:
            print("[MultilingualCrossEncoder] sentence-transformers not available, using fallback")
            return False
        except Exception as e:
            print(f"[MultilingualCrossEncoder] Failed to load model: {e}")
            return False

    def _sigmoid(self, x: float) -> float:
        """Simple sigmoid function for fallback scoring."""
        try:
            return 1 / (1 + math.exp(-x))
        except OverflowError:
            return 0.0 if x < 0 else 1.0

    def _fallback_score(self, query: str, passage: str) -> float:
        """Simple fallback scoring based on word overlap."""
        query_words = set(query.lower().split())
        passage_words = set(passage.lower().split())

        if not query_words:
            return 0.0

        overlap = len(query_words.intersection(passage_words))
        max_possible = len(query_words)

        # Convert to sigmoid-normalized score
        raw_score = (overlap / max_possible) * 4 - 2  # Scale to reasonable sigmoid input
        return self._sigmoid(raw_score)

    def predict(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """Predict relevance scores for query-passage pairs."""
        if not pairs:
            return []

        # Try to use the actual model
        if self._ensure_loaded():
            try:
                # Convert to format expected by CrossEncoder
                batch_texts = [[str(query), str(passage)] for query, passage in pairs]

                # Get raw scores (simple, fast prediction)
                raw_scores = self._model.predict(
                    batch_texts,
                    batch_size=min(32, len(batch_texts)),
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    convert_to_tensor=False
                )

                # Apply sigmoid normalization
                return [self._sigmoid(float(score)) for score in raw_scores]

            except Exception as e:
                print(f"[MultilingualCrossEncoder] Model prediction failed: {e}, using fallback")

        # Fallback scoring
        print("[MultilingualCrossEncoder] Using fallback scoring")
        return [self._fallback_score(str(query), str(passage)) for query, passage in pairs]

    def score_pairs(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """Alias for predict method to maintain compatibility."""
        return self.predict(pairs)

    async def compute_similarity_scores(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """Async compute similarity scores for compatibility."""
        return self.predict(pairs)

    async def predict_async(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """Async wrapper for predict method."""
        # Simple async wrapper - just call the sync version
        # The old version was fast enough that we don't need complex async handling
        return self.predict(pairs)


class MultilingualZeroShotClassifier:
    """Simplified zero-shot classifier for query intent detection."""

    def __init__(self, model_name: str | None = None) -> None:
        self._model = None
        self._loaded = False
        self._model_name = model_name or "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
        print(f"[MultilingualZeroShotClassifier] Initialized with model: {self._model_name}")

    def _ensure_loaded(self) -> bool:
        """Ensure the model is loaded and ready."""
        if self._loaded and self._model is not None:
            return True

        try:
            print(f"[MultilingualZeroShotClassifier] Loading model: {self._model_name}")
            from transformers import pipeline

            # Load model with GPU support if available
            device = 0 if os.getenv("CUDA_VISIBLE_DEVICES") else -1
            self._model = pipeline(
                "zero-shot-classification",
                model=self._model_name,
                device=device,
                trust_remote_code=True
            )
            self._loaded = True

            print(f"[MultilingualZeroShotClassifier] Model loaded successfully")
            return True

        except ImportError:
            print("[MultilingualZeroShotClassifier] transformers not available")
            return False
        except Exception as e:
            print(f"[MultilingualZeroShotClassifier] Failed to load model: {e}")
            return False

    def classify(self, text: str, candidate_labels: List[str]) -> str:
        """Classify text into one of the candidate labels."""
        if not candidate_labels:
            return "unknown"

        # Simple keyword-based fallback
        text_lower = text.lower()

        # Check for summary keywords in multiple languages
        summary_keywords = [
            "sammanfattning", "summary", "översikt", "overview",
            "resumé", "sammandrag", "summering"
        ]

        diagnostic_keywords = [
            "diagnos", "diagnosis", "vad", "what", "orsak", "cause",
            "fel", "wrong", "problem", "sjukdom", "disease"
        ]

        if any(keyword in text_lower for keyword in summary_keywords):
            return "summary"
        elif any(keyword in text_lower for keyword in diagnostic_keywords):
            return "diagnostic"

        # Try to use the actual model if available
        if self._ensure_loaded():
            try:
                result = self._model(text, candidate_labels)
                return result['labels'][0]  # Return highest confidence label
            except Exception as e:
                print(f"[MultilingualZeroShotClassifier] Classification failed: {e}")

        # Default fallback
        return candidate_labels[0] if candidate_labels else "unknown"

    def classify_query(self, text: str, candidate_labels: List[str]) -> str:
        """Classify query intent for SBAR flow routing."""
        return self.classify(text, candidate_labels)