from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_hash(obj: Any, namespace: str = "") -> str:
    """Create a deterministic short hash for idempotency and pseudonyms.

    - Sort keys for dicts
    - Convert non-serializable objects via repr
    - Include optional namespace salt
    """

    def default(o: Any) -> str:
        try:
            return repr(o)
        except Exception:
            return f"<unserializable:{type(o).__name__}>"

    data = json.dumps(obj, sort_keys=True, default=default, ensure_ascii=False)
    payload = f"{namespace}|{data}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


