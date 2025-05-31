
from pydantic import BaseModel

"""Shared Pydantic base class with frozen + no-extra config."""


class FrozenModel(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}