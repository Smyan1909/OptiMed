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
    GDPR-compliant: No database storage to prevent PHI persistence.
    
    This function now returns a mock UUID for backward compatibility
    but does not store any data in the database.
    """
    print(f"[GDPR] embed_and_store blocked for namespace={namespace}, object_type={object_type}, object_id={object_id}")
    
    # GDPR Compliance: Do not store any PHI data in the database
    # Return a mock UUID for backward compatibility
    import uuid
    return str(uuid.uuid4())