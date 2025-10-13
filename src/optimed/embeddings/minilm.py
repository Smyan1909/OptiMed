from sentence_transformers import SentenceTransformer
import asyncio
import numpy as np
from typing import Literal, List
import os
import logging
import torch

logger = logging.getLogger(__name__)

# Configurable embedding model (default: multilingual-e5-large for speed/quality balance)
# Options:
#   - intfloat/multilingual-e5-large: 1024-dim, fast, excellent multilingual (RECOMMENDED)
#   - intfloat/multilingual-e5-base: 768-dim, faster, good quality
#   - BAAI/bge-m3: 1024-dim, slower, highest quality
_model_name = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
_model = None  # Will be loaded on first use or explicit initialization
_model_loaded = False

# GPU optimization settings
_use_fp16 = os.getenv("EMBEDDING_USE_FP16", "True").lower() == "true"
_use_compile = os.getenv("EMBEDDING_USE_COMPILE", "True").lower() == "true"

# Embedding dimension (will be set after model loads)
_embedding_dim = None


def _ensure_model_loaded() -> None:
    """Ensure the embedding model is loaded and optimized.

    This function is called automatically on first use, but can also be
    called explicitly at startup to warm up the model.
    """
    global _model, _model_loaded, _embedding_dim

    if _model_loaded and _model is not None:
        return

    logger.info(f"Loading embedding model: {_model_name}")
    _model = SentenceTransformer(_model_name)

    # Apply GPU optimizations for 2-3x speedup
    if torch.cuda.is_available():
        # Enable FP16 for 2x inference speedup
        if _use_fp16:
            try:
                _model = _model.half()
                logger.info("Enabled FP16 precision for 2x embedding speedup")
            except Exception as e:
                logger.warning(f"Could not enable FP16: {e}")

        # Apply torch.compile for additional speedup
        if _use_compile and hasattr(torch, 'compile'):
            try:
                import platform
                if platform.system() != "Windows":  # Skip on Windows (Triton not available)
                    _model = torch.compile(_model, mode='reduce-overhead')  # type: ignore[assignment]
                    logger.info("Applied torch.compile() for additional speedup")
                else:
                    logger.info("Skipping torch.compile on Windows")
            except Exception as e:
                logger.warning(f"Could not compile model: {e}")

    # Determine embedding dimension based on model
    _embedding_dim = _model.get_sentence_embedding_dimension()
    _model_loaded = True

    logger.info(f"Embedding model loaded successfully (dim={_embedding_dim})")


def initialize_model() -> None:
    """Explicitly initialize the embedding model at startup.

    This should be called during application startup to ensure the model
    is loaded and ready before the first request.
    """
    _ensure_model_loaded()

# Batch size for embedding (configurable via environment)
# e5-large is more memory efficient, so we can use larger batches
_batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))  # Default 32 for e5-large

# Parallel processing configuration
# e5-large allows more parallelism due to better memory efficiency
_max_parallel_batches = int(os.getenv("EMBEDDING_MAX_PARALLEL", "6"))  # Process 6 groups concurrently

# Chunk size per parallel task (texts per concurrent worker)
_chunk_size = int(os.getenv("EMBEDDING_CHUNK_SIZE", "150"))  # Each worker handles 150 texts

async def embed(text: str, kind: Literal["query", "passage"] = "query") -> list[float]:
    """Embed a single text string into a vector.

    kind="query" is used for search queries; kind="passage" is used for content stored in the index.

    Note: E5 models require "query: " or "passage: " prefixes for optimal performance.
    """
    _ensure_model_loaded()
    assert _model is not None, "Model should be loaded after _ensure_model_loaded()"

    prefix = "query: " if kind == "query" else "passage: "
    vec = await asyncio.to_thread(
        _model.encode,
        prefix + text,
        normalize_embeddings=True,
    )
    if len(vec) != _embedding_dim:
        raise ValueError(f"Expected {_embedding_dim}-d embedding, got {len(vec)}")
    return vec.tolist()

async def embed_batch(texts: List[str], kind: Literal["query", "passage"] = "query") -> List[List[float]]:
    """Embed multiple texts with parallel batch processing for optimal GPU utilization.

    OPTIMIZATIONS:
    - Parallel processing: Splits texts into chunks and processes concurrently
    - GPU memory management: Clears CUDA cache between batches
    - Graceful degradation: Automatically reduces batch size on OOM
    - Configurable parallelism: Tune via environment variables

    For 800 chunks: ~100-200x faster than individual encoding!

    Args:
        texts: List of texts to embed
        kind: "query" for search queries, "passage" for content

    Returns:
        List of embedding vectors (each 1024-dimensional)

    Environment Variables:
        EMBEDDING_BATCH_SIZE: Batch size for model.encode() (default: 16)
        EMBEDDING_MAX_PARALLEL: Number of concurrent workers (default: 4)
        EMBEDDING_CHUNK_SIZE: Texts per worker (default: 200)
    """
    _ensure_model_loaded()

    if not texts:
        return []

    # For small batches, use simple sequential processing
    if len(texts) <= _chunk_size:
        return await _embed_chunk(texts, kind)

    # Split into chunks for parallel processing
    text_chunks = [texts[i:i + _chunk_size] for i in range(0, len(texts), _chunk_size)]

    logger.info(f"Embedding {len(texts)} texts in {len(text_chunks)} parallel chunks (chunk_size={_chunk_size}, batch_size={_batch_size})")

    # Process chunks concurrently with semaphore to limit parallelism
    semaphore = asyncio.Semaphore(_max_parallel_batches)

    async def process_with_limit(chunk):
        async with semaphore:
            return await _embed_chunk(chunk, kind)

    # Execute all chunks in parallel (limited by semaphore)
    tasks = [process_with_limit(chunk) for chunk in text_chunks]
    chunk_results = await asyncio.gather(*tasks)

    # Flatten results
    all_embeddings = []
    for chunk_result in chunk_results:
        all_embeddings.extend(chunk_result)

    logger.info(f"Successfully embedded {len(all_embeddings)} texts")
    return all_embeddings


async def _embed_chunk(texts: List[str], kind: Literal["query", "passage"]) -> List[List[float]]:
    """Embed a chunk of texts with GPU memory management and error handling.

    This function is called by embed_batch() for each parallel chunk.
    Includes automatic fallback to smaller batches on OOM errors.
    """
    if not texts:
        return []

    # Add prefix based on kind
    prefix = "query: " if kind == "query" else "passage: "
    prefixed_texts = [prefix + text for text in texts]

    # Encode in thread pool with GPU cleanup
    try:
        vectors = await asyncio.to_thread(
            _encode_with_cleanup,
            prefixed_texts,
            _batch_size
        )

        # Verify dimensions and convert to list
        if vectors.shape[1] != _embedding_dim:
            raise ValueError(f"Expected {_embedding_dim}-d embeddings, got {vectors.shape[1]}")

        return vectors.tolist()

    except RuntimeError as e:
        if "out of memory" in str(e).lower() or "CUDA" in str(e):
            logger.warning(f"OOM error with batch_size={_batch_size}, falling back to smaller batches")
            # Fallback: Split in half and retry recursively
            if len(texts) > 1:
                mid = len(texts) // 2
                result1 = await _embed_chunk(texts[:mid], kind)
                result2 = await _embed_chunk(texts[mid:], kind)
                return result1 + result2
            else:
                raise  # Single text causing OOM is unrecoverable
        else:
            raise


def _encode_with_cleanup(texts: List[str], batch_size: int) -> np.ndarray:
    """Encode texts with conditional GPU memory cleanup.

    This function runs in a thread pool to avoid blocking the event loop.
    Clears GPU cache only when memory usage is high (for speed).
    """
    assert _model is not None, "Model should be loaded before calling _encode_with_cleanup"
    try:
        # Encode with batching
        vectors = _model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        # Clear GPU cache only if memory usage is high (>80%)
        if torch.cuda.is_available():
            mem_allocated = torch.cuda.memory_allocated(0)
            mem_total = torch.cuda.get_device_properties(0).total_memory
            if mem_allocated / mem_total > 0.8:
                torch.cuda.empty_cache()
                logger.info("Cleared GPU cache (high memory usage)")

        return vectors

    except Exception as e:
        logger.error(f"Encoding error: {e}")
        # Always clear cache on error
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        raise