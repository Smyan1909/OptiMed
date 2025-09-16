from .atomic_fact_v1 import AtomicFactV1
from .narrative_v1 import NarrativeV1
from .time_bundle_v1 import TimeBundleV1

STRATEGY_IMPLEMENTATIONS = {
    "AtomicFactV1": AtomicFactV1,
    "NarrativeV1": NarrativeV1,
    "TimeBundleV1": TimeBundleV1,
}


