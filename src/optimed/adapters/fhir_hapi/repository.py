# mypy: ignore-errors
from __future__ import annotations
import base64
import os
from datetime import datetime, timezone
from typing import Optional, Sequence, Any
from pydantic import ValidationError

import httpx
from fhir.resources.patient import Patient # type: ignore[import-untyped]
from fhir.resources.observation import Observation # type: ignore[import-untyped]

from optimed.core.domain import PatientContext, JournalEntry, User, JournalEntryType, JournalEntryCreate, JournalEntryUpdate, DataSource
from optimed.core.ports import FHIRRepository
import uuid

"""
optimed.adapters.fhir_hapi.repository
-------------------------------------

Read-only FHIR adapter that talks to the public HAPI R4 demo server
(https://hapi.fhir.org/baseR4) and converts resources into the project’s
domain models.

✓ Implements FHIRRepository (core.ports)
✓ Async/await-friendly via httpx.AsyncClient
✓ No authentication – perfect for CI and early prototypes
"""

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_BASE_URL = "https://hapi.fhir.org/baseR4"
FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", DEFAULT_BASE_URL).rstrip("/")

# LOINC codes for quick MVP mapping  (add more when needed)
VITAL_CODES = {
    "8867-4": "Heart rate",
    "59408-5": "Respiratory rate",
    "8480-6": "Systolic BP",
    "8462-4": "Diastolic BP",
    "8310-5": "Body temperature",
    "2708-6": "Oxygen saturation",
    "9279-1": "Respiratory rate",
    "8287-5": "Head circumference",
    "29463-7": "Body weight",
    "8302-2": "Body height",
}

CRITICAL_LAB_CODES = {
    "2823-3": "Potassium",
    "2339-0": "Glucose",
    "2951-2": "Sodium",
    "6298-4": "Potassium",
    "33747-0": "Hemoglobin A1c",
    "718-7": "Hemoglobin",
    "4544-3": "Hematocrit",
    "6690-2": "White blood cells",
    "777-3": "Platelets",
    "2160-0": "Creatinine",
    "3094-0": "BUN",
    "1751-7": "Albumin",
    "1975-2": "Bilirubin",
}

IMAGING_CODES = {
    "18726-0": "Radiology report",
    "18748-4": "Diagnostic imaging study",
    "18747-6": "CT scan",
    "36643-5": "Ultrasound",
    "30954-2": "X-ray",
    "18745-0": "Cardiac catheterization",
    "18746-8": "Colonoscopy",
}

EXAM_CODES = {
    "8716-3": "Physical examination",
    "10210-3": "Physical findings",
    "8302-2": "Body height",
    "29463-7": "Body weight",
    "39156-5": "Body mass index",
    "8867-4": "Heart rate",
    "8480-6": "Systolic blood pressure",
    "8462-4": "Diastolic blood pressure",
    "8310-5": "Body temperature",
    "33747-0": "General appearance",
}

PROCEDURE_CODES = {
    "47519-4": "History of procedures",
    "8716-3": "Surgical procedure",
    "18776-5": "Treatment plan",
    "33747-0": "Procedure performed",
    "72133-2": "Procedure indication",
    "59776-5": "Procedure outcome",
}

SOCIAL_HISTORY_CODES = {
    "72166-2": "Tobacco smoking status",
    "11331-6": "History of occupational exposure",
    "76689-9": "Sex assigned at birth",
    "72133-2": "Social history",
    "229819007": "Tobacco use",
    "160573003": "Alcohol intake",
    "182836005": "Review of systems",
    "408512008": "Body piercing",
    "228273003": "Finding relating to drug misuse",
}

MEDICATION_CODES = {
    "10160-0": "History of medication use",
    "8716-3": "Medication administration",
    "182836005": "Drug therapy",
}

ALLERGY_CODES = {
    "48765-2": "Allergies and adverse reactions",
    "10155-0": "History of allergic reaction",
    "420134006": "Propensity to adverse reactions",
}

DIAGNOSIS_CODES = {
    "11348-0": "History of past illness",
    "10154-3": "Chief complaint",
    "46239-0": "Reason for encounter",
    "8716-3": "Problem list",
}

MEDICATION_STATEMENT_CODES = {
    "182840001": "Drug treatment",
    "182836005": "Review of medication",
    "432102000": "Administration of substance",
    "182849000": "Drug therapy discontinued",
    "182842009": "Drug treatment started",
    "182843004": "Drug treatment stopped",
}

QUESTIONNAIRE_CODES = {
    "273879006": "Patient questionnaire",
    "162673000": "General examination of patient",
    "225336008": "Suicide risk assessment",
    "273724008": "Quality of life assessment",
    "225358003": "Pain assessment",
    "386053000": "Evaluation procedure",
    "710830005": "Assessment of anxiety",
}

IMMUNIZATION_CODES = {
    "33879002": "Immunization procedure",
    "127786006": "Injection of vaccine product",
    "170433008": "Administration of vaccine",
    "396429000": "Vaccination for COVID-19",
    "72093006": "Influenza vaccination",
    "16290008": "Hepatitis B vaccination",
    "408864009": "Pneumococcal vaccination",
    "396430005": "Tetanus vaccination",
    "16584000": "Pertussis vaccination",
    "396431009": "Diphtheria vaccination",
    "396432002": "Polio vaccination",
    "396433007": "MMR vaccination",
}

ENCOUNTER_CODES = {
    "308335008": "Patient encounter procedure",
    "185349003": "Encounter for check up",
    "270427003": "Patient-initiated encounter",
    "50849002": "Emergency room visit",
    "183807002": "Inpatient stay",
    "185345009": "Outpatient visit",
}

COMPONENT_OBSERVATIONS = {
    "85354-9": {  # Blood pressure panel
        "components": {
            "8480-6": "Systolic BP",
            "8462-4": "Diastolic BP"
        }
    },
    "55284-4": {  # Blood pressure systolic and diastolic
        "components": {
            "8480-6": "Systolic BP", 
            "8462-4": "Diastolic BP"
        }
    }
}

# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #

def _unique_key(base: str, container: dict[str, Any]) -> str:
    """Ensure a unique display name key by appending (n) if needed."""
    if base not in container:
        return base
    idx = 2
    while f"{base} ({idx})" in container:
        idx += 1
    return f"{base} ({idx})"

def _create_data_source(
    resource_id: str,
    resource_type: str,
    base_url: str,
    timestamp: Optional[datetime] = None,
    category: Optional[str] = None,
    display_name: str = ""
) -> DataSource:
    """Create a DataSource object for traceability."""
    return DataSource(
        source_type=resource_type.lower(),
        resource_id=resource_id,
        resource_url=f"{base_url}/{resource_type}/{resource_id}",
        timestamp=timestamp or datetime.now(timezone.utc),
        category=category,
        display_name=display_name
    )

def _map_entry_type_to_fhir_type(entry_type: JournalEntryType) -> str:
    """Map journal entry type to FHIR DocumentReference type."""
    type_mapping = {
        JournalEntryType.NOTE: "11506-3",  # Progress note
        JournalEntryType.OBSERVATION: "11502-2",  # Laboratory report
        JournalEntryType.TREATMENT: "18842-5",  # Discharge summary
        JournalEntryType.DIAGNOSIS: "11488-4",  # Consultation note
        JournalEntryType.ASSESSMENT: "51847-2",  # Evaluation note
        JournalEntryType.PLAN: "18776-5"   # Plan of care note
    }
    return type_mapping.get(entry_type, "11506-3")

def _map_fhir_type_to_entry_type(fhir_type: str) -> JournalEntryType:
    """Map FHIR DocumentReference type back to journal entry type."""
    type_mapping = {
        "11506-3": JournalEntryType.NOTE,
        "11502-2": JournalEntryType.OBSERVATION, 
        "18842-5": JournalEntryType.TREATMENT,
        "11488-4": JournalEntryType.DIAGNOSIS,
        "51847-2": JournalEntryType.ASSESSMENT,
        "18776-5": JournalEntryType.PLAN
    }
    return type_mapping.get(fhir_type, JournalEntryType.NOTE)

def _age_from_birthdate(date) -> int:
    """Calculate age in years from FHIR birthDate."""
    if not date:
        return 0
    today = datetime.now(timezone.utc).date()
    return max(0, (today - date).days // 365)

def _fhir_name_to_str(p: Patient) -> str:
    """Return best effort full name"""
    if not p.name:
        return "Unknown"
    n = p.name[0]
    if n.text:
        return n.text
    parts = []
    if n.given:
        parts.extend(n.given)
    if n.family:
        parts.append(n.family)
    return " ".join(parts).strip() or "Unknown"

def _process_observation_components(obs, base_url: str, category: str) -> tuple[dict, dict, dict]:
    """
    Process multi-component observations and return individual components.
    Returns: (result_dict, timestamps_dict, sources_dict)
    """
    result = {}
    timestamps = {}
    sources = {}
    
    if not obs.component:
        return result, timestamps, sources
    
    # Get the main observation's LOINC code
    main_loinc = None
    if obs.code and obs.code.coding:
        for coding in obs.code.coding:
            if coding.system == "http://loinc.org":
                main_loinc = coding.code
                break
    
    # Check if this is a known multi-component observation
    if main_loinc and main_loinc in COMPONENT_OBSERVATIONS:
        component_config = COMPONENT_OBSERVATIONS[main_loinc]
        
        for component in obs.component:
            if component.code and component.code.coding:
                for coding in component.code.coding:
                    component_code = coding.code
                    
                    # Check if this component is one we want to extract
                    if component_code in component_config["components"]:
                        display_name = component_config["components"][component_code]
                        
                        # Extract value
                        value_str = "N/A"
                        if component.valueQuantity:
                            unit = component.valueQuantity.unit or ""
                            value_str = f"{component.valueQuantity.value} {unit}".strip()
                        elif component.valueString:
                            value_str = component.valueString
                        elif component.valueCodeableConcept:
                            if component.valueCodeableConcept.text:
                                value_str = component.valueCodeableConcept.text
                        
                        result[display_name] = value_str
                        
                        # Extract timestamp from parent observation
                        timestamp = obs.effectiveDateTime or obs.issued
                        if timestamp:
                            if hasattr(timestamp, 'strftime'):
                                timestamps[display_name] = timestamp.strftime("%Y-%m-%d %H:%M")
                                source_timestamp = timestamp
                            else:
                                try:
                                    dt = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
                                    timestamps[display_name] = dt.strftime("%Y-%m-%d %H:%M")
                                    source_timestamp = dt
                                except Exception:
                                    timestamps[display_name] = str(timestamp)[:16] if len(str(timestamp)) > 16 else str(timestamp)
                                    source_timestamp = None
                        else:
                            timestamps[display_name] = "Unknown"
                            source_timestamp = None
                        
                        # Create source link to parent observation
                        sources[display_name] = _create_data_source(
                            resource_id=obs.id or "unknown",
                            resource_type="Observation",
                            base_url=base_url,
                            timestamp=source_timestamp,
                            category=category,
                            display_name=display_name
                        )
    
    return result, timestamps, sources

def _obs_bundle_to_dict_with_timestamps(entries: list[Observation], base_url:str, category: str = "") -> tuple[dict[str, str], dict[str, str], dict[str, DataSource]]:
    """Convert observation bundle to dict with human-readable names and timestamps."""
    result = {}
    timestamps = {}
    sources = {}
    
    for obs in entries:
        # Handle both Observation objects and dict representations
        if isinstance(obs, dict):
            # Handle dict-based observations (from medications, allergies, diagnoses)
            if obs.get("code") and obs["code"].get("coding"):
                coding = obs["code"]["coding"][0]
                display_name = coding.get("display") or coding.get("code") or "Unknown"
                display_name = _unique_key(display_name, result)
                value_str = obs.get("valueString", "N/A")
                result[display_name] = value_str
                
                # Extract timestamp
                timestamp = obs.get("effectiveDateTime") or obs.get("issued") or "Unknown"
                if isinstance(timestamp, str):
                    try:
                        # Parse and format timestamp
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        timestamps[display_name] = dt.strftime("%Y-%m-%d %H:%M")
                        source_timestamp = dt
                    except Exception:
                        timestamps[display_name] = timestamp[:16] if len(timestamp) > 16 else timestamp
                        source_timestamp = None
                else:
                    timestamps[display_name] = "Unknown"
                    source_timestamp = None
                
                resource_id = obs.get("id", "unknown")
                resource_type = obs.get("resource_type", "observation")
                sources[display_name] = _create_data_source(
                    resource_id=resource_id,
                    resource_type=resource_type,
                    base_url=base_url,
                    timestamp=source_timestamp,
                    category=category,
                    display_name=display_name
                )
                
        else:
            # Handle actual Observation objects
            if obs.code and obs.code.coding:
                # Get the LOINC code
                loinc_code = None
                for coding in obs.code.coding:
                    if coding.system == "http://loinc.org":
                        loinc_code = coding.code
                        break
                
                
                if loinc_code and loinc_code in COMPONENT_OBSERVATIONS:
                    comp_result, comp_timestamps, comp_sources = _process_observation_components(obs, base_url, category)
                    result.update(comp_result)
                    timestamps.update(comp_timestamps)
                    sources.update(comp_sources)
                    continue
                
                
                if loinc_code:
                    # Determine category based on our mappings
                    display_name = None
                    if loinc_code in VITAL_CODES:
                        display_name = VITAL_CODES[loinc_code]
                    elif loinc_code in CRITICAL_LAB_CODES:
                        display_name = CRITICAL_LAB_CODES[loinc_code]
                    elif loinc_code in IMAGING_CODES:
                        display_name = IMAGING_CODES[loinc_code]
                    elif loinc_code in EXAM_CODES:
                        display_name = EXAM_CODES[loinc_code]
                    elif loinc_code in PROCEDURE_CODES:
                        display_name = PROCEDURE_CODES[loinc_code]
                    elif loinc_code in SOCIAL_HISTORY_CODES:
                        display_name = SOCIAL_HISTORY_CODES[loinc_code]
                    elif loinc_code in MEDICATION_CODES:
                        display_name = MEDICATION_CODES[loinc_code]
                    elif loinc_code in ALLERGY_CODES:
                        display_name = ALLERGY_CODES[loinc_code]
                    elif loinc_code in DIAGNOSIS_CODES:
                        display_name = DIAGNOSIS_CODES[loinc_code]
                    elif loinc_code in MEDICATION_STATEMENT_CODES:
                        display_name = MEDICATION_STATEMENT_CODES[loinc_code]
                    elif loinc_code in QUESTIONNAIRE_CODES:
                        display_name = QUESTIONNAIRE_CODES[loinc_code]
                    elif loinc_code in IMMUNIZATION_CODES:
                        display_name = IMMUNIZATION_CODES[loinc_code]
                    else:
                        # Fallback to the display name from FHIR or the code itself
                        display_name = obs.code.coding[0].display or loinc_code
                    display_name = _unique_key(display_name, result)
                    
                    # Get the value
                    value_str = "N/A"
                    if obs.valueQuantity:
                        unit = obs.valueQuantity.unit or ""
                        value_str = f"{obs.valueQuantity.value} {unit}".strip()
                    elif obs.valueString:
                        value_str = obs.valueString
                    elif obs.valueCodeableConcept:
                        if obs.valueCodeableConcept.text:
                            value_str = obs.valueCodeableConcept.text
                    
                    result[display_name] = value_str
                    
                    # Extract timestamp from observation
                    timestamp = obs.effectiveDateTime or obs.issued
                    if timestamp:
                        if hasattr(timestamp, 'strftime'):
                            timestamps[display_name] = timestamp.strftime("%Y-%m-%d %H:%M")
                            source_timestamp = timestamp
                        else:
                            # Handle string timestamps
                            try:
                                dt = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
                                timestamps[display_name] = dt.strftime("%Y-%m-%d %H:%M")
                                source_timestamp = dt
                            except Exception:
                                timestamps[display_name] = str(timestamp)[:16] if len(str(timestamp)) > 16 else str(timestamp)
                                source_timestamp = None
                    else:
                        timestamps[display_name] = "Unknown"
                        source_timestamp = None
                    
                    sources[display_name] = _create_data_source(
                        resource_id=obs.id or "unknown",
                        resource_type="Observation",
                        base_url=base_url,
                        timestamp=source_timestamp,
                        category=category,
                        display_name=display_name
                    )
    
    return result, timestamps, sources


def get_display_name(code: str, code_type: str = "vital") -> str:
    """Get human readable name for a LOINC code."""
    if code_type == "vital":
        return VITAL_CODES.get(code, code)
    elif code_type == "lab":
        return CRITICAL_LAB_CODES.get(code, code)
    return code

def _to_patient_ctx(
        patient: Patient,
        vitals: list[Observation] | None = None,
        labs: list[Observation] | None = None,
        imaging_observations: list[Observation] | None = None,
        exam: list[Observation] | None = None,
        procedure_observations: list[Observation] | None = None,
        social_history: list[Observation] | None = None,
        medications: list[Observation] | None = None,
        allergies: list[Observation] | None = None,
        diagnoses: list[Observation] | None = None,
        immunizations: list[Observation] | None = None,
        medication_statement: list[Observation] | None = None,
        questionnaire_response: list[Observation] | None = None,
        care_plan: list[Observation] | None = None,
        encounters: list[Any] | None = None,
        imaging_studies: list[Any] | None = None,
        procedures_fhir: list[Any] | None = None,
        diagnostic_reports: list[Any] | None = None,
        base_url: str = "http://example.com/fhir"  # Default base URL, can be overridden
) -> PatientContext:
    """Convert FHIR Patient + observations to PatientContext domain model."""
    if not patient.id:
        raise ValueError("Patient must have an ID")

    # Process observations with timestamps
    vitals_data, vitals_timestamps, vitals_sources = _obs_bundle_to_dict_with_timestamps(vitals or [], base_url, "vital-signs")
    labs_data, labs_timestamps, labs_sources = _obs_bundle_to_dict_with_timestamps(labs or [], base_url, "laboratory")
    imaging_observations_data, imaging_observations_timestamps, imaging_observations_sources = _obs_bundle_to_dict_with_timestamps(imaging_observations or [], base_url, "imaging")
    exam_data, exam_timestamps, exam_sources = _obs_bundle_to_dict_with_timestamps(exam or [], base_url, "exam")
    procedure_observations_data, procedure_observations_timestamps, procedure_observations_sources = _obs_bundle_to_dict_with_timestamps(procedure_observations or [], base_url, "procedure")
    social_history_data, social_history_timestamps, social_history_sources = _obs_bundle_to_dict_with_timestamps(social_history or [], base_url, "social-history")
    medications_data, medications_timestamps, medications_sources = _obs_bundle_to_dict_with_timestamps(medications or [], base_url, "medication")
    allergies_data, allergies_timestamps, allergies_sources = _obs_bundle_to_dict_with_timestamps(allergies or [], base_url, "allergy")
    diagnoses_data, diagnoses_timestamps, diagnoses_sources = _obs_bundle_to_dict_with_timestamps(diagnoses or [], base_url, "condition")
    immunizations_data, immunizations_timestamps, immunizations_sources = _obs_bundle_to_dict_with_timestamps(immunizations or [], base_url, "immunization")
    medication_statement_data, medication_statement_timestamps, medication_statement_sources = _obs_bundle_to_dict_with_timestamps(medication_statement or [], base_url, "medication-statement")
    questionnaire_response_data, questionnaire_response_timestamps, questionnaire_response_sources = _obs_bundle_to_dict_with_timestamps(questionnaire_response or [], base_url, "questionnaire")
    care_plan_data, care_plan_timestamps, care_plan_sources = _obs_bundle_to_dict_with_timestamps(care_plan or [], base_url, "care-plan")

    # Process FHIR /ImagingStudy and /Procedure resources (converted to dict-like entries upstream)
    imaging_data, imaging_timestamps, imaging_sources = _obs_bundle_to_dict_with_timestamps(imaging_studies or [], base_url, "imaging")
    procedure_data, procedure_timestamps, procedure_sources = _obs_bundle_to_dict_with_timestamps(procedures_fhir or [], base_url, "procedure")
    diagnostic_reports_data, diagnostic_reports_timestamps, diagnostic_reports_sources = _obs_bundle_to_dict_with_timestamps(diagnostic_reports or [], base_url, "diagnostic-report")
    
    # Process encounters and extract care unit information
    encounters_data = {}
    encounters_timestamps = {}
    encounters_sources = {}
    care_unit = "UNKNOWN"
    
    if encounters:
        for encounter in encounters:
            if isinstance(encounter, dict):
                encounter_type = encounter.get("type", [{}])[0].get("text", "Unknown Encounter")
                encounter_id = encounter.get("id", "unknown")
                encounters_data[encounter_id] = encounter_type
                
                # Extract care unit from encounter location or serviceType
                if care_unit == "UNKNOWN":
                    # Try to get care unit from location
                    locations = encounter.get("location", [])
                    if locations and len(locations) > 0:
                        location = locations[0].get("location", {})
                        if location.get("display"):
                            care_unit = location["display"]
                        elif location.get("reference"):
                            # Extract location name from reference
                            location_name = location["reference"].split("/")[-1]
                            care_unit = location_name
                    
                    # If no location found, try serviceType
                    if care_unit == "UNKNOWN":
                        service_type = encounter.get("serviceType")
                        if service_type and service_type.get("text"):
                            care_unit = service_type["text"]
                        elif service_type and service_type.get("coding"):
                            for coding in service_type["coding"]:
                                if coding.get("display"):
                                    care_unit = coding["display"]
                                    break
                    
                    # If still no care unit, try class display
                    if care_unit == "UNKNOWN":
                        encounter_class = encounter.get("class", {})
                        if encounter_class.get("display"):
                            care_unit = encounter_class["display"]
                
                # Extract encounter timestamp
                period = encounter.get("period", {})
                start_time = period.get("start")
                if start_time:
                    try:
                        dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                        encounters_timestamps[encounter_id] = dt.strftime("%Y-%m-%d %H:%M")
                        source_timestamp = dt
                    except Exception:
                        encounters_timestamps[encounter_id] = start_time[:16] if len(start_time) > 16 else start_time
                        source_timestamp = None
                else:
                    encounters_timestamps[encounter_id] = "Unknown"
                    source_timestamp = None
                
                encounters_sources[encounter_id] = _create_data_source(
                    resource_id=encounter_id,
                    resource_type="Encounter",
                    base_url=base_url,
                    timestamp=source_timestamp,
                    display_name=encounter_type
                )

    return PatientContext(
        patient_id=patient.id,
        name=_fhir_name_to_str(patient),
        age=_age_from_birthdate(patient.birthDate),
        sex=patient.gender or "unknown",
        care_unit=care_unit,
        
        # Data fields
        vitals=vitals_data,
        labs=labs_data,
        imaging=imaging_data,
        exam=exam_data,
        procedure=procedure_data,
        diagnostic_reports=diagnostic_reports_data,
        imaging_observations=imaging_observations_data,
        procedure_observations=procedure_observations_data,
        social_history=social_history_data,
        medications=medications_data,
        allergies=allergies_data,
        diagnoses=diagnoses_data,
        immunizations=immunizations_data,
        medication_statement=medication_statement_data,
        questionnaire_response=questionnaire_response_data,
        care_plan=care_plan_data,
        encounters=encounters_data,
        
        # Timestamp fields
        vitals_timestamps=vitals_timestamps,
        labs_timestamps=labs_timestamps,
        imaging_timestamps=imaging_timestamps,
        exam_timestamps=exam_timestamps,
        procedure_timestamps=procedure_timestamps,
        social_history_timestamps=social_history_timestamps,
        medications_timestamps=medications_timestamps,
        allergies_timestamps=allergies_timestamps,
        diagnoses_timestamps=diagnoses_timestamps,
        immunizations_timestamps=immunizations_timestamps,
        diagnostic_reports_timestamps=diagnostic_reports_timestamps,
        imaging_observations_timestamps=imaging_observations_timestamps,
        procedure_observations_timestamps=procedure_observations_timestamps,
        medication_statement_timestamps=medication_statement_timestamps,
        questionnaire_response_timestamps=questionnaire_response_timestamps,
        care_plan_timestamps=care_plan_timestamps,
        encounters_timestamps=encounters_timestamps,
        
        # Source tracking fields
        vitals_sources=vitals_sources,
        labs_sources=labs_sources,
        imaging_sources=imaging_sources,
        exam_sources=exam_sources,
        procedure_sources=procedure_sources,
        social_history_sources=social_history_sources,
        medications_sources=medications_sources,
        allergies_sources=allergies_sources,
        diagnoses_sources=diagnoses_sources,
        immunizations_sources=immunizations_sources,
        diagnostic_reports_sources=diagnostic_reports_sources,
        imaging_observations_sources=imaging_observations_sources,
        procedure_observations_sources=procedure_observations_sources,
        medication_statement_sources=medication_statement_sources,
        questionnaire_response_sources=questionnaire_response_sources,
        care_plan_sources=care_plan_sources,
        encounters_sources=encounters_sources,
    )

def _map_entry_type_to_fhir_type(entry_type: JournalEntryType) -> str:
    """Map journal entry type to FHIR DocumentReference type."""
    type_mapping = {
        JournalEntryType.NOTE: "11506-3",  # Progress note
        JournalEntryType.OBSERVATION: "11502-2",  # Laboratory report
        JournalEntryType.TREATMENT: "18842-5",  # Discharge summary
        JournalEntryType.DIAGNOSIS: "11488-4",  # Consultation note
        JournalEntryType.ASSESSMENT: "51847-2",  # Evaluation note
        JournalEntryType.PLAN: "18776-5"   # Plan of care note
    }
    return type_mapping.get(entry_type, "11506-3")  # Default to progress note

def _map_fhir_type_to_entry_type(fhir_type: str) -> JournalEntryType:
    """Map FHIR DocumentReference type back to journal entry type."""
    type_mapping = {
        "11506-3": JournalEntryType.NOTE,
        "11502-2": JournalEntryType.OBSERVATION, 
        "18842-5": JournalEntryType.TREATMENT,
        "11488-4": JournalEntryType.DIAGNOSIS,
        "51847-2": JournalEntryType.ASSESSMENT,
        "18776-5": JournalEntryType.PLAN
    }
    return type_mapping.get(fhir_type, JournalEntryType.NOTE)

def _parse_fhir_document_reference(fhir_resource: dict) -> JournalEntry:
    """Parse FHIR DocumentReference resource into JournalEntry."""
    entry_id = fhir_resource["id"]
    patient_id = fhir_resource["subject"]["reference"].split("/")[-1]
    
    # Extract entry type
    type_code = fhir_resource["type"]["coding"][0]["code"]
    entry_type = _map_fhir_type_to_entry_type(type_code)
    
    # Extract title and content
    title = fhir_resource.get("description", "Untitled Entry")
    content = ""
    if fhir_resource.get("content") and fhir_resource["content"][0].get("attachment"):
        attachment = fhir_resource["content"][0]["attachment"]
        if attachment.get("data"):
            # Decode from base64 if available
            try:
                import base64
                content = base64.b64decode(attachment["data"]).decode('utf-8')
            except Exception:
                content = attachment.get("title", "")
    
    # Extract author information
    author_display = "Unknown Author"
    author_id = "unknown"
    if fhir_resource.get("author") and len(fhir_resource["author"]) > 0:
        author = fhir_resource["author"][0]
        author_display = author.get("display", "Unknown Author")
        if author.get("reference"):
            author_id = author["reference"].split("/")[-1]
    
    # Extract timestamps
    created_at = fhir_resource.get("date", datetime.now(timezone.utc).isoformat())
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            created_at = datetime.now(timezone.utc)
    
    return JournalEntry(
        entry_id=entry_id,
        patient_id=patient_id,
        title=title,
        content=content,
        entry_type=entry_type,
        created_by=author_id,
        created_at=created_at,
        updated_at=created_at,
        author_name=author_display,
        author_role="Practitioner"
    )

# --------------------------------------------------------------------------- #
# Adapter class
# --------------------------------------------------------------------------- #

class HAPIFHIRRepository(FHIRRepository):
    """Read-only FHIR repository using the HAPI FHIR demo server."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base = (base_url or FHIR_BASE_URL).rstrip("/")
        self._client = client or httpx.AsyncClient(base_url=self._base, timeout=timeout, headers={"User-Agent": "OptiMedPrototype/0.1"})
        # In-memory storage for journal entries (since HAPI is read-only demo)
        self._journal_entries: dict[str, dict] = {}


    async def get_patient(self, patient_id: str) -> PatientContext:
        """Get patient context by ID."""
        
        patient = await self._get_patient_resource(patient_id)
        
        # Fetch all observation categories
        vitals = await self._get_observations(patient_id, category="vital-signs")
        labs = await self._get_observations(patient_id, category="laboratory")
        imaging_observations = await self._get_observations(patient_id, category="imaging")
        exam = await self._get_observations(patient_id, category="exam")
        procedure_observations = await self._get_observations(patient_id, category="procedure")
        social_history = await self._get_observations(patient_id, category="social-history")
        
        # For medications, allergies, and diagnoses, use different FHIR resources
        medications = await self._get_medications(patient_id)
        allergies = await self._get_allergies(patient_id)
        diagnoses = await self._get_conditions(patient_id)
        immunizations = await self._get_immunizations(patient_id)
        care_plan = await self._get_care_plans(patient_id)

        medication_statement = await self._get_medication_statements(patient_id)
        questionnaire_response = await self._get_questionnaire_responses(patient_id)
        encounters = await self._get_encounters(patient_id)
        imaging_studies = await self._get_imaging_studies(patient_id)
        procedures_fhir = await self._get_procedures(patient_id)
        diagnostic_reports = await self._get_diagnostic_reports(patient_id)
        
        return _to_patient_ctx(
            patient, vitals, labs, imaging_observations, exam, procedure_observations,
            social_history, medications, allergies, diagnoses, immunizations,
            medication_statement, questionnaire_response, care_plan, encounters, imaging_studies, procedures_fhir, diagnostic_reports, self._base
        )
    
    async def search_patients(self, query: Any) -> Sequence[PatientContext]:
        """Search patients by MRN or name."""
        

        query = query.strip()
        
        query = query.split()


        r = await self._client.get("/Patient", params={"name": query, "_count": 25})
        r.raise_for_status()
        bundle = r.json()

        results: list[PatientContext] = []
        for entry in bundle.get("entry", []):
            # drop the top‐level "text" block so Patient.model_validate won't expect text.div
            resource = entry["resource"].copy()
            resource.pop("text", None)
            try:
                p = Patient.model_validate(resource)
            except ValidationError:
                # skip any resource that still fails validation
                continue
            results.append(_to_patient_ctx(
                p,
                vitals=[],
                labs=[],
                imaging_observations=[],
                exam=[],
                procedure_observations=[],
                social_history=[],
                medications=[],
                allergies=[],
                diagnoses=[],
                immunizations=[],
                medication_statement=[],
                questionnaire_response=[],
                care_plan=[],
                encounters=[],
                imaging_studies=[],
                procedures_fhir=[],
                base_url=self._base
            ))

        return results
    
    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def _get_patient_resource(self, pid: str) -> Patient:
        """Fetch a single Patient resource by ID."""
        r = await self._client.get(f"/Patient/{pid}")
        r.raise_for_status()
        return Patient.model_validate(r.json())
    

    async def _get_medication_statements(self, patient_id: str) -> list[Observation]:
        """Fetch medication statement information for a patient."""
        try:
            r = await self._client.get("/MedicationStatement", params={
                "subject": patient_id,
                "_count": 100
            })
            r.raise_for_status()
            bundle = r.json()
            
            # Convert MedicationStatement to Observation-like structure
            statements = []
            for entry in bundle.get("entry", []):
                resource = entry["resource"]
                medication_name = "Unknown medication"
                
                # Extract medication name
                if resource.get("medicationCodeableConcept"):
                    medication_name = resource["medicationCodeableConcept"].get("text", medication_name)
                elif resource.get("medicationReference"):
                    medication_name = resource["medicationReference"].get("display", medication_name)
                
                # Extract status and dosage info
                status = resource.get("status", "unknown")
                effective_period = resource.get("effectivePeriod", {})
                dosage = ""
                if resource.get("dosage") and len(resource["dosage"]) > 0:
                    dosage_info = resource["dosage"][0]
                    dosage = dosage_info.get("text", "")
                
                value_str = f"{status.title()}"
                if dosage:
                    value_str += f" - {dosage}"
                if effective_period.get("start"):
                    value_str += f" (Since: {effective_period['start'][:10]})"
                
                statement_obs = {
                    "id": resource.get("id", "unknown"),
                    "status": status,
                    "code": {"coding": [{"code": "182840001", "display": "Medication Statement"}]},
                    "valueString": value_str,
                    "effectiveDateTime": effective_period.get("start", ""),
                    "resource_type": "MedicationStatement",
                }
                statements.append(statement_obs)
            
            return statements
        except Exception as e:
            print(f"Failed to fetch medication statements: {e}")
            return []

    async def _get_questionnaire_responses(self, patient_id: str) -> list[Observation]:
        """Fetch questionnaire response information for a patient."""
        try:
            r = await self._client.get("/QuestionnaireResponse", params={
                "subject": patient_id,
                "_count": 100
            })
            r.raise_for_status()
            bundle = r.json()
            
            # Convert QuestionnaireResponse to Observation-like structure
            responses = []
            for entry in bundle.get("entry", []):
                resource = entry["resource"]
                
                questionnaire_ref = resource.get("questionnaire", "")
                questionnaire_name = questionnaire_ref.split("/")[-1] if questionnaire_ref else "Unknown Questionnaire"
                
                # Extract responses
                response_text = []
                if resource.get("item"):
                    for item in resource["item"]:
                        question = item.get("text", "Question")
                        if item.get("answer"):
                            for answer in item["answer"]:
                                if answer.get("valueString"):
                                    response_text.append(f"{question}: {answer['valueString']}")
                                elif answer.get("valueInteger"):
                                    response_text.append(f"{question}: {answer['valueInteger']}")
                                elif answer.get("valueDecimal"):
                                    response_text.append(f"{question}: {answer['valueDecimal']}")
                                elif answer.get("valueBoolean"):
                                    response_text.append(f"{question}: {'Yes' if answer['valueBoolean'] else 'No'}")
                
                value_str = "; ".join(response_text) if response_text else "No responses recorded"
                
                response_obs = {
                    "id": resource.get("id", "unknown"),
                    "status": resource.get("status", "unknown"),
                    "code": {"coding": [{"code": "273879006", "display": questionnaire_name}]},
                    "valueString": value_str,
                    "effectiveDateTime": resource.get("authored", ""),
                    "resource_type": "QuestionnaireResponse"
                }
                responses.append(response_obs)
            
            return responses
        except Exception as e:
            print(f"Failed to fetch questionnaire responses: {e}")
            return []


    async def _get_medications(self, patient_id: str) -> list[Observation]:
        """Fetch medication information for a patient."""
        try:
            r = await self._client.get("/MedicationRequest", params={
                "patient": patient_id,
                "status": "active",
                "_count": 100
            })
            r.raise_for_status()
            bundle = r.json()
            
            # Convert MedicationRequest to Observation-like structure
            medications = []
            for entry in bundle.get("entry", []):
                resource = entry["resource"]
                # Create a simplified observation for medication
                med_obs = {
                    "id": resource.get("id", "unknown"),
                    "status": resource.get("status", "unknown"),
                    "code": {"coding": [{"code": "10160-0", "display": "Medication"}]},
                    "valueString": resource.get("medicationCodeableConcept", {}).get("text", "Unknown medication"),
                    "effectiveDateTime": resource.get("authoredOn", ""),
                    "resource_type": "MedicationStatement"
                }
                medications.append(med_obs)
            
            return medications
        except Exception:
            return []
    
    async def _get_allergies(self, patient_id: str) -> list[Observation]:
        """Fetch allergy information for a patient."""

        try:
            r = await self._client.get("/AllergyIntolerance", params={
                "patient": patient_id,
                "_count": 100
            })
            r.raise_for_status()
            bundle = r.json()
            
            # Convert AllergyIntolerance to Observation-like structure
            allergies = []
            for entry in bundle.get("entry", []):
                resource = entry["resource"]
                allergy_obs = {
                    "id": resource.get("id", "unknown"),
                    "status": resource.get("status", "unknown"),
                    "code": {"coding": [{"code": "48765-2", "display": "Allergies"}]},
                    "valueString": resource.get("code", {}).get("text", "Unknown allergy"),
                    "effectiveDateTime": resource.get("recordedDate", ""),
                    "resource_type": "AllergyIntolerance"
                }
                allergies.append(allergy_obs)
            
            return allergies
        except Exception:
            return []

    async def _get_immunizations(self, patient_id: str) -> list[Observation]:
        """Fetch immunization information for a patient."""
        try:
            r = await self._client.get("/Immunization", params={
                "patient": patient_id,
                "_count": 100
            })
            r.raise_for_status()
            bundle = r.json()
            
            # Convert Immunization to Observation-like structure
            immunizations = []
            for entry in bundle.get("entry", []):
                resource = entry["resource"]
                
                # Extract vaccine name
                vaccine_name = "Unknown vaccine"
                if resource.get("vaccineCode") and resource["vaccineCode"].get("text"):
                    vaccine_name = resource["vaccineCode"]["text"]
                elif resource.get("vaccineCode") and resource["vaccineCode"].get("coding"):
                    vaccine_name = resource["vaccineCode"]["coding"][0].get("display", "Unknown vaccine")
                
                # Extract administration date
                occurrence_date = resource.get("occurrenceDateTime", "")
                if occurrence_date:
                    occurrence_date = occurrence_date[:10]  # Just the date part
                
                # Extract status and lot number
                status = resource.get("status", "unknown")
                lot_number = resource.get("lotNumber", "")
                
                value_str = f"{status.title()}"
                if occurrence_date:
                    value_str += f" on {occurrence_date}"
                if lot_number:
                    value_str += f" (Lot: {lot_number})"
                
                immunization_obs = {
                    "id": resource.get("id", "unknown"),
                    "status": status,
                    "code": {"coding": [{"code": "33879002", "display": vaccine_name}]},
                    "valueString": value_str,
                    "effectiveDateTime": resource.get("occurrenceDateTime"),
                    "resource_type": "Immunization"
                }
                immunizations.append(immunization_obs)
            
            return immunizations
        except Exception as e:
            print(f"Failed to fetch immunizations: {e}")
            return []

    async def _get_conditions(self, patient_id: str) -> list[Observation]:
        """Fetch condition/diagnosis information for a patient."""

        try:
            r = await self._client.get("/Condition", params={
                "patient": patient_id,
                "_count": 100
            })
            r.raise_for_status()
            bundle = r.json()
            
            # Convert Condition to Observation-like structure
            conditions = []
            for entry in bundle.get("entry", []):
                resource = entry["resource"]
                condition_obs = {
                    "id": resource.get("id", "unknown"),
                    "status": resource.get("clinicalStatus", {}).get("text", "unknown"),
                    "code": {"coding": [{"code": "11348-0", "display": "Diagnosis"}]},
                    "valueString": resource.get("code", {}).get("text", "Unknown condition"),
                    "effectiveDateTime": resource.get("onsetDateTime", ""),
                    "resource_type": "Condition"
                }
                conditions.append(condition_obs)
            
            return conditions
        except Exception:
            return []

    async def _get_observations(
            self,
            pid: str,
            *,
            category: str,
            count: int = 100
    ) -> list[Observation]:
        """Fetch Observations of a given category for a patient."""
        r = await self._client.get(
            "/Observation",
            params={
                "patient": pid,
                "category": category,
                "_sort": "-date",
                "_count": count,
            },
        )
        r.raise_for_status()
        bundle = r.json()
        good: list[Observation] = []
        for entry in bundle.get("entry", []):
            try:
                good.append(Observation.model_validate(entry["resource"]))
            except ValidationError:
                # HAPI demo sometimes omits timezone in effectiveDateTime → skip
                continue
        return good


    async def _get_encounters(self, patient_id: str) -> list[Any]:
        """Fetch encounter information for a patient."""
        try:
            r = await self._client.get("/Encounter", params={
                "patient": patient_id,
                "_count": 100,
                "_sort": "-date"
            })
            r.raise_for_status()
            bundle = r.json()
            
            encounters = []
            for entry in bundle.get("entry", []):
                encounters.append(entry["resource"])
            
            return encounters
        except Exception as e:
            print(f"Failed to fetch encounters: {e}")
            return []

    async def _get_care_plans(self, patient_id: str) -> list[Observation]:
        """Fetch CarePlan resources and map to simple dict-like observations."""
        try:
            r = await self._client.get("/CarePlan", params={
                "subject": f"Patient/{patient_id}",
                "_count": 100,
                "_sort": "-date"
            })
            r.raise_for_status()
            bundle = r.json()

            care_plans: list[dict] = []
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                plan_id = resource.get("id", "unknown")
                status = resource.get("status", "unknown")
                intent = resource.get("intent", "plan")
                title = resource.get("title") or "Care Plan"
                period = resource.get("period", {})
                start = period.get("start", "")
                # Summarize activities if present
                activity_summaries: list[str] = []
                for act in resource.get("activity", []) or []:
                    detail = act.get("detail", {})
                    code = detail.get("code", {}) or {}
                    code_text = code.get("text")
                    if code_text:
                        activity_summaries.append(code_text)
                activities = "; ".join(activity_summaries)

                value_parts = [status.title(), intent]
                if activities:
                    value_parts.append(activities)
                value_str = " - ".join([p for p in value_parts if p])

                care_plans.append({
                    "id": plan_id,
                    "status": status,
                    "code": {"coding": [{"code": "care-plan", "display": title}]},
                    "valueString": value_str,
                    "effectiveDateTime": start,
                    "resource_type": "CarePlan",
                })

            return care_plans
        except Exception as e:
            print(f"Failed to fetch care plans: {e}")
            return []

    async def _get_imaging_studies(self, patient_id: str) -> list[dict]:
        """Fetch ImagingStudy resources and map to simple dict-like observations."""
        try:
            r = await self._client.get("/ImagingStudy", params={
                "patient": patient_id,
                "_count": 100,
                "_sort": "-date"
            })
            r.raise_for_status()
            bundle = r.json()

            studies: list[dict] = []
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                study_id = resource.get("id", "unknown")
                status = resource.get("status", "unknown")
                started = resource.get("started", "")
                description = resource.get("description") or "Imaging Study"

                modalities: list[str] = []
                for series in resource.get("series", []) or []:
                    for mod in (series.get("modality", {}) or {}).get("coding", []) or []:
                        disp = mod.get("display") or mod.get("code")
                        if disp:
                            modalities.append(disp)
                modality_str = ", ".join(sorted(set(modalities)))

                value_parts = [status.title()]
                if modality_str:
                    value_parts.append(modality_str)
                value_str = " - ".join([p for p in value_parts if p])

                studies.append({
                    "id": study_id,
                    "status": status,
                    "code": {"coding": [{"code": "imaging-study", "display": description}]},
                    "valueString": value_str,
                    "effectiveDateTime": started,
                    "resource_type": "ImagingStudy",
                })

            return studies
        except Exception as e:
            print(f"Failed to fetch imaging studies: {e}")
            return []

    async def _get_procedures(self, patient_id: str) -> list[dict]:
        """Fetch Procedure resources and map to simple dict-like observations."""
        try:
            r = await self._client.get("/Procedure", params={
                "patient": patient_id,
                "_count": 100,
                "_sort": "-date"
            })
            r.raise_for_status()
            bundle = r.json()

            procedures: list[dict] = []
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                proc_id = resource.get("id", "unknown")
                status = resource.get("status", "unknown")
                code = resource.get("code", {}) or {}
                code_text = code.get("text")
                if not code_text and code.get("coding"):
                    code_text = code["coding"][0].get("display") or code["coding"][0].get("code")

                # Determine performed time
                performed = resource.get("performedDateTime")
                if not performed:
                    period = resource.get("performedPeriod", {})
                    performed = period.get("start")

                outcome = resource.get("outcome", {})
                outcome_text = outcome.get("text") if isinstance(outcome, dict) else None
                value_parts = [status.title()]
                if outcome_text:
                    value_parts.append(outcome_text)
                value_str = " - ".join([p for p in value_parts if p])

                procedures.append({
                    "id": proc_id,
                    "status": status,
                    "code": {"coding": [{"code": "procedure", "display": code_text or "Procedure"}]},
                    "valueString": value_str,
                    "effectiveDateTime": performed or "",
                    "resource_type": "Procedure",
                })

            return procedures
        except Exception as e:
            print(f"Failed to fetch procedures: {e}")
            return []

    async def _get_diagnostic_reports(self, patient_id: str) -> list[dict]:
        """Fetch DiagnosticReport resources and map to dict-like entries."""
        try:
            r = await self._client.get("/DiagnosticReport", params={
                "patient": patient_id,
                "_count": 100,
                "_sort": "-issued"
            })
            r.raise_for_status()
            bundle = r.json()

            reports: list[dict] = []
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                rep_id = resource.get("id", "unknown")
                code = resource.get("code", {}) or {}
                code_text = code.get("text")
                if not code_text and code.get("coding"):
                    code_text = code["coding"][0].get("display") or code["coding"][0].get("code")
                conclusion = resource.get("conclusion") or ""
                status = resource.get("status", "unknown")
                issued = resource.get("issued") or resource.get("effectiveDateTime") or ""

                value_parts = [status.title()]
                if conclusion:
                    value_parts.append(conclusion)
                value_str = " - ".join([p for p in value_parts if p])

                reports.append({
                    "id": rep_id,
                    "status": status,
                    "code": {"coding": [{"code": "diagnostic-report", "display": code_text or "Diagnostic Report"}]},
                    "valueString": value_str,
                    "effectiveDateTime": issued,
                    "resource_type": "DiagnosticReport",
                })

            return reports
        except Exception as e:
            print(f"Failed to fetch diagnostic reports: {e}")
            return []

    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *exc):
        await self.close()


    # Journal methods implementation
    async def get_patient_journal_entries(self, patient_id: str) -> Sequence[JournalEntry]:
        """Get all journal entries for a patient from FHIR DocumentReference resources."""
        try:
            # Try to fetch from FHIR server first
            r = await self._client.get("/DocumentReference", params={
                "subject": f"Patient/{patient_id}",
                "_sort": "-date",
                "_count": "100"
            })
            r.raise_for_status()
            bundle = r.json()
            
            entries = []
            if bundle.get("entry"):
                for entry in bundle["entry"]:
                    try:
                        fhir_resource = entry["resource"]
                        entries.append(_parse_fhir_document_reference(fhir_resource))
                    except Exception as e:
                        # Skip invalid entries
                        print(f"Failed to parse DocumentReference: {e}")
                        continue
            
            # Also include in-memory entries for this patient
            for entry_data in self._journal_entries.values():
                if entry_data.get("subject", {}).get("reference") == f"Patient/{patient_id}":
                    try:
                        entries.append(_parse_fhir_document_reference(entry_data))
                    except Exception:
                        continue
            
            # Sort by creation date descending
            return sorted(entries, key=lambda e: e.created_at, reverse=True)
        except Exception:

            # Fallback to in-memory storage only
            entries = []
            for entry_data in self._journal_entries.values():
                if entry_data.get("subject", {}).get("reference") == f"Patient/{patient_id}":
                    try:
                        entries.append(_parse_fhir_document_reference(entry_data))
                    except Exception:
                        continue
            return sorted(entries, key=lambda e: e.created_at, reverse=True)

    async def create_journal_entry(self, entry: JournalEntryCreate, user: User) -> JournalEntry:
        """Create a new journal entry as FHIR DocumentReference."""
        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Create FHIR DocumentReference structure
        fhir_resource = {
            "resourceType": "DocumentReference",
            "id": entry_id,
            "meta": {
                "profile": ["http://hl7.org/fhir/StructureDefinition/DocumentReference"]
            },
            "identifier": [
                {
                    "system": "http://optimed.local/journal-entries",
                    "value": entry_id
                }
            ],
            "status": "current",
            "type": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": _map_entry_type_to_fhir_type(entry.entry_type),
                        "display": entry.entry_type.value.title()
                    }
                ]
            },
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
                            "code": "clinical-note",
                            "display": "Clinical Note"
                        }
                    ]
                }
            ],
            "subject": {
                "reference": f"Patient/{entry.patient_id}"
            },
            "date": now.isoformat(),
            "author": [
                {
                    "reference": f"Practitioner/{user.user_id}",
                    "display": user.display_name
                }
            ],
            "description": entry.title,
            "content": [
                {
                    "attachment": {
                        "contentType": "text/plain",
                        "data": base64.b64encode(entry.content.encode('utf-8')).decode('ascii'),
                        "title": entry.title
                    }
                }
            ],
            "context": {
                "period": {
                    "start": now.isoformat()
                }
            }
        }
        
        # Store in memory (HAPI is read-only)
        self._journal_entries[entry_id] = fhir_resource
        
        # Try to POST to FHIR server (will likely fail with HAPI demo)
        try:
            r = await self._client.post("/DocumentReference", json=fhir_resource)
            if r.status_code == 201:
                # Success - update with server response
                server_resource = r.json()
                self._journal_entries[entry_id] = server_resource
                return _parse_fhir_document_reference(server_resource)
        except Exception as e:
            # Expected for read-only HAPI demo
            print(f"Failed to POST to FHIR server (expected for HAPI demo): {e}")
        
        return _parse_fhir_document_reference(fhir_resource)

    async def get_journal_entry_by_id(self, entry_id: str) -> Optional[JournalEntry]:
        """Get a specific journal entry by ID."""
        # Try FHIR server first
        try:
            r = await self._client.get(f"/DocumentReference/{entry_id}")
            r.raise_for_status()
            fhir_resource = r.json()
            return _parse_fhir_document_reference(fhir_resource)
        except Exception:
            pass
        
        # Check in-memory storage
        fhir_resource = self._journal_entries.get(entry_id)
        if fhir_resource:
            return _parse_fhir_document_reference(fhir_resource)
        
        return None

    async def update_journal_entry(self, entry_id: str, updates: JournalEntryUpdate, user: User) -> JournalEntry:
        """Update an existing journal entry."""
        # Get existing entry
        existing_resource = self._journal_entries.get(entry_id)
        if not existing_resource:
            # Try to fetch from server
            try:
                r = await self._client.get(f"/DocumentReference/{entry_id}")
                r.raise_for_status()
                existing_resource = r.json()
            except Exception:
                raise ValueError(f"Journal entry {entry_id} not found")
        
        # Update the resource
        update_data = updates.model_dump(exclude_unset=True)
        
        if "title" in update_data:
            existing_resource["description"] = update_data["title"]
            if existing_resource.get("content") and existing_resource["content"][0].get("attachment"):
                existing_resource["content"][0]["attachment"]["title"] = update_data["title"]
        
        if "content" in update_data:
            if existing_resource.get("content") and existing_resource["content"][0].get("attachment"):
                import base64
                existing_resource["content"][0]["attachment"]["data"] = base64.b64encode(
                    update_data["content"].encode('utf-8')
                ).decode('ascii')
        
        if "entry_type" in update_data:
            existing_resource["type"]["coding"][0]["code"] = _map_entry_type_to_fhir_type(update_data["entry_type"])
            existing_resource["type"]["coding"][0]["display"] = update_data["entry_type"].value.title()
        
        # Update timestamp
        existing_resource["date"] = datetime.now(timezone.utc).isoformat()
        
        # Store updated version
        self._journal_entries[entry_id] = existing_resource
        
        # Try to PUT to FHIR server (will likely fail with HAPI demo)
        try:
            r = await self._client.put(f"/DocumentReference/{entry_id}", json=existing_resource)
            if r.status_code == 200:
                server_resource = r.json()
                self._journal_entries[entry_id] = server_resource
                return _parse_fhir_document_reference(server_resource)
        except Exception as e:
            print(f"Failed to PUT to FHIR server (expected for HAPI demo): {e}")
        
        return _parse_fhir_document_reference(existing_resource)

    async def delete_journal_entry(self, entry_id: str, user: User) -> bool:
        """Delete a journal entry."""
        # Try to delete from server first
        try:
            r = await self._client.delete(f"/DocumentReference/{entry_id}")
            if r.status_code in [200, 204]:
                # Remove from memory if it exists
                self._journal_entries.pop(entry_id, None)
                return True
        except Exception:
            pass
        
        # Remove from memory storage
        if entry_id in self._journal_entries:
            del self._journal_entries[entry_id]
            return True
        
        return False


    