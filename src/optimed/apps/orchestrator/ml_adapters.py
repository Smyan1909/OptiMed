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

        # Load model immediately at startup instead of lazy loading during inference
        logger.info("Loading model at initialization...")
        self._ensure_loaded()

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
                logger.info(f"GPU Memory: {gpu_mem:.2f} GB total")

                # Adjust batch size based on available memory if not explicitly set
                if not os.getenv("CROSS_ENCODER_BATCH_SIZE"):
                    if gpu_mem < 6:
                        self._optimal_batch_size = 16  # Conservative for small GPUs
                    elif gpu_mem < 12:
                        self._optimal_batch_size = 32  # Safer for 8GB (was 64, caused OOM)
                    else:
                        self._optimal_batch_size = 48  # For larger GPUs
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

            # Clear GPU cache only if memory usage is high (for speed)
            try:
                import torch
                if self._device == "cuda" and torch.cuda.is_available():
                    mem_allocated = torch.cuda.memory_allocated(0)
                    mem_total = torch.cuda.get_device_properties(0).total_memory
                    if mem_allocated / mem_total > 0.8:
                        torch.cuda.empty_cache()
                        logger.info("Cleared GPU cache (high memory usage)")
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

            # Clear GPU cache only if memory usage is high
            try:
                import torch
                if self._device == "cuda" and torch.cuda.is_available():
                    mem_allocated = torch.cuda.memory_allocated(0)
                    mem_total = torch.cuda.get_device_properties(0).total_memory
                    if mem_allocated / mem_total > 0.8:
                        torch.cuda.empty_cache()
                        logger.info("Cleared GPU cache (high memory usage)")
            except (ImportError, Exception):
                pass  # Ignore errors

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
