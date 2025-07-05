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
        care_unit="UNKNOWN",  # May need enhancement with SMART on FHIR data
        vitals=vitals_dict,
        labs=labs_dict,
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
        return _to_patient_ctx(patient, vitals, labs)
        
    async def search_patients(self, query: str) -> Sequence[PatientContext]:
        """Search patients by name or identifier."""
        await self._ensure_token_valid()
        
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
    
    async def _get_patient_resource(self, pid: str) -> Patient:
        """Fetch a single Patient resource by ID."""
        await self._ensure_token_valid()
        
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