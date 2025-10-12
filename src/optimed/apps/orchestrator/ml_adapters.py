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
                gpu_mem_free = torch.cuda.memory_reserved(0) / (1024**3)
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


class MultilingualZeroShotClassifier:
    """Semantic similarity-based classifier using dense embeddings (multilingual-e5-large).

    Uses dense vector embeddings and cosine similarity for fast, accurate classification.
    More efficient and deterministic than NLI-based zero-shot classification.

    Advantages over NLI approach:
    - 5-10x faster inference (single forward pass vs. N hypothesis evaluations)
    - Deterministic and reproducible results
    - Better multilingual support (e5-large supports 100+ languages)
    - Label embeddings cached for efficiency
    - More accurate for semantic intent matching

    Supported models:
    - intfloat/multilingual-e5-large (default, fast, excellent multilingual) - RECOMMENDED
    - intfloat/multilingual-e5-base (faster, good quality)
    - BAAI/bge-m3 (slower, highest quality)

    Set via environment variable: SEMANTIC_CLASSIFIER_MODEL
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._model: Any = None
        self._loaded = False
        self._device = None
        self._is_bge_model = False
        self._is_e5_model = False
        self._compiled = False
        # Check environment variable for model override
        default_model = "intfloat/multilingual-e5-large"  # Fast, excellent multilingual performance
        self._model_name = model_name or os.getenv("SEMANTIC_CLASSIFIER_MODEL", default_model)
        # Cache for label embeddings (labels don't change, so we can cache them)
        self._label_embeddings_cache: dict[str, Any] = {}
        # Performance optimizations
        self._use_fp16 = os.getenv("CLASSIFIER_USE_FP16", "True").lower() == "true"
        self._use_compile = os.getenv("CLASSIFIER_USE_COMPILE", "True").lower() == "true"
        logger.info(f"Initialized SemanticSimilarityClassifier with model: {self._model_name}")
        logger.info(f"FP16 enabled: {self._use_fp16}, Torch compile enabled: {self._use_compile}")
        if self._model_name != default_model:
            logger.info(f"Using non-default model: {self._model_name}")

        # Load model immediately at startup instead of lazy loading during inference
        logger.info("Loading model at initialization...")
        self._ensure_loaded()

    def _ensure_loaded(self) -> bool:
        """Ensure the embedding model is loaded and ready."""
        if self._loaded and self._model is not None:
            return True

        try:
            logger.info(f"Loading SemanticSimilarityClassifier model: {self._model_name}")
            from sentence_transformers import SentenceTransformer
            import torch

            # Detect GPU availability
            if torch.cuda.is_available():
                device = "cuda"
                device_name = torch.cuda.get_device_name(0)
                logger.info(f"GPU detected: {device_name}")
            else:
                device = "cpu"
                logger.info("No GPU available, using CPU")

            self._device = device

            # Load the sentence transformer model
            self._model = SentenceTransformer(
                self._model_name,
                device=device,
                trust_remote_code=True
            )

            # For bge and e5 models, we should add instruction prefix for queries
            self._is_bge_model = "bge" in self._model_name.lower()
            self._is_e5_model = "e5" in self._model_name.lower()
            if self._is_bge_model:
                logger.info("BGE model detected - will use query instruction prefix")
            elif self._is_e5_model:
                logger.info("E5 model detected - will use query instruction prefix")

            # Apply GPU optimizations for speed
            if device == "cuda":
                # Enable FP16 mixed precision for 2x speedup
                if self._use_fp16:
                    try:
                        # Convert model to FP16
                        self._model = self._model.half()
                        logger.info("Enabled FP16 mixed precision for 2x inference speedup")
                    except Exception as e:
                        logger.warning(f"Could not enable FP16: {e}")

                # Apply torch.compile for additional speedup (PyTorch 2.x)
                if self._use_compile and hasattr(torch, 'compile') and not self._compiled:
                    try:
                        import platform
                        # Skip compilation on Windows (Triton not available)
                        if platform.system() == "Windows":
                            logger.info("Skipping torch.compile on Windows (Triton not available)")
                        else:
                            # Compile for optimized inference
                            self._model = torch.compile(self._model, mode='reduce-overhead')
                            self._compiled = True
                            logger.info("Applied torch.compile() optimization for additional speedup")
                    except Exception as e:
                        logger.warning(f"Could not compile model (this is OK): {e}")

            self._loaded = True

            device_str = f"GPU ({torch.cuda.get_device_name(0)})" if device == "cuda" else "CPU"
            logger.info(f"SemanticSimilarityClassifier model loaded successfully on {device_str}")
            return True

        except ImportError:
            logger.warning("sentence-transformers not available")
            return False
        except Exception as e:
            logger.warning(f"Failed to load model: {e}")
            return False

    def _cosine_similarity(self, vec1: Any, vec2: Any) -> float:
        """Compute cosine similarity between two vectors."""
        try:
            import numpy as np
            # Ensure vectors are numpy arrays
            v1 = np.array(vec1).flatten()
            v2 = np.array(vec2).flatten()

            # Compute dot product and norms
            dot_product = np.dot(v1, v2)
            norm1 = np.linalg.norm(v1)
            norm2 = np.linalg.norm(v2)

            # Avoid division by zero
            if norm1 == 0 or norm2 == 0:
                return 0.0

            return float(dot_product / (norm1 * norm2))
        except Exception as e:
            logger.warning(f"Cosine similarity calculation failed: {e}")
            return 0.0

    def classify(self, text: str, candidate_labels: List[str]) -> str:
        """Classify text using semantic similarity (cosine similarity of embeddings)."""
        if not candidate_labels:
            return "unknown"

        # Use semantic similarity classification with BGE-M3 embeddings
        if self._ensure_loaded() and self._model is not None:
            try:
                import numpy as np

                # Map technical labels to descriptions that match USER QUERY PATTERNS
                # Describe what the query SOUNDS LIKE, not what the output is
                label_mapping = {
                    # User asks to "summarize [SPECIFIC CONDITION/ORGAN NAME]"
                    "focused_summary": "user requests summary about patient's heart cardiac cardiovascular diabetes kidney renal liver hepatic lung pulmonary respiratory brain neurological stroke cancer oncology hypertension blood-pressure thyroid endocrine gastrointestinal arthritis dermatology condition disease organ-system - query explicitly names the specific medical aspect to summarize - asks for information about one particular named health issue",

                    # User asks to "summarize THE PATIENT" or "summarize THIS patient" (no specific aspect)
                    "general_summary": "user requests overview or summary of THE patient or THIS patient without naming any particular condition or organ - asks for complete information about the patient as a whole - wants to see everything together - no specific medical aspect mentioned in the query",

                    # User explicitly asks for "discharge summary"
                    "discharge_summary": "user explicitly requests discharge summary or hospital discharge documentation - query contains the word discharge - asks about patient leaving hospital or discharge planning",

                    # User asks "when" or requests "timeline" or "chronological" or "history of events"
                    "timeline": "user asks when events happened or requests timeline or chronological history or sequence of events - query contains words like: general timeline, when, timeline, chronological, sequence, history, events over time, what happened when",

                    # User explicitly asks for "SBAR" or "handoff"
                    "sbar_handoff": "user explicitly requests SBAR report or handoff or shift-change communication - query contains the word SBAR or handoff or shift-change - asks for structured situation-background-assessment-recommendation format",

                    # User asks "what is" or "what was" seeking a single specific value
                    "lookup": "user asks what is or what was a specific value or measurement - query seeks one single data point like: what is blood pressure, what is latest creatinine, what is hemoglobin value, what was glucose - question asking for specific isolated fact",

                    # User asks to "write" or "create" or "generate" or "draft" a note/documentation
                    "note_generation": "user asks to write or create or generate or draft or compose new clinical note or documentation - query contains action verbs like: write, create, generate, draft, compose, produce followed by note or documentation - requests authoring new medical record",

                    # User asks "how has X changed" or "show trends" or "track over time"
                    "temporal-trend": "user asks how values changed or evolved or trended over time - query asks to show trends or track changes or analyze progression of measurements - contains words like: trend, change over time, how has X changed, progression, evolution of values",

                    # User asks to "compare X versus Y" or "compare X and Y" or "differences between"
                    "comparative": "user asks to compare two or more options or choices or alternatives - query contains words like: compare, versus, vs, versus, difference between, versus, contrast, compare X with Y, compare X and Y, which is better",

                    # User asks "why" or "what caused" or "what's causing"
                    "reasoning": "user asks why something happened or what caused symptoms or what is causing condition - query contains words like: why, what caused, what's causing, reason for, etiology, why does patient have, explain cause, differential diagnosis",

                    # User asks "how should we treat" or "what do guidelines recommend"
                    "guideline": "user asks how to treat or what guidelines recommend or best practices for management - query contains words like: how should we treat, what do guidelines say, treatment protocol, clinical guidelines, how to manage, recommended approach, best practice"
                }

                # Convert labels to natural language if mapping exists
                natural_labels = [label_mapping.get(label, label) for label in candidate_labels]

                # For BGE and E5 models, add instruction prefix to queries (but not to labels)
                query_text = text
                if self._is_bge_model:
                    query_text = f"Represent this sentence for searching relevant passages: {text}"
                elif self._is_e5_model:
                    # E5 models use "query: " prefix for asymmetric semantic search
                    query_text = f"query: {text}"

                # Embed the query
                logger.info(f"Embedding query: {text[:80]}...")
                query_embedding = self._model.encode(
                    query_text,
                    normalize_embeddings=True,  # Normalize for cosine similarity
                    show_progress_bar=False,
                    convert_to_numpy=True
                )

                # Prepare label texts for batch embedding
                label_texts_to_embed = []
                cache_keys_to_embed = []
                cached_indices = {}

                for i, natural_label in enumerate(natural_labels):
                    # For E5 models, add "passage: " prefix to label descriptions
                    label_text = natural_label
                    if self._is_e5_model:
                        label_text = f"passage: {natural_label}"

                    cache_key = label_text

                    # Check if already cached
                    if cache_key in self._label_embeddings_cache:
                        cached_indices[i] = cache_key
                    else:
                        label_texts_to_embed.append(label_text)
                        cache_keys_to_embed.append(cache_key)

                # Batch embed all uncached labels at once (MUCH faster than one-by-one)
                if label_texts_to_embed:
                    logger.info(f"Batch embedding {len(label_texts_to_embed)} uncached labels...")
                    batch_embeddings = self._model.encode(
                        label_texts_to_embed,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                        convert_to_numpy=True,
                        batch_size=32  # Process in optimal batches
                    )

                    # Cache the new embeddings
                    for cache_key, embedding in zip(cache_keys_to_embed, batch_embeddings):
                        self._label_embeddings_cache[cache_key] = embedding

                # Build final label embeddings list in correct order
                label_embeddings = []
                uncached_idx = 0
                for i, natural_label in enumerate(natural_labels):
                    label_text = natural_label
                    if self._is_e5_model:
                        label_text = f"passage: {natural_label}"
                    cache_key = label_text

                    if i in cached_indices:
                        label_embeddings.append(self._label_embeddings_cache[cache_key])
                    else:
                        label_embeddings.append(self._label_embeddings_cache[cache_key])

                # Compute cosine similarities between query and all labels
                similarities = []
                for i, label_emb in enumerate(label_embeddings):
                    sim = self._cosine_similarity(query_embedding, label_emb)
                    similarities.append((candidate_labels[i], natural_labels[i], sim))

                # Sort by similarity (highest first)
                similarities.sort(key=lambda x: x[2], reverse=True)

                # Log top 3 for debugging
                top_3 = similarities[:3] if len(similarities) >= 3 else similarities
                logger.info(f"Semantic similarity scores - Top 3:")
                for label, desc, score in top_3:
                    logger.info(f"  {label}: {score:.4f} ('{desc[:60]}...')")

                # Return the label with highest similarity
                best_label = similarities[0][0]
                best_score = similarities[0][2]
                logger.info(f"Final classification: {best_label} (similarity: {best_score:.4f})")

                # Cleanup GPU cache only at the end (not after every operation for speed)
                try:
                    import torch
                    if self._device == "cuda" and torch.cuda.is_available():
                        # Only clear if memory usage is high (>70%)
                        mem_allocated = torch.cuda.memory_allocated(0)
                        mem_total = torch.cuda.get_device_properties(0).total_memory
                        if mem_allocated / mem_total > 0.7:
                            torch.cuda.empty_cache()
                            logger.info("Cleared GPU cache (high memory usage)")
                except (ImportError, Exception):
                    pass  # Ignore errors

                return best_label

            except Exception as e:
                logger.warning(f"Semantic classification failed: {e}, falling back to heuristic")
                import traceback
                logger.warning(traceback.format_exc())
                pass

        # If model is not available, use simple heuristic
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