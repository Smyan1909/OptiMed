from __future__ import annotations

from optimed.core.domain import ChunkPolicy, PolicySet


# Strategy registry: resource_type -> strategy implementation name
STRATEGY_REGISTRY: dict[str, str] = {
    # atomic types
    "vital": "AtomicFactV1",
    "lab": "AtomicFactV1",
    "medication": "AtomicFactV1",
    "allergy": "AtomicFactV1",
    "diagnosis": "AtomicFactV1",
    "immunization": "AtomicFactV1",

    # narrative types
    "diagnostic_report": "NarrativeV1",
    "clinical_impression": "NarrativeV1",
    "questionnaire": "NarrativeV1",
    "journal_entry": "NarrativeV1",
    "document": "NarrativeV1",
    "csv_row": "NarrativeV1",
    "pdf": "NarrativeV1",

    # bundling stage
    "bundle": "TimeBundleV1",
    "default": "NarrativeV1",
}


POLICY_PRESETS = PolicySet(
    presets={
        "atomic_default": ChunkPolicy(name="atomic_default", max_tokens=180, overlap=0.0),
        "narrative_default": ChunkPolicy(name="narrative_default", max_tokens=800, overlap=0.12, boundary_rules={"sentence": True}),
        "bundle_default": ChunkPolicy(name="bundle_default", max_tokens=500, overlap=0.12, grouping_rules={"by": "encounter_or_month"}),
    }
)


FEATURE_FLAGS: dict[str, bool] = {
    "AtomicV2": False,
    "NarrativeV2": False,
    "TimeBundleV2": False,
}


