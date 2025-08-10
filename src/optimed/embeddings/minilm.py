from sentence_transformers import SentenceTransformer
import asyncio
from typing import Literal

# Multilingual model compatible with cross-lingual retrieval
_model = SentenceTransformer("intfloat/multilingual-e5-large")

async def embed(text: str, kind: Literal["query", "passage"] = "query") -> list[float]:
    """Embed a single text string into a vector.

    kind="query" is used for search queries; kind="passage" is used for content stored in the index.
    """
    prefix = "query: " if kind == "query" else "passage: "
    vec = await asyncio.to_thread(
        _model.encode,
        prefix + text,
        normalize_embeddings=True,
    )
    if len(vec) != 1024:
        raise ValueError(f"Expected 1024-d, got {len(vec)}")
    return vec.tolist()