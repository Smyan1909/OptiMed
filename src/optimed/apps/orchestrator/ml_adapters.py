from __future__ import annotations

import os
import math
import asyncio
import concurrent.futures
from typing import List, Tuple, Any
from optimed.core.logging_utils import get_logger

logger = get_logger(__name__)


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
        self._model: Any = None
        self._loaded = False
        self._model_name = model_name or "BAAI/bge-reranker-v2-m3"
        self._max_batch_size = max_batch_size
        self._use_fp16 = os.getenv("CROSS_ENCODER_USE_FP16", "True").lower() == "true"
        self._use_compile = os.getenv("CROSS_ENCODER_USE_COMPILE", "True").lower() == "true"
        self._device = None
        self._compiled = False

        # Determine optimal batch size based on environment and config
        env_batch_size = os.getenv("CROSS_ENCODER_BATCH_SIZE")
        if env_batch_size:
            self._optimal_batch_size = int(env_batch_size)
        elif os.getenv("AZURE_CONTAINER_APP"):
            self._optimal_batch_size = 16  # Conservative for Azure but higher than before
        else:
            self._optimal_batch_size = 64  # Aggressive for local GPU

        logger.info(f"Initialized MultilingualCrossEncoder with model: {self._model_name}")
        logger.info(f"Optimal batch size: {self._optimal_batch_size}")
        logger.info(f"FP16 enabled: {self._use_fp16}, Torch compile enabled: {self._use_compile}")

    def _ensure_loaded(self) -> bool:
        """Ensure the model is loaded and ready with GPU optimizations."""
        if self._loaded and self._model is not None:
            return True

        try:
            logger.info(f"Loading MultilingualCrossEncoder model: {self._model_name}")
            from sentence_transformers import CrossEncoder
            import torch

            # Detect GPU availability properly
            if torch.cuda.is_available():
                device = "cuda"
                self._device = device
                logger.info(f"GPU detected: {torch.cuda.get_device_name(0)}")

                # Get GPU memory info for dynamic batch sizing
                gpu_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)  # GB
                gpu_mem_free = torch.cuda.memory_reserved(0) / (1024**3)
                logger.info(f"GPU Memory: {gpu_mem:.2f} GB total")

                # Adjust batch size based on available memory if not explicitly set
                if not os.getenv("CROSS_ENCODER_BATCH_SIZE"):
                    if gpu_mem < 6:
                        self._optimal_batch_size = 16  # Conservative for small GPUs
                    elif gpu_mem < 12:
                        self._optimal_batch_size = 32  # Safer for 8GB (was 64, caused OOM)
                    else:
                        self._optimal_batch_size = 64  # For larger GPUs
                    logger.info(f"Auto-adjusted batch size to {self._optimal_batch_size} based on {gpu_mem:.2f}GB VRAM")

                # Enable cuDNN autotuner for optimal convolution algorithms
                torch.backends.cudnn.benchmark = True
                logger.info("Enabled cuDNN autotuner for GPU optimization")
            else:
                device = "cpu"
                self._device = device
                self._optimal_batch_size = 8  # Conservative for CPU
                logger.info("No GPU available, using CPU")

            # Load model
            self._model = CrossEncoder(self._model_name, device=device, trust_remote_code=True)

            # Apply GPU optimizations
            if device == "cuda":
                # Enable FP16 mixed precision for faster inference
                if self._use_fp16:
                    try:
                        self._model.model.half()
                        logger.info("Enabled FP16 mixed precision for 2-3x speedup")
                    except Exception as e:
                        logger.warning(f"Could not enable FP16: {e}")

                # Apply torch.compile for PyTorch 2.x optimization (requires Triton on Linux)
                if self._use_compile and hasattr(torch, 'compile') and not self._compiled:
                    try:
                        import platform
                        # Triton is not easily available on Windows, skip compilation
                        if platform.system() == "Windows":
                            logger.info("Skipping torch.compile on Windows (Triton not available)")
                        else:
                            # Compile the underlying model for optimization
                            self._model.model = torch.compile(self._model.model, mode='reduce-overhead')
                            self._compiled = True
                            logger.info("Applied torch.compile() optimization for PyTorch 2.x")
                    except Exception as e:
                        logger.warning(f"Could not compile model (this is OK): {e}")

            self._loaded = True
            logger.info(f"MultilingualCrossEncoder model loaded successfully on {device}")
            return True

        except ImportError:
            logger.warning("sentence-transformers not available, using fallback")
            return False
        except Exception as e:
            logger.warning(f"Failed to load model: {e}")
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
                logger.warning(f"Model prediction failed: {e}, using fallback")

        # Fallback scoring with safe unpacking
        logger.info("Using fallback scoring")
        fallback_scores = []
        for item in pairs:
            try:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    query, passage = item[0], item[1]
                    fallback_scores.append(self._fallback_score(str(query), str(passage)))
                else:
                    logger.warning(f"Invalid pair format in fallback: {item}")
                    fallback_scores.append(0.5)  # neutral score
            except Exception as e:
                logger.warning(f"Error in fallback unpacking: {e}")
                fallback_scores.append(0.5)  # neutral score
        return fallback_scores

    def _predict_with_model(self, pairs: List[Tuple[str, str]], timeout: float) -> List[float]:
        """Predict using the actual cross-encoder model."""
        batch_size = min(self._optimal_batch_size, len(pairs))
        all_scores = []

        logger.info(f"Processing {len(pairs)} pairs in batches of {batch_size}")

        # Process in batches for better performance
        for i in range(0, len(pairs), batch_size):
            batch_pairs = pairs[i:i + batch_size]
            batch_num = i//batch_size + 1
            total_batches = math.ceil(len(pairs) / batch_size)

            logger.info(f"Processing batch {batch_num}/{total_batches}")

            try:
                # Direct batch prediction without threading for single batch
                if len(batch_pairs) <= batch_size:
                    batch_scores = self._batch_predict(batch_pairs)
                    all_scores.extend(batch_scores)
                else:
                    # Use threading only for larger batches
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(self._batch_predict, batch_pairs)
                        batch_scores = future.result(timeout=min(timeout, 30.0))
                        all_scores.extend(batch_scores)

            except concurrent.futures.TimeoutError:
                logger.warning(f"Batch {i//batch_size + 1} timed out")
                # Use fallback for this batch with safe unpacking
                fallback_scores = []
                for item in batch_pairs:
                    try:
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            q, p = item[0], item[1]
                            fallback_scores.append(self._fallback_score(str(q), str(p)))
                        else:
                            logger.warning(f"Invalid pair format: {item}")
                            fallback_scores.append(0.5)  # neutral score
                    except Exception as unpacking_error:
                        logger.warning(f"Error unpacking item: {unpacking_error}")
                        fallback_scores.append(0.5)  # neutral score
                all_scores.extend(fallback_scores)
            except Exception as e:
                logger.warning(f"Batch {i//batch_size + 1} failed: {e}")
                # Use fallback for this batch with safe unpacking
                fallback_scores = []
                for item in batch_pairs:
                    try:
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            q, p = item[0], item[1]
                            fallback_scores.append(self._fallback_score(str(q), str(p)))
                        else:
                            logger.warning(f"Invalid pair format: {item}")
                            fallback_scores.append(0.5)  # neutral score
                    except Exception as unpacking_error:
                        logger.warning(f"Error unpacking item: {unpacking_error}")
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
                    logger.warning(f"Invalid item format: {item}")
                    # Skip invalid items or provide fallback
                    continue

            if not batch_texts:
                logger.warning("No valid pairs for prediction")
                return []

            # Get raw scores with optimal batch size
            if self._model is None:
                logger.warning("Model not loaded")
                return []
            # Use the optimized batch size determined during initialization
            actual_batch_size = min(len(batch_texts), self._optimal_batch_size)
            raw_scores = self._model.predict(
                batch_texts,
                batch_size=actual_batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
                convert_to_tensor=False
            )

            # Optionally clear GPU cache (only if memory pressure detected)
            # Note: empty_cache() is expensive, so we only do it periodically
            try:
                import torch
                if self._device == "cuda" and torch.cuda.is_available():
                    # Only clear cache if we're using more than 80% of memory
                    mem_allocated = torch.cuda.memory_allocated(0)
                    mem_total = torch.cuda.get_device_properties(0).total_memory
                    if mem_allocated / mem_total > 0.8:
                        torch.cuda.empty_cache()
            except (ImportError, Exception):
                pass  # Ignore errors

            # Apply sigmoid normalization
            normalized_scores = [self._sigmoid(float(score)) for score in raw_scores]
            return normalized_scores

        except Exception as e:
            logger.warning(f"Batch prediction error: {e}")
            # Return fallback scores for each pair
            fallback_scores = []
            for item in batch_pairs:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    fallback_scores.append(self._fallback_score(str(item[0]), str(item[1])))
                else:
                    fallback_scores.append(0.5)  # neutral score
            return fallback_scores

    async def predict_async(self, pairs: List[Tuple[str, str]], timeout: float = 60.0) -> List[float]:
        """Async wrapper for predict method with improved timeout handling."""
        if not pairs:
            return []

        try:
            # Direct async execution without double-threading
            loop = asyncio.get_event_loop()

            def run_prediction():
                return self.predict(pairs, timeout)

            # Run prediction in thread pool with proper timeout
            result = await asyncio.wait_for(
                loop.run_in_executor(None, run_prediction),
                timeout=timeout
            )
            return result

        except asyncio.TimeoutError:
            logger.warning(f"Async prediction timed out after {timeout}s")
            # Return fallback scores
            return [self._fallback_score(str(pair[0]), str(pair[1])) for pair in pairs]
        except Exception as e:
            logger.warning(f"Async prediction error: {e}")
            # Return fallback scores
            return [self._fallback_score(str(pair[0]), str(pair[1])) for pair in pairs]

    def score_pairs(self, pairs: List[Tuple[str, str]], timeout: float = 30.0) -> List[float]:
        """Alias for predict method to maintain compatibility."""
        return self.predict(pairs, timeout)

    async def compute_similarity_scores(self, pairs: List[Tuple[str, str]], timeout: float = 30.0) -> List[float]:
        """Async compute similarity scores for compatibility."""
        return await self.predict_async(pairs, timeout)


class MultilingualZeroShotClassifier:
    """Pure semantic zero-shot classifier for medical query intent detection.

    Uses Natural Language Inference (NLI) models to determine query intent without
    keyword matching. Classification is based entirely on semantic understanding.

    Supported models (in order of accuracy, slowest to fastest):
    - MoritzLaurer/deberta-v3-large-zeroshot-v2.0 (best accuracy, ~1GB, recommended for production)
    - MoritzLaurer/deberta-v3-base-zeroshot-v2.0 (good balance)
    - MoritzLaurer/mDeBERTa-v3-base-mnli-xnli (default, multilingual, fast, ~600MB)

    Set via environment variable: ZERO_SHOT_CLASSIFIER_MODEL
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._model: Any = None
        self._loaded = False
        # Check environment variable for model override
        default_model = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"  # Multilingual, balanced
        self._model_name = model_name or os.getenv("ZERO_SHOT_CLASSIFIER_MODEL", default_model)
        logger.info(f"Initialized MultilingualZeroShotClassifier with model: {self._model_name}")
        if self._model_name != default_model:
            logger.info(f"Using non-default model for potentially better accuracy")

    def _ensure_loaded(self) -> bool:
        """Ensure the model is loaded and ready."""
        if self._loaded and self._model is not None:
            return True

        try:
            logger.info(f"Loading MultilingualZeroShotClassifier model: {self._model_name}")
            from transformers import pipeline
            import torch

            # Detect GPU availability properly
            if torch.cuda.is_available():
                device = 0  # First GPU
                device_name = torch.cuda.get_device_name(0)
                logger.info(f"GPU detected: {device_name}")
            else:
                device = -1  # CPU
                logger.info("No GPU available, using CPU")

            self._model = pipeline(
                "zero-shot-classification",
                model=self._model_name,
                device=device,
                trust_remote_code=True
            )
            self._loaded = True

            device_str = f"GPU ({torch.cuda.get_device_name(0)})" if device == 0 else "CPU"
            logger.info(f"MultilingualZeroShotClassifier model loaded successfully on {device_str}")
            return True

        except ImportError:
            logger.warning("transformers not available")
            return False
        except Exception as e:
            logger.warning(f"Failed to load model: {e}")
            return False

    def classify(self, text: str, candidate_labels: List[str]) -> str:
        """Classify text into one of the candidate labels using pure semantic understanding."""
        if not candidate_labels:
            return "unknown"

        # Use pure semantic classification with the NLI model
        if self._ensure_loaded() and self._model is not None:
            try:
                # Map technical labels to semantically rich descriptions that capture user intent
                # These descriptions help the NLI model understand what the user actually wants
                label_mapping = {
                    "sbar_handoff": "structured patient handoff communication for care transition between healthcare providers during shift changes or transfers",
                    "general_summary": "comprehensive overview covering all of the patient's medical conditions, medications, history, problems, and overall health status across all body systems",
                    "focused_summary": "in-depth detailed information specifically about one particular medical condition, disease, organ system, or specific health aspect mentioned in the query",
                    "timeline": "chronological sequence showing when medical events occurred over time with dates and temporal ordering",
                    "note_generation": "creating or generating formal clinical documentation such as progress notes, SOAP notes, or discharge summaries",
                    "discharge_summary": "comprehensive discharge documentation summarizing hospital stay and follow-up care instructions",
                    "lookup": "finding a specific fact, data point, lab value, or piece of information from patient records",
                    "temporal-trend": "analyzing how specific measurements, values, or conditions have changed or trended over a period of time",
                    "comparative": "comparing and contrasting two or more different conditions, treatments, medications, or test results",
                    "reasoning": "clinical reasoning to determine differential diagnoses, most likely diagnosis, or diagnostic possibilities",
                    "guideline": "retrieving clinical practice guidelines, protocols, or evidence-based recommendations for treatment"
                }

                # Convert labels to natural language if mapping exists
                natural_labels = [label_mapping.get(label, label) for label in candidate_labels]

                # Use hypothesis template optimized for query intent classification
                # Research shows that framing it as "The user wants X" works best for intent detection
                # This frames the classification as determining what the user is requesting
                result = self._model(
                    text,
                    natural_labels,
                    hypothesis_template="The user wants {}",
                    multi_label=False
                )

                # Log classification results for debugging
                top_3_labels = result['labels'][:3] if len(result['labels']) >= 3 else result['labels']
                top_3_scores = result['scores'][:3] if len(result['scores']) >= 3 else result['scores']
                logger.info(f"Model classification - Top 3: {list(zip(top_3_labels, top_3_scores))}")

                # Map back to original label
                top_natural_label = result['labels'][0]
                for original_label, natural_label in label_mapping.items():
                    if natural_label == top_natural_label:
                        logger.info(f"Final classification: {original_label} (via mapping from '{top_natural_label}')")
                        return original_label

                # If no mapping found, try direct match
                if top_natural_label in candidate_labels:
                    logger.info(f"Final classification: {top_natural_label} (direct match)")
                    return top_natural_label

                # Fallback to first candidate
                logger.info(f"Final classification: {candidate_labels[0]} (fallback)")
                return candidate_labels[0]

            except Exception as e:
                logger.warning(f"Model classification failed: {e}, falling back to heuristic")
                # Fallback: Try to infer from length and structure
                # This is not ideal but better than random selection
                pass

        # If model is not available, use simple heuristic based on query structure
        # This is a last resort and should rarely be used
        logger.warning(f"Semantic classification unavailable - using basic fallback for query: {text[:50]}...")

        # Very simple heuristic: prefer general_summary over others as safe default
        if "general_summary" in candidate_labels:
            logger.info("Fallback: selecting general_summary as safe default")
            return "general_summary"
        elif "lookup" in candidate_labels:
            logger.info("Fallback: selecting lookup as safe default")
            return "lookup"
        else:
            logger.info(f"Fallback: selecting first candidate: {candidate_labels[0]}")
            return candidate_labels[0] if candidate_labels else "unknown"

    def classify_query(self, text: str, candidate_labels: List[str]) -> str:
        """Classify query intent for SBAR flow routing."""
        return self.classify(text, candidate_labels)