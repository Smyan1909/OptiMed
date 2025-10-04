from __future__ import annotations
import os
from typing import Any
from dotenv import load_dotenv
from optimed.adapters.vectorstores.pgvector import PGVectorAdapter
from optimed.core.logging_utils import get_logger

load_dotenv()

logger = get_logger(__name__)
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
    logger.info(f"GDPR compliance: embed_and_store blocked for namespace={namespace}, object_type={object_type}")

    # GDPR Compliance: Do not store any PHI data in the database
    # Return a mock UUID for backward compatibility
    import uuid
    return str(uuid.uuid4())