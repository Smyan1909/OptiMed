from __future__ import annotations
import base64
import os
from datetime import datetime, timezone
from typing import Optional, Sequence
from pydantic import ValidationError

import httpx
from fhir.resources.patient import Patient # type: ignore[import-untyped]
from fhir.resources.observation import Observation # type: ignore[import-untyped]

from optimed.core.domain import PatientContext
from optimed.core.ports import FHIRRepository

from optimed.core.domain import PatientContext, JournalEntry, JournalEntryCreate, JournalEntryUpdate, JournalEntryType, User
from datetime import datetime, timezone
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
        except:
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
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base = (base_url or FHIR_BASE_URL).rstrip("/")
        self._client = client or httpx.AsyncClient(base_url=self._base, timeout=timeout, headers={"User-Agent": "OptiMedPrototype/0.1"})
        # In-memory storage for journal entries (since HAPI is read-only demo)
        self._journal_entries: dict[str, dict] = {}


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
            # drop the top‐level "text" block so Patient.model_validate won't expect text.div
            resource = entry["resource"].copy()
            resource.pop("text", None)
            try:
                p = Patient.model_validate(resource)
            except ValidationError:
                # skip any resource that still fails validation
                continue
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


    # Journal methods implementation
    async def get_patient_journal_entries(self, patient_id: str) -> Sequence[JournalEntry]:
        """Get all journal entries for a patient from FHIR DocumentReference resources."""
        try:
            # Try to fetch from FHIR server first
            r = await self._client.get("/DocumentReference", params={
                "subject": f"Patient/{patient_id}",
                "category": "clinical-note",
                "_sort": "-date",
                "_count": "50"
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
            
        except Exception as e:
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


    