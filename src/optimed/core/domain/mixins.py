
"""OptiMed domain entities (v0).

All classes are **immutable** (Pydantic frozen models) and contain only
*side‑effect‑free* helper methods.  External I/O lives in adapters or
service layers.
"""

"""Shared Pydantic base class with frozen + no-extra config."""

from pydantic import BaseModel


class FrozenModel(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}