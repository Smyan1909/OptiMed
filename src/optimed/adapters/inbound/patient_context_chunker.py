from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

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
        def emit_atomic(resource_type: str, kv: Dict[str, str], ts: Dict[str, str] | None = None, units_map: Dict[str, str] | None = None, sources_dict: Dict[str, Any] | None = None):
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
                
                # Include source information in the text field for atomic records
                text_content = redacted_value
                if sources_dict and key in sources_dict:
                    source = sources_dict[key]
                    source_url = getattr(source, 'resource_url', None)
                    if source_url:
                        text_content = f"{redacted_value} [EHR Source]({source_url})"
                    else:
                        text_content = f"{redacted_value} (from EHR, no link available)"
                else:
                    # No source information available
                    text_content = f"{redacted_value} (from EHR, no link available)"
                
                records.append(
                    Record(
                        patient_ref=pseudo_patient,
                        encounter_ref=None,
                        resource_type=resource_type,
                        key=key,
                        value=redacted_value,
                        text=text_content,  # Include source links in text
                        units=unit,
                        timestamp=timestamp,
                    )
                )

        emit_atomic("vital", patient.vitals, patient.vitals_timestamps, sources_dict=patient.vitals_sources)
        emit_atomic("lab", patient.labs, patient.labs_timestamps, sources_dict=patient.labs_sources)
        emit_atomic("medication", patient.medications, patient.medications_timestamps, sources_dict=patient.medications_sources)
        emit_atomic("allergy", patient.allergies, patient.allergies_timestamps, sources_dict=patient.allergies_sources)
        emit_atomic("diagnosis", patient.diagnoses, patient.diagnoses_timestamps, sources_dict=patient.diagnoses_sources)
        emit_atomic("immunization", patient.immunizations, patient.immunizations_timestamps, sources_dict=patient.immunizations_sources)

        # Long text narratives
        def emit_narrative(resource_type: str, kv: Dict[str, str], ts: Dict[str, str] | None = None, sources_dict: Dict[str, Any] | None = None):
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
                
                # Include source information in narrative text
                text_content = redacted_text
                if sources_dict and key in sources_dict:
                    source = sources_dict[key]
                    source_url = getattr(source, 'resource_url', None)
                    if source_url:
                        text_content = f"{redacted_text}\n\n**Source:** [EHR Record]({source_url})"
                    else:
                        text_content = f"{redacted_text}\n\n**Source:** (from EHR, no link available)"
                else:
                    # No source information available
                    text_content = f"{redacted_text}\n\n**Source:** (from EHR, no link available)"
                
                records.append(
                    Record(
                        patient_ref=pseudo_patient,
                        encounter_ref=None,
                        resource_type=resource_type,
                        key=key,
                        text=text_content,
                        timestamp=timestamp,
                    )
                )

        emit_narrative("diagnostic_report", patient.diagnostic_reports, patient.diagnostic_reports_timestamps, sources_dict=patient.diagnostic_reports_sources)
        emit_narrative("clinical_impression", patient.clinical_impressions, patient.clinical_impressions_timestamps, sources_dict=patient.clinical_impressions_sources)
        emit_narrative("questionnaire", patient.questionnaire_response, patient.questionnaire_response_timestamps, sources_dict=patient.questionnaire_response_sources)

        return records


