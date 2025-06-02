from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Sequence
from pydantic import ValidationError

import httpx
from fhir.resources.patient import Patient # type: ignore[import-untyped]
from fhir.resources.observation import Observation # type: ignore[import-untyped]

from optimed.core.domain import PatientContext
from optimed.core.ports import FHIRRepository

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
    "59408-5": "Resp rate",
    "8480-6": "Systolic BP",
    "8462-4": "Diastolic BP",
    "8310-5": "Body temperature",
}

CRITICAL_LAB_CODES = {
    "2823-3": "Potassium",         # used by PatientContext.has_critical_lab()
    "2339-0": "Glucose",
}

# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #

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

def _obs_bundle_to_dict(entries: list[Observation]) -> dict[str, str]:
    """Convert a list of Observations to a dict of code → value"""
    out: dict[str, str] = {}
    for obs in entries:
        if not obs.code or not obs.code.coding:
            continue
        code = obs.code.coding[0].code
        if not obs.valueQuantity:
            continue
        value = obs.valueQuantity.value
        unit = obs.valueQuantity.unit 
        out[code] = f"{value} {unit}"

    return out 

def _to_patient_ctx(
        patient: Patient,
        vitals: list[Observation] | None = None,
        labs: list[Observation] | None = None,
) -> PatientContext:
    """Convert FHIR Patient + vitals/labs to PatientContext domain model."""
    if not patient.id:
        raise ValueError("Patient must have an ID")

    vitals_dict = _obs_bundle_to_dict(vitals or [])
    labs_dict = _obs_bundle_to_dict(labs or [])

    return PatientContext(
        patient_id=patient.id,
        name=_fhir_name_to_str(patient),
        age=_age_from_birthdate(patient.birthDate),
        sex=patient.gender or "unknown",
        care_unit="UNKOWN",  # HAPI demo has no care unit info
        vitals=vitals_dict,
        labs=labs_dict,
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
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base = (base_url or FHIR_BASE_URL).rstrip("/")
        self._client = client or httpx.AsyncClient(base_url=self._base, timeout=timeout, headers={"User-Agent": "OptiMedPrototype/0.1"})


    async def get_patient(self, patient_id: str) -> PatientContext:
        patient = await self._get_patient_resource(patient_id)
        vitals = await self._get_observations(patient_id, category="vital-signs")
        labs = await self._get_observations(patient_id, category="laboratory")
        return _to_patient_ctx(patient, vitals, labs)
    
    async def search_patients(self, query: str) -> Sequence[PatientContext]:
        """Search patients by MRN or name."""
        
        r = await self._client.get("/Patient", params={"name": query, "_count": 10})
        r.raise_for_status()
        bundle = r.json()

        results: list[PatientContext] = []
        for entry in bundle.get("entry", []):
            p = Patient.model_validate(entry["resource"])
            results.append(_to_patient_ctx(p, [], []))
        
        return results
    
    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def _get_patient_resource(self, pid: str) -> Patient:
        """Fetch a single Patient resource by ID."""
        r = await self._client.get(f"/Patient/{pid}")
        r.raise_for_status()
        return Patient.model_validate(r.json())
    
    async def _get_observations(
            self,
            pid: str,
            *,
            category: str,
            count: int = 10
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

    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *exc):
        await self.close()

    