from sentence_transformers import SentenceTransformer
import asyncio

_model = SentenceTransformer("intfloat/e5-large-v2")

async def embed(text: str) -> list[float]:
    """Embed a single text string into a vector."""
    vec = await asyncio.to_thread(
        _model.encode,
        "query: " + text,
        normalize_embeddings=True,
    )
    if len(vec) != 1024:
        raise ValueError(f"Expected 1024-d, got {len(vec)}")
    return vec.tolist()