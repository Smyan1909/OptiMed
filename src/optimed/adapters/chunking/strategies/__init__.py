from typing import Dict

from optimed.core.ports import ChunkingStrategy

from .atomic_fact_v1 import AtomicFactV1
from .narrative_v1 import NarrativeV1
from .time_bundle_v1 import TimeBundleV1

# Mapping from strategy name to concrete strategy classes
STRATEGY_IMPLEMENTATIONS: Dict[str, type[ChunkingStrategy]] = {
    "AtomicFactV1": AtomicFactV1,
    "NarrativeV1": NarrativeV1,
    "TimeBundleV1": TimeBundleV1,
}


