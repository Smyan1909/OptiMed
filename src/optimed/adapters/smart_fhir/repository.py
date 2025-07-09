from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Sequence, Dict, Any, Optional
from pydantic import ValidationError

import httpx

from fhir.resources.patient import Patient  # type: ignore[import-untyped]
from fhir.resources.observation import Observation  # type: ignore[import-untyped]

from optimed.core.ports import FHIRRepository, AuthenticatedFHIRRepository, AuthenticationProvider
from optimed.core.domain import PatientContext, UserEHRConnection, JournalEntry, JournalEntryCreate, JournalEntryUpdate, JournalEntryType, User
import uuid
import base64


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

"""
optimed.adapters.smart_fhir.repository
-------------------------------------

SMART on FHIR adapter that implements the FHIRRepository protocol with OAuth2 authentication
for secure access to EHR systems.
"""

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

def _parse_smart_fhir_document_reference(fhir_resource: dict) -> JournalEntry:
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
            try:
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
        except Exception:
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
    """Convert observation bundle to dict with human-readable names."""
    result = {}
    for obs in entries:
        # Handle both Observation objects and dict representations
        if isinstance(obs, dict):
            # Handle dict-based observations (from medications, allergies, diagnoses)
            if obs.get("code") and obs["code"].get("coding"):
                coding = obs["code"]["coding"][0]
                display_name = coding.get("display", "Unknown")
                value_str = obs.get("valueString", "N/A")
                result[display_name] = value_str
        else:
            # Handle actual Observation objects
            if obs.code and obs.code.coding:
                # Get the LOINC code
                loinc_code = None
                for coding in obs.code.coding:
                    if coding.system == "http://loinc.org":
                        loinc_code = coding.code
                        break
                
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
                    else:
                        # Fallback to the display name from FHIR or the code itself
                        display_name = obs.code.coding[0].display or loinc_code
                    
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
    
    return result

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
        imaging: list[Observation] | None = None,
        exam: list[Observation] | None = None,
        procedure: list[Observation] | None = None,
        social_history: list[Observation] | None = None,
        medications: list[Observation] | None = None,
        allergies: list[Observation] | None = None,
        diagnoses: list[Observation] | None = None,
) -> PatientContext:
    """Convert FHIR Patient + observations to PatientContext domain model."""
    if not patient.id:
        raise ValueError("Patient must have an ID")

    return PatientContext(
        patient_id=patient.id,
        name=_fhir_name_to_str(patient),
        age=_age_from_birthdate(patient.birthDate),
        sex=patient.gender or "unknown",
        care_unit="UNKNOWN",  # May need enhancement with SMART on FHIR data
        vitals=_obs_bundle_to_dict(vitals or []),
        labs=_obs_bundle_to_dict(labs or []),
        imaging=_obs_bundle_to_dict(imaging or []),
        exam=_obs_bundle_to_dict(exam or []),
        procedure=_obs_bundle_to_dict(procedure or []),
        social_history=_obs_bundle_to_dict(social_history or []),
        medications=_obs_bundle_to_dict(medications or []),
        allergies=_obs_bundle_to_dict(allergies or []),
        diagnoses=_obs_bundle_to_dict(diagnoses or []),
    )

class SMARTFHIRRepository(FHIRRepository, AuthenticatedFHIRRepository):
    """SMART on FHIR repository implementation with OAuth2 support."""

    def __init__(
            self,
            connection: UserEHRConnection,
            auth_provider: Optional[AuthenticationProvider] = None,
            timeout: float = 10.0,
    ) -> None:
        """Initialize the SMART on FHIR repository with a UserEHRConnection."""
        if connection.provider_type != "smart_fhir":
            raise ValueError(f"Expected smart_fhir connection, got {connection.provider_type}")
        
        self._connection = connection
        self._auth_provider = auth_provider
        self._base = connection.fhir_server_url.rstrip("/")
        self._timeout = timeout
        
        self._client_id = connection.client_id
        self._client_secret = None  # Will be set by auth_provider if needed
        self._redirect_uri = "http://localhost:8000/auth/ehr-callback"  # Default
        self._scope = connection.scope or "patient/*.read"
        self._token_url = f"{self._base}/token"

        # Extract credentials from UserEHRConnection
        self._access_token = connection.access_token
        self._refresh_token = connection.refresh_token
        self._token_expiry = connection.token_expires_at
        
        # Initialize client
        headers = {"User-Agent": "OptiMed-SMART/0.1"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        
        self._client = httpx.AsyncClient(
            base_url=self._base, 
            timeout=self._timeout,
            headers=headers
        )    

    @staticmethod
    async def from_connection(
        connection: UserEHRConnection,
        auth_provider: Optional[AuthenticationProvider] = None,
        **kwargs: Any
    ) -> 'AuthenticatedFHIRRepository':
        """Create repository instance from UserEHRConnection."""
        return SMARTFHIRRepository(connection, auth_provider, **kwargs)

    async def is_authenticated(self) -> bool:
        """Check if the repository is properly authenticated."""
        if not self._access_token:
            return False
        
        if self._auth_provider:
            result = await self._auth_provider.validate_token(self._access_token)
            return result.get("valid", False)
        
        return True

    async def refresh_authentication(self) -> bool:
        """Refresh authentication if possible."""
        if not self._refresh_token or not self._auth_provider:
            return False
        
        try:
            new_credentials = await self._auth_provider.refresh_token(self._refresh_token)
            
            # Update internal state
            self._access_token = new_credentials["access_token"]
            self._refresh_token = new_credentials.get("refresh_token", self._refresh_token)
            
            if new_credentials.get("expires_in"):
                self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=new_credentials["expires_in"])
            
            self._client.headers["Authorization"] = f"Bearer {self._access_token}"
            return True
        except Exception:
            return False

    async def authenticate(self, code: str) -> Dict[str, Any]:
        """Authenticate using the provided authorization code."""
        
        if code: 
             
             data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
                "client_id": self._client_id,
             }

             if self._client_secret:
                data["client_secret"] = self._client_secret
        else:
             
             data = {
                "grant_type": "client_credentials",
                "scope": self._scope,
                "client_id": self._client_id,
             }

             if self._client_secret:
                data["client_secret"] = self._client_secret

        async with httpx.AsyncClient(timeout=self._timeout) as auth_client:
            response = await auth_client.post(self._token_url, data=data)
            response.raise_for_status()
            token_data = response.json()

            self._access_token = token_data["access_token"]
            self._refresh_token = token_data["refresh_token"] if "refresh_token" in token_data else None
            expires_in = token_data.get("expires_in", 3600)
            self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            self._client.headers["Authorization"] = f"Bearer {self._access_token}"

            return token_data
        
    async def _ensure_token_valid(self) -> None:
        """Ensure the access token is valid, refreshing if necessary."""
        if not self._access_token:
            raise ValueError("Access token is not set. Please authenticate first.")
        
        # Check if token is expired and needs refresh
        if (self._token_expiry and 
            datetime.now(timezone.utc) >= self._token_expiry and 
            self._refresh_token):
            
            success = await self.refresh_authentication()
            if not success:
                raise ValueError("Failed to refresh authentication")

    async def get_patient(self, patient_id: str) -> PatientContext:
        """Get patient context by ID."""
        await self._ensure_token_valid()
        
        patient = await self._get_patient_resource(patient_id)
        vitals = await self._get_observations(patient_id, category="vital-signs")
        labs = await self._get_observations(patient_id, category="laboratory")
        imaging = await self._get_observations(patient_id, category="imaging")
        exam = await self._get_observations(patient_id, category="exam")
        procedure = await self._get_observations(patient_id, category="procedure")
        social_history = await self._get_observations(patient_id, category="social-history")
        
        # For medications, allergies, and diagnoses, use different FHIR resources
        medications = await self._get_medications(patient_id)
        allergies = await self._get_allergies(patient_id)
        diagnoses = await self._get_conditions(patient_id)
        
        return _to_patient_ctx(
            patient, vitals, labs, imaging, exam, procedure, 
            social_history, medications, allergies, diagnoses
        )
        
    async def search_patients(self, query: str) -> Sequence[PatientContext]:
        """Search patients by name or identifier."""
        await self._ensure_token_valid()
        
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
            results.append(_to_patient_ctx(p, [], []))

        return results
    
    async def _get_patient_resource(self, pid: str) -> Patient:
        """Fetch a single Patient resource by ID."""
        await self._ensure_token_valid()
        
        r = await self._client.get(f"/Patient/{pid}")
        r.raise_for_status()
        return Patient.model_validate(r.json())
    
    async def _get_medications(self, patient_id: str) -> list[Observation]:
        """Fetch medication information for a patient."""
        await self._ensure_token_valid()
        
        try:
            r = await self._client.get("/MedicationRequest", params={
                "patient": patient_id,
                "status": "active",
                "_count": 20
            })
            r.raise_for_status()
            bundle = r.json()
            
            # Convert MedicationRequest to Observation-like structure
            medications = []
            for entry in bundle.get("entry", []):
                resource = entry["resource"]
                # Create a simplified observation for medication
                med_obs = {
                    "code": {"coding": [{"code": "10160-0", "display": "Medication"}]},
                    "valueString": resource.get("medicationCodeableConcept", {}).get("text", "Unknown medication")
                }
                medications.append(med_obs)
            
            return medications
        except Exception:
            return []
    
    async def _get_allergies(self, patient_id: str) -> list[Observation]:
        """Fetch allergy information for a patient."""
        await self._ensure_token_valid()
        
        try:
            r = await self._client.get("/AllergyIntolerance", params={
                "patient": patient_id,
                "_count": 20
            })
            r.raise_for_status()
            bundle = r.json()
            
            # Convert AllergyIntolerance to Observation-like structure
            allergies = []
            for entry in bundle.get("entry", []):
                resource = entry["resource"]
                allergy_obs = {
                    "code": {"coding": [{"code": "48765-2", "display": "Allergies"}]},
                    "valueString": resource.get("code", {}).get("text", "Unknown allergy")
                }
                allergies.append(allergy_obs)
            
            return allergies
        except Exception:
            return []

    async def _get_conditions(self, patient_id: str) -> list[Observation]:
        """Fetch condition/diagnosis information for a patient."""
        await self._ensure_token_valid()
        
        try:
            r = await self._client.get("/Condition", params={
                "patient": patient_id,
                "_count": 20
            })
            r.raise_for_status()
            bundle = r.json()
            
            # Convert Condition to Observation-like structure
            conditions = []
            for entry in bundle.get("entry", []):
                resource = entry["resource"]
                condition_obs = {
                    "code": {"coding": [{"code": "11348-0", "display": "Diagnosis"}]},
                    "valueString": resource.get("code", {}).get("text", "Unknown condition")
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
            count: int = 10
    ) -> list[Observation]:
        """Fetch Observations of a given category for a patient."""
        await self._ensure_token_valid()
        
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
                # Skip invalid entries
                continue
        return good
    

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, *exc):
        await self.close()


    
    # Journal methods implementation
    async def get_patient_journal_entries(self, patient_id: str) -> Sequence[JournalEntry]:
        """Get all journal entries for a patient from FHIR DocumentReference resources."""
        await self._ensure_token_valid()
        
        try:
            r = await self._client.get("/DocumentReference", params={
                "subject": f"Patient/{patient_id}",
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
                        entries.append(_parse_smart_fhir_document_reference(fhir_resource))
                    except Exception as e:
                        # Skip invalid entries
                        print(f"Failed to parse DocumentReference: {e}")
                        continue
            
            return entries
            
        except Exception as e:
            print(f"Failed to fetch journal entries from FHIR server: {e}")
            return []

    async def create_journal_entry(self, entry: JournalEntryCreate, user: User) -> JournalEntry:
        """Create a new journal entry as FHIR DocumentReference."""
        await self._ensure_token_valid()
        
        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Create FHIR DocumentReference structure
        fhir_resource = {
            "resourceType": "DocumentReference",
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
        
        try:
            r = await self._client.post("/DocumentReference", json=fhir_resource)
            r.raise_for_status()
            created_resource = r.json()
            return _parse_smart_fhir_document_reference(created_resource)
        except Exception as e:
            raise ValueError(f"Failed to create journal entry: {e}")

    async def get_journal_entry_by_id(self, entry_id: str) -> Optional[JournalEntry]:
        """Get a specific journal entry by ID."""
        await self._ensure_token_valid()
        
        try:
            r = await self._client.get(f"/DocumentReference/{entry_id}")
            r.raise_for_status()
            fhir_resource = r.json()
            return _parse_smart_fhir_document_reference(fhir_resource)
        except Exception:
            return None

    async def update_journal_entry(self, entry_id: str, updates: JournalEntryUpdate, user: User) -> JournalEntry:
        """Update an existing journal entry."""
        await self._ensure_token_valid()
        
        # Get existing entry
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
                existing_resource["content"][0]["attachment"]["data"] = base64.b64encode(
                    update_data["content"].encode('utf-8')
                ).decode('ascii')
        
        if "entry_type" in update_data:
            existing_resource["type"]["coding"][0]["code"] = _map_entry_type_to_fhir_type(update_data["entry_type"])
            existing_resource["type"]["coding"][0]["display"] = update_data["entry_type"].value.title()
        
        # Update timestamp
        existing_resource["date"] = datetime.now(timezone.utc).isoformat()
        
        try:
            r = await self._client.put(f"/DocumentReference/{entry_id}", json=existing_resource)
            r.raise_for_status()
            updated_resource = r.json()
            return _parse_smart_fhir_document_reference(updated_resource)
        except Exception as e:
            raise ValueError(f"Failed to update journal entry: {e}")

    async def delete_journal_entry(self, entry_id: str, user: User) -> bool:
        """Delete a journal entry."""
        await self._ensure_token_valid()
        
        try:
            r = await self._client.delete(f"/DocumentReference/{entry_id}")
            return r.status_code in [200, 204]
        except Exception:
            return False

    # ...existing methods...