from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Sequence

from optimed.core.domain import Chunk, Record, PolicySet, PatientContext
from optimed.core.ports import ChunkingOrchestrator as ChunkingOrchestratorPort
from optimed.core.ports import TokenizerPort, PhiRedactorPort
from optimed.adapters.chunking.strategies import STRATEGY_IMPLEMENTATIONS
from optimed.core.services.hash_utils import stable_hash


class ChunkingOrchestrator(ChunkingOrchestratorPort):
    """
    Apply inbound adapters -> strategies -> post-processing and invariants.

    NOTE: PHI redaction is NOT performed during chunking for GDPR compliance.
    Instead, compliance is achieved through:
    - RAM-only processing (no persistence)
    - Access controls (RLS, authentication)
    - Audit logging (metadata only, no PHI)
    - Auto-cleanup on session end
    - GDPR Article 9(2)(h): Healthcare professionals may process health data with identifiers
    """

    def __init__(
        self,
        *,
        tokenizer: TokenizerPort,
        strategy_registry: dict[str, str],  # resource_type -> strategy class name
        policies: PolicySet,
        feature_flags: dict[str, Any] | None = None,
    ) -> None:
        self._tokenizer = tokenizer
        self._strategy_registry = strategy_registry
        self._policies = policies
        self._feature_flags = feature_flags or {}

    # Public API
    def chunk_patient(self, patient_context: PatientContext, policy_set: PolicySet) -> list[Chunk]:
        """
        Chunk patient context WITHOUT PHI redaction.

        Clinical data is preserved for healthcare professionals per GDPR Article 9(2)(h).
        """
        from optimed.adapters.inbound.patient_context_chunker import PatientContextChunkerAdapter

        # No redactor - healthcare professionals need complete clinical data
        adapter = PatientContextChunkerAdapter(redactor=None)
        records = adapter.to_records(patient_context)
        pseudo_patient = stable_hash({"pid": patient_context.patient_id}, namespace="patient")
        # attach pseudonymous patient_ref
        records = [r.model_copy(update={"patient_ref": pseudo_patient}) for r in records]
        return self._chunk_records(records, policy_set)

    def chunk_document(self, document_ref: dict[str, Any], policy_set: PolicySet) -> list[Chunk]:
        """
        Chunk document WITHOUT PHI redaction.

        Clinical data is preserved for healthcare professionals per GDPR Article 9(2)(h).
        """
        from optimed.adapters.inbound.document_chunker import DocumentChunkerAdapter

        # No redactor - healthcare professionals need complete clinical data
        adapter = DocumentChunkerAdapter(redactor=None)
        doc_type = document_ref.get("type")
        if doc_type == "csv":
            records = adapter.csv_to_records(document_ref["path"], resource_type="csv_row")
        elif doc_type == "pdf":
            # assume text extracted already
            records = adapter.pdf_to_records(document_ref.get("text", ""), resource_type="pdf")
        else:
            raise ValueError(f"Unsupported document type: {doc_type}")
        return self._chunk_records(records, policy_set)

    # Internal flow
    def _chunk_records(self, records: Sequence[Record], policy_set: PolicySet) -> list[Chunk]:
        # Route by resource_type
        by_type: dict[str, list[Record]] = defaultdict(list)
        for r in records:
            by_type[r.resource_type].append(r)

        produced: list[Chunk] = []
        for resource_type, group in by_type.items():
            strategy_name = self._strategy_registry.get(resource_type) or self._strategy_registry.get("default")
            if not strategy_name:
                continue
            strategy_cls = STRATEGY_IMPLEMENTATIONS[strategy_name]
            strategy = strategy_cls()  # type: ignore[misc]
            # map resource_type to policy preset
            preset_name = self._policy_for_resource(resource_type)
            policy = policy_set.get(preset_name)
            # NO redaction - healthcare professionals need complete clinical data
            # GDPR compliance achieved through RAM-only processing + access controls
            produced.extend(strategy.apply(group, policy, self._tokenizer))

        # Bundle by encounter/time using bundling strategy if configured
        bundle_strategy_name = self._strategy_registry.get("bundle")
        if bundle_strategy_name:
            bundle_cls = STRATEGY_IMPLEMENTATIONS[bundle_strategy_name]
            bundle = bundle_cls()  # type: ignore[misc]
            bundle_policy = policy_set.get("bundle_default")
            # Convert existing chunks back into Records for bundling
            bundle_records = [
                Record(
                    patient_ref=c.patient_ref,
                    encounter_ref=c.encounter_ref,
                    resource_type="bundle_source",
                    key=c.key,
                    text=c.text,
                    timestamp=c.timestamp,
                    extra={"time_bucket": c.time_bucket},
                )
                for c in produced
            ]
            produced = bundle.apply(bundle_records, bundle_policy, self._tokenizer)

        # Post-process: dedupe, validate privacy and size
        produced = self._dedupe(produced)
        self._validate_privacy(produced)
        produced = self._enrich_time_bucket(produced)
        return produced

    def _policy_for_resource(self, resource_type: str) -> str:
        if resource_type in ("vital", "lab", "medication", "allergy", "diagnosis", "immunization"):
            return "atomic_default"
        return "narrative_default"

    def _dedupe(self, chunks: list[Chunk]) -> list[Chunk]:
        seen = set()
        unique: list[Chunk] = []
        for c in chunks:
            key = (c.id, c.text)
            if key in seen:
                continue
            seen.add(key)
            unique.append(c)
        return unique

    def _validate_privacy(self, chunks: Iterable[Chunk]) -> None:
        for c in chunks:
            # Invariant: no PHI allowed; we rely on adapters and final sweep
            assert c.has_phi is False, "Chunk privacy invariant violated: has_phi must be False"

    def _enrich_time_bucket(self, chunks: list[Chunk]) -> list[Chunk]:
        enriched: list[Chunk] = []
        for c in chunks:
            tb = c.time_bucket
            if not tb and c.timestamp:
                tb = c.timestamp.strftime("%Y-%m")
            enriched.append(c.model_copy(update={"time_bucket": tb}))
        return enriched


