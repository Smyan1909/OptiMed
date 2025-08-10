from __future__ import annotations
import os 
import json 
import datetime as dt
from typing import Sequence, Any
from dotenv import load_dotenv
from optimed.embeddings.minilm import embed          # multilingual e5 with kind prefixes
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter

load_dotenv()

_VECTOR_STORE = PGVectorAdapter(os.getenv("PGVECTOR_DSN")) # type: ignore

async def embed_and_store(
    *,
    namespace: str,
    object_type: str,
    object_id: str,
    text: str | dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """
    Embed `text` and upsert into the embeddings table.

    Returns the row's UUID (primary key).
    """
    # Prepare content for embedding (always use string for embedding)
    embed_text = text if isinstance(text, str) else json.dumps(text)
    
    # run embed model (sync or async) — passages for stored content
    vec: Sequence[float] = await embed(embed_text, "passage")

    key = f"{namespace}:{object_type}:{object_id}"
    
    # Ensure content is always a valid JSON object for database storage
    if isinstance(text, str):
        content = {"text": text}  # Wrap plain text in JSON object
    else:
        content = text
    
    row_uuid = await _VECTOR_STORE.upsert(
        embedding_id=key,
        embedding=vec,
        object_type=object_type,
        object_id=object_id,
        content=content,  # This will now always be a dict, which gets JSON serialized
        metadata={
            **(metadata or {}),
            "namespace": namespace,
            "object_type": object_type,
            "ingested_at": dt.datetime.utcnow().isoformat(),
        },
    )
    return row_uuid