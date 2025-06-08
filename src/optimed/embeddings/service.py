from __future__ import annotations
import os, json, datetime as dt
from typing import Sequence, Any

from optimed.embeddings.minilm import embed          # or whichever model
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter

_VECTOR_STORE = PGVectorAdapter(os.getenv("PGVECTOR_DSN"))


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
    # run embed model (sync or async)
    vec: Sequence[float] = await embed(text if isinstance(text, str) else json.dumps(text))

    key = f"{namespace}:{object_type}:{object_id}"
    row_uuid = await _VECTOR_STORE.upsert(
        embedding_id=key,
        embedding=vec,
        object_type=object_type,
        object_id=object_id,
        content=text if isinstance(text, str) else json.dumps(text),
        metadata={
            **(metadata or {}),
            "namespace": namespace,
            "object_type": object_type,
            "ingested_at": dt.datetime.utcnow().isoformat(),
        },
    )
    return row_uuid