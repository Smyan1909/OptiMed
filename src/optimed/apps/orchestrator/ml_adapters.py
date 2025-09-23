from __future__ import annotations

import os
import math
import asyncio
import concurrent.futures
from typing import List, Optional, Tuple
from pathlib import Path


class MultilingualCrossEncoder:
    """Simplified, high-performance cross-encoder for Azure Container Apps.

    Optimizations:
    - No caching (causes issues and complexity)
    - Direct model loading with GPU acceleration
    - Optimized batch processing
    - Azure Container App compatible
    - Simple fallback mechanism
    """

    def __init__(self, model_name: str | None = None, max_batch_size: int = 32) -> None:
        self._model = None
        self._loaded = False
        self._model_name = model_name or "BAAI/bge-reranker-v2-m3"
        self._max_batch_size = max_batch_size

        # Determine optimal batch size based on environment
        if os.getenv("AZURE_CONTAINER_APP"):
            self._optimal_batch_size = 16  # Conservative for Azure
        else:
            self._optimal_batch_size = max_batch_size

        print(f"[MultilingualCrossEncoder] Initialized with model: {self._model_name}")
        print(f"[MultilingualCrossEncoder] Optimal batch size: {self._optimal_batch_size}")

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

    def predict(self, pairs: List[Tuple[str, str]], timeout: float = 30.0) -> List[float]:
        """Predict relevance scores for query-passage pairs."""
        if not pairs:
            return []

        # Try to use the actual model
        if self._ensure_loaded():
            try:
                return self._predict_with_model(pairs, timeout)
            except Exception as e:
                print(f"[MultilingualCrossEncoder] Model prediction failed: {e}, using fallback")

        # Fallback scoring with safe unpacking
        print("[MultilingualCrossEncoder] Using fallback scoring")
        fallback_scores = []
        for item in pairs:
            try:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    query, passage = item[0], item[1]
                    fallback_scores.append(self._fallback_score(str(query), str(passage)))
                else:
                    print(f"[MultilingualCrossEncoder] Invalid pair format in fallback: {item}")
                    fallback_scores.append(0.5)  # neutral score
            except Exception as e:
                print(f"[MultilingualCrossEncoder] Error in fallback unpacking: {e}")
                fallback_scores.append(0.5)  # neutral score
        return fallback_scores

    def _predict_with_model(self, pairs: List[Tuple[str, str]], timeout: float) -> List[float]:
        """Predict using the actual cross-encoder model."""
        batch_size = min(self._optimal_batch_size, len(pairs))
        all_scores = []

        print(f"[MultilingualCrossEncoder] Processing {len(pairs)} pairs in batches of {batch_size}")

        # Process in batches for better performance
        for i in range(0, len(pairs), batch_size):
            batch_pairs = pairs[i:i + batch_size]

            try:
                # Direct prediction with timeout
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self._batch_predict, batch_pairs)
                    batch_scores = future.result(timeout=timeout)
                    all_scores.extend(batch_scores)

            except concurrent.futures.TimeoutError:
                print(f"[MultilingualCrossEncoder] Batch {i//batch_size + 1} timed out")
                # Use fallback for this batch with safe unpacking
                fallback_scores = []
                for item in batch_pairs:
                    try:
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            q, p = item[0], item[1]
                            fallback_scores.append(self._fallback_score(str(q), str(p)))
                        else:
                            print(f"[MultilingualCrossEncoder] Invalid pair format: {item}")
                            fallback_scores.append(0.5)  # neutral score
                    except Exception as unpacking_error:
                        print(f"[MultilingualCrossEncoder] Error unpacking item {item}: {unpacking_error}")
                        fallback_scores.append(0.5)  # neutral score
                all_scores.extend(fallback_scores)
            except Exception as e:
                print(f"[MultilingualCrossEncoder] Batch {i//batch_size + 1} failed: {e}")
                # Use fallback for this batch with safe unpacking
                fallback_scores = []
                for item in batch_pairs:
                    try:
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            q, p = item[0], item[1]
                            fallback_scores.append(self._fallback_score(str(q), str(p)))
                        else:
                            print(f"[MultilingualCrossEncoder] Invalid pair format: {item}")
                            fallback_scores.append(0.5)  # neutral score
                    except Exception as unpacking_error:
                        print(f"[MultilingualCrossEncoder] Error unpacking item {item}: {unpacking_error}")
                        fallback_scores.append(0.5)  # neutral score
                all_scores.extend(fallback_scores)

        return all_scores

    def _batch_predict(self, batch_pairs: List[Tuple[str, str]]) -> List[float]:
        """Predict scores for a single batch."""
        if not batch_pairs:
            return []

        try:
            # Convert to format expected by CrossEncoder
            batch_texts = []
            for item in batch_pairs:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    query, passage = item[0], item[1]
                    batch_texts.append([str(query), str(passage)])
                else:
                    print(f"[MultilingualCrossEncoder] Invalid item format: {item}")
                    # Skip invalid items or provide fallback
                    continue

            if not batch_texts:
                print("[MultilingualCrossEncoder] No valid pairs for prediction")
                return []

            # Get raw scores
            raw_scores = self._model.predict(
                batch_texts,
                batch_size=len(batch_texts),
                show_progress_bar=False,
                convert_to_numpy=True,
                convert_to_tensor=False
            )

            # Apply sigmoid normalization
            normalized_scores = [self._sigmoid(float(score)) for score in raw_scores]
            return normalized_scores

        except Exception as e:
            print(f"[MultilingualCrossEncoder] Batch prediction error: {e}")
            # Return fallback scores for each pair
            fallback_scores = []
            for item in batch_pairs:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    fallback_scores.append(self._fallback_score(str(item[0]), str(item[1])))
                else:
                    fallback_scores.append(0.5)  # neutral score
            return fallback_scores

    async def predict_async(self, pairs: List[Tuple[str, str]], timeout: float = 30.0) -> List[float]:
        """Async wrapper for predict method."""
        loop = asyncio.get_event_loop()

        # Run in thread pool to avoid blocking
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.predict, pairs, timeout)

            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(None, future.result),
                    timeout=timeout + 5.0  # Add buffer for async overhead
                )
            except asyncio.TimeoutError:
                print(f"[MultilingualCrossEncoder] Async prediction timed out after {timeout}s")
                # Return fallback scores
                return [self._fallback_score(query, passage) for query, passage in pairs]

    def score_pairs(self, pairs: List[Tuple[str, str]], timeout: float = 30.0) -> List[float]:
        """Alias for predict method to maintain compatibility."""
        return self.predict(pairs, timeout)

    async def compute_similarity_scores(self, pairs: List[Tuple[str, str]], timeout: float = 30.0) -> List[float]:
        """Async compute similarity scores for compatibility."""
        return await self.predict_async(pairs, timeout)


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