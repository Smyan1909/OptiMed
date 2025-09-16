from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from optimed.core.domain import PatientContext, Record, PolicySet
from optimed.core.ports import ChunkerPort, PhiRedactorPort


class PatientContextChunkerAdapter(ChunkerPort):
    """Convert PatientContext into Records and delegate chunking via orchestrator.

    This adapter only builds Records and enforces basic PHI stripping from
    demographic fields before producing records.
    """

    def __init__(self, redactor: PhiRedactorPort):
        self._redactor = redactor

    def chunk_from_patient(self, patient_context: PatientContext, policy_set: PolicySet) -> list:
        raise NotImplementedError("Use orchestrator.chunk_patient which calls this adapter to produce Records")

    def chunk_from_document(self, document_ref: dict[str, Any], policy_set: PolicySet) -> list:
        raise NotImplementedError("Not supported in PatientContext adapter")

    # --- helpers ---
    def to_records(self, patient: PatientContext) -> list[Record]:
        records: list[Record] = []
        pseudo_patient = None  # created by orchestrator

        # Atomic facts from dict fields
        def emit_atomic(resource_type: str, kv: Dict[str, str], ts: Dict[str, str] | None = None, units_map: Dict[str, str] | None = None):
            if not kv:
                return
            for key, value in kv.items():
                # conservative redaction on value
                redacted_value = self._redactor.redact(value)
                timestamp = None
                if ts and key in ts and ts[key]:
                    try:
                        timestamp = datetime.fromisoformat(ts[key])
                    except Exception:
                        timestamp = None
                unit = units_map.get(key) if units_map else None
                records.append(
                    Record(
                        patient_ref=pseudo_patient,
                        encounter_ref=None,
                        resource_type=resource_type,
                        key=key,
                        value=redacted_value,
                        units=unit,
                        timestamp=timestamp,
                    )
                )

        emit_atomic("vital", patient.vitals, patient.vitals_timestamps)
        emit_atomic("lab", patient.labs, patient.labs_timestamps)
        emit_atomic("medication", patient.medications, patient.medications_timestamps)
        emit_atomic("allergy", patient.allergies, patient.allergies_timestamps)
        emit_atomic("diagnosis", patient.diagnoses, patient.diagnoses_timestamps)
        emit_atomic("immunization", patient.immunizations, patient.immunizations_timestamps)

        # Long text narratives
        def emit_narrative(resource_type: str, kv: Dict[str, str], ts: Dict[str, str] | None = None):
            if not kv:
                return
            for key, text in kv.items():
                redacted_text = self._redactor.redact(text)
                timestamp = None
                if ts and key in ts and ts[key]:
                    try:
                        timestamp = datetime.fromisoformat(ts[key])
                    except Exception:
                        timestamp = None
                records.append(
                    Record(
                        patient_ref=pseudo_patient,
                        encounter_ref=None,
                        resource_type=resource_type,
                        key=key,
                        text=redacted_text,
                        timestamp=timestamp,
                    )
                )

        emit_narrative("diagnostic_report", patient.diagnostic_reports, patient.diagnostic_reports_timestamps)
        emit_narrative("clinical_impression", patient.clinical_impressions, patient.clinical_impressions_timestamps)
        emit_narrative("questionnaire", patient.questionnaire_response, patient.questionnaire_response_timestamps)

        return records


